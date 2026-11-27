# SPDX-License-Identifier: GPL-3.0-or-later
"""The Render Viewer's parts (viewer.py): the menus and buttons above the picture, the column at its right (Navigator or
Histogram; History, Info, Layer, Filter) and the frames below it. Every key is also in the menus."""
import os
import subprocess
import sys

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d

from . import menus, roles, strip, viewer as V

S = V.S
BG = (0.169, 0.169, 0.169, 1.0)
FIELD = (0.11, 0.11, 0.11, 1.0)
BUTTON = (0.225, 0.225, 0.225, 1.0)
ACTIVE = (0.294, 0.294, 0.427, 1.0)
LINE = (0.11, 0.11, 0.11, 1.0)
ROW = (0.15, 0.15, 0.15, 0.6)
TEXT = (0.82, 0.82, 0.82, 1.0)
DIM = (0.55, 0.55, 0.55, 1.0)
GREEN = (0.42, 0.85, 0.52, 1.0)
ORANGE = (0.95, 0.65, 0.25, 1.0)
RED = (0.85, 0.2, 0.2, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
_handles, _keymaps = [], []


# --- drawing ------------------------------------------------------------------------------------------------------------
def _s():
    return bpy.context.preferences.system.ui_scale


def _hit(role, box, action, drag=False):
    S.hits.setdefault(role, []).append((box, action, drag))


def _width(text, size=12):
    blf.size(0, size * _s())
    return blf.dimensions(0, text)[0]


def _label(x, y, text, color=TEXT, size=12):
    gpu.state.blend_set("ALPHA")
    blf.size(0, size * _s())
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, text)
    gpu.state.blend_set("NONE")


def _clip(text, width, size=12):
    if _width(text, size) <= width:
        return text
    while text and _width(text + "...", size) > width:
        text = text[:-1]
    return text + "..."


def _button(x0, y0, x1, y1, color=BUTTON):
    strip._round_rect(x0, y0, x1, y1, 3 * _s(), color)


def _lines(pts, color, width=1.2):
    sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(sh, "LINE_STRIP", {"pos": [(p[0], p[1], 0.0) for p in pts]})
    gpu.state.blend_set("ALPHA")
    sh.bind()
    sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    sh.uniform_float("lineWidth", width * _s())
    sh.uniform_float("color", color)
    batch.draw(sh)
    gpu.state.blend_set("NONE")


def _disc(cx, cy, r, color):
    strip._round_rect(cx - r, cy - r, cx + r, cy + r, r, color)


def _tri(pts, color):
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(sh, "TRIS", {"pos": pts})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def _transport(name, cx, cy, r, color):
    """The play buttons' shapes."""
    if name == "pause":
        for d in (-0.45, 0.45):
            strip._rect(cx + d * r - 1.5 * _s(), cy - r * .8, cx + d * r + 1.5 * _s(), cy + r * .8, color)
        return
    w = -1 if name in ("first", "prev", "back") else 1
    if name in ("first", "last", "prev", "next"):
        bar = cx + w * r * (.75 if name in ("first", "last") else -.75)
        strip._rect(bar - _s(), cy - r * .8, bar + _s(), cy + r * .8, color)
    _tri([(cx + w * r * .6, cy), (cx - w * r * .55, cy + r * .8), (cx - w * r * .55, cy - r * .8)], color)


def _tab(role, x0, y0, x1, y1, label, on, action):
    _button(x0, y0, x1, y1, ACTIVE if on else BUTTON)
    _label((x0 + x1 - _width(label)) / 2, (y0 + y1) / 2 - 4 * _s(), label, WHITE if on else TEXT)
    _hit(role, (x0, y0, x1, y1), action)


def _field(role, x0, y0, x1, y1, text, action=None):
    _button(x0, y0, x1, y1, FIELD)
    text = _clip(text, x1 - x0 - 6 * _s())
    _label((x0 + x1 - _width(text)) / 2, (y0 + y1) / 2 - 4 * _s(), text)
    if action:
        _hit(role, (x0, y0, x1, y1), action)


# --- the column at the right ----------------------------------------------------------------------------------------------
def _thumb(frame):
    """The texture of a frame's small picture: it can only be made while drawing."""
    if frame is None or frame.thumb is None:
        return None
    if frame.tex is None:
        h, w = frame.thumb.shape[:2]
        frame.tex = gpu.types.GPUTexture((w, h), format="RGBA16F", data=gpu.types.Buffer("FLOAT", w * h * 4, frame.thumb.ravel()))
    return frame.tex


def _draw_side(region):
    s, w, h = _s(), region.width, region.height
    strip._rect(0, 0, w, h, BG)
    m, y = 6 * s, h - 6 * s
    half = (w - 2 * m - 4 * s) / 2
    for i, name in enumerate(("Navigator", "Histogram")):
        x0 = m + i * (half + 4 * s)
        _tab(V.SIDE, x0, y - 22 * s, x0 + half, y, name, S.tab_top == name, ("tab_top", name))
    y -= 29 * s
    if h > 330 * s:                                        # a short column keeps its list
        (_navigator if S.tab_top == "Navigator" else _histogram)(region, y, m)
        y -= 112 * s
    strip._rect(m, y, w - m, y + 1, LINE)
    y -= 5 * s
    quarter = (w - 2 * m - 9 * s) / 4
    for i, name in enumerate(("History", "Info", "Layer", "Filter")):
        x0 = m + i * (quarter + 3 * s)
        _tab(V.SIDE, x0, y - 22 * s, x0 + quarter, y, name, S.tab_side == name, ("tab_side", name))
    y -= 29 * s
    {"History": _history, "Info": _info, "Filter": _filter, "Layer": _layer}[S.tab_side](region, y, m)


def _navigator(region, y, m):
    s, w = _s(), region.width
    frame = V.current()
    size = frame.size if frame is not None and frame.size[0] else (16, 9)
    bh = 74 * s
    bw = bh * size[0] / max(size[1], 1)
    if bw > w - 2 * m - 2:
        bw = w - 2 * m - 2
        bh = bw * size[1] / max(size[0], 1)
    x0 = (w - bw) / 2
    strip._rect(x0 - 1, y - bh - 1, x0 + bw + 1, y + 1, (0.35, 0.35, 0.35, 1))
    strip._rect(x0, y - bh, x0 + bw, y, (0, 0, 0, 1))
    tex = _thumb(frame)
    if tex is not None:
        gpu.state.blend_set("ALPHA")
        draw_texture_2d(tex, (x0, y - bh), bw, bh)
        gpu.state.blend_set("NONE")
    yz, pc = y - 92 * s, V.zoom_percent()
    _field(V.SIDE, m, yz - 10 * s, m + 62 * s, yz + 10 * s, f"{pc} %", ("menu", "zoom"))
    x0, x1 = m + 74 * s, w - m - 8 * s
    _button(x0, yz - 1.5 * s, x1, yz + 1.5 * s, FIELD)
    _disc(x0 + min(max(np.log2(max(pc, 1) / 12.5) / 6.0, 0.0), 1.0) * (x1 - x0), yz, 5 * s, (0.45, 0.45, 0.65, 1))
    _hit(V.SIDE, (x0 - 5 * s, yz - 10 * s, x1 + 5 * s, yz + 10 * s), ("zoom", x0, x1), True)


_hist = {"key": None, "lines": []}


def _histogram(region, y, m):
    s, w = _s(), region.width
    x0, x1, y0 = m, w - m, y - 78 * s
    strip._rect(x0, y0, x1, y, FIELD)
    px = V.pixels()
    if px is not None:
        key = (S.pixels_key, S.hist_mode)
        if _hist["key"] != key:
            sample = px[::max(1, px.shape[0] // 200000)]
            lum = sample[:, 0] * .2126 + sample[:, 1] * .7152 + sample[:, 2] * .0722
            r, g, b = ((sample[:, i], c) for i, c in enumerate(((.9, .25, .25, 1), (.25, .85, .35, 1), (.35, .5, .95, 1))))
            rows = {"RGB": (r, g, b), "Red": (r,), "Green": (g,), "Blue": (b,), "Luminance": ((lum, TEXT),)}[S.hist_mode]
            out = []
            for values, color in rows:
                hist = np.histogram(np.clip(values, 0, 1), 128, (0, 1))[0][1:-1].astype(float)
                out.append((hist / max(hist.max(), 1.0), color))
            _hist.update(key=key, lines=out)
        for hist, color in _hist["lines"]:
            _lines([(x0 + (x1 - x0) * i / 125, y0 + hist[i] * 74 * s) for i in range(126)], color)
    _field(V.SIDE, m, y0 - 24 * s, m + 100 * s, y0 - 4 * s, S.hist_mode, ("menu", "histogram"))


def rows():
    out = []
    for q in S.seqs:
        if not q.still:
            out.append((q, None))
        if q.open or q.still:
            out.extend((q, i) for i in range(len(q.frames)))
    return out


def _history(region, y, m):
    s, w = _s(), region.width
    x1 = w - m
    c0, c1 = x1 - 98 * s, x1 - 78 * s
    strip._rect(m, y - 20 * s, x1, y, FIELD)
    _label(m + 6 * s, y - 14 * s, "Name", DIM, 11)
    _label(c0 + 4 * s, y - 14 * s, "R", DIM, 11)
    _label(c1 + 4 * s, y - 14 * s, "Render Time", DIM, 11)
    y -= 21 * s
    row, all_rows = 20 * s, rows()
    room = max(1, int((y - 4 * s) / row))
    S.scroll = max(0, min(S.scroll, len(all_rows) - room))
    S.rows_room, S.rows_total = room, len(all_rows)
    if not all_rows:
        _label(m + 6 * s, y - 18 * s, "Renders show up here", DIM)
    for n, (q, i) in enumerate(all_rows[S.scroll:S.scroll + room]):
        yr = y - n * row
        on = S.seq is q and i == S.index
        if on:
            strip._rect(m, yr - row, x1, yr, ACTIVE)
        elif n % 2:
            gpu.state.blend_set("ALPHA")
            strip._rect(m, yr - row, x1, yr, ROW)
        yt = yr - 14 * s
        if i is None:
            x = m + 8 * s
            _tri([(x - 4 * s, yr - 8 * s), (x + 4 * s, yr - 8 * s), (x, yr - 13 * s)] if q.open else
                 [(x - 2 * s, yr - 6 * s), (x - 2 * s, yr - 14 * s), (x + 4 * s, yr - 10 * s)], DIM)
            _label(m + 18 * s, yt, _clip(f"{q.name}  ({len(q.frames)})", c1 - m - 24 * s))
            _label(c1 + 4 * s, yt, _clock(sum(_secs(f) for f in q.frames)), DIM)
            _hit(V.SIDE, (m, yr - row, x1, yr), ("fold", q))
            continue
        f = q.frames[i]
        tx = m + (18 if not q.still else 4) * s
        tex = _thumb(f)
        if tex is not None:
            gpu.state.blend_set("ALPHA")
            draw_texture_2d(tex, (tx, yr - 17 * s), 24 * s, 14 * s)
            gpu.state.blend_set("NONE")
        else:
            strip._rect(tx, yr - 17 * s, tx + 24 * s, yr - 3 * s, FIELD)
        name = q.name if q.still else str(f.number)
        _label(tx + 30 * s, yt, _clip(name + ("" if f.saved else " *"), c0 - tx - 34 * s), ORANGE if on else TEXT)
        letter = "A" if S.a == (q, i) else "B" if S.b == (q, i) else None
        if letter:
            _label(c0 + 4 * s, yt, letter, GREEN)
        else:
            _disc(c0 + 8 * s, yr - row / 2, 3.5 * s, ORANGE if f.state == "rendering" else GREEN)
        _label(c1 + 4 * s, yt, _clock(_secs(f)), ORANGE if on else DIM)
        _hit(V.SIDE, (m, yr - row, x1, yr), ("row", q, i))
    if len(all_rows) > room:
        top, bottom = y, y - room * row
        long, at = (top - bottom) * room / len(all_rows), top - (top - bottom) * S.scroll / len(all_rows)
        strip._round_rect(x1 - 5 * s, at - long, x1 - 1 * s, at, 2 * s, (0.4, 0.4, 0.4, 1))
        _hit(V.SIDE, (x1 - 9 * s, bottom, x1, top), ("scroll", top, bottom), True)


def _info(region, y, m):
    s, frame = _s(), V.current()
    if frame is None:
        return
    q = S.seq
    out = [("Name", q.name if q.still else f"{q.name}, frame {frame.number}"), ("Size", f"{frame.size[0]} x {frame.size[1]}"),
           ("File", os.path.basename(frame.path) if q.kept else "Not saved: kept until Blender is closed"),
           ("Folder", os.path.dirname(frame.path) if q.kept else ""), ("On disk", _memory(frame)), ("Added", frame.added),
           ("Render Time", f"{_clock(_secs(frame))}" + ("" if q.still else f" (all: {_clock(sum(_secs(f) for f in q.frames))})"))]
    if not q.still:
        out.append(("Animation", f"{len(q.frames)} frames at {q.fps} a second"))
    y -= 14 * s
    for label, value in out:
        if not value:
            continue
        _label(m + 4 * s, y, label, DIM, 11)
        _label(m + 78 * s, y, _clip(str(value), region.width - 2 * m - 80 * s, 11), TEXT, 11)
        y -= 18 * s


def _layer(region, y, m):
    s = _s()
    if bpy.data.images.get("Render Result") is None:
        _label(m + 4 * s, y - 16 * s, "Nothing has been rendered yet", DIM)
        return
    for n, line in enumerate(("The latest render's layers and", "passes are in the menus above", "the picture.")):
        _label(m + 4 * s, y - (16 + 16 * n) * s, line, DIM)


FILTER_ROWS = (("Saturation", "sat", -100.0, 100.0, "%"), ("Brightness", "bright", -100.0, 100.0, "%"), ("Contrast", "contrast", -100.0, 100.0, "%"),
               ("Exposure", "exposure", -10.0, 10.0, ""), ("Gamma", "gamma", 0.1, 5.0, ""), ("Black Point", "black", 0.0, 1.0, ""),
               ("White Point", "white", 0.0, 1.0, ""))


def _check(x, y, label, on, action):
    s = _s()
    _button(x, y - 6 * s, x + 12 * s, y + 6 * s, ACTIVE if on else FIELD)
    if on:
        _lines([(x + 3 * s, y), (x + 5 * s, y - 3 * s), (x + 10 * s, y + 4 * s)], WHITE, 1.6)
    _label(x + 17 * s, y - 4 * s, label)
    _hit(V.SIDE, (x, y - 8 * s, x + 19 * s + _width(label), y + 8 * s), action)


def _filter(region, y, m):
    s, w = _s(), region.width
    y -= 10 * s
    _check(m + 4 * s, y, "Enable Filter", S.filter["on"], ("flag", "on"))
    y -= 21 * s
    for label, key, lo, hi, unit in FILTER_ROWS:
        v = S.filter[key]
        _label(m + 4 * s, y - 4 * s, label, TEXT if S.filter["on"] else DIM, 11)
        x0, x1 = m + 76 * s, m + 118 * s
        _field(V.SIDE, x0, y - 8 * s, x1, y + 8 * s, f"{v:.0f} %" if unit else f"{v:.2f}")
        a, b = x1 + 8 * s, w - m - 8 * s
        if b > a + 10 * s:
            _button(a, y - 1.5 * s, b, y + 1.5 * s, FIELD)
            _disc(a + (b - a) * (v - lo) / (hi - lo), y, 5 * s, (0.45, 0.45, 0.65, 1))
            _hit(V.SIDE, (a - 5 * s, y - 9 * s, b + 5 * s, y + 9 * s), ("filter", key, lo, hi, a, b), True)
        y -= 20 * s
    x = m + 4 * s
    for label, key in (("R", "r"), ("G", "g"), ("B", "b"), ("Invert", "invert")):
        _check(x, y, label, S.filter[key], ("flag", key))
        x += 30 * s + _width(label)
    y -= 24 * s
    _field(V.SIDE, m + 4 * s, y - 10 * s, m + 94 * s, y + 10 * s, "Reset Filter", ("cmd", "FILTER_RESET"))


# --- the frames below -------------------------------------------------------------------------------------------------------
def _secs(f):
    """Render time so far: while a frame renders it holds when that began."""
    import time
    if f.state == "rendering":
        return time.time() - f.seconds if S.rendering and f.seconds > 1e9 else 0.0
    return f.seconds


def _clock(seconds):
    t = int(seconds + 0.5)
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


def _memory(f):
    try:
        size = os.path.getsize(f.path)
    except OSError:
        return ""
    return f"{size / 1048576:.2f} MB" if size >= 1048576 else f"{size / 1024:.1f} KB"


def status():
    f = V.current()
    if f is None:
        return "Rendering..." if S.rendering else "Render something to see it here"
    q = S.seq
    if S.rendering:
        done = sum(x.state == "done" for x in q.frames)
        total = max(1, S.goal - (q.frames[0].number if q.frames else S.goal) + 1)
        return f"Rendering frame {f.number}, {_clock(_secs(f))}" + (f", {done} of {total} done" if total > 1 else "") + f"   {f.size[0]} x {f.size[1]}"
    head = _clock(_secs(f)) if q.still else f"{S.index + 1} of {len(q.frames)}  ({f.number} F)"
    return f"{head}   {f.size[0]} x {f.size[1]}   {_memory(f)}"


def _draw_bottom(region):
    s, w, h = _s(), region.width, region.height
    strip._rect(0, 0, w, h, BG)
    y3, left = 14 * s, 8 * s
    _field(V.BOTTOM, left, y3 - 10 * s, left + 62 * s, y3 + 10 * s, f"{V.zoom_percent()} %", ("menu", "zoom"))
    _label(left + 76 * s, y3 - 4 * s, _clip(status(), w - 110 * s))
    if S.seq is None or len(S.seq.frames) < 2 or h < 80 * s:
        return
    S.index = min(S.index, len(S.seq.frames) - 1)
    first, last = V.first_last()
    lo, hi = S.lo, max(S.hi, S.lo)
    y1, y2, x_end = h - 14 * s, h - 40 * s, w - 8 * s
    fw = 66 * s
    _field(V.BOTTOM, left, y1 - 10 * s, left + fw, y1 + 10 * s, f"{V.fps()} FPS", ("menu", "rates"))
    cur = S.seq.frames[S.index].number
    _field(V.BOTTOM, x_end - fw, y1 - 10 * s, x_end, y1 + 10 * s, f"{cur} F")
    a, b, span = left + fw + 10 * s, x_end - fw - 10 * s, max(hi - lo, 1)

    def at(f):
        return a + (b - a) * (f - lo) / span
    _button(a, y1 - 10 * s, b, y1 + 10 * s, FIELD)
    step = next((v for v in (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000) if (b - a) / span * v >= 40 * s), 2000)
    for f in range(lo + (-lo) % step, hi + 1, step):
        x = at(f)
        strip._rect(x, y1 - 8 * s, x + 1, y1 - 2 * s, DIM)
        if x < b - 20 * s:
            _label(x + 3 * s, y1 - 3 * s, str(f), DIM, 11)
    if lo <= cur <= hi:
        x = at(cur)
        strip._rect(x - 3 * s, y1 - 10 * s, x + 3 * s, y1 + 10 * s, (0.42, 0.42, 0.68, 1))
    _hit(V.BOTTOM, (a, y1 - 10 * s, b, y1 + 10 * s), ("scrub", a, b), True)
    _field(V.BOTTOM, left, y2 - 10 * s, left + fw, y2 + 10 * s, f"{lo} F")
    names = (("first", "START"), ("prev", "PREV"), ("back", "BACK"), ("pause" if S.play else "fwd", "PLAY"), ("next", "NEXT"), ("last", "END"))
    r0, r1 = a, x_end - fw - 10 * s - len(names) * 22 * s - 6 * s
    length = max(last - first, 1)
    p0, p1 = r0 + (r1 - r0) * (lo - first) / length, r0 + (r1 - r0) * (hi - first) / length
    if r1 > r0 + 40 * s:
        _button(r0, y2 - 10 * s, r1, y2 + 10 * s, FIELD)
        strip._round_rect(p0, y2 - 8 * s, max(p1, p0 + 12 * s), y2 + 8 * s, 3 * s, (.29, .29, .29, 1))
        _hit(V.BOTTOM, (r0, y2 - 10 * s, r1, y2 + 10 * s), ("range", r0, r1, p0, p1), True)
    x = r1 + 16 * s
    for name, cmd in names:
        _transport(name, x, y2, 6.5 * s, GREEN if name == "pause" else TEXT)
        _hit(V.BOTTOM, (x - 10 * s, y2 - 10 * s, x + 10 * s, y2 + 10 * s), ("cmd", cmd))
        x += 22 * s
    _field(V.BOTTOM, x_end - fw, y2 - 10 * s, x_end, y2 + 10 * s, f"{hi} F")


def _draw():
    ctx = bpy.context
    name = roles.role(ctx.area)
    if name not in (V.SIDE, V.BOTTOM) or ctx.region.type != "WINDOW":
        return
    S.hits[name] = []
    (_draw_side if name == V.SIDE else _draw_bottom)(ctx.region)


def _own_texture(path):
    """A finished frame as a texture: it can only be made while drawing. The ones not shown for long are let go."""
    own = V.OWN
    if path in own["ready"]:
        px = own["ready"].pop(path)
        h, w = px.shape[:2]
        own["tex"][path] = (gpu.types.GPUTexture((w, h), format="RGBA8", data=gpu.types.Buffer("FLOAT", w * h * 4, px.ravel())), (w, h))
        while len(own["tex"]) > 2 and sum(t[1][0] * t[1][1] * 4 for t in own["tex"].values()) > V.OWN_ROOM:
            own["tex"].popitem(last=False)
    if path in own["tex"]:
        own["tex"].move_to_end(path)
    return own["tex"].get(path)


def _draw_own():
    """The picture while a GPU engine renders (viewer.py): the frame asked for, whole, in the middle of its area."""
    ctx, own = bpy.context, V.OWN
    if not own["on"] or ctx.region.type != "WINDOW" or ctx.area != V.editor():
        return
    w, h = ctx.region.width, ctx.region.height
    strip._rect(0, 0, w, h, BG)
    for path in [p for p in list(own["ready"]) if p != own["want"]][:2]:      # frames read ahead for playing
        _own_texture(path)
    if _own_texture(own["want"]) is not None:
        own["shown"] = own["want"]
    tex = own["tex"].get(own["shown"])                     # until the one asked for is read: the one before
    if tex is None:
        return
    iw, ih = tex[1]
    k = min(w / iw, h / ih)
    draw_texture_2d(tex[0], ((w - iw * k) / 2, (h - ih * k) / 2), iw * k, ih * k)


def _image_box(region):
    v = region.view2d
    return v.view_to_region(0.0, 0.0, clip=False), v.view_to_region(1.0, 1.0, clip=False)


def _draw_compare():
    ctx = bpy.context
    if not V.compare_ready() or S.diff or ctx.region.type != "WINDOW" or ctx.area != V.editor():
        return
    (x0, y0), (x1, y1) = _image_box(ctx.region)
    t, s = S.line, _s()
    if S.vertical:
        a, b = (x0 + (x1 - x0) * t, y0), (x0 + (x1 - x0) * t, y1)
        spots = (("A", a[0] - 22 * s, y1 - 22 * s), ("B", a[0] + 6 * s, y1 - 22 * s))
    else:
        a, b = (x0, y0 + (y1 - y0) * t), (x1, y0 + (y1 - y0) * t)
        spots = (("A", x1 - 22 * s, a[1] + 4 * s), ("B", x1 - 22 * s, a[1] - 22 * s))
    if S.show_line:
        _lines((a, b), WHITE, 1.4)
    if S.show_text:
        for text, x, y in spots:
            strip._rect(x, y, x + 16 * s, y + 18 * s, RED)
            _label(x + 4 * s, y + 5 * s, text, WHITE)


# --- commands -----------------------------------------------------------------------------------------------------------------------
def _flag(key):
    S.filter[key] = not S.filter[key]
    V.refresh()


def _set(key, value):
    setattr(S, key, value)


def _file(f):
    return f.saved_path if f.saved_path and os.path.exists(f.saved_path) else f.path


def _reveal():
    f = V.current()
    if f is None or not f.path:
        return
    path = _file(f)
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _transform(value):
    S.transform = value
    V.refresh()


def _alpha():
    sp = V._space()
    if sp is not None:
        sp.display_channels = "COLOR" if sp.display_channels != "COLOR" else "COLOR_ALPHA"


def _alpha_on():
    sp = V._space()
    return sp is not None and sp.display_channels != "COLOR"


def _clear_cache():
    sp = V._space()
    V._drop([p for p, name in list(V._ready.items()) if sp is None or sp.image is None or sp.image.name != name])
    S.ab_px.clear()
    S.pixels = S.pixels_key = None


def _range_here(end):
    if S.seq is not None:
        V.set_range(end, S.seq.frames[S.index].number)


def _setting():
    """A render setting with the values this render was made with."""
    if S.seq is None or not S.seq.settings:
        return
    import json
    from . import render_settings as rs
    scene = bpy.context.scene
    rs.ensure(scene)
    rs.commit(scene)
    r = rs.sets(scene).add()
    r.name = rs._unique(scene, S.seq.name)
    r.values = json.dumps(S.seq.settings)


def _shown():
    return V.current() is not None and bool(V.current().path)


def _many():
    return S.seq is not None and len(S.seq.frames) > 1


# command: (label, icon, what it does, can it be used now, is it on, tooltip)
C = {
    "OPEN": ("Open Image...", "FILE_FOLDER", lambda: bpy.ops.blenda4d.viewer_open_file("INVOKE_DEFAULT"), None, None, "Open an image, a numbered sequence or a movie in the Render Viewer"),
    "SAVE": ("Save Image as...", "FILE_TICK", lambda: bpy.ops.blenda4d.viewer_save("INVOKE_DEFAULT"), _shown, None, "Save the picture shown under a name of your choice"),
    "RENDER": ("Render to Render Viewer", "RENDER_STILL", lambda: bpy.ops.blenda4d.render("INVOKE_DEFAULT", animation=False), lambda: not S.rendering, None, "Render the current frame"),
    "RENDER_ANIM": ("Render Animation", "RENDER_ANIMATION", lambda: bpy.ops.blenda4d.render("INVOKE_DEFAULT", animation=True), lambda: not S.rendering, None, "Render the animation"),
    "RESUME": ("Resume Rendering", "PLAY", V.resume, lambda: S.resume is not None and not S.rendering, None, "Go on with the animation that was stopped: only the frames that were never made"),
    "REVEAL": ({"darwin": "Show File in Finder", "win32": "Show File in Explorer"}.get(sys.platform, "Show File in Folder"), "FILEBROWSER", _reveal, _shown, None, "Show the picture's file where it is on disk"),
    "REMOVE": ("Remove Image", "REMOVE", lambda: V.remove([S.seq]), lambda: S.seq is not None and not S.rendering, None, "Take this render out of History. Files you saved stay on disk"),
    "REMOVE_ALL": ("Remove All Images", "TRASH", lambda: V.remove(S.seqs), lambda: bool(S.seqs) and not S.rendering, None, "Empty History. Files you saved stay on disk"),
    "CLEAR": ("Clear Cache", "FILE_REFRESH", _clear_cache, lambda: bool(S.seqs), None, "Let go of the frames kept in memory; they are read again when shown"),
    "SETTING": ("Create Render Setting from Render", "PRESET_NEW", _setting, lambda: S.seq is not None and bool(S.seq.settings), None, "Add a render setting with the values this render was made with"),
    "FIT": ("Fit to Screen", "FULLSCREEN_ENTER", V.fit, _shown, lambda: S.auto, "Show the whole picture, and keep showing it whole"),
    "ZOOM_IN": ("Zoom In", "ZOOM_IN", lambda: V.set_zoom(V.zoom_percent() * 2), None, None, "Show the picture twice as large"),
    "ZOOM_OUT": ("Zoom Out", "ZOOM_OUT", lambda: V.set_zoom(V.zoom_percent() / 2), None, None, "Show the picture half as large"),
    "ALPHA": ("Image Transparency", "IMAGE_ALPHA", _alpha, _shown, _alpha_on, "Show the picture's transparency"),
    "FILTER": ("Filter", "MODIFIER", lambda: _flag("on"), _shown, lambda: S.filter["on"], "Change how the picture looks here; the file is not changed"),
    "FILTER_RESET": ("Reset Filter", "LOOP_BACK", lambda: (S.filter.update(V.FILTER), V.refresh()), None, None, "Put every filter value back"),
    "FOLD": ("Fold All", "TRIA_RIGHT", lambda: [setattr(q, "open", False) for q in S.seqs], None, None, "Close every render in History"),
    "UNFOLD": ("Unfold All", "TRIA_DOWN", lambda: [setattr(q, "open", True) for q in S.seqs], None, None, "Open every render in History"),
    "EMBEDDED": ("Embedded", "IMAGE_DATA", lambda: _transform("EMBEDDED"), None, lambda: S.transform == "EMBEDDED", "Show pictures as they were saved"),
    "SCENE": ("Scene", "SCENE_DATA", lambda: _transform("SCENE"), None, lambda: S.transform == "SCENE", "Show pictures through the scene's view transform"),
    "AB": ("AB Compare", "SPLIT_VERTICAL", V.toggle_ab, _shown, lambda: S.ab, "Compare two pictures of the same size with a line you can drag"),
    "SET_A": ("Set as A", "EVENT_A", lambda: V.mark("a"), _shown, None, "The picture shown is A"),
    "SET_B": ("Set as B", "EVENT_B", lambda: V.mark("b"), _shown, None, "The picture shown is B"),
    "SWAP": ("Swap AB", "ARROW_LEFTRIGHT", V.swap_ab, lambda: bool(S.a and S.b), None, "A becomes B and B becomes A"),
    "DIFF": ("Difference", "SELECT_DIFFERENCE", lambda: (_set("diff", not S.diff), V.compare()), lambda: V.compare_ready(), lambda: S.diff, "Show how much A and B differ"),
    "DIRECTION": ("Swap Vert./Horiz.", "SPLIT_HORIZONTAL", lambda: (_set("vertical", not S.vertical), V.compare()), lambda: V.compare_ready(), None, "Turn the comparing line the other way"),
    "SHOW_LINE": ("Show Line", "IPO_LINEAR", lambda: _set("show_line", not S.show_line), None, lambda: S.show_line, "Show the comparing line"),
    "SHOW_TEXT": ("Show Text", "FONT_DATA", lambda: _set("show_text", not S.show_text), None, lambda: S.show_text, "Show the letters A and B"),
    "PLAY": ("Play Forwards / Stop", "PLAY", lambda: V.play(1), _many, lambda: S.play > 0, "Play the frames"),
    "BACK": ("Play Backwards", "PLAY_REVERSE", lambda: V.play(-1), _many, lambda: S.play < 0, "Play the frames backwards"),
    "PREV": ("Go to Previous Image", "FRAME_PREV", lambda: V.go(S.index - 1), _many, None, "The frame before"),
    "NEXT": ("Go to Next Image", "FRAME_NEXT", lambda: V.go(S.index + 1), _many, None, "The frame after"),
    "START": ("Go to Preview Start", "REW", lambda: V.go(S.lo - V.first_last()[0]), _many, None, "The first frame that plays"),
    "END": ("Go to Preview End", "FF", lambda: V.go(S.hi - V.first_last()[0]), _many, None, "The last frame that plays"),
    "SET_START": ("Set as Preview Start", "TRIA_LEFT_BAR", lambda: _range_here(0), _many, None, "Play from the frame shown"),
    "SET_END": ("Set as Preview End", "TRIA_RIGHT_BAR", lambda: _range_here(1), _many, None, "Play up to the frame shown"),
    "SIMPLE": ("Simple", "FORWARD", lambda: _set("repeat", "SIMPLE"), None, lambda: S.repeat == "SIMPLE", "Play once and stop"),
    "CYCLE": ("Cycle", "FILE_REFRESH", lambda: _set("repeat", "CYCLE"), None, lambda: S.repeat == "CYCLE", "Play again from the start"),
    "PINGPONG": ("Ping-Pong", "ARROW_LEFTRIGHT", lambda: _set("repeat", "PINGPONG"), None, lambda: S.repeat == "PINGPONG", "Play forwards, then backwards"),
    "LINK": ("Link Time", "LINKED", lambda: _set("link", not S.link), None, lambda: S.link, "The scene goes to the frame that is shown"),
    "FPS_SEQ": ("Sequence Frame Rate", "TIME", lambda: _set("rate", 0), None, lambda: S.rate == 0, "Play at the render's own frame rate"),
    "POP": ("Open in a Window", "WINDOW", lambda: _pop(True), None, None, "Move the Render Viewer to a window of its own"),
    "DOCK": ("Put in the Viewport's Place", "FULLSCREEN_EXIT", lambda: _pop(False), None, None, "Move the Render Viewer back under the tabs"),
}
for _z in (12.5, 25, 50, 100, 200, 400, 800):
    C[f"ZOOM_{_z:g}"] = (f"{_z:g}%", "BLANK1", (lambda z=_z: V.set_zoom(z)), None, (lambda z=_z: abs(V.zoom_percent() - z) < 1), "Show the picture at this size")
for _r in V.RATES:
    C[f"FPS_{_r}"] = (str(_r), "BLANK1", (lambda r=_r: _set("rate", r)), None, (lambda r=_r: S.rate == r), "Play at this many frames a second")
for _m in ("RGB", "Red", "Green", "Blue", "Luminance"):
    C[f"HIST_{_m}"] = (_m, "BLANK1", (lambda m=_m: _set("hist_mode", m)), None, (lambda m=_m: S.hist_mode == m), "What the histogram counts")

MENUS = {
    "File": ["OPEN", "SAVE", "REVEAL", None, "RENDER", "RENDER_ANIM", "RESUME", None, "SETTING", None, "POP", "DOCK"],
    "Edit": ["REMOVE", "REMOVE_ALL", None, "CLEAR"],
    "View": ["#zoom", "FIT", "ZOOM_IN", "ZOOM_OUT", None, "ALPHA", "FILTER", "FILTER_RESET", None, "EMBEDDED", "SCENE", None, "FOLD", "UNFOLD"],
    "Compare": ["AB", "SET_A", "SET_B", "SWAP", None, "DIFF", "DIRECTION", None, "SHOW_LINE", "SHOW_TEXT"],
    "Animation": ["#rates", None, "PLAY", "BACK", None, "PREV", "NEXT", "START", "END", None, "SET_START", "SET_END", None, "SIMPLE", "CYCLE", "PINGPONG", None, "LINK"],
    "zoom": ["FIT", None] + [f"ZOOM_{z:g}" for z in (12.5, 25, 50, 100, 200, 400, 800)],
    "rates": ["FPS_SEQ", None] + [f"FPS_{r}" for r in V.RATES],
    "histogram": [f"HIST_{m}" for m in ("RGB", "Red", "Green", "Blue", "Luminance")],
    "transform": ["EMBEDDED", "SCENE"],
    "context": ["REVEAL", "SAVE", None, "SET_A", "SET_B", None, "SETTING", None, "REMOVE", "REMOVE_ALL"],
}
TITLES = {"zoom": "Zoom Values", "rates": "Frame Rate", "histogram": "Histogram", "transform": "View Transform", "context": "History"}
TIPS = {"File": "Open, save and render", "Edit": "Remove renders and free memory", "View": "How the picture is shown", "Compare": "Compare two pictures",
        "Animation": "Play the frames"}
KEYS = (("A", {}, "SET_A"), ("B", {}, "SET_B"), ("S", {}, "SWAP"), ("SPACE", {}, "PLAY"), ("I", {}, "SET_START"), ("O", {}, "SET_END"), ("H", {}, "FIT"),
        ("NUMPAD_PLUS", {}, "ZOOM_IN"), ("NUMPAD_MINUS", {}, "ZOOM_OUT"), ("LEFT_ARROW", {}, "PREV"), ("RIGHT_ARROW", {}, "NEXT"))


class BLENDA4D_OT_viewer_cmd(bpy.types.Operator):
    bl_idname = "blenda4d.viewer_cmd"
    bl_label = "Render Viewer"
    bl_options = {"INTERNAL"}
    cmd: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return V.is_part(context)

    @classmethod
    def description(cls, context, props):
        return C[props.cmd][5] if props.cmd in C else cls.bl_label

    def execute(self, context):
        c = C.get(self.cmd)
        if c is None or (c[3] is not None and not c[3]()):
            return {"CANCELLED"}
        c[2]()
        V.redraw()
        return {"FINISHED"}


def _items(lay, keys):
    main = V.docked()
    for k in keys:
        if k is None:
            lay.separator()
        elif k.startswith("#"):
            lay.menu(f"BLENDA4D_MT_viewer_{k[1:]}", text=TITLES[k[1:]], icon="VIEWZOOM" if k == "#zoom" else "TIME")
        elif k in ("POP", "DOCK") and (k == "POP") != main:
            continue
        else:
            label, icon, _fn, can, on, _tip = C[k]
            row = lay.row()
            row.enabled = can is None or bool(can())
            row.operator("blenda4d.viewer_cmd", text=label + ("  (on)" if on is not None and on() else ""), icon=icon).cmd = k


def _menu(key):
    def draw(self, context):
        _items(self.layout, MENUS[key])
    return type(f"BLENDA4D_MT_viewer_{key}", (bpy.types.Menu,), {
        "bl_idname": f"BLENDA4D_MT_viewer_{key}", "bl_label": TITLES.get(key, key), "bl_description": TIPS.get(key, TITLES.get(key, key)), "draw": draw})


MENU_CLASSES = {k: _menu(k) for k in MENUS}
BAR = [MENU_CLASSES[k] for k in ("File", "Edit", "View", "Compare", "Animation")]
TOOLS = (("OPEN", "SAVE"), ("RENDER", "RENDER_ANIM", "RESUME"), ("CLEAR",), ("ALPHA", "FILTER"), ("AB", "SET_A", "SET_B", "SWAP"), ("DIFF", "DIRECTION"), ("FIT",))


class BLENDA4D_PT_viewer_top(roles.RolePanel, bpy.types.Panel):
    bl_label = "Render Viewer"
    role = V.TOP

    def draw(self, context):
        from . import bars, fitzoom
        col = self.layout.column(align=False)
        region, s = context.region, _s()
        wide = region.width / max(0.1, fitzoom.zoom_of(region)) - 2 * bars.PANEL_MARGIN * s
        row = col.row(align=False)
        left = row.row(align=True)
        left.alignment = "LEFT"
        left.label(text="", icon="COLLAPSEMENU")
        full = wide > 560 * s
        menus.menu_bar(left, BAR, avail=max(40 * s, wide - 24 * s - (230 if full else 34) * s))
        right = row.row(align=True)
        right.alignment = "RIGHT"
        if full:
            right.label(text="View Transform")
            box = right.row(align=True)
            box.ui_units_x = 5
            box.menu("BLENDA4D_MT_viewer_transform", text=C[S.transform][0])
            right.separator(factor=1.0)
        k = "POP" if V.docked() else "DOCK"
        right.operator("blenda4d.viewer_cmd", text="", icon=C[k][1], emboss=False).cmd = k
        tools = col.row(align=True)
        tools.alignment = "LEFT"
        tools.scale_x = tools.scale_y = 1.2
        free = wide / (24 * s)
        for n, group in enumerate(TOOLS):                  # whole groups that do not fit are in the menus
            keys = [k for k in group if k != "RESUME" or S.resume is not None]
            need = len(keys) + (0.7 if n else 0)
            if need > free:
                break
            free -= need
            if n:
                tools.separator(factor=1.4)
            for k in keys:
                _l, icon, _fn, can, on, _t = C[k]
                b = tools.row(align=True)
                b.alignment = "LEFT"
                b.enabled = can is None or bool(can())
                b.operator("blenda4d.viewer_cmd", text="", icon=icon, depress=bool(on is not None and on())).cmd = k
        if bpy.app.is_job_running("RENDER") and free > 8:
            tools.separator(factor=1.4)
            tools.template_running_jobs()                  # Blender's own progress and its button to stop
        sp = V._space()
        if S.layers and sp is not None and sp.image is not None and free > 8:
            tools.separator(factor=1.4)
            tools.template_image_layers(sp.image, sp.image_user)
        for _h, draw in V.EXTRA:
            draw(col, context)


# --- opening --------------------------------------------------------------------------------------------------------------------
class BLENDA4D_OT_render_viewer(bpy.types.Operator):
    bl_idname = "blenda4d.render_viewer"
    bl_label = "Render Viewer"
    bl_description = "Show this session's renders, to look at, play and compare"

    def execute(self, context):
        return {"FINISHED"} if V.open_docked(context) else {"CANCELLED"}


def _pop(out):
    from . import build
    win = V.window()
    if win is None or build.busy():
        return
    if out:
        build.run_steps(V.leave_steps(win), done=lambda: V.open_window(bpy.context))
    else:
        def back():
            V.close_window()
            V.open_docked(bpy.context)
            return None
        bpy.app.timers.register(back, first_interval=0.0)  # not while the window being closed runs this


class BLENDA4D_OT_viewer_open_file(bpy.types.Operator):
    bl_idname = "blenda4d.viewer_open_file"
    bl_label = "Open Image"
    bl_description = "Open an image, a numbered sequence or a movie in the Render Viewer"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    filter_movie: bpy.props.BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            V.add_file(bpy.path.abspath(self.filepath))
        except (RuntimeError, OSError, ValueError) as ex:
            self.report({"WARNING"}, f"Could not open it: {ex}")
            return {"CANCELLED"}
        return {"FINISHED"}


class BLENDA4D_OT_viewer_save(bpy.types.Operator):
    bl_idname = "blenda4d.viewer_save"
    bl_label = "Save Image as"
    bl_description = "Save the picture shown under a name of your choice"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        f = V.current()
        if f is None or not f.path:
            return {"CANCELLED"}
        ext = os.path.splitext(f.path)[1]
        self.filepath = S.seq.name + ("" if S.seq.still else f"_{f.number:04d}") + ext
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import shutil
        f = V.current()
        if f is None:
            return {"CANCELLED"}
        path, ext = bpy.path.abspath(self.filepath), os.path.splitext(f.path)[1]
        if not path.lower().endswith(ext.lower()):
            path += ext
        try:
            if os.path.abspath(path) != os.path.abspath(f.path):
                shutil.copyfile(f.path, path)
        except OSError as ex:
            self.report({"WARNING"}, str(ex))
            return {"CANCELLED"}
        f.saved, f.saved_path = True, path
        V.redraw()
        return {"FINISHED"}


# --- clicks and wheel -----------------------------------------------------------------------------------------------------------
def _do(action):
    kind = action[0]
    if kind == "menu":
        bpy.ops.wm.call_menu(name=f"BLENDA4D_MT_viewer_{action[1]}")
    elif kind == "cmd":
        c = C[action[1]]
        if c[3] is None or c[3]():
            c[2]()
    elif kind == "tab_top":
        S.tab_top = action[1]
    elif kind == "tab_side":
        S.tab_side = action[1]
        if action[1] == "Layer":
            V.show_layers()
        elif S.layers:
            V.refresh()
    elif kind == "row":
        q = action[1]
        if S.seq is not q or q.still:
            a, b = q.frames[0].number, q.frames[-1].number
            S.lo, S.hi = a, b
        S.play = 0
        if not S.rendering or q is S.seq:               # the render's own finished frames can be looked at meanwhile
            V.show(q, action[2])
    elif kind == "fold":
        action[1].open = not action[1].open
    elif kind == "flag":
        _flag(action[1])


class BLENDA4D_OT_viewer_press(bpy.types.Operator):
    bl_idname = "blenda4d.viewer_press"
    bl_label = "Render Viewer"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) in (V.SIDE, V.BOTTOM)

    def invoke(self, context, event):
        name = roles.role(context.area)
        x, y = event.mouse_region_x, event.mouse_region_y
        for box, action, drag in reversed(S.hits.get(name, [])):
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                if event.type == "RIGHTMOUSE":
                    if action[0] == "row":
                        _do(action)
                        V.redraw()
                        bpy.ops.wm.call_menu(name="BLENDA4D_MT_viewer_context")
                    return {"FINISHED"}
                if not drag:
                    _do(action)
                    V.redraw()
                    return {"FINISHED"}
                self.action, self.start, self.lo0, self.hi0, self.part = action, x, S.lo, S.hi, None
                if action[0] == "range":
                    _k, _r0, _r1, p0, p1 = action
                    self.part = "lo" if abs(x - p0) < 8 * _s() else "hi" if abs(x - p1) < 8 * _s() else "body"
                self._apply(x, event)
                context.window_manager.modal_handler_add(self)
                return {"RUNNING_MODAL"}
        return {"FINISHED"} if event.type == "RIGHTMOUSE" else {"PASS_THROUGH"}

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            self._apply(event.mouse_region_x, event)
        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _apply(self, x, event):
        a = self.action
        kind = a[0]
        if kind == "scrub":
            t = min(max((x - a[1]) / max(a[2] - a[1], 1), 0.0), 1.0)
            V.go(int(round(S.lo + (S.hi - S.lo) * t)) - V.first_last()[0])
        elif kind == "range":
            first, last = V.first_last()
            d = int(round((x - self.start) * (last - first) / max(a[2] - a[1], 1)))
            if self.part == "body":
                d = min(max(d, first - self.lo0), last - self.hi0)
                S.lo, S.hi = self.lo0 + d, self.hi0 + d
            else:
                V.set_range(0 if self.part == "lo" else 1, (self.lo0 if self.part == "lo" else self.hi0) + d)
        elif kind == "scroll":
            S.scroll = int(S.rows_total * (a[1] - event.mouse_region_y) / max(a[1] - a[2], 1) - S.rows_room / 2)
        elif kind == "zoom":
            V.set_zoom(12.5 * 2 ** (min(max((x - a[1]) / max(a[2] - a[1], 1), 0.0), 1.0) * 6))
        elif kind == "filter":
            _k, key, lo, hi, x0, x1 = a
            S.filter[key] = lo + (hi - lo) * min(max((x - x0) / max(x1 - x0, 1), 0.0), 1.0)
            if not S.filter["on"]:
                S.filter["on"] = True
            V.refresh()
        V.redraw()


class BLENDA4D_OT_viewer_wheel(bpy.types.Operator):
    bl_idname = "blenda4d.viewer_wheel"
    bl_label = "Render Viewer scroll"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) in (V.SIDE, V.BOTTOM)

    def invoke(self, context, event):
        if roles.role(context.area) == V.BOTTOM:
            if event.type != "TRACKPADPAN" and _many():
                V.go(S.index + (-1 if event.type == "WHEELUPMOUSE" else 1))
            return {"FINISHED"}
        if event.type == "TRACKPADPAN":
            S.pan += event.mouse_y - event.mouse_prev_y
            step = 20 * _s()
            whole = int(S.pan / step)
            S.pan -= whole * step
            S.scroll += whole
        else:
            S.scroll += -3 if event.type == "WHEELUPMOUSE" else 3
        V.redraw()
        return {"FINISHED"}


class BLENDA4D_OT_viewer_drag(bpy.types.Operator):
    bl_idname = "blenda4d.viewer_drag"
    bl_label = "Render Viewer picture"
    bl_description = "Drag the picture, or the line between A and B. Double-click: 100%, or the whole picture"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "IMAGE_EDITOR" and V._top(context.screen) is not None and context.area == V.editor(context.window)

    def invoke(self, context, event):
        if V.compare_ready() and not S.diff:
            (x0, y0), (x1, y1) = _image_box(context.region)
            mouse, lo, hi = (event.mouse_region_x, x0, x1) if S.vertical else (event.mouse_region_y, y0, y1)
            if abs(mouse - (lo + (hi - lo) * S.line)) < 8 * _s():
                context.window_manager.modal_handler_add(self)
                return {"RUNNING_MODAL"}
        if event.value == "DOUBLE_CLICK":
            V.fit() if V.zoom_percent() == 100 else V.set_zoom(100)
            return {"FINISHED"}
        S.auto = False
        return bpy.ops.image.view_pan("INVOKE_DEFAULT")

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            (x0, y0), (x1, y1) = _image_box(context.region)
            at, lo, hi = (event.mouse_region_x, x0, x1) if S.vertical else (event.mouse_region_y, y0, y1)
            S.line = min(max((at - lo) / max(hi - lo, 1), 0.0), 1.0)
            V.compare()
            V.redraw()
        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


classes = (BLENDA4D_OT_viewer_cmd, BLENDA4D_OT_render_viewer, BLENDA4D_OT_viewer_open_file, BLENDA4D_OT_viewer_save, BLENDA4D_OT_viewer_press,
           BLENDA4D_OT_viewer_wheel, BLENDA4D_OT_viewer_drag, *MENU_CLASSES.values(), BLENDA4D_PT_viewer_top)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    P = bpy.types.SpaceProperties
    _handles.append((P, P.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")))
    I = bpy.types.SpaceImageEditor
    _handles.append((I, I.draw_handler_add(_draw_compare, (), "WINDOW", "POST_PIXEL")))
    N = bpy.types.SpaceInfo
    _handles.append((N, N.draw_handler_add(_draw_own, (), "WINDOW", "POST_PIXEL")))
    kc = bpy.context.window_manager.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES", region_type="WINDOW")
    for kind in ("LEFTMOUSE", "RIGHTMOUSE"):
        _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_viewer_press.bl_idname, kind, "PRESS", head=True)))
    for name in ("View2D", "View2D Buttons List"):
        k2 = kc.keymaps.new(name=name, space_type="EMPTY", region_type="WINDOW")
        for kind in ("WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN"):
            _keymaps.append((k2, k2.keymap_items.new(BLENDA4D_OT_viewer_wheel.bl_idname, kind, "ANY", head=True)))
    ki = kc.keymaps.new(name="Image", space_type="IMAGE_EDITOR", region_type="WINDOW")
    for value in ("PRESS", "DOUBLE_CLICK"):
        _keymaps.append((ki, ki.keymap_items.new(BLENDA4D_OT_viewer_drag.bl_idname, "LEFTMOUSE", value, head=True)))
    kn = kc.keymaps.new(name="Info", space_type="INFO", region_type="WINDOW")     # the picture while a GPU engine renders
    for keymap in (km, ki, kn):
        for kind, mods, cmd in KEYS:
            kmi = keymap.keymap_items.new("blenda4d.viewer_cmd", kind, "PRESS", head=True, **mods)
            kmi.properties.cmd = cmd
            _keymaps.append((keymap, kmi))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    for space, h in _handles:
        space.draw_handler_remove(h, "WINDOW")
    _handles.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
