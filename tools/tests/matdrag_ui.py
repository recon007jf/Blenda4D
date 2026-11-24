# UI run of material drag and drop: the sample scene from tools/try_ui.py, the Material Manager column opened, and a
# real mouse drag from a material onto an Object Manager row in each of the three views (icons, list, layers, the
# list at another preview size and with the search on), screenshots mid-drag (the row highlight) and after, a drop
# on empty space and an ESC (both must change nothing), a drop on a light (refused), drags into the 3D view onto the
# object under the mouse and onto empty 3D space, and the Blenda 4D | Blender switch off and on. When the plan is
# done the test writes done.txt and quits Blender itself (wm.quit_blender does not ask to save), so no window with a
# modal drag is left behind.
#   BLENDER_USER_CONFIG=<scratch> B4D_OUT=<scratch> Blender --factory-startup --enable-event-simulate \
#       --window-geometry 100 60 1700 1000 --python tools/tests/matdrag_ui.py
import os
import runpy

import bpy

os.environ["B4D_STEPS"] = "wait"
HERE = os.path.dirname(os.path.abspath(__file__))
ns = runpy.run_path(os.path.join(HERE, "..", "try_ui.py"))
PLAN, shot, toggle, ev = ns["PLAN"], ns["shot"], ns["toggle"], ns["ev"]
row_y, row_index, om_region = ns["row_y"], ns["row_index"], ns["om_region"]

from blenda4d import managers, matdrag, matman, roles, switch  # noqa: E402

FAIL = []


def check(cond, what):
    """Record one test result.

    cond: the condition that must hold; what: the description printed (and kept on failure).
    """
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAIL.append(what)


def mm_area():
    """The Material Manager area of the test window. Returns the Area."""
    return roles.areas(bpy.context.window_manager.windows[0].screen, "MATERIALS")[0]


def mm_region():
    """The Material Manager area's window region. Returns the Region."""
    return next(r for r in mm_area().regions if r.type == "WINDOW")


def mat_index(name):
    """Index of a material in the manager's current list (newest first, after the search filter).

    name: the material's name. Returns its row index; raises ValueError when it is not listed.
    """
    return [m.name for m in matman.materials(bpy.context)].index(name)


def mat_xy(i):
    """Window position of the middle of material i's own row/tile (the inverse of matdrag.mat_at).

    i: the material's index in matman.materials. Returns the window (x, y) to press on.
    """
    wm = bpy.context.window_manager
    r = mm_region()
    ui = bpy.context.preferences.system.ui_scale
    unit = 20 * ui
    if wm.b4d_mm_view == "ICONS":
        px = wm.b4d_mm_px
        avail = r.width / ui - 24
        cw = px + 12
        cols = max(1, int(avail // cw))
        row, col = divmod(i, cols)
        pitch = px * ui + (matman.NAME_UNITS + matman.ROW_GAP) * unit
        slot = min(1.0, cols * cw / max(avail, 1)) * (r.width - 13 * ui) / cols
        vx = 3.5 * ui + (col + 0.5) * slot
        vy = -(matman.GRID_TOP * unit + row * pitch + px * ui / 2)
        x, y = r.view2d.view_to_region(vx, vy, clip=False)
        return r.x + int(x), r.y + int(y)
    top = matdrag.LIST_TOP * unit
    row_h = matdrag._row_h(bpy.context)
    for k, m in enumerate(matman.materials(bpy.context)):
        h = row_h
        if wm.b4d_mm_view == "LAYERS":
            h += max(1, len(matman._textures(m))) * managers.row_height()
        if k == i:
            vy = -(top + row_h / 2)
            x, y = r.view2d.view_to_region(0, vy, clip=False)
            s = max(1.0, min(wm.b4d_mm_px, 80) / 20)
            return r.x + int(s * unit / 2), r.y + int(y)
        top += h
    raise IndexError(i)


def calib():
    """Print the manager's region and check mat_at finds every listed material at its computed position.

    No arguments; runs in the current view, preview size and search filter.
    """
    wm = bpy.context.window_manager
    w = bpy.context.window_manager.windows[0]
    r = mm_region()
    mats = matman.materials(bpy.context)
    print("B4D MM REGION", r.x, r.y, r.width, r.height, "view", wm.b4d_mm_view, "px", wm.b4d_mm_px,
          "mats", [m.name for m in mats], flush=True)
    for i, m in enumerate(mats):
        x, y = mat_xy(i)
        with bpy.context.temp_override(window=w, area=mm_area(), region=r):
            back = matdrag.mat_at(bpy.context, x - r.x, y - r.y)
        print("B4D MM AT", i, m.name, (x, y), "->", back and back.name, flush=True)
        check(back == m, f"mat_at finds {m.name} at its row in the {wm.b4d_mm_view} view")


_st = {}


def drag_start(name):
    """Press on a material in the manager and move just past the drag threshold, starting blenda4d.mm_drag.

    name: the material to drag. The press position is kept in _st["xy"] for the drag_to* helpers.
    """
    i = mat_index(name)
    x, y = mat_xy(i)
    _st["mat"] = name
    _st["xy"] = (x, y)
    ev("MOUSEMOVE", "NOTHING", x, y)
    ev("LEFTMOUSE", "PRESS", x, y)
    ev("MOUSEMOVE", "NOTHING", x + 4, y)         # small moves past the drag threshold while still inside the
    ev("MOUSEMOVE", "NOTHING", x + 8, y)         # manager, so the CLICK_DRAG starts there and not over another area


def drag_to(obj, mid_shot=None):
    """Move the running drag onto an object's row in the Object Manager and release there.

    obj: the Object whose row is the drop target; mid_shot: optional screenshot name taken mid-drag.
    The target is kept in _st["target"] for drag_report.
    """
    x, y = _st["xy"]
    r = om_region()
    tx, ty = r.x + 70, row_y(row_index(obj))
    for k in range(1, 7):
        ev("MOUSEMOVE", "NOTHING", x + (tx - x) * k // 6, y + (ty - y) * k // 6)
    if mid_shot:
        shot(mid_shot)
    ev("LEFTMOUSE", "RELEASE", tx, ty)
    _st["target"] = obj


def drag_report():
    """Print and return the material slots of the last drop target (_st["target"]).

    No arguments. Returns the list of slot material names (None for an empty slot).
    """
    ob = bpy.data.objects[_st["target"]]
    mats = [s.material.name if s.material else None for s in ob.material_slots]
    print("B4D DRAG", _st["mat"], "->", ob.name, "slots", mats, "drop prop", repr(bpy.context.window_manager.b4d_mat_drop), flush=True)
    return mats


def drag_cancel(kind):
    """End the running drag without a drop: move away and press ESC, or release below the last row.

    kind: "esc" cancels with the ESC key; anything else releases below the Object Manager rows (no target).
    Sets _st["target"] to None.
    """
    x, y = _st["xy"]
    r = om_region()
    if kind == "esc":
        tx, ty = r.x + 70, row_y(row_index("Cube"))
        for k in range(1, 4):
            ev("MOUSEMOVE", "NOTHING", x + (tx - x) * k // 3, y + (ty - y) * k // 3)
        ev("ESC", "PRESS", tx, ty)
    else:                                               # drop below the last row: no object there
        rows = managers.visible_rows(bpy.context)
        tx, ty = r.x + 70, row_y(len(rows) + 1)
        for k in range(1, 7):
            ev("MOUSEMOVE", "NOTHING", x + (tx - x) * k // 6, y + (ty - y) * k // 6)
        ev("LEFTMOUSE", "RELEASE", tx, ty)
    _st["target"] = None


def slots():
    """Every object's material slots in the scene. Returns {object name: [slot material names]}."""
    return {o.name: [s.material.name if s.material else None for s in o.material_slots] for o in bpy.data.objects}


def view_area():
    """The largest 3D view in the window (as managers._main_view picks it)."""
    w = bpy.context.window_manager.windows[0]
    views = [a for a in w.screen.areas if a.type == "VIEW_3D" and len(a.spaces)]
    return max(views, key=lambda a: a.width * a.height)


def view_region():
    """The largest 3D view's window region. Returns the Region."""
    return next(r for r in view_area().regions if r.type == "WINDOW")


def obj_view_xy(name):
    """Window position of an object's centre projected into the 3D view.

    name: the object's name. Returns the window (x, y), or None when the object is out of view.
    """
    from bpy_extras import view3d_utils
    r = view_region()
    ob = bpy.data.objects[name]
    co = view3d_utils.location_3d_to_region_2d(r, view_area().spaces.active.region_3d, ob.matrix_world.translation)
    return None if co is None else (r.x + int(co.x), r.y + int(co.y))


def drag_to_view(obj, mid_shot=None):
    """Move the running drag onto an object in the 3D view and release there (the drop ray-casts the surface).

    obj: the Object under the target pixel; mid_shot: optional screenshot name taken mid-drag. When the object
    is out of view the drag is released at its start (a cancel). Sets _st["target"].
    """
    x, y = _st["xy"]
    pos = obj_view_xy(obj)
    if pos is None:                             # out of view: release where the drag started (a cancel, no drop)
        print("B4D VIEW", obj, "not in view, cancelling the drag", flush=True)
        ev("LEFTMOUSE", "RELEASE", x, y)
        _st["target"] = None
        return
    tx, ty = pos
    for k in range(1, 7):
        ev("MOUSEMOVE", "NOTHING", x + (tx - x) * k // 6, y + (ty - y) * k // 6)
    if mid_shot:
        shot(mid_shot)
    ev("LEFTMOUSE", "RELEASE", tx, ty)
    _st["target"] = obj


def empty_view_xy():
    """Scan the 3D view for a window position whose drop ray hits no object.

    No arguments. Returns the window (x, y), or None when every scanned pixel hits something.
    """
    from blenda4d import assets
    w = bpy.context.window_manager.windows[0]
    vp = view_area()
    r = view_region()
    for fy in (0.97, 0.93, 0.88, 0.82, 0.75):
        for fx in (0.5, 0.08, 0.92):
            x, y = r.x + int(r.width * fx), r.y + int(r.height * fy)
            with bpy.context.temp_override(window=w, area=vp, region=r):
                _loc, ob = assets.drop_point(bpy.context, r, x, y)
            if ob is None:
                return x, y
    return None


def drag_to_empty_view():
    """Move the running drag to a spot in the 3D view where the ray hits nothing and release there.

    Falls back to the view's header (outside its canvas) when no empty pixel is found. Sets _st["target"] to None.
    """
    x, y = _st["xy"]
    pos = empty_view_xy()
    if pos is None:                             # no empty pixel found: release over the view's header instead
        r = view_region()
        pos = (r.x + 10, r.y + r.height + 8)
        print("B4D VIEW no empty pixel, using the header", flush=True)
    tx, ty = pos
    for k in range(1, 7):
        ev("MOUSEMOVE", "NOTHING", x + (tx - x) * k // 6, y + (ty - y) * k // 6)
    ev("LEFTMOUSE", "RELEASE", tx, ty)
    _st["target"] = None


def add_green():
    """Add a third material to the sample scene. No arguments; returns nothing."""
    bpy.data.materials.new("Green")


W = [lambda: None] * 6
done = PLAN.pop()
PLAN += [lambda: toggle("MATERIALS")] + W + [add_green] + W + [lambda: shot("mm_icons"), calib]

# icons view: Blue onto the Torus (no slot yet), then Orange onto the Sphere (replaces Blue)
PLAN += [lambda: drag_start("Blue")] + [lambda: drag_to("Torus", "drag_icons_mid"), lambda: None]
PLAN += [lambda: check(drag_report() == ["Blue"], "icons view: Blue landed on the Torus")]
PLAN += [lambda: drag_start("Orange")] + [lambda: drag_to("Sphere"), lambda: None]
PLAN += [lambda: check(drag_report() == ["Orange"], "icons view: Orange replaced the Sphere's Blue")]

# list view: Green onto the Cube (replaces Orange)
PLAN += [lambda: setattr(bpy.context.window_manager, "b4d_mm_view", "LIST")] + W + [lambda: shot("mm_list"), calib]
PLAN += [lambda: drag_start("Green")] + [lambda: drag_to("Cube", "drag_list_mid"), lambda: None]
PLAN += [lambda: check(drag_report() == ["Green"], "list view: Green landed on the Cube")]

# list view at a larger preview size: Blue onto the Sphere
PLAN += [lambda: setattr(bpy.context.window_manager, "b4d_mm_px", 120)] + W + [calib]
PLAN += [lambda: drag_start("Blue")] + [lambda: drag_to("Sphere"), lambda: None]
PLAN += [lambda: check(drag_report() == ["Blue"], "list view at 120 px: Blue landed on the Sphere")]
PLAN += [lambda: setattr(bpy.context.window_manager, "b4d_mm_px", 64)]

# layer view: Orange onto the Torus (replaces Blue)
PLAN += [lambda: setattr(bpy.context.window_manager, "b4d_mm_view", "LAYERS")] + W + [lambda: shot("mm_layers"), calib]
PLAN += [lambda: drag_start("Orange")] + [lambda: drag_to("Torus", "drag_layers_mid"), lambda: None]
PLAN += [lambda: check(drag_report() == ["Orange"], "layer view: Orange landed on the Torus")]

# search on: only Green is listed, drag it onto the Floor
PLAN += [lambda: setattr(bpy.context.window_manager, "b4d_mm_view", "LIST"),
         lambda: setattr(bpy.context.window_manager, "b4d_mm_search", True),
         lambda: setattr(bpy.context.window_manager, "b4d_mm_filter", "gre")] + W + [calib]
PLAN += [lambda: drag_start("Green")] + [lambda: drag_to("Floor"), lambda: None]
PLAN += [lambda: check(drag_report() == ["Green"], "search on: Green landed on the Floor")]
PLAN += [lambda: setattr(bpy.context.window_manager, "b4d_mm_filter", ""),
         lambda: setattr(bpy.context.window_manager, "b4d_mm_search", False)] + W

# into the 3D view: Orange onto the Sphere under the mouse, then Green onto the Torus
PLAN += [lambda: drag_start("Orange")] + [lambda: drag_to_view("Sphere", "drag_view_mid"), lambda: None]
PLAN += [lambda: (drag_report(), print("B4D SLOTS", slots(), flush=True),
                  check(drag_report() == ["Orange"], "3D view: Orange landed on the Sphere under the mouse"))]
PLAN += [lambda: drag_start("Blue")] + [lambda: drag_to_view("Cube"), lambda: None]
PLAN += [lambda: (print("B4D SLOTS", slots(), flush=True),
                  check(drag_report() == ["Blue"], "3D view: Blue landed on the Cube under the mouse"))]

# a drop on empty space and an ESC change nothing; a drop on a light is refused
PLAN += [lambda: _st.update(before=slots())]
PLAN += [lambda: drag_start("Blue")] + [drag_to_empty_view, lambda: None]
PLAN += [lambda: check(slots() == _st["before"], "drop on empty 3D space changes nothing")]
PLAN += [lambda: drag_start("Blue")] + [lambda: drag_cancel("empty"), lambda: None]
PLAN += [lambda: check(slots() == _st["before"], "drop below the rows changes nothing")]
PLAN += [lambda: drag_start("Blue")] + [lambda: drag_cancel("esc"), lambda: None]
PLAN += [lambda: check(slots() == _st["before"], "ESC cancels the drag, nothing changes")]
PLAN += [lambda: drag_start("Blue")] + [lambda: drag_to("Area"), lambda: None]
PLAN += [lambda: check(slots() == _st["before"], "drop on a light is refused, nothing changes")]
PLAN += [lambda: shot("mm_done")]

# the switch off and on restores everything
PLAN += [lambda: switch.set_mode(False)] + W + [
    lambda: check(not hasattr(bpy.types.WindowManager, "b4d_mat_drop") and not hasattr(bpy.types, "BLENDA4D_OT_mm_drag"),
                  "switch off: drag registration is gone"),
    lambda: shot("matdrag_off")]
PLAN += [lambda: switch.set_mode(True)] + W + [
    lambda: check(hasattr(bpy.types.WindowManager, "b4d_mat_drop") and hasattr(bpy.types, "BLENDA4D_OT_mm_drag"),
                  "switch on: drag registration is back"),
    lambda: shot("matdrag_on")]
def finish():
    """Last plan step: print the result, write done.txt, cancel any stray drag and quit Blender. No arguments."""
    print("MATDRAG UI RESULT", "PASS" if not FAIL else f"FAIL {FAIL}", flush=True)
    done()                                      # the done.txt the runner waits for
    try:
        ev("ESC", "PRESS", 0, 0)                # cancel any drag left modal, so nothing holds the window's input
    except Exception:
        pass
    bpy.ops.wm.quit_blender()                   # close the test window ourselves: no save prompt, no lingering modal


PLAN += [finish]
