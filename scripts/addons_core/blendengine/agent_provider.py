# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional OpenAI-compatible transport for the native editor agent.

Call ``request_plan`` in a worker thread, then validate its returned dictionary
with ``agent_core.validate_plan`` on receipt. This module has no Blender API,
starts no threads, stores no credentials and makes no request on import.

``endpoint`` accepts a full ``/chat/completions`` URL, a ``/v1`` base (including
a proxy prefix), or a server origin, which becomes ``/v1/chat/completions``.
Plain HTTP is supported only for loopback model servers. Redirects are refused
so an endpoint cannot forward a bearer token to another host.
"""

import http.client
import ipaddress
import json
import math
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PROMPT_BYTES = 32 * 1024
MAX_CONTEXT_BYTES = 96 * 1024
MAX_REQUEST_BYTES = 192 * 1024


class ProviderError(RuntimeError):
    """A provider boundary failure, safe to display without response contents."""


class ProviderCancelled(ProviderError):
    """The caller cancelled the pending plan; its result must not be applied."""


def _is_loopback(host):
    if host.rstrip(".").lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_endpoint(endpoint):
    """Return a chat-completions URL without accepting credentials in its URL."""
    if not isinstance(endpoint, str):
        raise ProviderError("Enter an HTTP loopback or HTTPS model endpoint.")
    endpoint = endpoint.strip()
    if (not endpoint or len(endpoint) > 2048 or "?" in endpoint or "#" in endpoint
            or any(ord(c) < 33 for c in endpoint)):
        raise ProviderError("The model endpoint must not contain whitespace, a query or a fragment.")
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ProviderError("The model endpoint is not a valid URL.") from None
    if (parsed.scheme not in {"http", "https"} or not host or "@" in parsed.netloc
            or parsed.username is not None or parsed.password is not None
            or parsed.netloc.endswith(":")):
        raise ProviderError("Use an HTTP loopback or HTTPS endpoint without URL credentials.")
    if port is not None and not 1 <= port <= 65535:
        raise ProviderError("The model endpoint port is invalid.")
    if parsed.scheme == "http" and not _is_loopback(host):
        raise ProviderError("Remote model endpoints require HTTPS; HTTP is limited to loopback.")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1/chat/completions"
    elif path.endswith("/v1"):
        path += "/chat/completions"
    elif not path.endswith("/chat/completions"):
        raise ProviderError("Use a /v1 base or a full /chat/completions endpoint.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _cancelled(cancel_event):
    if cancel_event is not None:
        if not callable(getattr(cancel_event, "is_set", None)):
            raise ProviderError("The cancellation handle is invalid.")
        if cancel_event.is_set():
            raise ProviderCancelled("Agent request cancelled.")


def _system_prompt():
    from .agent_core import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _json_bytes(value, message):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ProviderError(message) from None


def _read_response(response, deadline, cancel_event):
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            length = int(length)
        except ValueError:
            raise ProviderError("The provider sent an invalid response length.") from None
        if length < 0 or length > MAX_RESPONSE_BYTES:
            raise ProviderError("The provider response exceeds the 1 MiB limit.")
    parts, size = [], 0
    reader = getattr(response, "read1", response.read)
    while True:
        _cancelled(cancel_event)
        if time.monotonic() >= deadline:
            raise ProviderError("The model provider timed out.")
        part = reader(min(65536, MAX_RESPONSE_BYTES + 1 - size))
        if not part:
            return b"".join(parts)
        size += len(part)
        if size > MAX_RESPONSE_BYTES:
            raise ProviderError("The provider response exceeds the 1 MiB limit.")
        parts.append(part)


def _reject_constant(_value):
    raise ValueError("Non-finite JSON number")


def _parse_plan(raw):
    try:
        result = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ProviderError("The provider did not return a valid JSON completion.") from None
    if not isinstance(result, dict):
        raise ProviderError("The provider did not return a chat-completions object.")
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError("The provider response has no completion choice.")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderError("The provider response has no assistant message.")
    if message.get("refusal"):
        raise ProviderError("The model declined this request.")
    if choice.get("finish_reason") == "length":
        raise ProviderError("The model response was truncated; try a shorter request.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("The model returned no JSON plan.")
    content = content.strip()
    if content.startswith("```"):
        fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", content,
                              flags=re.DOTALL | re.IGNORECASE)
        if fenced is None:
            raise ProviderError("The model must return one JSON object without surrounding code.")
        content = fenced.group(1)
    try:
        plan = json.loads(content, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ProviderError("The model returned an invalid JSON plan.") from None
    if not isinstance(plan, dict):
        raise ProviderError("The model plan must be a JSON object.")
    return plan


def request_plan(prompt, context, *, endpoint, model, api_key=None, timeout=20,
                 cancel_event=None):
    """Return a parsed plan; the caller must still apply the tool-schema validator.

    Cancellation discards results before/after network activity and between
    body reads. An already-blocked socket finishes at its timeout; this function
    must never run on Blender's UI thread. API errors intentionally omit server
    bodies, URLs and underlying exception text to avoid leaking credentials.
    """
    _cancelled(cancel_event)
    endpoint = normalize_endpoint(endpoint)
    try:
        prompt_size = len(prompt.encode("utf-8")) if isinstance(prompt, str) else 0
    except UnicodeError:
        raise ProviderError("The agent request contains invalid text.") from None
    if not isinstance(prompt, str) or not prompt.strip() or prompt_size > MAX_PROMPT_BYTES:
        raise ProviderError("Enter a request of at most 32 KiB.")
    if not isinstance(context, dict):
        raise ProviderError("The agent scene context must be an object.")
    context_bytes = _json_bytes(context, "The agent scene context is not valid JSON.")
    if len(context_bytes) > MAX_CONTEXT_BYTES:
        raise ProviderError("The scene context exceeds 96 KiB; summarize fewer objects.")
    if (not isinstance(model, str) or not model.strip() or len(model) > 128
            or any(ord(c) < 32 for c in model)):
        raise ProviderError("Enter a model name of at most 128 characters.")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= 120):
        raise ProviderError("Provider timeout must be between 0 and 120 seconds.")
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": "BlendEngine-Editor-Agent/1"}
    if api_key is not None:
        if (not isinstance(api_key, str) or len(api_key) > 4096
                or not api_key.isascii() or any(ord(c) < 32 for c in api_key)):
            raise ProviderError("The provider API key is invalid.")
        if api_key.strip():
            headers["Authorization"] = "Bearer " + api_key.strip()
    try:
        system_prompt = _system_prompt()
    except ImportError:
        raise ProviderError("The editor agent core is unavailable.") from None
    user_content = _json_bytes({"request": prompt, "scene": context},
                               "The agent request is not valid JSON.").decode("utf-8")
    body = _json_bytes({"model": model.strip(), "temperature": 0.2,
                        "max_tokens": 4096,
                        "messages": [{"role": "system", "content": system_prompt},
                                     {"role": "user", "content": user_content}]},
                       "The agent request is not valid JSON.")
    if len(body) > MAX_REQUEST_BYTES:
        raise ProviderError("The complete agent request exceeds 192 KiB.")
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    host = urllib.parse.urlsplit(endpoint).hostname
    # Local model requests must not be forwarded through an environment proxy.
    proxy = urllib.request.ProxyHandler({}) if _is_loopback(host) else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(proxy, _NoRedirect())
    _cancelled(cancel_event)
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = _read_response(response, deadline, cancel_event)
    except ProviderError:
        raise
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if 300 <= status < 400:
            raise ProviderError("Model endpoint redirects are disabled; use its final URL.") from None
        raise ProviderError("The model provider returned HTTP %d." % status) from None
    except (TimeoutError, socket.timeout):
        raise ProviderError("The model provider timed out.") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        raise ProviderError("Could not reach the model provider; check its endpoint and connection.") from None
    _cancelled(cancel_event)
    plan = _parse_plan(raw)
    _cancelled(cancel_event)
    return plan
