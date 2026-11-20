# Headless test of the MoClone module: the Cloner copies the objects under it in every mode, every Attribute Manager
# row changes the result, the children show as a wire while copied and come back when taken out, every effector
# setting changes the copies (and nothing else does once the check mark is off), settings survive a rebuild, and
# switching the module off leaves no handler or property behind while the file keeps showing the copies.
#   BLENDER_USER_CONFIG=<scratch> Blender -b --factory-startup --python tools/tests/moclone_engine.py
import math
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from blenda4d import bars, kinds, menus, moclone as M, moclone_nodes as MN  # noqa: E402

bpy.utils.register_class(kinds.BLENDA4D_OT_add_kind)
M.register()
fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)
        print("FAIL", msg, flush=True)
    else:
        print("ok  ", msg, flush=True)


def update():
    for _ in range(2):
        M.sync(bpy.context.scene)
        bpy.context.view_layer.update()


def result(ob):
    """The Cloner's evaluated points and copy colours, rounded: two results differ when the copies changed."""
    update()
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    pts = tuple(sorted(tuple(round(c, 4) for c in v.co) for v in me.vertices))
    attr = me.attributes.get(MN.COLOR_ATTR)
    cols = tuple(sorted(tuple(round(c, 3) for c in d.color) for d in attr.data)) if attr else ()
    ev.to_mesh_clear()
    return pts, cols


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for ng in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(ng)


def select(*obs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0] if obs else None


def add(kind, *sel):
    select(*sel)
    bpy.ops.blenda4d.add_kind(kind=kind)
    return bpy.context.view_layer.objects.active


def cube(name="Box", size=0.4, loc=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
    bpy.context.object.name = name
    return bpy.context.object


def changes(ob, name, value, msg):
    before = result(ob)
    old = M.get(ob, name)
    old = tuple(old) if hasattr(old, "__len__") and not isinstance(old, str) else old
    M.put(ob, name, value)
    after = result(ob)
    check(before != after, msg)
    M.put(ob, name, old)
    return after


def test_cloner_basics():
    print("== cloner")
    clear()
    box = cube()
    c = add("cloner", box)
    check(M.is_cloner(c) and box.parent == c, "made around the selected object")
    check(box.display_type == "WIRE" and box.hide_render, "the copied child shows as a wire and does not render")
    pts, cols = result(c)
    check(len(pts) == 3 * 8, f"Linear: 3 copies of the box ({len(pts)} points)")
    check(cols and all(col == (1.0, 1.0, 1.0, 1.0) for col in cols), "copies carry a white Clone Color")
    box.scale = (1.0, 3.0, 1.0)
    sized = result(c)
    check(sized[0] != pts, "the child's size carries to the copies")
    box.location.x += 2.0
    check(result(c)[0] == sized[0], "the child's place does not move the copies (the layout places them)")
    box.location.x -= 2.0
    box.scale = (1.0, 1.0, 1.0)
    box.parent = None
    update()
    check(box.display_type != "WIRE" and not box.hide_render, "taken out of the Cloner: the child looks as before")
    box.parent = c
    update()
    c["_b4d_enabled"] = False
    update()
    check(box.display_type != "WIRE", "Cloner switched off: the child looks as before")
    c["_b4d_enabled"] = True
    update()
    check(box.display_type == "WIRE", "switched back on: the child is a wire again")


def test_rows():
    print("== every row changes the result")
    clear()
    box = cube()
    c = add("cloner", box)
    M.put(c, "Mode", "Linear")
    changes(c, "Count", 6, "Linear: Count")
    changes(c, "Offset", (0.0, 150.0, 0.0), "Linear: Offset")
    changes(c, "Step Rotation", (0.0, 30.0, 0.0), "Linear: Step Rotation")
    changes(c, "Step Size", 50.0, "Linear: Step Size")
    M.put(c, "Mode", "Grid")
    check(len(result(c)[0]) == 15 * 8, "Grid: 5 x 1 x 3 copies")
    for name in ("Count X", "Count Y", "Count Z"):
        changes(c, name, 4, f"Grid: {name}")
    changes(c, "Spacing", (60.0, 60.0, 250.0), "Grid: Spacing")
    M.put(c, "Mode", "Radial")
    changes(c, "Count", 8, "Radial: Count")
    changes(c, "Radius", 400.0, "Radial: Radius")
    changes(c, "Plane", "XY", "Radial: Plane")
    changes(c, "Start Angle", 45.0, "Radial: Start Angle")
    changes(c, "End Angle", 180.0, "Radial: End Angle")
    changes(c, "Align", False, "Radial: Align")
    # Object mode: a spline and a polygon object to lay copies on
    bpy.ops.curve.primitive_bezier_circle_add(radius=2.0)
    ring = bpy.context.object
    bpy.ops.mesh.primitive_uv_sphere_add(radius=2.0, segments=12, ring_count=6, location=(5, 0, 0))
    ball = bpy.context.object
    M.put(c, "Mode", "Object")
    check(len(result(c)[0]) == 0, "Object: nothing until an object is picked")
    M.put(c, "Object", ring)
    check(len(result(c)[0]) == 3 * 8, "Object along a spline: Count copies")
    changes(c, "Count", 10, "Object along a spline: Count")
    changes(c, "Align", False, "Object along a spline: Align")
    changes(c, "Object", ball, "Object: picking another object")
    M.put(c, "Object", ball)
    M.put(c, "Distribution", "Points")
    n_pts = len(ball.data.vertices)
    check(len(result(c)[0]) == n_pts * 8, f"Object on points: one copy per point ({n_pts})")
    changes(c, "Align", False, "Object on points: Align")
    changes(c, "Distribution", "Surface", "Object: Distribution")
    M.put(c, "Distribution", "Surface")
    M.put(c, "Count", 40)
    got = len(result(c)[0]) // 8
    check(20 <= got <= 60, f"Object on the surface: about Count copies ({got})")
    changes(c, "Count", 80, "Object on the surface: Count")
    changes(c, "Seed", 7, "Object on the surface: Seed")
    changes(c, "Align", False, "Object on the surface: Align")
    # several children: in turn or at random
    M.put(c, "Mode", "Linear")
    M.put(c, "Count", 12)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, segments=8, ring_count=4)
    ball2 = bpy.context.object
    ball2.name = "Ball"
    ball2.parent = c
    update()
    check(not M._needs_rebuild(c) and ball2.display_type == "WIRE", "a second child is picked up")
    check(M.get(c, "Count") == 12 and M.get(c, "Mode") == "Linear", "settings are kept when the group is built again")
    changes(c, "Clone Order", "Random", "Clone Order")
    M.put(c, "Clone Order", "Random")
    changes(c, "Seed", 5, "Random order: Seed")
    M.put(c, "Clone Order", "Iterate")
    update()
    inst = [i for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance and i.parent and i.parent.original == c]
    M.put(c, "Keep Instances", True)
    update()
    inst2 = [i for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance and i.parent and i.parent.original == c]
    check(len(inst) == 0 and len(inst2) == 12, f"Keep as Instances: copies stay instances ({len(inst)} -> {len(inst2)})")


EFFECTOR_ROWS = {   # each row and a value that must change the copies
    "random_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 80.0, 0.0)), ("b4d_eff_rotation", (0.5, 0.0, 0.0)),
                        ("b4d_eff_scale", (50.0, 0.0, 0.0)), ("b4d_eff_seed", 9), ("b4d_eff_use_color", True)],
    "step_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 80.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.0, 0.7)),
                      ("b4d_eff_scale", (0.0, 30.0, 0.0)), ("b4d_eff_use_color", True)],
    "target_effector": [("b4d_eff_strength", 40.0)],
    "time_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (10.0, 0.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.3, 0.0)),
                      ("b4d_eff_scale", (20.0, 20.0, 20.0))],
}


def setv(ob, key, v):
    ob[key] = list(v) if isinstance(v, tuple) else v
    ob.update_tag()


def test_effector(kind):
    print("==", kind)
    clear()
    box = cube(size=0.4)
    box.scale = (1.0, 2.0, 0.5)                       # not round, so turning shows
    c = add("cloner", box)
    M.put(c, "Count", 5)
    bpy.context.scene.frame_set(25)                   # Time works on the scene's time
    base = result(c)
    e = add(kind, c)
    check(M.effector_kind(e) == kind and [o for o, k in M.effectors_of(c)] == [e], "made with the Cloner selected: in its list")
    if kind == "time_effector":
        bpy.context.scene.frame_set(1)
        at1 = result(c)
        bpy.context.scene.frame_set(13)
        check(result(c) != at1, "changes the copies as the animation plays")
        bpy.context.scene.frame_set(25)
    on = result(c)
    check(on != base, "changes the copies")
    if kind == "step_effector":                           # from unchanged at the first copy to the full amount at the last
        for k, v in (("b4d_eff_position", (0.0, 0.0, 0.0)), ("b4d_eff_scale", (0.0, 100.0, 0.0))):
            setv(e, k, v)
        update()
        ev = c.evaluated_get(bpy.context.evaluated_depsgraph_get())
        check(abs(ev.dimensions.z - 0.4) < 1e-3, f"Step: the last copy gets the full amount and no more (twice as tall) ({ev.dimensions.z:.3f} m)")
        setv(e, "b4d_eff_scale", (100.0, 100.0, 100.0))
        on = result(c)
    if kind == "target_effector":
        e.location.x += 4.0
        check(result(c) != on, "moving the effector turns the copies again")
    for key, v in EFFECTOR_ROWS[kind]:
        before = result(c)
        old = e[key]
        old = tuple(old) if hasattr(old, "__len__") else old
        setv(e, key, v)
        check(result(c) != before, f"row {key}")
        if key == "b4d_eff_use_color":
            cols = result(c)[1]
            check(any(col != (1.0, 1.0, 1.0, 1.0) for col in cols), "Color tints the copies")
            before = result(c)
            setv(e, "b4d_eff_color", (0.0, 1.0, 0.0))
            check(result(c) != before, "row b4d_eff_color")
        else:
            setv(e, key, old)
    e["_b4d_enabled"] = False
    e.update_tag()
    check(result(c) == base, "check mark off: the copies are as without it")
    e["_b4d_enabled"] = True
    e.update_tag()
    check(result(c) != base, "check mark on again: it acts again")
    c.b4d_effectors.remove(0)
    update()
    check(result(c) == base, "taken out of the list: the copies are as without it")


def test_two_cloners_one_effector():
    print("== one effector, two Cloners, list order")
    clear()
    a = add("cloner", cube("A"))
    b = add("cloner", cube("B", loc=(0, 3, 0)))
    base_a, base_b = result(a), result(b)
    select(a, b)
    bpy.ops.blenda4d.add_kind(kind="random_effector")
    e = bpy.context.view_layer.objects.active
    check(result(a) != base_a and result(b) != base_b, "added to every selected Cloner")
    setv(e, "b4d_eff_seed", 3)
    check(result(a) != base_a and result(b) != base_b, "a change on the effector reaches both")
    select(a)
    bpy.ops.blenda4d.add_kind(kind="step_effector")
    s = bpy.context.view_layer.objects.active
    setv(s, "b4d_eff_rotation", (0.0, 0.0, 1.0))
    one = result(a)
    select(a)
    bpy.ops.blenda4d.effector_slot(action="UP")
    check([o.name for o, _k in M.effectors_of(a)] == [s.name, e.name], "Up moves the effector earlier")
    check(result(a) != one, "the order changes the result")


def test_switch():
    print("== switching off and on")
    clear()
    box = cube()
    c = add("cloner", box)
    e = add("random_effector", c)
    shown = result(c)
    M.unregister()
    check(M._on_update not in bpy.app.handlers.depsgraph_update_post, "off: no handler left")
    check(not hasattr(bpy.types.Object, "b4d_effectors"), "off: no Object property left")
    check(all(k not in kinds.KINDS for k in ("cloner",) + M.EFFECTOR_ORDER), "off: no object kinds left")
    check(all(m[2] is None for g in ("moclone", "effectors") for m in bars.GROUPS[g]), "off: the create column is greyed again")
    check(any(it[0] == "Cloner" and it[1] is None for it in menus.MAIN["MoClone"] if isinstance(it, tuple)),
          "off: the MoClone menu is as it was")
    check(not any(e[1] == "cloner" for e in kinds.menu_items("MoClone")), "off: no MoClone menu entries left")
    bpy.context.view_layer.update()                     # no sync: with the module off nothing keeps the Cloner in step
    ev = c.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    plain = tuple(sorted(tuple(round(x, 4) for x in v.co) for v in me.vertices))
    ev.to_mesh_clear()
    check(plain == shown[0], "off: the file still shows the same copies (plain Blender)")
    M.register()
    check(bars.GROUPS["moclone"][0][2] == "blenda4d.add_kind" and
          [m[0] for m in bars.GROUPS["effectors"] if m[2]] == [M.EFFECTORS[k][0] for k in M.EFFECTOR_ORDER],
          "on again: Cloner and the four effectors are live in the create column")
    check(not any(isinstance(it, tuple) and it[0] in ("Cloner", "Effectors") and it[1] is None for it in menus.MAIN["MoClone"]),
          "on again: no greyed stand-ins in the MoClone menu")
    check(len(c.b4d_effectors) == 1 and c.b4d_effectors[0].object == e, "on again: the effector list is still there")
    check(result(c) == shown, "on again: same copies")


EFFECTOR_TESTS = [(lambda k: lambda: test_effector(k))(k) for k in M.EFFECTOR_ORDER]
for t in (test_cloner_basics, test_rows, *EFFECTOR_TESTS, test_two_cloners_one_effector, test_switch):
    try:
        t()
    except Exception:
        traceback.print_exc()
        fails.append(getattr(t, "__name__", "test") + ": error")

M.unregister()
print("B4D MOCLONE", "FAILS" if fails else "OK", len(fails), flush=True)
for f in fails:
    print("  ", f)
sys.exit(1 if fails else 0)
