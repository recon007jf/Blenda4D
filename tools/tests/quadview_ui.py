# UI run of the four-view button: split one view into four, expand the Top view, split again (the others come back as
# they were), expand the Perspective view, split and reset the layout, then switch Blenda off and on.
#   BLENDER_USER_CONFIG=<scratch> B4D_OUT=<scratch> Blender --factory-startup --window-geometry 100 60 1700 1000 \
#       --python tools/tests/quadview_ui.py
# Prints "B4D QV ..." lines and "B4D QV FAIL ..." for every check that does not hold.
import os
import runpy

import bpy

os.environ["B4D_STEPS"] = "wait"
HERE = os.path.dirname(os.path.abspath(__file__))
ns = runpy.run_path(os.path.join(HERE, "..", "try_ui.py"))
PLAN, shot = ns["PLAN"], ns["shot"]
_seen = {}


def win():
    return bpy.context.window_manager.windows[0]


def vs():
    from blenda4d import quadview
    return quadview.views(win().screen)


def corner(name):
    from blenda4d import quadview
    return next(a for a in vs() if quadview.corner_of(a, win().screen) == name)


def press(area_fn):
    def go():
        a = area_fn()
        r = next(r for r in a.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win(), screen=win().screen, area=a, region=r):
            print("B4D QV press", bpy.ops.blenda4d.quad_view(), flush=True)
    return go


def check(cond, what):
    print("B4D QV", "ok" if cond else "FAIL", what, flush=True)


def look(a):
    rv = a.spaces.active.region_3d
    return (tuple(round(v, 3) for v in rv.view_rotation), rv.view_perspective, rv.lock_rotation,
            round(rv.view_distance, 3), a.spaces.active.shading.type, a.spaces.active.overlay.show_floor)


def setup():
    a = vs()[0]
    rv = a.spaces.active.region_3d
    rv.view_distance = 23.0
    a.spaces.active.shading.type = "SOLID"
    _seen["persp0"] = look(a)


def four(tag):
    def go():
        from blenda4d import quadview
        v = vs()
        check(len(v) == 4, f"{tag}: four views ({len(v)})")
        if len(v) != 4:
            return
        for c in quadview.CORNERS:
            a = corner(c)
            lk = look(a)
            print("B4D QV", tag, c, lk, "headers", a.spaces.active.show_region_header, a.spaces.active.show_region_tool_header, flush=True)
            if c == "PERSP":
                check(lk[1] == "PERSP" and not lk[2], f"{tag}: Perspective is perspective, free")
            else:
                q = quadview.AXIS_ROTATION[c]
                rot = a.spaces.active.region_3d.view_rotation
                check(abs(q.rotation_difference(rot).angle) < 1e-3 and lk[1] == "ORTHO" and lk[2], f"{tag}: {c} ortho locked")
        sizes = sorted((a.width, a.height) for a in v)
        check(sizes[-1][0] - sizes[0][0] <= 2 and sizes[-1][1] - sizes[0][1] <= 2, f"{tag}: equal quarters {sizes}")
    return go


def tweak():
    """Make each hidden view distinct, to see it come back."""
    corner("RIGHT").spaces.active.shading.type = "WIREFRAME"
    corner("FRONT").spaces.active.overlay.show_floor = False
    corner("FRONT").spaces.active.region_3d.view_distance = 7.5
    corner("TOP").spaces.active.region_3d.view_distance = 12.0
    for c in ("PERSP", "TOP", "RIGHT", "FRONT"):
        _seen[c] = look(corner(c))


def single(tag, want):
    def go():
        from blenda4d import quadview
        v = vs()
        check(len(v) == 1, f"{tag}: one view ({len(v)})")
        if not v:
            return
        lk = look(v[0])
        print("B4D QV", tag, lk, "alone", quadview.alone_corner(), "areas", len(win().screen.areas), flush=True)
        check(lk == _seen[want], f"{tag}: the full view is {want} as it was")
        check(quadview.alone_corner() == want, f"{tag}: remembered corner {want}")
    return go


def same(tag):
    def go():
        for c in ("PERSP", "TOP", "RIGHT", "FRONT"):
            if len(vs()) == 4:
                check(look(corner(c)) == _seen[c], f"{tag}: {c} came back as it was {look(corner(c))}")
    return go


def roles_report(tag):
    def go():
        from blenda4d import roles
        names = sorted(n for n in (roles.role(a) for a in win().screen.areas) if n)
        print("B4D QV", tag, "areas", [(a.type) for a in win().screen.areas], names, flush=True)
    return go


def reset_layout():
    with bpy.context.temp_override(window=win(), screen=win().screen):
        print("B4D QV layout", bpy.ops.blenda4d.layout_use(name="Standard"), flush=True)


W = [lambda: None] * 6
done = PLAN.pop()
PLAN += [setup, lambda: shot("qv_single"),
         press(lambda: vs()[0])] + W + [four("split1"), lambda: _seen.update(PERSP=_seen["persp0"]),
         lambda: check(look(corner("PERSP")) == _seen["persp0"], "split1: Perspective keeps the pressed view"),
         lambda: check(all(look(corner(c))[4] == "WIREFRAME" for c in ("TOP", "RIGHT", "FRONT")), "split1: new side views are Lines"),
         tweak, lambda: shot("qv_four"),
         press(lambda: corner("TOP"))] + W + [single("expand_top", "TOP"), lambda: shot("qv_top_full"),
         press(lambda: vs()[0])] + W + [four("split2"), same("split2"), lambda: shot("qv_four_again"),
         press(lambda: corner("PERSP"))] + W + [single("expand_persp", "PERSP"), lambda: shot("qv_persp_full"),
         press(lambda: vs()[0])] + W + [four("split3"), same("split3"),
         reset_layout] + W * 2 + [roles_report("reset"),
         lambda: check(len(vs()) == 1, "reset layout: one view"), lambda: shot("qv_reset"),
         press(lambda: vs()[0])] + W + [four("split4"),
         lambda: ns["blenda4d"].switch.set_mode(False)] + W + [roles_report("off"),
         lambda: check(not any(w.name == "Blenda 4D" for w in bpy.data.workspaces), "off: Blenda workspace removed"),
         lambda: shot("qv_off"),
         lambda: ns["blenda4d"].switch.set_mode(True)] + W * 2 + [roles_report("on"),
         lambda: check(len(vs()) == 1, "on again: one view"), lambda: shot("qv_on"),
         press(lambda: vs()[0])] + W + [four("split5"), lambda: shot("qv_on_four"), done]
