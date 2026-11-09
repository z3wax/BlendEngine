# SPDX-License-Identifier: GPL-2.0-or-later
#
# AI Studio: a chat-first workspace for the AI Game Creator.
#
# Layout (one Blender workspace, two 3D View areas):
#
#   +---------------------------+---------------------------------------+
#   | games  |  conversation    |                                       |
#   | list   |  (user / AI      |        live 3D game (camera view)     |
#   |        |   messages)      |                                       |
#   |        +------------------+                                       |
#   |        | composer: [mode] [message .....................] [Send]  |
#   +---------------------------+---------------------------------------+
#
# The left area is a 3D View whose main region is fully painted by a GPU
# draw handler (Blender has no chat widget); its header is moved to the
# bottom and draws the message composer. The right area is the game itself.

import math
import time

import blf
import bpy
import gpu
from bpy.props import IntProperty
from bpy.types import Menu, Operator
from gpu_extras.batch import batch_for_shader

from . import ai_game_creator, ai_game_planner as planner, utils


STUDIO = utils.STUDIO_WORKSPACE
FONT = 0

PALETTE = {
    "bg": (0.055, 0.06, 0.07, 1.0),
    "sidebar": (0.075, 0.082, 0.095, 1.0),
    "line": (0.13, 0.14, 0.16, 1.0),
    "text": (0.9, 0.92, 0.94, 1.0),
    "muted": (0.55, 0.59, 0.64, 1.0),
    "bubble": (0.15, 0.165, 0.19, 1.0),
    "chip": (0.11, 0.125, 0.145, 1.0),
    "accent": (0.0, 0.78, 0.64, 1.0),
    "accent_dim": (0.0, 0.42, 0.35, 1.0),
    "error": (0.45, 0.12, 0.13, 1.0),
    "selected": (0.12, 0.135, 0.155, 1.0),
}

_draw_handle = None
_original_header_draw = None
_shader = None


# ---------------------------------------------------------------------------
# Drawing primitives.
# ---------------------------------------------------------------------------

def _uniform_shader():
    global _shader
    if _shader is None:
        try:
            _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        except (ValueError, TypeError):
            _shader = gpu.shader.from_builtin("2D_UNIFORM_COLOR")
    return _shader


def _round_rect(x, y, w, h, radius, color, segments=6):
    if w <= 0 or h <= 0:
        return
    radius = max(0.0, min(radius, w * 0.5, h * 0.5))
    points = [(x + w * 0.5, y + h * 0.5)]
    corners = ((x + w - radius, y + radius, -90.0), (x + w - radius, y + h - radius, 0.0),
               (x + radius, y + h - radius, 90.0), (x + radius, y + radius, 180.0))
    for cx, cy, start in corners:
        for step in range(segments + 1):
            angle = math.radians(start + 90.0 * step / segments)
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    points.append(points[1])
    shader = _uniform_shader()
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": points})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _circle(x, y, radius, color):
    _round_rect(x - radius, y - radius, radius * 2.0, radius * 2.0, radius, color, segments=10)


def _font(size):
    try:
        blf.size(FONT, size)
    except TypeError:  # Blender 3.x also takes a DPI argument
        blf.size(FONT, size, 72)


def _text(x, y, text, size, color):
    _font(size)
    blf.color(FONT, *color)
    blf.position(FONT, x, y, 0)
    blf.draw(FONT, text)


def _width(text, size):
    _font(size)
    return blf.dimensions(FONT, text)[0]


def _wrap(text, size, max_width):
    _font(size)
    lines = []
    for paragraph in str(text).split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = (current + " " + word).strip()
            if current and blf.dimensions(FONT, candidate)[0] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def _ellipsize(text, size, max_width):
    if _width(text, size) <= max_width:
        return text
    while text and _width(text + "…", size) > max_width:
        text = text[:-1]
    return text + "…"


# ---------------------------------------------------------------------------
# Chat column.
# ---------------------------------------------------------------------------

def _games(messages):
    titles = []
    for message in messages:
        title = message.get("title")
        if message.get("role") == "assistant" and title:
            if title in titles:
                titles.remove(title)
            titles.append(title)
    return list(reversed(titles))


def _message_height(message, width, s):
    role = message.get("role")
    if role == "user":
        lines = _wrap(message.get("text", ""), 13 * s, width * 0.78 - 28 * s)
        return len(lines) * 19 * s + 22 * s
    if role == "error":
        lines = _wrap(message.get("text", ""), 13 * s, width - 60 * s)
        return len(lines) * 19 * s + 24 * s
    body = width - 44 * s
    height = 28 * s  # title
    if message.get("text"):
        height += len(_wrap(message["text"], 13 * s, body)) * 19 * s + 8 * s
    height += len(message.get("facts", [])) * 26 * s + 6 * s
    for note in message.get("notes", []):
        height += len(_wrap(note, 12 * s, body - 16 * s)) * 17 * s + 4 * s
    return height + 30 * s


def _draw_message(message, x, y_top, width, s):
    role = message.get("role")
    if role == "user":
        lines = _wrap(message.get("text", ""), 13 * s, width * 0.78 - 28 * s)
        text_w = max(_width(line, 13 * s) for line in lines)
        bubble_w = text_w + 28 * s
        height = len(lines) * 19 * s + 22 * s
        bx = x + width - bubble_w
        _round_rect(bx, y_top - height, bubble_w, height, 14 * s, PALETTE["bubble"])
        for index, line in enumerate(lines):
            _text(bx + 14 * s, y_top - 24 * s - index * 19 * s, line, 13 * s, PALETTE["text"])
        return height
    if role == "error":
        lines = _wrap(message.get("text", ""), 13 * s, width - 60 * s)
        height = len(lines) * 19 * s + 24 * s
        _round_rect(x, y_top - height, width, height, 12 * s, PALETTE["error"])
        for index, line in enumerate(lines):
            _text(x + 16 * s, y_top - 25 * s - index * 19 * s, line, 13 * s, PALETTE["text"])
        return height

    # Assistant: avatar, title, summary, facts as chips, design notes, footer.
    body_x = x + 40 * s
    body = width - 44 * s
    _circle(x + 14 * s, y_top - 14 * s, 13 * s, PALETTE["accent"])
    _text(x + 6 * s, y_top - 19 * s, "AI", 11 * s, (0.02, 0.06, 0.06, 1.0))
    cursor = y_top - 19 * s
    _text(body_x, cursor, message.get("title", "Game"), 16 * s, PALETTE["text"])
    cursor -= 28 * s
    if message.get("text"):
        for line in _wrap(message["text"], 13 * s, body):
            _text(body_x, cursor, line, 13 * s, PALETTE["muted"])
            cursor -= 19 * s
        cursor -= 4 * s
    for fact in message.get("facts", []):
        fact = _ellipsize(fact, 12 * s, body - 24 * s)
        chip_w = _width(fact, 12 * s) + 22 * s
        _round_rect(body_x, cursor - 8 * s, chip_w, 22 * s, 11 * s, PALETTE["chip"])
        _text(body_x + 11 * s, cursor - 1 * s, fact, 12 * s, PALETTE["text"])
        cursor -= 26 * s
    cursor -= 6 * s
    for note in message.get("notes", []):
        _circle(body_x + 3 * s, cursor + 4 * s, 2.5 * s, PALETTE["accent"])
        for line in _wrap(note, 12 * s, body - 16 * s):
            _text(body_x + 14 * s, cursor, line, 12 * s, PALETTE["text"])
            cursor -= 17 * s
        cursor -= 4 * s
    designer = "Claude" if message.get("source") == "claude" else "Offline planner"
    footer = "%s · %s objects · built in the panel on the right" % (designer, message.get("objects", "?"))
    _text(body_x, cursor - 6 * s, footer, 11 * s, PALETTE["muted"])
    return y_top - (cursor - 16 * s)


def _draw_empty_state(x, width, top, s):
    title = "What should we build?"
    _text(x + (width - _width(title, 26 * s)) * 0.5, top - 90 * s, title, 26 * s, PALETTE["text"])
    subtitle = "Describe a game in any language. The game appears on the right."
    _text(x + (width - _width(subtitle, 13 * s)) * 0.5, top - 120 * s, subtitle, 13 * s, PALETTE["muted"])
    card_w = (width - 12 * s) * 0.5
    card_h = 74 * s
    for index, (label, prompt) in enumerate(ai_game_creator.EXAMPLE_PROMPTS):
        column, row = index % 2, index // 2
        cx = x + column * (card_w + 12 * s)
        cy = top - 160 * s - row * (card_h + 12 * s) - card_h
        _round_rect(cx, cy, card_w, card_h, 12 * s, PALETTE["chip"])
        _text(cx + 14 * s, cy + card_h - 22 * s, label, 13 * s, PALETTE["accent"])
        for line_index, line in enumerate(_wrap(prompt, 11 * s, card_w - 28 * s)[:2]):
            _text(cx + 14 * s, cy + card_h - 42 * s - line_index * 15 * s, line, 11 * s, PALETTE["muted"])
    hint = "Pick one from Examples below, or type your own idea."
    _text(x + (width - _width(hint, 12 * s)) * 0.5, top - 360 * s, hint, 12 * s, PALETTE["muted"])


def draw_chat():
    context = bpy.context
    if not utils.is_studio_chat_area(context):
        return
    region = context.region
    scene = context.scene
    if region is None or scene is None or not hasattr(scene, "blendengine_ai"):
        return
    s = context.preferences.system.ui_scale
    width, height = region.width, region.height
    settings = scene.blendengine_ai
    messages = ai_game_creator.chat_messages(scene)

    gpu.state.blend_set("ALPHA")
    _round_rect(0, 0, width, height, 0, PALETTE["bg"])

    # Sidebar: brand, new game, games list, designer status.
    side = min(210 * s, width * 0.34)
    _round_rect(0, 0, side, height, 0, PALETTE["sidebar"])
    _round_rect(side - 1, 0, 1, height, 0, PALETTE["line"])
    _circle(20 * s, height - 26 * s, 6 * s, PALETTE["accent"])
    _text(34 * s, height - 31 * s, "BlendEngine AI", 14 * s, PALETTE["text"])
    _round_rect(12 * s, height - 72 * s, side - 24 * s, 28 * s, 8 * s, PALETTE["selected"])
    _text(24 * s, height - 63 * s, "+  New game", 12 * s, PALETTE["text"])
    _text(16 * s, height - 100 * s, "GAMES", 10 * s, PALETTE["muted"])
    current = None
    stored = ai_game_creator._stored_spec(scene) if settings.last_spec_json else None
    if stored is not None:
        current = stored["title"]
    y = height - 126 * s
    for title in _games(messages)[:14]:
        if title == current:
            _round_rect(8 * s, y - 8 * s, side - 16 * s, 26 * s, 7 * s, PALETTE["selected"])
            _circle(18 * s, y + 5 * s, 3 * s, PALETTE["accent"])
        _text(28 * s, y, _ellipsize(title, 12 * s, side - 44 * s), 12 * s,
              PALETTE["text"] if title == current else PALETTE["muted"])
        y -= 30 * s
    label, _icon = ai_game_creator.designer_status(context)
    _text(16 * s, 16 * s, _ellipsize(label, 11 * s, side - 28 * s), 11 * s, PALETTE["muted"])

    # Conversation column.
    left = side + 24 * s
    column = min(width - left - 24 * s, 720 * s)
    left += max(0.0, (width - left - 24 * s - column) * 0.5)
    header_h = 46 * s
    _round_rect(side, height - header_h, width - side, 1, 0, PALETTE["line"])
    heading = current or "New game"
    _text(left, height - 29 * s, _ellipsize(heading, 15 * s, column - 160 * s), 15 * s, PALETTE["text"])
    if current is not None:
        project = scene.blendengine_project
        state = project.test_status if project.test_running or project.test_status not in {"", "Not running"} else "Ready"
        chip = "Playing" if project.test_running else state
        chip_w = _width(chip, 11 * s) + 20 * s
        _round_rect(left + column - chip_w, height - 36 * s, chip_w, 22 * s, 11 * s, PALETTE["accent_dim"])
        _text(left + column - chip_w + 10 * s, height - 29 * s, chip, 11 * s, PALETTE["text"])

    if not messages and not settings.busy:
        _draw_empty_state(left, column, height - header_h, s)
        gpu.state.blend_set("NONE")
        return

    # Messages flow top-down like a chat; when they overflow, the oldest
    # ones scroll off the top so the latest exchange stays in view.
    top = height - header_h - 22 * s
    available = top - 18 * s - (44 * s if settings.busy else 0.0)
    shown, used = [], 0.0
    for message in reversed(messages):
        needed = _message_height(message, column, s)
        if shown and used + needed > available:
            break
        shown.insert(0, (message, needed))
        used += needed + 18 * s
    y = top
    for message, needed in shown:
        _draw_message(message, left, y, column, s)
        y -= needed + 18 * s
    if settings.busy:
        dots = "." * (1 + int(time.time() * 3) % 3)
        _circle(left + 14 * s, y - 14 * s, 13 * s, PALETTE["accent"])
        _text(left + 6 * s, y - 19 * s, "AI", 11 * s, (0.02, 0.06, 0.06, 1.0))
        _text(left + 40 * s, y - 19 * s, "Designing your game" + dots, 13 * s, PALETTE["muted"])
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------------------
# Headers: composer under the chat, game controls above the game.
# ---------------------------------------------------------------------------

class BE_MT_ai_examples(Menu):
    bl_idname = "BE_MT_ai_examples"
    bl_label = "Examples"

    def draw(self, _context):
        for index, (label, prompt) in enumerate(ai_game_creator.EXAMPLE_PROMPTS):
            op = self.layout.operator("blendengine.ai_chat_example", text="%s — %s" % (label, prompt[:60]))
            op.index = index


def draw_composer(layout, context):
    settings = context.scene.blendengine_ai
    s = context.preferences.system.ui_scale
    region_units = context.region.width / (20.0 * s) if context.region else 40.0
    row = layout.row(align=True)
    row.operator("blendengine.ai_chat_new", text="", icon="ADD")
    has_game = bool(settings.last_spec_json)
    if has_game:
        row.prop(settings, "chat_mode", text="")
    field = layout.row(align=True)
    field.ui_units_x = max(8.0, region_units - (24.0 if has_game else 15.0))
    field.enabled = not settings.busy
    field.scale_y = 1.2
    hint = "Ask for a change…" if has_game else "Describe a game…"
    try:  # placeholder text exists in newer Blender releases only
        field.prop(settings, "chat_input", text="", icon="SHADERFX", placeholder=hint)
    except TypeError:
        field.prop(settings, "chat_input", text="", icon="SHADERFX")
    send = layout.row(align=True)
    send.scale_y = 1.2
    if settings.busy:
        send.operator("blendengine.ai_cancel", text="Stop", icon="CANCEL")
    else:
        send.operator("blendengine.ai_chat_send", text="Send", icon="PLAY")
    layout.menu(BE_MT_ai_examples.bl_idname, text="Examples")
    layout.prop(settings, "provider", text="")


def draw_game_header(layout, context):
    scene = context.scene
    project = scene.blendengine_project
    space = context.space_data
    row = layout.row(align=True)
    row.label(text="Game", icon="PLAY")
    layout.separator_spacer()
    row = layout.row(align=True)
    row.scale_x = 1.2
    if project.test_running:
        row.operator("blendengine.stop_test_run", text="Stop", icon="PAUSE")
    else:
        row.operator("blendengine.test_run_scene", text="Play", icon="PLAY")
    row = layout.row(align=True)
    row.operator("blendengine.ai_variation", text="New Layout", icon="FILE_REFRESH")
    row.operator("blendengine.ai_show_spec", text="Spec", icon="TEXT")
    row.operator("blendengine.prepare_build", text="Build", icon="EXPORT")
    if space is not None and space.type == "VIEW_3D":
        layout.prop(space.shading, "type", text="", expand=True)
        layout.operator("blendengine.ai_studio_camera", text="", icon="CAMERA_DATA")


def _header_draw(self, context):
    if utils.is_studio_chat_area(context):
        draw_composer(self.layout, context)
    elif utils.is_studio_game_area(context):
        draw_game_header(self.layout, context)
    else:
        _original_header_draw(self, context)


# ---------------------------------------------------------------------------
# Workspace.
# ---------------------------------------------------------------------------

def _region(area, kind):
    return next((region for region in area.regions if region.type == kind), None)


def split_studio(window):
    """Leave one 3D View and split it into chat (left) and game (right)."""
    screen = window.screen
    views = utils.studio_view_areas(screen)
    if not views:
        return False
    main = max(views, key=lambda area: area.width * area.height)
    for area in list(screen.areas):
        if area != main:
            with bpy.context.temp_override(window=window, screen=screen, area=area):
                try:
                    bpy.ops.screen.area_close()
                except RuntimeError:
                    pass
    views = utils.studio_view_areas(screen)
    if len(views) < 2:
        with bpy.context.temp_override(window=window, screen=screen, area=views[0],
                                       region=_region(views[0], "WINDOW")):
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.4)
    return len(utils.studio_view_areas(screen)) >= 2


def _fit_camera(window, area):
    region = _region(area, "WINDOW")
    if region is None:
        return
    with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
        try:
            bpy.ops.view3d.view_center_camera()
        except RuntimeError:
            pass


def style_studio(window):
    """Style the chat and game areas. A freshly split area has no regions
    until it has been drawn once, so this runs on a later tick than the split."""
    screen = window.screen
    views = utils.studio_view_areas(screen)
    if len(views) < 2 or any(not area.regions for area in views):
        return False
    chat, game = views[0], views[-1]

    space = chat.spaces.active
    space.show_region_header = True
    for name in ("show_region_toolbar", "show_region_ui", "show_region_tool_header", "show_region_hud"):
        if hasattr(space, name):
            setattr(space, name, False)
    space.show_gizmo = False
    space.overlay.show_overlays = False
    space.shading.type = "SOLID"
    header = _region(chat, "HEADER")
    if header is not None and header.alignment == "TOP":
        with bpy.context.temp_override(window=window, screen=screen, area=chat, region=header):
            try:
                bpy.ops.screen.region_flip()
            except RuntimeError:
                pass

    space = game.spaces.active
    space.show_region_header = True
    for name in ("show_region_toolbar", "show_region_ui", "show_region_tool_header"):
        if hasattr(space, name):
            setattr(space, name, False)
    space.overlay.show_overlays = False
    space.show_gizmo = False
    space.shading.type = "RENDERED"
    if bpy.context.scene.camera is not None:
        space.region_3d.view_perspective = "CAMERA"
        _fit_camera(window, game)
    for area in (chat, game):
        area.tag_redraw()
    return True


def open_studio(context):
    window = context.window
    if window is None:
        return None
    workspace = bpy.data.workspaces.get(STUDIO)
    if workspace is None:
        source = bpy.data.workspaces.get("BlendEngine") or window.workspace
        window.workspace = source
        before = set(bpy.data.workspaces)
        with context.temp_override(window=window):
            bpy.ops.workspace.duplicate()
        created = [ws for ws in bpy.data.workspaces if ws not in before]
        workspace = created[0] if created else window.workspace
        workspace.name = STUDIO
    window.workspace = workspace

    state = {"split": False, "tries": 0}

    def _apply():
        # The workspace switch, the split and the first draw of the new area
        # each land on their own event loop tick, so take one step per tick.
        state["tries"] += 1
        for candidate in bpy.context.window_manager.windows:
            if candidate.workspace is None or candidate.workspace.name != STUDIO:
                continue
            if not state["split"]:
                split_studio(candidate)
                state["split"] = True
            elif style_studio(candidate):
                return None
            break
        return 0.2 if state["tries"] < 30 else None

    bpy.app.timers.register(_apply, first_interval=0.1)
    return workspace


def configure_studio(window):
    """Split and style in one call (used where no redraw is needed in between)."""
    split_studio(window)
    return style_studio(window)


class BE_OT_open_ai_studio(Operator):
    bl_idname = "blendengine.open_ai_studio"
    bl_label = "AI Studio"
    bl_description = "Open the chat-first AI Studio: talk to the AI on the left, play the game on the right"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if open_studio(context) is None:
            self.report({"ERROR"}, "AI Studio needs a window.")
            return {"CANCELLED"}
        return {"FINISHED"}


class BE_OT_ai_chat_send(Operator):
    bl_idname = "blendengine.ai_chat_send"
    bl_label = "Send"
    bl_description = "Send the message: design a new game, or change the current one"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        settings = scene.blendengine_ai
        text = settings.chat_input.strip()
        if not text:
            self.report({"WARNING"}, "Type a message first.")
            return {"CANCELLED"}
        base = ai_game_creator._stored_spec(scene) if settings.chat_mode == "CHANGE" else None
        try:
            if base is not None:
                settings.refine_prompt = text
                ai_game_creator.start_design(context, text, base_spec=base, replace_scene=True)
            else:
                settings.prompt = text
                ai_game_creator.start_design(context, text, replace_scene=settings.replace_scene)
        except planner.PlannerError as ex:
            ai_game_creator.record_chat(scene, "error", str(ex))
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        settings.chat_input = ""
        settings.chat_mode = "CHANGE"
        return {"FINISHED"}


class BE_OT_ai_chat_new(Operator):
    bl_idname = "blendengine.ai_chat_new"
    bl_label = "New Game"
    bl_description = "Start a new conversation; the next message designs a new game"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.blendengine_ai
        settings.chat_json = "[]"
        settings.chat_mode = "NEW"
        settings.chat_input = ""
        return {"FINISHED"}


class BE_OT_ai_chat_example(Operator):
    bl_idname = "blendengine.ai_chat_example"
    bl_label = "Use Example"
    bl_options = {"REGISTER", "INTERNAL"}

    index: IntProperty(default=0, min=0, max=len(ai_game_creator.EXAMPLE_PROMPTS) - 1)

    def execute(self, context):
        settings = context.scene.blendengine_ai
        settings.chat_input = ai_game_creator.EXAMPLE_PROMPTS[self.index][1]
        settings.chat_mode = "NEW"
        return {"FINISHED"}


class BE_OT_ai_studio_camera(Operator):
    bl_idname = "blendengine.ai_studio_camera"
    bl_label = "Game Camera"
    bl_description = "Look through the game camera"
    bl_options = {"REGISTER"}

    def execute(self, context):
        space = context.space_data
        if space is not None and space.type == "VIEW_3D" and context.scene.camera is not None:
            space.region_3d.view_perspective = "CAMERA"
            if context.window is not None and context.area is not None:
                _fit_camera(context.window, context.area)
        return {"FINISHED"}


classes = (
    BE_MT_ai_examples,
    BE_OT_open_ai_studio,
    BE_OT_ai_chat_send,
    BE_OT_ai_chat_new,
    BE_OT_ai_chat_example,
    BE_OT_ai_studio_camera,
)


def register():
    global _draw_handle, _original_header_draw
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_chat, (), "WINDOW", "POST_PIXEL")
    # The composer and game controls replace the 3D View header only inside
    # the AI Studio; every other 3D View keeps Blender's own header.
    _original_header_draw = bpy.types.VIEW3D_HT_header.draw
    bpy.types.VIEW3D_HT_header.draw = _header_draw


def unregister():
    global _draw_handle, _original_header_draw
    if _original_header_draw is not None:
        bpy.types.VIEW3D_HT_header.draw = _original_header_draw
        _original_header_draw = None
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

