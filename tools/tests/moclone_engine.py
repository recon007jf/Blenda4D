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
                        ("b4d_eff_scale", (50.0, 0.0, 0.0)), ("b4d_eff_seed", 9), ("b4d_eff_use_color", True)],
    "step_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 80.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.0, 0.7)),
                      ("b4d_eff_scale", (0.0, 30.0, 0.0)), ("b4d_eff_use_color", True)],
    "plain_effector": [("b4d_eff_strength", 40.0), ("b4d_eff_position", (0.0, 30.0, 0.0)), ("b4d_eff_rotation", (0.0, 0.4, 0.0)),
                       ("b4d_eff_scale", (0.0, 50.0, 0.0)), ("b4d_eff_use_color", True)],
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
    check(M.drop(bpy.context, Ev(), [f], e.name) and [o for o, _k in M.fields_of(e)] == [f],
          "a Field dropped on an effector's row goes into its Fields list")
    check(not M.drop(bpy.context, Ev(), [f], c.name), "a Field dropped on a Cloner is not taken")


FIELD_ROWS = {
    "spherical_field": [("b4d_fld_radius", 120.0), ("b4d_fld_falloff", 90.0)],
    "box_field": [("b4d_fld_size", (180.0, 400.0, 200.0)), ("b4d_fld_falloff", 90.0)],
    "linear_field": [("b4d_fld_length", 900.0)],
    "random_field": [("b4d_fld_noise_size", 60.0), ("b4d_fld_seed", 4), ("b4d_fld_contrast", 100.0), ("b4d_fld_speed", 2.0)],
}


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
    check([o for o, _k in M.fields_of(e)] == [f], "made with the effector selected: in its Fields list")
    if kind == "linear_field":
        f.rotation_euler = (0.0, 0.0, -1.5708)          # its Z (shown) along the row
    f.location = (0.0, 0.0, 0.0)
    bpy.context.scene.frame_set(12)
    limited = result(c)
    check(limited != full and limited != base, "the effector now acts on some copies, not all of them the same")
    for key, v in FIELD_ROWS[kind] + [("b4d_fld_strength", 30.0), ("b4d_fld_invert", True)]:
        before = result(c)
        old = f[key]
        old = tuple(old) if hasattr(old, "__len__") else old
        if key == "b4d_fld_speed":
            setv(f, key, v)
            bpy.context.scene.frame_set(40)
            check(result(c) != before, f"row {key} (the pattern moves)")
            bpy.context.scene.frame_set(12)
        else:
            setv(f, key, v)
            check(result(c) != before, f"row {key}")
        setv(f, key, old)
    if kind != "random_field":
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


EFFECTOR_TESTS = [(lambda k: lambda: test_effector(k))(k) for k in M.EFFECTOR_ORDER if k != "delay_effector"]
FIELD_TESTS = [(lambda k: lambda: test_field(k))(k) for k in M.FIELD_ORDER]
for t in (test_cloner_basics, test_rows, test_more_layouts, *EFFECTOR_TESTS, test_list_checkboxes, test_drop,
          *FIELD_TESTS, test_two_fields, test_two_cloners_one_effector, test_matrix, test_fracture, test_voronoi,
          test_tracer, test_delay, test_switch):
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
