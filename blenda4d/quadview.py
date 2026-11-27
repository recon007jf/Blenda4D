# SPDX-License-Identifier: GPL-3.0-or-later
"""Four views: the viewport's expand / contract button.

One full-size view + the button: the viewport splits into four real 3D views, Perspective top left, Top top right,
Right bottom left and Front bottom right. The side views are orthographic with their rotation locked; the view the
button was pressed in becomes the Perspective one (or, after an expand, the corner it came from) and keeps its view.

Four views + the button in one of them: that view fills the viewport again and the other three are joined away. Each
view's state (where it looks, projection, shading and overlays) is remembered, so the next split brings the three
hidden views back as they were.

The split is one step (Blender's own area_split, several times before anything is drawn). Areas are joined one step
per redraw (an area's size only updates on the next event loop) with area_join; a join that does not take falls back
to area_close, and a step that still fails stops there and leaves every area a working viewport."""
import math

import bpy
from mathutils import Euler

from . import build, roles

CORNERS = ("PERSP", "TOP", "RIGHT", "FRONT")          # top left, top right, bottom left, bottom right
AXIS = {"PERSP": None, "TOP": "TOP", "RIGHT": "RIGHT", "FRONT": "FRONT"}
_r = math.radians
AXIS_ROTATION = {"TOP": Euler((0, 0, 0)).to_quaternion(), "FRONT": Euler((_r(90), 0, 0)).to_quaternion(),
                 "RIGHT": Euler((_r(90), 0, _r(90))).to_quaternion()}
SHADING = ("type", "light", "color_type", "single_color", "show_xray", "xray_alpha", "show_shadows", "show_cavity",
           "use_scene_lights", "use_scene_world", "use_scene_lights_render", "use_scene_world_render",
           "wireframe_color_type", "show_backface_culling", "show_object_outline", "show_xray_wireframe",
           "xray_alpha_wireframe", "render_pass", "studio_light")
OVERLAY = ("show_overlays", "show_floor", "show_axis_x", "show_axis_y", "show_axis_z", "show_wireframes",
           "show_face_orientation", "show_outline_selected", "show_relationship_lines", "show_extras", "show_bones")
SPACE = ("lens", "clip_start", "clip_end", "lock_camera", "camera", "show_gizmo")

_saved = {}            # corner -> remembered state of a view; "ALONE" -> the corner the single view stands for


# --- a view's state -------------------------------------------------------------------------------------------------

def views(screen):
    return [a for a in screen.areas if a.type == "VIEW_3D"]


def _region(area):
    from .roles import alive
    if not alive(area):                                    # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == "WINDOW"), None)


def corner_of(area, screen):
    """Which corner of the four-view arrangement an area sits in."""
    vs = views(screen)
    x0, x1 = min(a.x for a in vs), max(a.x + a.width for a in vs)
    y0, y1 = min(a.y for a in vs), max(a.y + a.height for a in vs)
    left = area.x + area.width / 2 < (x0 + x1) / 2
    top = area.y + area.height / 2 > (y0 + y1) / 2
    return {(True, True): "PERSP", (False, True): "TOP", (True, False): "RIGHT", (False, False): "FRONT"}[(left, top)]


def alone_corner():
    return _saved.get("ALONE", "PERSP")


def _axis_corner(area):
    """The side corner a view looks like (orthographic, locked, straight down that axis), else None."""
    rv = area.spaces.active.region_3d
    if rv.view_perspective != "ORTHO" or not rv.lock_rotation:
        return None
    return next((c for c, q in AXIS_ROTATION.items() if abs(q.rotation_difference(rv.view_rotation).angle) < 1e-3), None)


def corner_of_single(area):
    """The corner a single view stands for: the one it was expanded from, unless the layout was rebuilt since and the
    view no longer looks like it (then: the side view it matches, else Perspective)."""
    remembered, looks = alone_corner(), _axis_corner(area)
    if (remembered == "PERSP" and looks is None) or remembered == looks:
        return remembered
    return looks or "PERSP"


def state(area):
    sp = area.spaces.active
    rv = sp.region_3d
    return {"rot": rv.view_rotation.copy(), "loc": rv.view_location.copy(), "dist": rv.view_distance,
            "persp": rv.view_perspective, "lock": rv.lock_rotation,
            "shading": {k: _copy(getattr(sp.shading, k)) for k in SHADING if hasattr(sp.shading, k)},
            "overlay": {k: getattr(sp.overlay, k) for k in OVERLAY if hasattr(sp.overlay, k)},
            "space": {k: getattr(sp, k) for k in SPACE if hasattr(sp, k)}}


def _copy(v):
    return v[:] if hasattr(v, "__len__") and not isinstance(v, str) else v


def apply(area, st):
    sp = area.spaces.active
    rv = sp.region_3d
    for group, target in (("shading", sp.shading), ("overlay", sp.overlay), ("space", sp)):
        for k, v in st.get(group, {}).items():
            try:
                if getattr(target, k) != v:
                    setattr(target, k, v)
            except (AttributeError, TypeError, ValueError, ReferenceError):
                pass
    rv.lock_rotation = False
    rv.view_perspective = st["persp"]
    rv.view_rotation = st["rot"]
    rv.view_location = st["loc"]
    rv.view_distance = st["dist"]
    rv.lock_rotation = st["lock"]


def _axis_view(window, area, corner):
    """Turn a view to look straight down an axis, orthographic, rotation locked."""
    rv = area.spaces.active.region_3d
    rv.lock_rotation = False
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=_region(area)):
            bpy.ops.view3d.view_axis(type=AXIS[corner])     # also names the view ("Top Orthographic")
    except RuntimeError:
        rv.view_rotation = AXIS_ROTATION[corner]
    rv.view_perspective = "ORTHO"
    rv.lock_rotation = True


# --- splitting and joining ------------------------------------------------------------------------------------------

def _half(window, area, direction):
    """Split an area in half and give the new half, at once."""
    before = {a.as_pointer() for a in window.screen.areas}
    with build._ov(window, area):
        bpy.ops.screen.area_split(direction=direction, factor=0.5)
    new = next(a for a in window.screen.areas if a.as_pointer() not in before)
    space = new.spaces.active
    with build._ov(window, new):                           # a new area has no size, and cannot be split, until Blender
        space.show_region_ui = not space.show_region_ui    # lays it out: switching a region on and off makes it do so
        space.show_region_ui = not space.show_region_ui
    return new


def _show(window, area, corner):
    """A view of the four gets what its corner shows: as it was left, or new (a side view starts as Lines)."""
    build.dress_view(area)
    st = _saved.get(corner)
    rv = area.spaces.active.region_3d
    if st is not None:
        apply(area, st)
    elif AXIS[corner]:
        from . import display_modes
        _axis_view(window, area, corner)
        display_modes.set_shading(area.spaces.active, "G")
    else:
        rv.lock_rotation = False
        if rv.view_perspective == "ORTHO":
            rv.view_perspective = "PERSP"
    area.tag_redraw()


def _touching(a, b):
    """Do a and b share one whole edge (what area_join needs)?"""
    gap = 4 + round(4 * bpy.context.preferences.system.ui_scale)    # the gap between areas grows with the UI scale
    rows = abs(a.y - b.y) <= 2 and abs(a.height - b.height) <= 2
    cols = abs(a.x - b.x) <= 2 and abs(a.width - b.width) <= 2
    beside = abs(a.x + a.width - b.x) <= gap or abs(b.x + b.width - a.x) <= gap
    stacked = abs(a.y + a.height - b.y) <= gap or abs(b.y + b.height - a.y) <= gap
    return (rows and beside) or (cols and stacked)


def _join(window, gone, keep):
    """Join `gone` into `keep` (keep stays, with its view). False when Blender would not do it."""
    screen = window.screen
    count = len(screen.areas)
    # Run the join from a third area. Blender forgets the region under the last mouse event (screen.active_region)
    # only when the join runs from an area other than the one that stays; run from `keep`, it can go on pointing
    # into `gone` after `gone` is freed, and drawing the area edges then reads freed memory (a crash on Windows).
    # With no third area, area_close below does the join (it always forgets that region).
    other = next((a for a in screen.areas if a != keep and a != gone), None)
    if other is not None:
        try:
            with bpy.context.temp_override(window=window, screen=screen, area=other, region=_region(other)):
                # the area under source_xy stays, the one under target_xy goes
                bpy.ops.screen.area_join(source_xy=(keep.x + keep.width // 2, keep.y + keep.height // 2),
                                         target_xy=(gone.x + gone.width // 2, gone.y + gone.height // 2))
        except (RuntimeError, TypeError):
            pass
        yield
        if len(screen.areas) < count:
            return True
    try:
        with bpy.context.temp_override(window=window, screen=screen, area=gone, region=_region(gone)):
            bpy.ops.screen.area_close()
    except RuntimeError:
        pass
    yield
    return len(screen.areas) < count


def split_steps(window):
    """One view -> four, all in one step: the four views are there at once, each already showing what it should."""
    from . import magnify
    magnify.leave_all()
    screen = window.screen
    vs = views(screen)
    if len(vs) != 1:
        return
    view = vs[0]
    alone = corner_of_single(view)
    _saved.pop("ALONE", None)
    _saved[alone] = state(view)
    wide = view.width                                      # an area's size only updates once Blender has drawn: count along
    # one create column for all four views, full height on the right (each view's own strip would repeat it)
    # one tools column for all four too, full height on the left (in the views it would be cut in two), unless the
    # Asset Browser or the open Timeline has it already
    if not roles.areas(screen, "MODES") and not roles.areas(screen, "ASSETS"):
        build.role_now(build.split_now(window, view, "VERTICAL", build.side_px(), "LEFT"), "MODES", window)
        wide -= build.side_px()
    if not roles.areas(screen, "CREATE"):                 # a layout with editors under the viewport has it already
        build.role_now(build.split_now(window, view, "VERTICAL", build.px(build.CREATE_PX) + build.EDGE, "RIGHT", wide), "CREATE", window)
    # one row of View | Render Settings | Render Viewer
    build.role_now(build.split_now(window, view, "HORIZONTAL", build.px(build.VIEW_TABS_PX) + build.EDGE, "TOP"), "VIEW_TABS", window)
    left = _half(window, view, "VERTICAL")                 # Blender gives the left and the lower half as the new one
    guess = {"TOP": view, "PERSP": left, "FRONT": _half(window, view, "HORIZONTAL"), "RIGHT": _half(window, left, "HORIZONTAL")}
    for corner, area in guess.items():
        _show(window, area, corner)
    yield
    for area in views(screen):                             # where each view really is, had Blender given the other half
        corner = corner_of(area, screen)
        if guess[corner] != area:
            _show(window, area, corner)


def expand_steps(window, keep):
    """Four views -> the one pressed, full size; the others are remembered."""
    from . import magnify
    magnify.leave_all()
    screen = window.screen
    vs = views(screen)
    if len(vs) < 2 or keep not in vs:
        return
    for a in vs:
        _saved[corner_of(a, screen)] = state(a)
    _saved["ALONE"] = corner_of(keep, screen)
    for _ in range(12):
        others = [a for a in views(screen) if a != keep]
        if not others:
            break
        pair = next(((a, keep) for a in others if _touching(a, keep)), None) or \
            next(((a, b) for a in others for b in others if a != b and _touching(a, b)), None)
        if pair is None:
            print("Blenda 4D: four views: no pair of views to join")
            break
        ok = yield from _join(window, *pair)
        if not ok:
            print("Blenda 4D: four views: could not join two views; leaving them as they are")
            break
    for t in roles.areas(screen, "VIEW_TABS"):            # first: it is as wide as the view alone
        if views(screen):
            yield from _join(window, t, views(screen)[0])
    own = [] if build.stacked(screen) else roles.areas(screen, "CREATE") + roles.areas(screen, "MODES")
    for c in own:                                         # the four views' two columns go: the viewport draws them again
        if views(screen):
            yield from _join(window, c, views(screen)[0])
    for a in views(screen):
        build.dress_view(a)
    for a in screen.areas:
        a.tag_redraw()


def renew_steps(window):
    """Four views again, with their columns at their own widths."""
    vs = views(window.screen)
    keep = next((a for a in vs if corner_of(a, window.screen) == "PERSP"), vs[0])
    yield from expand_steps(window, keep)
    yield from split_steps(window)


class BLENDA4D_OT_quad_view(bpy.types.Operator):
    bl_idname = "blenda4d.quad_view"
    bl_label = "Four Views / Full Size"
    bl_description = "One view: split it into four (Perspective, Top, Right, Front). Four views: make this one full size"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and not build.busy()

    def execute(self, context):
        if len(views(context.screen)) > 1:
            build.run_steps(expand_steps(context.window, context.area))
        else:
            build.run_steps(split_steps(context.window))
        return {"FINISHED"}


def register():
    bpy.utils.register_class(BLENDA4D_OT_quad_view)


def unregister():
    _saved.clear()
    bpy.utils.unregister_class(BLENDA4D_OT_quad_view)
