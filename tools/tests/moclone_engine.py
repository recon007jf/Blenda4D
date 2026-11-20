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
        if o is not None:
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
                        ("b4d_eff_scale", (50.0, 0.0, 0.0)), ("b4d_eff_seed", 9), ("b4d_eff_random_mode", 1),
                        ("b4d_eff_random_mode", 2), ("b4d_eff_use_color", True)],
    "shader_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.4, 0.0)),
                        ("b4d_eff_scale", (0.0, 50.0, 0.0)), ("b4d_eff_pattern", 1), ("b4d_eff_pattern", 2), ("b4d_eff_pattern", 3),
                        ("b4d_eff_pattern", 4),
                        ("b4d_eff_noise_size", 60.0), ("b4d_eff_contrast", 20.0), ("b4d_eff_seed", 5),
                        ("b4d_eff_use_color", True)],
    "wave_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.4, 0.0)),
                      ("b4d_eff_scale", (0.0, 50.0, 0.0)), ("b4d_eff_wave_shape", 1), ("b4d_eff_wave_shape", 2),
                      ("b4d_eff_wave_shape", 3), ("b4d_eff_frequency", 1.3), ("b4d_eff_spread", 2.5), ("b4d_eff_use_color", True)],
    "step_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 80.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.0, 0.7)),
                      ("b4d_eff_scale", (0.0, 30.0, 0.0)), ("b4d_eff_use_color", True)],
    "plain_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.4, 0.0)),
                       ("b4d_eff_scale", (0.0, 50.0, 0.0)), ("b4d_eff_use_color", True)],
    "target_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_upright", True)],
    "time_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (10.0, 0.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.3, 0.0)),
                      ("b4d_eff_scale", (20.0, 20.0, 20.0))],
    "inheritance_effector": [("b4d_eff_strength", 40.0)],
    "push_apart_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_radius", 150.0), ("b4d_eff_iterations", 1)],
    "spline_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_start", 20.0), ("b4d_eff_end", 60.0), ("b4d_eff_offset", 10.0),
                        ("b4d_eff_align", False)],
    "formula_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.4, 0.0)),
                         ("b4d_eff_scale", (0.0, 50.0, 0.0)), ("b4d_eff_formula", "id * 0.3 + x / 400"), ("b4d_eff_use_color", True)],
    "sound_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_gain", 40.0),
                       ("b4d_eff_use_color", True)],
    "group_effector": [("b4d_eff_strength", 40.0)],
    "volume_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.4, 0.0)),
                        ("b4d_eff_scale", (0.0, 50.0, 0.0)), ("b4d_eff_use_color", True)],
}


def points_mesh(name, pts):
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, [], [])
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def spline(name="Path"):
    cu = bpy.data.curves.new(name, "CURVE")
    sp = cu.splines.new("POLY")
    sp.points.add(2)
    for p, co in zip(sp.points, ((-2.0, 1.0, 0.0, 1.0), (0.0, 3.0, 0.0, 1.0), (2.0, 1.0, 1.0, 1.0))):
        p.co = co
    ob = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(ob)
    return ob


def setup_effector(kind, e):
    """What the effector needs before it can act: a source, a spline or a volume."""
    if kind == "inheritance_effector":
        setv(e, "b4d_eff_source", points_mesh("Spots", [(i * 0.3, 2.0, i * 0.2) for i in range(4)]))
    elif kind == "spline_effector":
        setv(e, "b4d_eff_spline", spline())
    elif kind == "shader_effector":
        setv(e, "b4d_eff_image", gradient_image())
    elif kind == "sound_effector":
        setv(e, "b4d_eff_sound", tone_file())
        M.bake_bands(e, bpy.context.scene)
        bpy.context.scene.frame_set(3)
    elif kind == "group_effector":
        select(e)
        bpy.ops.blenda4d.add_kind(kind="plain_effector")
        member = bpy.context.view_layer.objects.active
        member.select_set(False)
        e.select_set(True)
        bpy.context.view_layer.objects.active = e
    elif kind == "volume_effector":
        vol = cube("Inside", size=1.0, loc=(0.0, 0.0, 0.0))
        vol.select_set(False)
        setv(e, "b4d_eff_volume", vol)


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
    bpy.context.scene.frame_set(3 if kind == "sound_effector" else 25)   # Time works on the scene's time; frame 3 is loud
    base = result(c)
    e = add(kind, c)
    check(M.effector_kind(e) == kind and [o for o, k in M.effectors_of(c)] == [e], "made with the Cloner selected: in its list")
    if kind in ("inheritance_effector", "spline_effector", "volume_effector", "group_effector"):
        check(result(c) == base, "with nothing picked or held yet: no change")
    setup_effector(kind, e)
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
    if kind == "inheritance_effector":
        setv(e, "b4d_eff_strength", 100.0)
        pts = sorted(result(c)[0])
        src = e["b4d_eff_source"]
        ys = [p[1] for p in pts]
        check(1.55 < min(ys) and max(ys) < 2.45, f"full Strength: the copies sit on the Source's points (y {min(ys):.2f}..{max(ys):.2f})")
        m = M.create_object(bpy.context, "matrix")
        M.put(m, "Count", 5)
        M.put(m, "Offset", (0.0, 120.0, 0.0))
        setv(e, "b4d_eff_source", m)
        check(sorted(result(c)[0]) != pts, "Source a Matrix: the copies take its places")
        src.location.x += 1.0
        setv(e, "b4d_eff_source", src)
        on = result(c)
    if kind == "spline_effector":
        sp = e["b4d_eff_spline"]
        before = result(c)
        sp.location.z += 1.0
        check(result(c) != before, "moving the spline moves the copies")
    if kind == "group_effector":
        member = e.b4d_effectors[0].object
        check(M.effector_kind(member) == "plain_effector" and not M.effectors_of(c)[1:],
              "made with the Group selected: it goes into the Group, not the Cloner")
        before = result(c)
        setv(member, "b4d_eff_position", (0.0, 0.0, 250.0))
        check(result(c) != before, "a change on an effector in the Group reaches the copies")
        e.b4d_effectors[0].use = False
        check(result(c) == base, "unticked in the Group: it no longer acts")
        e.b4d_effectors[0].use = True
        on = result(c)
    if kind == "sound_effector":
        bands3 = list(e["b4d_eff_bands"])
        bpy.context.scene.frame_set(18)
        bands18 = list(e["b4d_eff_bands"])
        check(max(bands3) > 0.3 and max(bands18) < max(bands3) * 0.2,
              f"bands baked: loud frames high, quiet frames low ({max(bands3):.2f}, {max(bands18):.2f})")
        check(max(range(16), key=lambda i: bands3[i]) in range(5, 11), "the 440 Hz tone lands in a middle band")
        quiet = result(c)
        bpy.context.scene.frame_set(3)
        check(result(c) != quiet, "the copies follow the sound from frame to frame")
    if kind == "volume_effector":
        vol = e["b4d_eff_volume"]
        before = result(c)
        vol.location.x += 0.6
        check(result(c) != before, "moving the volume changes which copies are inside")
    for key, v in EFFECTOR_ROWS[kind]:
        before = result(c)
        old = e[key]
        old = tuple(old) if hasattr(old, "__len__") and not isinstance(old, str) else old
        setv(e, key, v)
        check(result(c) != before, f"row {key}")
        if key == "b4d_eff_use_color":
            cols = result(c)[1]
            check(any(col != (1.0, 1.0, 1.0, 1.0) for col in cols), "Color tints the copies")
            before = result(c)
            setv(e, "b4d_eff_color", (0.0, 1.0, 0.0))
            check(result(c) != before, "row b4d_eff_color")
            before = result(c)
            setv(e, "b4d_eff_color_mode", 1)
            check(result(c)[1] != before[1], "Color Mode Gradient: the tint changes")
            before = result(c)
            setv(e, "b4d_eff_color2", (1.0, 0.0, 1.0))
            check(result(c)[1] != before[1], "row b4d_eff_color2 (gradient's other end)")
            setv(e, "b4d_eff_color_mode", 0)
        else:
            setv(e, key, old)
    if kind in ("random_effector", "shader_effector"):     # Speed: the pattern (Random in Noise mode) moves in time
        if kind == "random_effector":
            setv(e, "b4d_eff_random_mode", 2)
        before = result(c)
        setv(e, "b4d_eff_speed", 3.0)
        check(result(c) != before, "row b4d_eff_speed")
        setv(e, "b4d_eff_speed", 1.0)
        if kind == "random_effector":
            setv(e, "b4d_eff_random_mode", 0)
    e["_b4d_enabled"] = False
    e.update_tag()
    check(result(c) == base, "check mark off: the copies are as without it")
    e["_b4d_enabled"] = True
    e.update_tag()
    check(result(c) != base, "check mark on again: it acts again")
    c.b4d_effectors.remove(0)
    update()
    check(result(c) == base, "taken out of the list: the copies are as without it")


def test_null_clone():
    print("== a Null with objects under it, copied as one clone")
    clear()
    null = bpy.data.objects.new("Group", None)
    bpy.context.collection.objects.link(null)
    a = cube("Top", size=0.2, loc=(0.0, 0.0, 0.3))
    b = cube("Bottom", size=0.2, loc=(0.0, 0.0, -0.3))
    for o in (a, b):
        o.parent = null
    select(null)
    c = add("cloner", null)
    check(null.parent == c and M.kids_of(c) == [null], "the Null goes under the Cloner and is its one child")
    M.put(c, "Count", 3)
    pts = result(c)[0]
    check(len(pts) == 3 * 16, f"each clone is both cubes together ({len(pts)} points for 3 clones)")
    check(a.display_type == "WIRE" and b.display_type == "WIRE", "the objects under the Null show as a wire while copied")
    a.location.z += 0.5
    check(result(c)[0] != pts, "moving an object under the Null changes every clone")
    b.parent = None
    update()
    check(b.display_type != "WIRE", "taken out from under the Null: it shows again")


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
    bpy.ops.blenda4d.link_slot(prop="b4d_effectors", action="UP")
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
    check(all(k not in kinds.KINDS for k in M.GROUP_OF), "off: no MoClone kinds left")
    check(all(m[2] is None for g in ("moclone", "effectors", "fields") for m in bars.GROUPS[g]),
          "off: the create column's MoClone, effector and field groups are greyed again")
    check(any(it[0] == "Matrix" and it[1] is None for it in menus.MAIN["MoClone"] if isinstance(it, tuple)),
          "off: the MoClone menu is as it was")
    check(not kinds.menu_items("MoClone"), "off: no MoClone menu entries left")
    from blenda4d import managers
    check(M.drop not in managers.OM_DROP, "off: the Object Manager drop hook is gone")
    bpy.context.view_layer.update()                     # no sync: with the module off nothing keeps the Cloner in step
    ev = c.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    plain = tuple(sorted(tuple(round(x, 4) for x in v.co) for v in me.vertices))
    ev.to_mesh_clear()
    check(plain == shown[0], "off: the file still shows the same copies (plain Blender)")
    M.register()
    live = {m[0] for g in ("moclone", "effectors", "fields") for m in bars.GROUPS[g] if m[2]}
    want = {v[0] for v in list(M.OBJECTS.values()) + list(M.EFFECTORS.values()) + list(M.FIELDS.values())}
    check(live == want and all(m[2] for g in ("moclone", "effectors", "fields") for m in bars.GROUPS[g]),
          f"on again: every MoClone, effector and field button is live ({len(live)})")
    check(not any(isinstance(it, tuple) and it[1] is None for it in menus.MAIN["MoClone"]),
          "on again: no greyed stand-ins in the MoClone menu")
    check({e[1] for e in kinds.menu_items("MoClone")} == set(M.GROUP_OF), "on again: the MoClone menu lists everything")
    check(len(c.b4d_effectors) == 1 and c.b4d_effectors[0].object == e, "on again: the effector list is still there")
    check(result(c) == shown, "on again: same copies")


def count(ob):
    """(points, instances) the object shows."""
    update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    ev.to_mesh_clear()
    return n, sum(1 for i in dg.object_instances if i.is_instance and i.parent and i.parent.original == ob)


def test_more_layouts():
    print("== Honeycomb, end points, Grid forms")
    clear()
    c = add("cloner", cube())
    M.put(c, "Mode", "Linear")
    M.put(c, "Count", 4)
    per = result(c)
    M.put(c, "Offset Mode", "End Point")
    end = result(c)
    check(end != per, "Linear: End Point spreads Offset over the row")
    xs = sorted({p[0] for p in end[0]})
    check(abs((xs[-1] - xs[0]) - (1.0 + 0.4)) < 1e-3, f"Linear End Point: the row is Offset long ({xs[-1] - xs[0]:.3f} m incl. one box)")
    M.put(c, "Mode", "Honeycomb")
    check(len(result(c)[0]) == 15 * 8, "Honeycomb: Count X by Count Z copies")
    for name, v in (("Count X", 6), ("Count Z", 4), ("Spacing", (90.0, 100.0, 200.0)), ("Spacing Mode", "End Point")):
        changes(c, name, v, f"Honeycomb: {name}")
    pts = result(c)[0]
    rows = {}
    for p in pts:
        rows.setdefault(round(p[1], 3), []).append(p[0])
    shifts = sorted({round(min(v), 3) for v in rows.values()})
    check(len(shifts) == 2, f"Honeycomb: every other row is shifted ({shifts})")
    M.put(c, "Mode", "Grid")
    M.put(c, "Count Y", 5)
    M.put(c, "Count X", 5)
    M.put(c, "Count Z", 5)
    box = len(result(c)[0]) // 8
    for form, want in (("Sphere", lambda n: n < box), ("Cylinder", lambda n: n < box)):
        M.put(c, "Form", form)
        n = len(result(c)[0]) // 8
        check(want(n), f"Grid Form {form}: keeps the places inside ({n} of {box})")
    M.put(c, "Form", "Box")
    changes(c, "Spacing Mode", "End Point", "Grid: Spacing Mode")


def test_list_checkboxes():
    print("== list check boxes")
    clear()
    c = add("cloner", cube())
    base = result(c)
    e = add("plain_effector", c)
    on = result(c)
    check(on != base, "Plain Effector moves every copy")
    c.b4d_effectors[0].use = False
    check(result(c) == base and e in [x for x in bpy.data.objects] and len(c.b4d_effectors) == 1,
          "unticking the row leaves the effector out but keeps it in the list")
    c.b4d_effectors[0].use = True
    check(result(c) == on, "ticking it again brings it back")


class Ev:                                              # the parts of a mouse event the drop reads
    mouse_x = mouse_y = -1


def test_drop():
    print("== drag and drop into the lists")
    clear()
    c = add("cloner", cube())
    select()
    e = add("random_effector")
    check(not len(c.b4d_effectors), "an effector made with nothing selected is in no list")
    base = result(c)
    check(M.drop(bpy.context, Ev(), [e], c.name) and [o for o, _k in M.effectors_of(c)] == [e],
          "an effector dropped on the Cloner's row goes into its Effectors list")
    check(e.parent is None and result(c) != base, "...without being put under it, and it acts")
    check(M.drop(bpy.context, Ev(), [e], c.name) and len(c.b4d_effectors) == 1, "dropping it again does not add it twice")
    plain = cube("Plain", loc=(3, 0, 0))
    check(not M.drop(bpy.context, Ev(), [plain], c.name), "a plain object dropped on the Cloner is left to the Object Manager")
    select()
    f = add("box_field")
    check(M.drop(bpy.context, Ev(), [f], e.name) and [x[0] for x in M.fields_of(e)] == [f],
          "a Field dropped on an effector's row goes into its Fields list")
    check(not M.drop(bpy.context, Ev(), [f], c.name), "a Field dropped on a Cloner is not taken")


AXIS_X = (0.0, 1.5708, 0.0)                         # the Field's up axis (shown Y, Blender Z) along the row of copies
FIELD_POSE = {"linear_field": ((0.0, 0.0, 0.0), (0.0, 0.0, -1.5708)), "cylinder_field": ((0.0, 1.0, 0.0), AXIS_X),
              "capsule_field": ((0.0, 1.0, 0.0), AXIS_X), "cone_field": ((0.0, 0.5, 0.0), AXIS_X),
              "radial_field": ((4.0, -1.0, 0.0), (0.0, 0.0, 0.0))}
FIELD_ROWS = {
    "cylinder_field": [("b4d_fld_radius", 20.0), ("b4d_fld_height", 150.0), ("b4d_fld_falloff", 90.0)],
    "capsule_field": [("b4d_fld_radius", 20.0), ("b4d_fld_height", 900.0), ("b4d_fld_falloff", 90.0)],
    "cone_field": [("b4d_fld_radius", 900.0), ("b4d_fld_height", 300.0), ("b4d_fld_falloff", 90.0)],
    "torus_field": [("b4d_fld_radius", 500.0), ("b4d_fld_tube", 160.0), ("b4d_fld_falloff", 90.0)],
    "radial_field": [("b4d_fld_sweep", 1.0)],
    "shader_field": [("b4d_fld_pattern", 1), ("b4d_fld_pattern", 2), ("b4d_fld_pattern", 3), ("b4d_fld_noise_size", 60.0),
                     ("b4d_fld_seed", 4), ("b4d_fld_contrast", 20.0), ("b4d_fld_speed", 2.0)],
    "wave_field": [("b4d_fld_wavelength", 130.0), ("b4d_fld_speed", 2.0)],
    "image_field": [("b4d_fld_image_size", 900.0)],
    "sound_field": [("b4d_fld_gain", 40.0)],
    "spherical_field": [("b4d_fld_radius", 120.0), ("b4d_fld_falloff", 90.0)],
    "box_field": [("b4d_fld_size", (180.0, 400.0, 200.0)), ("b4d_fld_falloff", 90.0)],
    "linear_field": [("b4d_fld_length", 900.0)],
    "random_field": [("b4d_fld_noise_size", 60.0), ("b4d_fld_seed", 4), ("b4d_fld_contrast", 100.0), ("b4d_fld_speed", 2.0)],
    "formula_field": [("b4d_fld_formula", "x / 300")],
    "time_field": [("b4d_fld_duration", 5.0), ("b4d_fld_delay", 0.2)],
    "object_field": [("b4d_fld_distance", 300.0)],
    "spline_field": [("b4d_fld_radius", 60.0), ("b4d_fld_falloff", 90.0)],
    "material_field": [("b4d_fld_image_size", 900.0)],
    "group_field": [("b4d_fld_falloff", 50.0)],
}
FIELD_ROWS["group_field"] = []


def test_field(kind):
    print("==", kind)
    clear()
    c = add("cloner", cube())
    M.put(c, "Count", 9)
    M.put(c, "Offset", (100.0, 0.0, 0.0))
    base = result(c)
    e = add("plain_effector", c)
    full = result(c)
    f = add(kind, e)
    check([x[0] for x in M.fields_of(e)] == [f], "made with the effector selected: in its Fields list")
    loc, rot = FIELD_POSE.get(kind, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
    f.location, f.rotation_euler = loc, rot
    if kind == "image_field":                         # bright on the right half only
        setv(f, "b4d_fld_image", gradient_image())
    if kind == "sound_field":                         # loud on even half-seconds, quiet on odd ones
        setv(f, "b4d_fld_sound", tone_file())
        M.bake_sound(f, bpy.context.scene)
        bpy.context.scene.frame_set(3)
        loud = result(c)
        bpy.context.scene.frame_set(18)
        check(result(c) != loud and loud != base, "Sound: the effect follows the loudness from frame to frame")
        bpy.context.scene.frame_set(12)
    if kind == "object_field":
        ball = points_mesh("Lump", [])
        bpy.data.objects.remove(ball)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.2, location=(1.0, 0.0, 0.0))
        ball = bpy.context.object
        setv(f, "b4d_fld_object", ball)
    if kind == "spline_field":
        setv(f, "b4d_fld_spline", spline())
        f["b4d_fld_spline"].location = (0.0, -2.0, 0.0)
    if kind == "material_field":
        mat = bpy.data.materials.new("Stripes")
        mat.use_nodes = True
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = gradient_image()
        setv(f, "b4d_fld_material", mat)
    if kind == "group_field":
        select(f)
        bpy.ops.blenda4d.add_kind(kind="spherical_field")
        inner = bpy.context.view_layer.objects.active
        setv(inner, "b4d_fld_radius", 150.0)
        check([x[0] for x in M.fields_of(f)] == [inner], "a Field made with the Group Field selected goes into it")
    if kind == "torus_field":
        setv(f, "b4d_fld_radius", 250.0)
        setv(f, "b4d_fld_tube", 100.0)
    bpy.context.scene.frame_set(12)
    limited = result(c)
    check(limited != full and limited != base, "the effector now acts on some copies, not all of them the same")
    for key, v in FIELD_ROWS[kind] + [("b4d_fld_strength", 30.0), ("b4d_fld_invert", True)]:
        before = result(c)
        old = f[key]
        old = tuple(old) if hasattr(old, "__len__") and not isinstance(old, str) else old
        if key == "b4d_fld_speed":
            setv(f, key, v)
            bpy.context.scene.frame_set(40)
            check(result(c) != before, f"row {key} (the pattern moves)")
            bpy.context.scene.frame_set(12)
        else:
            setv(f, key, v)
            check(result(c) != before, f"row {key}")
        setv(f, key, old)
    if kind == "time_field":
        bpy.context.scene.frame_set(36)
        check(result(c) != limited, "Time: later in the animation the effect has grown")
        bpy.context.scene.frame_set(12)
    if kind not in ("random_field", "shader_field", "wave_field", "sound_field", "time_field", "object_field",
                    "spline_field", "group_field"):
        f.location.x += 3.0
        check(result(c) != limited, "moving the Field moves where the effector acts")
        f.location.x -= 3.0
    f["_b4d_enabled"] = False
    f.update_tag()
    check(result(c) == full, "Field switched off: the effector acts everywhere again")
    f["_b4d_enabled"] = True
    f.update_tag()
    e.b4d_fields[0].use = False
    check(result(c) == full, "row unticked in the Fields list: the same")
    e.b4d_fields[0].use = True
    check(result(c) == limited, "ticked again: limited again")


def test_two_fields():
    print("== two Fields: the stronger wins")
    clear()
    c = add("cloner", cube())
    M.put(c, "Count", 9)
    e = add("plain_effector", c)
    a = add("spherical_field", e)
    setv(a, "b4d_fld_radius", 150.0)
    one = result(c)
    b = add("spherical_field", e)
    b.location = (8.0, 0.0, 0.0)
    setv(b, "b4d_fld_radius", 150.0)
    check(result(c) != one, "a second Field adds the places it reaches")
    e.b4d_fields[1].use = False
    check(result(c) == one, "...and leaving it out takes them away again")


def gradient_image():
    """A 4 x 4 image: black on the left half, white on the right."""
    img = bpy.data.images.get("B4D Gradient") or bpy.data.images.new("B4D Gradient", 4, 4)
    px = []
    for y in range(4):
        for x in range(4):
            v = 1.0 if x >= 2 else 0.0
            px += [v, v, v, 1.0]
    img.pixels[:] = px
    return img


def tone_file():
    """A 2 s 440 Hz tone: loud for half a second, near silent for half a second, and again."""
    import math, struct, tempfile, wave
    path = os.path.join(tempfile.gettempdir(), "b4d_tone.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(struct.pack("<h", int(30000 * math.sin(2 * math.pi * 440 * i / 22050) *
                                                       (1.0 if (i // 11025) % 2 == 0 else 0.02))) for i in range(44100)))
    return path


def test_image_and_sound():
    print("== Image and Sound Fields")
    clear()
    c = add("cloner", cube())
    M.put(c, "Count", 9)
    M.put(c, "Offset", (50.0, 0.0, 0.0))
    e = add("plain_effector", c)
    full = result(c)
    f = add("image_field", e)
    no_image = result(c)
    check(no_image != full, "Image Field with no image: the effector acts nowhere")
    img = gradient_image()
    setv(f, "b4d_fld_image", img)
    half = result(c)
    check(half not in (full, no_image), "with a half-white image: the effector acts on part of the copies")
    black = bpy.data.images.new("B4D Black", 2, 2)
    black.pixels[:] = [0.0, 0.0, 0.0, 1.0] * 4
    setv(f, "b4d_fld_image", black)
    check(result(c) == no_image, "a black image: acts nowhere (picking another image rebuilds)")
    setv(f, "b4d_fld_image", img)
    clear()
    c = add("cloner", cube())
    e = add("plain_effector", c)
    s = add("sound_field", e)
    path = tone_file()
    setv(s, "b4d_fld_sound", path)
    n = M.bake_sound(s, bpy.context.scene)
    check(n == 48, f"Sound: one loudness value per frame ({n} frames for 2 s at 24 fps)")
    bpy.context.scene.frame_set(3)
    loud = float(s["b4d_fld_level"])
    bpy.context.scene.frame_set(18)
    quiet = float(s["b4d_fld_level"])
    check(loud > 0.8 and quiet < 0.1, f"Sound: loud frames near 1, quiet ones near 0 ({loud:.2f}, {quiet:.2f})")
    setv(s, "b4d_fld_high", 100.0)
    M.bake_sound(s, bpy.context.scene)
    bpy.context.scene.frame_set(3)
    check(float(s["b4d_fld_level"]) < loud * 0.6, "row High: leaving out the 440 Hz tone lowers the loudness")
    setv(s, "b4d_fld_high", 20000.0)
    setv(s, "b4d_fld_low", 2000.0)
    M.bake_sound(s, bpy.context.scene)
    bpy.context.scene.frame_set(3)
    check(float(s["b4d_fld_level"]) < loud * 0.6, "row Low: the same from below")


def test_row_mix_and_memory():
    print("== Mix per row, and Fields that remember")
    clear()
    c = add("cloner", cube())
    M.put(c, "Count", 9)
    e = add("plain_effector", c)
    f = add("spherical_field", e)
    setv(f, "b4d_fld_radius", 150.0)
    full = result(c)
    e.b4d_fields[0].mix = 50.0
    check(result(c) != full, "row Mix: half the Field, half the effect")
    e.b4d_fields[0].mix = 100.0
    # the Field travels along the row from frame 1 to 10
    f.location = (0.0, 0.0, 0.0)
    f.keyframe_insert("location", frame=1)
    f.location = (8.0, 0.0, 0.0)
    f.keyframe_insert("location", frame=10)

    def lifted():
        """How many copies are lifted (moved up) now."""
        pts = result(c)[0]
        return len({round(p[0], 1) for p in pts if p[2] > 0.5})

    def play(to):
        update()
        bpy.context.scene.frame_set(1)
        for fr in range(1, to + 1):
            bpy.context.scene.frame_set(fr)
    play(10)
    now_only = lifted()
    setv(e, "b4d_eff_memory", 1)
    play(10)
    kept = lifted()
    check(kept > now_only, f"Remember Keep: the copies the Field passed stay lifted ({now_only} -> {kept})")
    setv(e, "b4d_eff_memory", 2)
    setv(e, "b4d_eff_fade", 0.1)
    play(10)
    faded = lifted()
    check(now_only <= faded < kept, f"Remember Fade: they let go after Fade Time ({faded})")
    setv(e, "b4d_eff_fade", 5.0)
    play(10)
    check(lifted() > faded, "row Fade Time: a longer fade keeps more lifted")
    setv(e, "b4d_eff_memory", 0)
    play(10)
    check(lifted() == now_only, "Remember Off: as before")


def test_field_blends():
    print("== Field blend modes")
    clear()
    c = add("cloner", cube())
    M.put(c, "Count", 9)
    e = add("plain_effector", c)
    a = add("spherical_field", e)
    setv(a, "b4d_fld_radius", 300.0)
    setv(a, "b4d_fld_falloff", 90.0)
    b = add("box_field", e)
    b.location = (2.0, 0.0, 0.0)                      # overlapping the ball, both with soft edges
    setv(b, "b4d_fld_size", (400.0, 400.0, 400.0))
    setv(b, "b4d_fld_falloff", 90.0)
    seen = {}
    for blend in ("MAX", "ADD", "SUBTRACT", "MULTIPLY", "MIN"):
        e.b4d_fields[1].blend = blend
        seen[blend] = result(c)
    check(len(set(seen.values())) == 5, f"every way of combining gives its own result ({len(set(seen.values()))} of 5)")
    e.b4d_fields[0].blend = "SUBTRACT"
    e.b4d_fields[1].blend = "MAX"
    check(result(c) == seen["MAX"], "the first row's way of combining does nothing (it starts the reach)")


def test_matrix():
    print("== Matrix")
    clear()
    m = add("matrix")
    check(m.hide_render, "a Matrix does not render")
    n, inst = count(m)
    check(inst == 15 and n == 0, f"Grid of small cubes as instances ({inst})")
    def cube_size():
        update()
        dg = bpy.context.evaluated_depsgraph_get()
        sizes = [max(i.object.dimensions) * i.matrix_world.to_scale()[0] for i in dg.object_instances
                 if i.is_instance and i.parent and i.parent.original == m]
        return round(sizes[0], 4) if sizes else 0.0
    small = cube_size()
    M.put(m, "Cube Size", 40.0)
    check(abs(small - 0.1) < 1e-3 and abs(cube_size() - 0.4) < 1e-3, f"Cube Size ({small} m -> {cube_size()} m)")
    for name, v in (("Mode", "Linear"), ("Mode", "Radial"), ("Mode", "Honeycomb")):
        before = count(m)[1]
        M.put(m, name, v)
        check(count(m)[1] != 0, f"Matrix {v}: places shown")
    M.put(m, "Mode", "Grid")
    c = add("cloner", cube("Box", size=0.2, loc=(0, 0, 3)))
    M.put(c, "Mode", "Object")
    M.put(c, "Object", m)
    M.put(c, "Distribution", "Points")
    check(len(result(c)[0]) == 15 * 8, "a Cloner on the Matrix's places: one copy per place")
    before = result(c)
    e = add("random_effector", m)
    check(result(c) != before, "an effector on the Matrix moves the Cloner's copies too")


def test_fracture():
    print("== Fracture")
    clear()
    a = cube("A", size=1.0, loc=(-2, 0, 0))
    b = cube("B", size=1.0, loc=(2, 0, 0))
    fr = add("fracture", a, b)
    check(a.parent == fr and b.parent == fr and a.display_type == "WIRE", "made around the selected objects, which show as a wire")
    n, inst = count(fr)
    check(n == 16, f"both objects show as they are ({n} points)")
    base = result(fr)
    e = add("random_effector", fr)
    check(result(fr) != base, "an effector moves the pieces")
    M.put(fr, "Keep Instances", True)
    check(count(fr)[1] == 2, "every object is one piece")
    M.put(fr, "Keep Instances", False)
    joined = cube("Two", size=1.0, loc=(0, 4, 0))
    other = cube("Other", size=0.5, loc=(0, 6, 0))
    select(joined, other)
    bpy.context.view_layer.objects.active = joined
    bpy.ops.object.join()
    joined.parent = fr
    M.put(fr, "Explode Segments", True)
    M.put(fr, "Keep Instances", True)
    check(count(fr)[1] == 4, f"Explode Segments: every loose part is a piece ({count(fr)[1]})")
    M.put(fr, "Keep Instances", False)
    e["_b4d_enabled"] = False
    e.update_tag()
    off = result(fr)
    e["_b4d_enabled"] = True
    fr.b4d_effectors.remove(0)
    check(result(fr) == off, "with the effector off the pieces sit where they were")


def test_voronoi():
    print("== Voronoi Fracture")
    clear()
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    block = bpy.context.object
    stone = bpy.data.materials.new("Stone")
    block.data.materials.append(stone)
    v = add("voronoi_fracture", block)
    update()
    setv(v, "b4d_vor_count", 8)
    M.put(v, "Keep Instances", True)
    n, inst = count(v)
    check(6 <= inst <= 8, f"about Pieces pieces ({inst})")
    M.put(v, "Keep Instances", False)
    xs = [p.co.x for p in v.data.vertices]
    check(xs and abs(min(xs) + 1.0) < 1e-3 and abs(max(xs) - 1.0) < 1e-3, "the pieces fill the block exactly")
    check(list(v.data.materials) == [stone] and all(m is None or m.original == m for m in v.data.materials),
          "the pieces use the child's own material (not a temporary copy Blender frees later)")
    before = result(v)
    setv(v, "b4d_vor_seed", 5)
    check(result(v) != before, "row Seed")
    M.put(v, "Keep Instances", True)
    setv(v, "b4d_vor_count", 14)
    check(count(v)[1] > inst, "row Pieces")
    M.put(v, "Keep Instances", False)
    changes(v, "Piece Size", 80.0, "row Piece Size")
    base = result(v)
    add("random_effector", v)
    check(result(v) != base, "an effector moves the pieces")


def test_tracer():
    print("== Tracer")
    clear()
    bpy.ops.object.empty_add(location=(0, 0, 0))
    mover = bpy.context.object
    mover.keyframe_insert("location", frame=1)
    mover.location = (4, 0, 0)
    mover.keyframe_insert("location", frame=11)
    t = add("tracer", mover)
    check(M.get(t, "Object") == mover, "made with an object selected: traces it")

    def points():
        dg = bpy.context.evaluated_depsgraph_get()
        geo = t.evaluated_get(dg).evaluated_geometry()
        crv = geo.curves
        return len(crv.points) if crv else 0, len(crv.curves) if crv else 0

    for f in range(1, 12):
        bpy.context.scene.frame_set(f)
    n, lines = points()
    check(n >= 10 and lines == 1, f"one line through the places it passed ({n} points)")
    M.put(t, "Limit", 4)
    bpy.context.scene.frame_set(1)
    for f in range(1, 12):
        bpy.context.scene.frame_set(f)
    check(points()[0] <= 6, f"Limit keeps only the last frames ({points()[0]})")
    M.put(t, "Thickness", 5.0)
    update()
    check(count(t)[0] > 0, "Thickness turns the line into a tube that renders")
    c = add("cloner", cube())
    M.put(c, "Keep Instances", True)
    M.put(t, "Object", c)
    M.put(t, "Limit", 0)
    M.put(t, "Thickness", 0.0)
    e = add("time_effector", c)
    setv(e, "b4d_eff_position", (0.0, 100.0, 0.0))
    bpy.context.scene.frame_set(1)
    for f in range(1, 8):
        bpy.context.scene.frame_set(f)
    check(points()[1] == 3, f"traces every copy of a Cloner kept as instances ({points()[1]} lines)")


def test_delay():
    print("== Delay Effector")
    clear()
    c = add("cloner", cube())
    plain = add("plain_effector", c)
    setv(plain, "b4d_eff_position", (0.0, 0.0, 0.0))
    plain["b4d_eff_position"] = [0.0, 0.0, 0.0]
    plain.keyframe_insert('["b4d_eff_position"]', frame=1)
    plain["b4d_eff_position"] = [0.0, 300.0, 0.0]
    plain.keyframe_insert('["b4d_eff_position"]', frame=5)

    def top():
        return max(p[2] for p in result(c)[0])
    bpy.context.scene.frame_set(1)
    for f in range(1, 6):
        bpy.context.scene.frame_set(f)
    direct = top()
    d = add("delay_effector", c)
    check([k for _o, k in M.effectors_of(c)] == ["plain_effector", "delay_effector"], "added after the Plain Effector")
    bpy.context.scene.frame_set(1)
    for f in range(1, 6):
        bpy.context.scene.frame_set(f)
    lag = top()
    check(lag < direct - 0.2, f"the copies trail behind ({lag:.2f} m vs {direct:.2f} m)")
    for f in range(6, 40):
        bpy.context.scene.frame_set(f)
    check(abs(top() - direct) < 0.05, f"...and catch up ({top():.2f} m)")
    setv(d, "b4d_eff_strength", 20.0)
    bpy.context.scene.frame_set(1)
    for f in range(1, 6):
        bpy.context.scene.frame_set(f)
    check(lag < top() < direct + 1e-3, "less Strength trails less")
    setv(d, "b4d_eff_strength", 80.0)
    setv(d, "b4d_eff_delay_mode", 1)

    def peak():
        bpy.context.scene.frame_set(1)
        best = 0.0
        for f in range(1, 30):
            bpy.context.scene.frame_set(f)
            best = max(best, top())
        return best
    sprung = peak()
    check(sprung > direct + 0.05, f"Spring: the copies overshoot and bounce ({sprung:.2f} m vs {direct:.2f} m)")
    setv(d, "b4d_eff_damping", 90.0)
    check(peak() < sprung - 0.01, "row Damping: more damping, less overshoot")
    setv(d, "b4d_eff_stiffness", 200.0)
    check(abs(peak() - sprung) > 0.01, "row Stiffness changes the bounce")


def _named(f, n):
    f.__name__ = n
    return f


EFFECTOR_TESTS = [(lambda k: _named(lambda: test_effector(k), k))(k) for k in M.EFFECTOR_ORDER if k != "delay_effector"]
FIELD_TESTS = [(lambda k: _named(lambda: test_field(k), k))(k) for k in M.FIELD_ORDER]
for t in (test_cloner_basics, test_rows, test_more_layouts, *EFFECTOR_TESTS, test_list_checkboxes, test_drop,
          *FIELD_TESTS, test_two_fields, test_field_blends, test_image_and_sound, test_row_mix_and_memory, test_two_cloners_one_effector, test_matrix, test_fracture, test_voronoi,
          test_tracer, test_delay, test_null_clone, test_switch):
    if os.environ.get("B4D_ONLY") and os.environ["B4D_ONLY"] not in getattr(t, "__name__", ""):
        continue
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
