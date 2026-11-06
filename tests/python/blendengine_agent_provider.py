# SPDX-License-Identifier: GPL-2.0-or-later
"""Native editor provider boundary tests using an actual loopback HTTP server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest import mock
import urllib.error


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/addons_core/blendengine/agent_provider.py"
SPEC = importlib.util.spec_from_file_location("blendengine_agent_provider", MODULE_PATH)
provider = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider)


def completion(plan, *, finish_reason="stop", refusal=None):
    content = json.dumps(plan) if isinstance(plan, dict) else plan
    return json.dumps({"choices": [{"finish_reason": finish_reason,
                                    "message": {"content": content, "refusal": refusal}}]}).encode()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.received.append({"path": self.path, "headers": dict(self.headers),
                                     "body": json.loads(data)})
        if self.server.on_request:
            self.server.on_request()
        time.sleep(self.server.delay)
        self.send_response(self.server.status)
        self.send_header("Content-Type", self.server.content_type)
        if self.server.redirect:
            self.send_header("Location", self.server.redirect)
        if self.server.advertised_length is not None:
            self.send_header("Content-Length", str(self.server.advertised_length))
        self.end_headers()
        try:
            self.wfile.write(self.server.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format, *_arguments):
        pass


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.received = []
        self.server.delay = 0
        self.server.status = 200
        self.server.redirect = None
        self.server.on_request = None
        self.server.advertised_length = None
        self.server.content_type = "application/json"
        self.plan = {"summary": "Create a cube", "actions": [{"tool": "create_object", "name": "Cube"}]}
        self.server.body = completion(self.plan)
        self.endpoint = "http://127.0.0.1:%d/v1" % self.server.server_port
        self.prompt_patch = mock.patch.object(provider, "_system_prompt", return_value="Return a JSON scene plan.")
        self.prompt_patch.start()
        self.addCleanup(self.prompt_patch.stop)

    def request(self, **kwargs):
        options = {"endpoint": self.endpoint, "model": "local-test", "timeout": 2}
        options.update(kwargs)
        return provider.request_plan("Qizil kub qo'sh", {"selected": ["Cube"]}, **options)

    def test_actual_request_has_typed_messages_and_optional_auth(self):
        result = self.request(api_key="secret-fixture")
        self.assertEqual(result, self.plan)
        sent = self.server.received[0]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer secret-fixture")
        self.assertEqual(sent["body"]["model"], "local-test")
        self.assertEqual([m["role"] for m in sent["body"]["messages"]], ["system", "user"])
        user = json.loads(sent["body"]["messages"][1]["content"])
        self.assertEqual(user, {"request": "Qizil kub qo'sh", "scene": {"selected": ["Cube"]}})
        self.server.received.clear()
        self.request()
        self.assertNotIn("Authorization", self.server.received[0]["headers"])

    def test_json_fence_is_accepted_but_surrounding_code_is_not(self):
        self.server.body = completion("```json\n" + json.dumps(self.plan) + "\n```")
        self.assertEqual(self.request(), self.plan)
        for text in ("```python\n" + json.dumps(self.plan) + "\n```",
                     "```json\n" + json.dumps(self.plan) + "\n```\nprint('unsafe')",
                     json.dumps(self.plan) + "\nprint('unsafe')"):
            with self.subTest(text=text):
                self.server.body = completion(text)
                with self.assertRaises(provider.ProviderError):
                    self.request()

    def test_malformed_envelopes_refusals_and_truncation(self):
        for body in (b"<html>wrong endpoint</html>", b"[]", b"{}", b'{"choices":[]}',
                     b'{"choices":[{"message":{}}]}', completion("[]"),
                     completion('{"actions":NaN}'), completion(self.plan, finish_reason="length"),
                     completion(self.plan, refusal="private provider explanation")):
            with self.subTest(body=body[:100]):
                self.server.body = body
                with self.assertRaises(provider.ProviderError):
                    self.request()

    def test_oversized_body_is_bounded_with_or_without_length_header(self):
        self.server.advertised_length = provider.MAX_RESPONSE_BYTES + 1
        with self.assertRaisesRegex(provider.ProviderError, "1 MiB"):
            self.request()
        self.server.advertised_length = None
        self.server.body = b"x" * (provider.MAX_RESPONSE_BYTES + 1)
        with self.assertRaisesRegex(provider.ProviderError, "1 MiB"):
            self.request()

    def test_http_errors_do_not_expose_key_or_response_body(self):
        key = "secret-do-not-display"
        self.server.status = 401
        self.server.body = ("provider echoed " + key).encode()
        with self.assertRaises(provider.ProviderError) as raised:
            self.request(api_key=key)
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn(key, str(raised.exception))
        self.assertNotIn("provider echoed", str(raised.exception))

    def test_redirect_does_not_forward_authorization(self):
        self.server.status = 307
        self.server.redirect = self.endpoint + "/chat/completions"
        with self.assertRaisesRegex(provider.ProviderError, "redirects"):
            self.request(api_key="secret-fixture")
        self.assertEqual(len(self.server.received), 1)

    def test_connection_failure_does_not_expose_underlying_details(self):
        with mock.patch.object(provider.urllib.request.OpenerDirector, "open",
                               side_effect=urllib.error.URLError("secret-from-provider")):
            with self.assertRaises(provider.ProviderError) as raised:
                self.request(api_key="secret-from-provider")
        self.assertNotIn("secret-from-provider", str(raised.exception))
        self.assertIn("Could not reach", str(raised.exception))

    def test_timeout_and_cancellation_discard_results(self):
        self.server.delay = .15
        with self.assertRaisesRegex(provider.ProviderError, "timed out"):
            self.request(timeout=.03)
        # Let the timed-out handler leave its fixture before the next request.
        time.sleep(.18)
        self.server.delay = 0
        cancel = threading.Event()
        cancel.set()
        count = len(self.server.received)
        with self.assertRaises(provider.ProviderCancelled):
            self.request(cancel_event=cancel)
        self.assertEqual(len(self.server.received), count)
        cancel.clear()
        self.server.on_request = cancel.set
        with self.assertRaises(provider.ProviderCancelled):
            self.request(cancel_event=cancel)

    def test_loopback_bypasses_environment_proxy(self):
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1",
                                          "HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            self.assertEqual(self.request(), self.plan)

    def test_cancellation_during_preparation_prevents_network_dispatch(self):
        cancel = threading.Event()
        def system_prompt():
            cancel.set()
            return "Return JSON."
        with mock.patch.object(provider, "_system_prompt", side_effect=system_prompt):
            with self.assertRaises(provider.ProviderCancelled):
                self.request(cancel_event=cancel)
        self.assertEqual(self.server.received, [])

    def test_endpoint_normalization_and_rejections(self):
        good = {
            "http://localhost:8000": "http://localhost:8000/v1/chat/completions",
            "http://127.0.0.2:8000/v1/": "http://127.0.0.2:8000/v1/chat/completions",
            "http://[::1]:8000/v1": "http://[::1]:8000/v1/chat/completions",
            "https://example.com/proxy/v1": "https://example.com/proxy/v1/chat/completions",
            "https://example.com/api/chat/completions": "https://example.com/api/chat/completions",
        }
        for value, expected in good.items():
            self.assertEqual(provider.normalize_endpoint(value), expected)
        for bad in ("file:///tmp/secret", "http://example.com/v1", "http://localhost.evil/v1",
                    "https://key:secret@example.com/v1", "https://@example.com/v1",
                    "https://example.com/v1?key=secret", "https://example.com/v1#token",
                    "https://example.com:/v1", "https://example.com:99999/v1",
                    "https://example.com/api/chat", "https://example.com/\n/v1", ""):
            with self.subTest(endpoint=bad):
                with self.assertRaises(provider.ProviderError):
                    provider.normalize_endpoint(bad)

    def test_invalid_inputs_fail_before_network(self):
        for options in ({"model": ""}, {"model": "x" * 129}, {"timeout": 0},
                        {"timeout": True}, {"timeout": float("nan")}, {"timeout": 121},
                        {"api_key": "secret\r\nBad: value"}):
            with self.subTest(options=options):
                with self.assertRaises(provider.ProviderError):
                    self.request(**options)
        with self.assertRaises(provider.ProviderError):
            provider.request_plan("x" * (provider.MAX_PROMPT_BYTES + 1), {},
                                  endpoint=self.endpoint, model="test")
        with self.assertRaises(provider.ProviderError):
            provider.request_plan("bad\ud800text", {}, endpoint=self.endpoint, model="test")
        for context in ([], {"bad": float("inf")}, {"objects": "x" * provider.MAX_CONTEXT_BYTES}):
            with self.assertRaises(provider.ProviderError):
                provider.request_plan("add cube", context, endpoint=self.endpoint, model="test")
        self.assertEqual(self.server.received, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
