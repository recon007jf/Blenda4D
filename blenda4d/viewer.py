# SPDX-License-Identifier: GPL-3.0-or-later
"""The Render Viewer: this session's renders, to look at, play and compare.

It opens in the viewport's place, under the tabs, or in a window of its own. The picture is Blender's Image Editor, so
a render shows while it is made; around it are Blenda's own parts (viewer_ui.py): menus and buttons above, Navigator,
History and the rest at the right, the frames below. Every render made from Blenda is kept in History: the frames are
the files Blender wrote or, when nothing is to be saved, files kept for this session only."""
import os
import re
import shutil
import tempfile
import time

import bpy
import numpy as np

from . import build, roles

TOP, SIDE, BOTTOM = "PV_TOP", "PV_SIDE", "PV_BOTTOM"
PARTS = (TOP, SIDE, BOTTOM)
WINDOW = (1200, 800)
TOP_PX, SIDE_PX, BOTTOM_PX = 60, 250, 92
RATES = (1, 5, 10, 12, 15, 18, 24, 25, 30, 48, 50, 60, 100)
FILTER = {"on": False, "sat": 0.0, "bright": 0.0, "contrast": 0.0, "exposure": 0.0, "gamma": 1.0, "black": 0.0,
          "white": 1.0, "r": True, "g": True, "b": True, "invert": False}
PREFIX = ".viewer "           # the names of the images made here: hidden, and never left in a saved file
EXTRA = []                    # more rows under the buttons, from other modules: (height in px, draw(layout, context))


class Frame:
    def __init__(self, number):
        self.number, self.path, self.seconds, self.state, self.thumb, self.tex = number, "", 0.0, "rendering", None, None
        self.saved, self.size, self.added, self.saved_path = False, (0, 0), time.strftime("%B %d, %Y, %I:%M %p"), ""


class Seq:
    def __init__(self, name, folder, fps):
        self.name, self.folder, self.fps, self.frames, self.open = name, folder, fps, [], True
        self.settings, self.kept = None, True              # kept: its files are the user's own, never deleted here
        self.rendered = False                              # made by a render here, not opened from a file (delete_files)

    @property
    def still(self):
        return len(self.frames) == 1


class State:
    def __init__(self):
        self.seqs, self.seq, self.index = [], None, 0
        self.play, self.repeat, self.rate, self.link = 0, "CYCLE", 0, False
        self.lo, self.hi = 0, 0
        self.tab_top, self.tab_side = "Navigator", "History"
        self.scroll, self.hits, self.rendering, self.side_on = 0, {}, False, True
        self.filter = dict(FILTER)
        self.pixels, self.pixels_key, self.hist_mode = None, None, "RGB"
        self.queue, self.keep_display, self.restore_path = [], None, None
        self.resume, self.goal, self.span, self.layers, self.transform = None, 0, None, False, "EMBEDDED"
        self.ab, self.diff, self.a, self.b, self.line, self.vertical, self.show_line, self.show_text = False, False, None, None, 0.5, True, True, True
        self.ab_px, self.four, self.pan, self.auto = {}, False, 0.0, True
        self.rows_room = self.rows_total = 1
        self.live = True          # while rendering: the picture follows the frame being made (off once you look back)


S = State()
_cache_root = [None]


# --- where it is ------------------------------------------------------------------------------------------------------
def window():
    """The window that shows the viewer, or None."""
    wm = bpy.context.window_manager
    for w in wm.windows if wm else ():
        if any(roles.role(a) == TOP for a in w.screen.areas):
            return w
    return None


def top_px():
    return TOP_PX + sum(e[0] for e in EXTRA)


def _top(screen):
    return next((a for a in screen.areas if roles.role(a) == TOP), None)


def editor(win=None):
    """The picture's area: the one right under the viewer's top rows."""
    win = win or window()
    top = _top(win.screen) if win is not None else None
    if top is None:
        return None
    gap = 6 + round(4 * build._scale())
    under = [a for a in win.screen.areas if a.type in {"IMAGE_EDITOR", "VIEW_3D"} and abs(a.y + a.height - top.y) <= gap
             and top.x - 4 <= a.x < top.x + top.width]
    return min(under, key=lambda a: a.x) if under else None


def docked(win=None):
    """Is it in the viewport's place (not in a window of its own)?"""
    win = win or window()
    return win is not None and _top(win.screen) is not None and bool(roles.areas(win.screen, "OBJECTS"))


def parts(screen):
    return [a for a in screen.areas if roles.role(a) in PARTS]


def is_part(context):
    """Is the pointer over the viewer?"""
    a = context.area
    if a is None or context.window is None:
        return False
    return roles.role(a) in PARTS or (a.type in {"IMAGE_EDITOR", "VIEW_3D"} and _top(context.screen) is not None and a == editor(context.window))


def redraw():
    w = window()
    for a in w.screen.areas if w is not None else ():
        a.tag_redraw()


# --- into the viewport's place, and out again -------------------------------------------------------------------------
def _split_parts(win, area, tabs):
    """The picture's area is split into the viewer's parts."""
    for name, direction, size, side in ([("VIEW_TABS", "HORIZONTAL", build.px(build.VIEW_TABS_PX) + build.EDGE, "TOP")] if tabs else []) + [
            (TOP, "HORIZONTAL", build.px(top_px()) + build.EDGE, "TOP"), (BOTTOM, "HORIZONTAL", build.px(BOTTOM_PX) + build.EDGE, "BOTTOM"),
            (SIDE, "VERTICAL", build.px(SIDE_PX) + build.EDGE, "RIGHT")]:
        room = area.height if direction == "HORIZONTAL" else area.width
        if name == SIDE and room < 1.6 * size:             # a small place keeps it for the picture
            continue
        before = {a.as_pointer() for a in win.screen.areas}
        piece = yield from build.split(win, area, direction, min(size, round(room * 0.45)), side)
        pair = [a for a in win.screen.areas if a.as_pointer() not in before] + [area]
        area = next(a for a in pair if a != piece)
        yield from build.make_role(win, piece, name)
    _dress(area)


def dock_steps(win):
    """The viewer takes the viewport's place. The area keeps its 3D view, which comes back as it was (leave_steps)."""
    from . import quadview, render_settings
    screen = win.screen
    if _top(screen) is not None:
        return
    render_settings.show_view(screen)
    yield
    S.four = len(quadview.views(screen)) > 1
    if S.four:
        yield from quadview.expand_steps(win, build._persp(screen))
    view = build.biggest_view(screen)
    view.type = "IMAGE_EDITOR"
    view.ui_type = "IMAGE_EDITOR"
    yield
    yield from _split_parts(win, view, True)
    _after_dock(win)


def _after_dock(win):
    if S.seq is not None:
        show(S.seq, S.index)
    for a in win.screen.areas:
        a.tag_redraw()


def leave_steps(win):
    """Back to the viewport. Does nothing when the viewer is not in this window."""
    from . import quadview
    screen = win.screen
    if _top(screen) is None or not roles.areas(screen, "OBJECTS"):
        return
    S.play = 0
    for role in (SIDE, BOTTOM, TOP, "VIEW_TABS"):
        pic = _pic(win)
        for a in roles.areas(screen, role):
            if pic is not None:
                yield from quadview._join(win, a, pic)
                pic = _pic(win)
    pic = _pic(win)
    if pic is not None:
        pic.type = "VIEW_3D"
    yield
    for a in screen.areas:
        if a.type == "VIEW_3D":
            build.dress_view(a)
    _forget_images()
    if S.four:
        S.four = False
        yield from quadview.split_steps(win)
    for a in screen.areas:
        a.tag_redraw()


_kept = {}


def _pic(win):
    """The picture's area, also while its parts are being joined back into it."""
    a = editor(win)
    if a is not None:
        _kept["ptr"] = a.as_pointer()
        return a
    return next((a for a in win.screen.areas if a.as_pointer() == _kept.get("ptr")), None)


def _dress(area):
    if area is None or area.type != "IMAGE_EDITOR":
        return
    sp = area.spaces.active
    for attr in ("show_region_header", "show_region_tool_header", "show_region_ui", "show_region_toolbar", "show_region_asset_shelf",
                 "show_annotation", "show_gizmo"):
        try:
            setattr(sp, attr, False)
        except (AttributeError, TypeError):
            pass
    sp.display_channels = "COLOR"
    try:
        sp.overlay.show_overlays = False
    except (AttributeError, TypeError):
        pass
    if S.rendering:
        sp.image = bpy.data.images.get("Render Result")


def open_docked(context):
    """In the viewport's place when this window has Blenda's layout, else in a window of its own."""
    win = window()
    if win is not None:
        return True
    main = next((w for w in context.window_manager.windows if roles.areas(w.screen, "OBJECTS")), None)
    if main is None:
        return open_window(context)
    if not build.busy():
        build.run_steps(dock_steps(main))
    return True


def open_window(context):
    """A window of its own."""
    if window() is not None:
        return True
    wm = context.window_manager
    before = {w.as_pointer() for w in wm.windows}
    bpy.ops.screen.drivers_editor_show("INVOKE_DEFAULT")       # Blender's way to open a small floating window
    win = next((w for w in wm.windows if w.as_pointer() not in before), None)
    if win is None:
        return False
    win.screen.areas[0].type = "IMAGE_EDITOR"

    def steps():
        for _ in range(60):                                # until Blender has laid the new window out
            area = win.screen.areas[0]
            region = build._region(area, "WINDOW")
            if region is not None and region.height > 200:
                break
            yield
        yield
        yield from _split_parts(win, win.screen.areas[0], False)
        _after_dock(win)
    build.run_steps(steps())
    return True


def close_window():
    win = window()
    if win is not None and not docked(win):
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.window_close()


# --- the picture --------------------------------------------------------------------------------------------------------
def current():
    if S.seq is None or not S.seq.frames:
        return None
    return S.seq.frames[min(S.index, len(S.seq.frames) - 1)]


def _space():
    a = editor()
    return a.spaces.active if a is not None and a.type == "IMAGE_EDITOR" else None


def zoom_percent():
    sp = _space()
    return int(round(sp.zoom[0] * 100 / (bpy.context.preferences.system.pixel_size or 1))) if sp is not None else 100


def view(fn, **kw):
    """Run one of Blender's image commands on the picture."""
    win, area = window(), editor()
    if area is None or area.type != "IMAGE_EDITOR":
        return
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=win, area=area, region=region):
        try:
            fn(**kw)
        except RuntimeError:
            pass


def set_zoom(percent):
    S.auto = False
    view(bpy.ops.image.view_zoom_ratio, ratio=percent / 100.0 * (bpy.context.preferences.system.pixel_size or 1))
    redraw()


def fit():
    S.auto = True
    view(bpy.ops.image.view_all, fit_view=True)


ROOM = 1.5e9                  # bytes of pictures kept ready to show
_ready = {}                   # file -> the image that has it, the one shown last at the end


def _image_of(frame):
    """The image of a frame's file. Each frame is an image of its own; the ones not shown for long are let go."""
    path = frame.path
    img = bpy.data.images.get(_ready.pop(path, ""))
    if img is None:
        if not os.path.exists(path):
            return bpy.data.images.get("Render Result")
        img = bpy.data.images.load(path, check_existing=False)
        img.name = f"{PREFIX}{len(_ready)} {os.path.basename(path)}"
    _ready[path] = img.name
    size = max(1, frame.size[0] * frame.size[1] * 4)
    while len(_ready) > 2 and len(_ready) * size > ROOM:
        old = bpy.data.images.get(_ready.pop(next(iter(_ready))))
        if old is not None:
            bpy.data.images.remove(old)
    img.use_view_as_render = S.transform == "SCENE"
    return img


def _drop(paths):
    """Let go of these files' images."""
    for p in paths:
        img = bpy.data.images.get(_ready.pop(p, ""))
        if img is not None:
            bpy.data.images.remove(img)


def show(seq, index):
    """Put a frame in the picture. Blender's Image Editor keeps the frames it has read, so a sequence plays."""
    S.seq, S.index, S.layers = seq, max(0, min(index, len(seq.frames) - 1)), False
    sp, frame = _space(), current()
    if sp is None or frame is None:
        return redraw()
    if compare_ready():
        compare()
        return redraw()
    if S.rendering:                                    # looking back at a finished frame stops following the render
        S.live = frame.state == "rendering" or not frame.path
    if not frame.path or (frame.state == "rendering" and S.rendering):
        sp.image = bpy.data.images.get("Render Result")
    elif S.filter["on"]:
        px = pixels()
        if px is not None:
            to_screen(filtered(px, S.filter), frame.size)
    else:
        img = _image_of(frame)
        if img is not None and img.source == "MOVIE":
            iu = sp.image_user
            # the Image Editor works a movie's frame out from the scene's own: the start is what picks it
            iu.frame_duration, iu.use_auto_refresh, iu.frame_offset = len(seq.frames), False, 0
            iu.frame_start = bpy.context.scene.frame_current - S.index
            sp.image = None                                # only a new image makes it read the frame again
        sp.image = img
    if S.auto:
        bpy.app.timers.register(_fit_soon, first_interval=0.02)
    if S.link and not S.rendering:
        bpy.context.scene.frame_set(frame.number)
    redraw()


def _fit_soon():
    if S.auto:
        view(bpy.ops.image.view_all, fit_view=True)
    return None


def show_layers():
    """The latest render itself, whose layers and passes can be picked."""
    sp, img = _space(), bpy.data.images.get("Render Result")
    if sp is None or img is None:
        return False
    S.layers = True
    sp.image = img
    redraw()
    return True


def load_pixels(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        return px.reshape(-1, 4), (w, h)
    finally:
        bpy.data.images.remove(img)


def pixels():
    frame = current()
    if frame is None or not frame.path or not os.path.exists(frame.path) or S.rendering or frame.path.lower().endswith(MOVIES):
        return None
    if S.pixels_key != frame.path:
        S.pixels, _size = load_pixels(frame.path)
        S.pixels_key = frame.path
    return S.pixels


MOVIES = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".ogv", ".mpg", ".mpeg", ".m4v")


def filtered(px, f):
    """Exposure, brightness and contrast, the black and white points, saturation, gamma, the channels, invert."""
    rgb = px[:, :3] * 2.0 ** f["exposure"] + f["bright"] / 100.0
    rgb = (rgb - 0.5) * (1.0 + f["contrast"] / 100.0) + 0.5
    rgb = (rgb - f["black"]) / max(f["white"] - f["black"], 1e-5)
    lum = (rgb @ np.array((.2126, .7152, .0722), dtype=np.float32))[:, None]
    rgb = np.maximum(lum + (rgb - lum) * (1.0 + f["sat"] / 100.0), 0.0) ** (1.0 / max(f["gamma"], 0.01))
    for i, key in enumerate("rgb"):
        if not f[key]:
            rgb[:, i] = 0.0
    if f["invert"]:
        rgb = 1.0 - rgb
    return np.concatenate((rgb, px[:, 3:]), axis=1)


def to_screen(px, size):
    name = PREFIX + "picture"
    img = bpy.data.images.get(name)
    if img is None or tuple(img.size) != tuple(size):
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(name, size[0], size[1], alpha=True)
    img.pixels.foreach_set(px.astype(np.float32).ravel())
    img.update()
    sp = _space()
    if sp is not None:
        sp.image = None
        sp.image = img


def refresh():
    if S.seq is not None and current() is not None:
        show(S.seq, S.index)


def _forget_images():
    """The images made here go, so none is left in a saved file."""
    sp = _space()
    if sp is not None and sp.image is not None and sp.image.name.startswith(PREFIX):
        sp.image = None
    for img in [i for i in bpy.data.images if i.name.startswith(PREFIX)]:
        bpy.data.images.remove(img)
    _ready.clear()


# --- comparing two frames -------------------------------------------------------------------------------------------------
def _size_of(ref):
    return ref[0].frames[ref[1]].size


def compare_ready():
    return bool(S.ab and S.a and S.b and not S.rendering and _size_of(S.a) == _size_of(S.b))


def _ref_pixels(ref):
    path = ref[0].frames[ref[1]].path
    if path not in S.ab_px:
        if len(S.ab_px) >= 2:
            S.ab_px.clear()
        S.ab_px[path] = load_pixels(path)
    return S.ab_px[path]


def compare():
    """One picture made of both: A up to the line and B past it, or how much they differ."""
    if not compare_ready():
        return
    one, size = _ref_pixels(S.a)
    two = _ref_pixels(S.b)[0]
    w, h = size
    if S.diff:
        out = np.abs(one - two)
        out[:, 3] = 1.0
    else:
        pick = np.tile(np.arange(w) < int(S.line * w), h) if S.vertical else np.repeat(np.arange(h) >= int(S.line * h), w)
        out = np.where(pick[:, None], one, two)
    to_screen(out, size)


def mark(which):
    setattr(S, which, (S.seq, S.index) if current() is not None and current().path else None)
    S.ab_px.clear()
    if S.ab:
        compare()


def toggle_ab():
    S.ab = not S.ab
    if S.ab and S.a is None:
        mark("a")
    if not S.ab:
        S.diff = False
    refresh()


def swap_ab():
    S.a, S.b = S.b, S.a
    S.ab_px.clear()
    compare()


# --- playing ------------------------------------------------------------------------------------------------------------------
def fps():
    return S.rate or (S.seq.fps if S.seq else 24)


def first_last():
    if S.seq is None or not S.seq.frames:
        return 0, 0
    return S.seq.frames[0].number, S.seq.frames[-1].number


def _last_done():
    """Index of the last finished frame of the sequence (while rendering, the ones after it are not made yet)."""
    for i in range(len(S.seq.frames) - 1, -1, -1):
        if S.seq.frames[i].state == "done" and S.seq.frames[i].path:
            return i
    return -1


def _playback():
    if not S.play or S.seq is None or len(S.seq.frames) < 2 or window() is None:
        S.play = 0
        redraw()
        return None
    first = S.seq.frames[0].number
    i, low, high = S.index + S.play, S.lo - first, S.hi - first
    if S.rendering:                                     # play what is made, and stop at the newest finished frame
        high = min(high, _last_done())
        if i > high:
            S.play = 0
            redraw()
            return None
    if i > high or i < low:
        if S.repeat == "SIMPLE":
            S.play = 0
            redraw()
            return None
        if S.repeat == "PINGPONG":
            S.play = -S.play
            i = S.index + S.play
        else:
            i = low if S.play > 0 else high
    show(S.seq, i)
    return 1.0 / max(fps(), 1)


def play(direction):
    was, S.play = S.play, 0 if S.play == direction else direction
    if S.play and not was and not bpy.app.timers.is_registered(_playback):
        bpy.app.timers.register(_playback, first_interval=0.0)
    redraw()


def go(index):
    S.play = 0
    if S.seq is not None:
        show(S.seq, index)


def set_range(end, value):
    a, b = first_last()
    value = int(min(max(value, a), b))
    if end == 0:
        S.lo = min(value, S.hi)
    else:
        S.hi = max(value, S.lo)


@bpy.app.handlers.persistent
def _scene_frame(_scene, *_a):
    """The scene went to another frame: a movie keeps showing its own."""
    if not S.rendering and not S.link and S.seq is not None and not S.seq.still and not S.play and not S.layers \
            and S.seq.frames and S.seq.frames[0].path.lower().endswith(MOVIES) and not bpy.app.is_job_running("RENDER") and window() is not None:
        show(S.seq, S.index)


# --- renders into History ----------------------------------------------------------------------------------------------------
def cache():
    if _cache_root[0] is None:
        _cache_root[0] = tempfile.mkdtemp(prefix="blenda_viewer_")
    return _cache_root[0]


def begin(scene, first, last, keep, seq=None):
    """Right before a render starts. keep: Blender writes to the scene's own output path; else to this session's files."""
    S.play = 0
    if seq is None:
        name = bpy.path.display_name_from_filepath(bpy.data.filepath) or scene.name
        folder = os.path.join(cache(), f"{len(S.seqs):04d}_{int(time.time())}")
        os.makedirs(folder, exist_ok=True)
        seq = Seq(name, folder, int(round(scene.render.fps / max(scene.render.fps_base, 1e-6))))
        seq.kept, seq.rendered = keep, True
        try:
            from . import render_settings
            seq.settings = render_settings.capture(scene)
        except (AttributeError, RuntimeError):
            pass
        S.seqs.append(seq)
        S.lo = first
    S.seq, S.index, S.rendering, S.layers, S.ab = seq, max(0, len(seq.frames) - 1), True, False, False
    S.live = True
    S.hi, S.goal, S.resume = last, last, None
    S.restore_path = None
    if not keep:
        S.restore_path = scene.render.filepath
        scene.render.filepath = os.path.join(seq.folder, "f")
    prefs = bpy.context.preferences.view
    S.keep_display = prefs.render_display_type
    prefs.render_display_type = "NONE"                     # the render shows here, not in a window of Blender's
    for h, fn in (("render_pre", _on_pre), ("render_write", _on_write), ("render_complete", _on_end), ("render_cancel", _on_end)):
        hs = getattr(bpy.app.handlers, h)
        if fn not in hs:
            hs.append(fn)
    open_docked(bpy.context)
    sp = _space()
    if sp is not None:
        sp.image = bpy.data.images.get("Render Result")
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, first_interval=0.1, persistent=True)


def failed():
    """The render did not start."""
    S.queue.append(("end", 0, time.time(), None))


# the next three run on the render's own thread: no Blender data is touched there
@bpy.app.handlers.persistent
def _on_pre(scene, *_a):
    if S.rendering:
        S.queue.append(("pre", scene.frame_current, time.time(), None))


@bpy.app.handlers.persistent
def _on_write(scene, *_a):
    if S.rendering:
        r = scene.render
        S.queue.append(("post", scene.frame_current, time.time(),
                        (r.frame_path(frame=scene.frame_current), bpy.path.abspath(r.filepath) + r.file_extension, bpy.path.abspath(r.filepath))))


@bpy.app.handlers.persistent
def _on_end(*_a):
    if S.rendering:
        S.queue.append(("end", 0, time.time(), None))


def _drain():
    while S.queue:
        kind, number, now, paths = S.queue.pop(0)
        seq = S.seq if S.rendering else None
        if seq is None or seq not in S.seqs:
            continue
        if kind == "pre":
            if seq.frames and seq.frames[-1].state == "rendering" and seq.frames[-1].number == number:
                continue
            frame = Frame(number)
            frame.seconds = now
            r = bpy.context.scene.render
            frame.size = (r.resolution_x * r.resolution_percentage // 100, r.resolution_y * r.resolution_percentage // 100)
            seq.frames.append(frame)
            if S.live:
                S.index = len(seq.frames) - 1
        elif kind == "post" and seq.frames:
            f = seq.frames[-1]
            f.path = next((p for p in paths if os.path.isfile(p)), "")
            f.state, f.seconds, f.saved = "done", now - f.seconds, seq.kept
        elif kind == "end":
            _ended(seq)
            return None
    if S.rendering and S.live:
        sp = _space()
        if sp is not None and (sp.image is None or sp.image.type != "RENDER_RESULT"):
            sp.image = bpy.data.images.get("Render Result")
            bpy.app.timers.register(_fit_soon, first_interval=0.05)
        redraw()
    return 0.1


def _ended(seq):
    S.rendering = False
    scene = bpy.context.scene
    if S.span:
        scene.frame_start, scene.frame_end = S.span
        S.span = None
    if S.restore_path is not None:
        scene.render.filepath, S.restore_path = S.restore_path, None
    if S.keep_display:
        bpy.context.preferences.view.render_display_type, S.keep_display = S.keep_display, None
    movie = next((f.path for f in seq.frames if f.path.lower().endswith(MOVIES)), None)
    for f in seq.frames:
        f.path = movie or f.path
    seq.frames[:] = [f for f in seq.frames if f.state == "done" and f.path]
    if not seq.frames:
        S.seqs.remove(seq)
        S.seq, S.index = (S.seqs[-1], 0) if S.seqs else (None, 0)
        redraw()
        return
    S.lo, S.hi = seq.frames[0].number, seq.frames[-1].number
    S.resume = (seq, seq.frames[-1].number + 1, S.goal) if not movie and seq.frames[-1].number < S.goal else None
    _drop([f.path for f in seq.frames])
    S.pixels_key = None
    show(seq, len(seq.frames) - 1)
    bpy.app.timers.register(_thumbs, first_interval=0.1)


def _thumbs():
    """The small pictures, after the render: reading images while one runs can crash Blender."""
    if S.rendering or bpy.app.is_job_running("RENDER"):
        return None
    f = next((f for q in S.seqs for f in q.frames if f.thumb is None and f.path and not f.path.lower().endswith(MOVIES)
              and os.path.exists(f.path)), None)
    if f is None:
        return None
    try:
        px, f.size = load_pixels(f.path)
    except RuntimeError:
        f.thumb = np.zeros((1, 1, 4), dtype=np.float32)
        return 0.01
    w, h = f.size
    step = max(1, w // 128)
    grid = px.reshape(h, w, 4)[::step, ::step].copy()
    grid[..., 3] = 1.0
    f.thumb = grid.astype(np.float32)
    redraw()
    return 0.01


def resume():
    """Go on with a render that was stopped: the frames that were never made, into the same folder."""
    if S.resume is None or S.rendering:
        return
    seq, first, last = S.resume
    scene = bpy.context.scene
    S.span = (scene.frame_start, scene.frame_end)
    begin(scene, first, last, seq.kept, seq)
    scene.frame_start, scene.frame_end = first, last
    main = next((w for w in bpy.context.window_manager.windows if roles.areas(w.screen, "OBJECTS")), bpy.context.window)
    try:
        with bpy.context.temp_override(window=main):
            bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
    except RuntimeError:
        failed()


def add_file(path):
    """An image, or the numbered sequence it belongs to, or a movie, into History."""
    folder, name = os.path.split(path)
    found = [(0, path)]
    m = re.match(r"(.*?)(\d+)(\.\w+)$", name)
    if m and not path.lower().endswith(MOVIES):
        head, digits, ext = m.groups()
        hits = (re.fullmatch(re.escape(head) + r"(\d{%d})" % len(digits) + re.escape(ext), f) for f in os.listdir(folder))
        numbered = sorted((int(h.group(1)), os.path.join(folder, h.group(0))) for h in hits if h)
        if len(numbered) > 1:
            found = numbered
    rate = bpy.context.scene.render.fps
    seq = Seq(os.path.splitext(name)[0], folder, rate)
    if path.lower().endswith(MOVIES):
        img = bpy.data.images.load(path, check_existing=False)
        found = [(i + 1, path) for i in range(max(1, img.frame_duration))]
        size = tuple(img.size)
        bpy.data.images.remove(img)
    else:
        size = load_pixels(found[0][1])[1]
    for number, file in found:
        f = Frame(number)
        f.path, f.state, f.saved, f.size = file, "done", True, size
        seq.frames.append(f)
    S.seqs.append(seq)
    S.lo, S.hi = seq.frames[0].number, seq.frames[-1].number
    show(seq, 0)
    bpy.app.timers.register(_thumbs, first_interval=0.1)


def remove_frame(seq, index):
    """Take one frame out of History. A file kept for the session only goes with it; a file you saved stays."""
    if len(seq.frames) < 2 or seq.frames[0].path.lower().endswith(MOVIES):
        return remove([seq])
    f = seq.frames.pop(index)
    _drop([f.path])
    if not seq.kept and _cache_root[0] and f.path.startswith(_cache_root[0]):
        try:
            os.remove(f.path)
        except OSError:
            pass
    S.a, S.b, S.ab = None, None, False                     # A and B name frames by their place
    S.ab_px.clear()
    S.lo, S.hi = seq.frames[0].number, seq.frames[-1].number
    show(seq, min(index, len(seq.frames) - 1))


def delete_files(seq):
    """Delete a render's files from disk and take it out of History: only a render made here, never pictures that
    were opened from a file. Rows of other renders that showed the same files go too (renders written to the same
    folder share them). Gives the number of files deleted."""
    if not seq.rendered:
        return 0
    paths = {f.path for f in seq.frames}
    _drop(paths)
    gone = 0
    for path in paths:
        try:
            os.remove(path)
            gone += 1
        except OSError:
            pass
    for q in S.seqs:
        q.frames[:] = [f for f in q.frames if f.path not in paths]
    S.a, S.b, S.ab = None, None, False
    S.ab_px.clear()
    remove([q for q in S.seqs if not q.frames])
    return gone


def remove(seqs):
    """Take renders out of History. Files kept for the session go with them; files you saved stay."""
    for q in list(seqs):
        _drop([f.path for f in q.frames])
        if not q.kept and _cache_root[0] and q.folder.startswith(_cache_root[0]):
            shutil.rmtree(q.folder, ignore_errors=True)
        if q in S.seqs:
            S.seqs.remove(q)
        for k in ("a", "b"):
            if getattr(S, k) and getattr(S, k)[0] is q:
                setattr(S, k, None)
    if S.seq not in S.seqs:
        S.seq, S.index = (S.seqs[-1], 0) if S.seqs else (None, 0)
    sp = _space()
    if S.seq is not None:
        show(S.seq, S.index)
    elif sp is not None:
        sp.image = None
    redraw()


# --- files ---------------------------------------------------------------------------------------------------------------------
@bpy.app.handlers.persistent
def _before_save(*_a):
    _forget_images()


@bpy.app.handlers.persistent
def _after_save(*_a):
    if window() is not None and not S.rendering:
        refresh()


@bpy.app.handlers.persistent
def _loaded(*_a):
    """Another file: History stays, its images are read again when they are shown."""
    S.play, S.four, S.pixels_key, S.ab = 0, False, None, False
    _ready.clear()


_outside = []


@bpy.app.handlers.persistent
def _on_init(scene, *_a):
    """A render Blenda did not start (Blender's own F12 or Ctrl+F12, a script, another add-on): the Render Viewer
    follows it too. This may run on the render's thread, so the viewer is set up from a timer on the main one."""
    if not S.rendering and not _outside:
        _outside.append((scene.name, scene.frame_current, scene.frame_start, scene.frame_end))
        bpy.app.timers.register(_adopt, first_interval=0.0)


def _adopt():
    if not _outside:
        return None
    name, now, first, last = _outside.pop()
    _outside.clear()
    scene = bpy.data.scenes.get(name)
    if scene is None or S.rendering:
        return None
    try:
        begin(scene, now, last, keep=True)            # Blender writes where the scene says: nothing is moved
    except Exception as e:
        print("Blenda 4D: Render Viewer could not follow the render", e)
    return None


_kept_display = [None]


def own_render_display(on):
    """In Blenda mode every render shows in the Render Viewer only: Blender's own render window is switched off (its
    preference set to Keep User Interface) so it never opens, even for F12 or a script's render. Closing that window
    once it is open is no answer: closing it cancels the render. Back in Blender mode the preference returns."""
    v = bpy.context.preferences.view
    if on:
        from . import prefs_memory
        kept = prefs_memory.original(v, "render_display_type", v.render_display_type, "NONE")
        if kept != "NONE":
            _kept_display[0] = kept
        v.render_display_type = "NONE"
    else:
        if v.render_display_type == "NONE":
            v.render_display_type = _kept_display[0] or "WINDOW"
        _kept_display[0] = None


HANDLERS = (("render_init", _on_init), ("save_pre", _before_save), ("save_post", _after_save), ("load_post", _loaded), ("frame_change_post", _scene_frame))


def register():
    for name, fn in HANDLERS:
        h = getattr(bpy.app.handlers, name)
        if fn not in h:
            h.append(fn)
    from . import viewer_ui
    viewer_ui.register()


def unregister():
    from . import viewer_ui
    viewer_ui.unregister()
    for name, fn in HANDLERS + (("render_pre", _on_pre), ("render_write", _on_write), ("render_complete", _on_end), ("render_cancel", _on_end)):
        h = getattr(bpy.app.handlers, name)
        if fn in h:
            h.remove(fn)
    for t in (_playback, _drain, _thumbs):
        if bpy.app.timers.is_registered(t):
            bpy.app.timers.unregister(t)
    if S.keep_display:
        bpy.context.preferences.view.render_display_type = S.keep_display
    win = window()
    if win is not None:
        if docked(win):                                    # Blenda is being turned off: its layout goes with it
            _forget_images()
        else:
            close_window()
    S.__init__()
    if _cache_root[0]:
        shutil.rmtree(_cache_root[0], ignore_errors=True)
        _cache_root[0] = None
