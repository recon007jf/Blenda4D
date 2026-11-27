# Headless test of symmetry_draw: the mirrored selection picks each partner, Extrude moves every group straight out
# (also by a typed offset on a block with a point in the middle) and leaves no loose edges, Inset adds its ring,
# shrinks rounded groups without folding, flares out when negative, keeps shape keys, and Escape gives back the mesh
# exactly with its UV map and vertex group weights.
#   Blender -b --factory-startup --python tools/tests/symmetry_engine.py
import os
import sys
import traceback

import bpy
import bmesh  # after bpy: outside Blender's own Python, bpy is what makes bmesh importable
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from blenda4d import symmetry_draw as S  # noqa: E402

for cls in (S.BLENDA4D_OT_symmetry_extrude, S.BLENDA4D_OT_symmetry_inset):
    bpy.utils.register_class(cls)
fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)
        print("FAIL", msg, flush=True)
    else:
        print("ok  ", msg, flush=True)


def clear():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)


def edit(ob):
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    return bmesh.from_edit_mesh(ob.data)


def pick(ob, test):
    bm = bmesh.from_edit_mesh(ob.data)
    for f in bm.faces:
        f.select_set(False)
    for f in bm.faces:
        if test(f.calc_center_median(), f.normal):
            f.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data)


def grid(name="Grid", cuts=4):
    """A flat, subdivided plane facing +Z: a 2 x 2 block in its middle has a point in the middle."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=cuts, y_subdivisions=cuts, size=2)
    ob = bpy.context.object
    ob.name = name
    return ob


def rounded(name="Rounded"):
    """A long box with a rounded end, like an arm."""
    bpy.ops.mesh.primitive_cube_add(size=2)
    ob = bpy.context.object
    ob.name = name
    m = ob.modifiers.new("s", "SUBSURF")
    m.levels = 2
    bpy.ops.object.modifier_apply(modifier=m.name)
    ob.scale = (2.5, 1.0, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    return ob


def folded(bm):
    return sum(1 for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < -0.2)


def snapshot(ob):
    bm = bmesh.from_edit_mesh(ob.data)
    return sorted(tuple(round(c, 5) for c in v.co) for v in bm.verts), len(bm.faces)


def mirrored_selection():
    clear()
    ob = grid()
    ob.data.use_mirror_x = True
    edit(ob)
    pick(ob, lambda c, n: abs(c.x - 0.75) < 0.01 and abs(c.y - 0.25) < 0.01)
    side = S.mirror_selection(ob, (False, False, True))
    bm = bmesh.from_edit_mesh(ob.data)
    picked = sorted((round(f.calc_center_median().x, 3), round(f.calc_center_median().y, 3)) for f in bm.faces if f.select)
    check(picked == [(-0.75, 0.25), (0.75, 0.25)], f"the partner on the other side is picked too ({picked})")
    check(side is not None and side[0] > 0, "the side of the fresh pick is reported")


def extrude_drag():
    clear()
    ob = rounded()
    ob.data.use_mirror_x = True
    edit(ob)
    pick(ob, lambda c, n: c.x > 1.6)
    S.mirror_selection(ob, (False, False, True))
    got = S.extrude_regions(ob)
    check(got is not None, "extrude starts on two mirrored groups")
    check(S.place(ob, got[0], 0.5), "the extrusion moves")
    S.BLENDA4D_OT_symmetry_extrude._finish(ob, got)
    bm = bmesh.from_edit_mesh(ob.data)
    xs = [v.co.x for v in bm.verts]
    check(abs(max(xs) + min(xs)) < 1e-4 and max(xs) > 2.5, f"both ends grew out as mirror images ({min(xs):.3f}, {max(xs):.3f})")
    loose = sum(1 for e in bm.edges if not e.link_faces) + sum(1 for v in bm.verts if not v.link_edges)
    check(loose == 0, f"no loose edges or points left inside ({loose})")
    check(folded(bm) == 0, "no folded polygons")


def extrude_typed():
    clear()
    ob = grid()
    edit(ob)
    pick(ob, lambda c, n: abs(c.x) < 0.5 and abs(c.y) < 0.5)          # the 2 x 2 block round the middle point
    r = bpy.ops.blenda4d.symmetry_extrude("EXEC_DEFAULT", offset=0.3)
    bm = bmesh.from_edit_mesh(ob.data)
    up = [v for v in bm.verts if abs(v.co.z - 0.3) < 1e-5]
    check(r == {"FINISHED"} and len(up) == 9, f"a typed offset lifts the whole block by it ({r}, {len(up)} of 9 points up)")
    check(not any(v.co.length < 1e-5 for v in bm.verts), "the old middle point went with the old polygons")
    loose = sum(1 for e in bm.edges if not e.link_faces) + sum(1 for v in bm.verts if not v.link_edges)
    check(loose == 0, f"no loose edges or points left ({loose})")
    check(sum(1 for f in bm.faces if f.select) == 4, "the four new top polygons are picked")


def inset_basic():
    clear()
    ob = grid()
    edit(ob)
    pick(ob, lambda c, n: abs(c.x) < 0.5 and abs(c.y) < 0.5)
    faces0 = len(bmesh.from_edit_mesh(ob.data).faces)
    bpy.ops.blenda4d.symmetry_inset("EXEC_DEFAULT", thickness=0.2)
    bm = bmesh.from_edit_mesh(ob.data)
    sel = [f for f in bm.faces if f.select]
    reach = max(max(abs(v.co.x), abs(v.co.y)) for f in sel for v in f.verts)
    check(len(bm.faces) == faces0 + 8, f"the ring adds a polygon per outline edge ({len(bm.faces) - faces0})")
    check(len(sel) == 4 and abs(reach - 0.3) < 1e-4, f"only the inset polygons stay picked, 0.2 in ({len(sel)}, {reach:.4f})")
    flat = sum(1 for f in bm.faces if f.normal.length < 0.5)
    check(flat == 0, f"every polygon, the new ring too, has a normal to shade by in Edit mode ({flat} without)")
    bpy.ops.object.mode_set(mode="OBJECT")
    edit(ob)
    pick(ob, lambda c, n: abs(c.x) < 0.5 and abs(c.y) < 0.5)
    bpy.ops.blenda4d.symmetry_inset("EXEC_DEFAULT", thickness=-0.2)
    bm = bmesh.from_edit_mesh(ob.data)
    sel = [f for f in bm.faces if f.select]
    reach = max(max(abs(v.co.x), abs(v.co.y)) for f in sel for v in f.verts)
    flat = max(abs(v.co.z) for f in sel for v in f.verts)
    check(reach > 0.69 and flat < 1e-6, f"a negative offset flares the group out in its own plane ({reach:.4f})")


def inset_rounded():
    for t in (0.05, 0.1, 0.15):                           # short of the middle of the rounded tip
        clear()
        ob = rounded()
        edit(ob)
        pick(ob, lambda c, n: c.x > 1.6)
        bpy.ops.blenda4d.symmetry_inset("EXEC_DEFAULT", thickness=t)
        bm = bmesh.from_edit_mesh(ob.data)
        bm.normal_update()
        check(folded(bm) == 0, f"inset {t:+.2f} on a rounded end folds nothing ({folded(bm)})")


def inset_keeps_data():
    clear()
    ob = grid()
    ob.shape_key_add(name="Basis")
    key = ob.shape_key_add(name="Lift")
    lifted = [i for i, v in enumerate(ob.data.vertices) if abs(v.co.x) < 0.6 and abs(v.co.y) < 0.6]
    for i in lifted:
        key.data[i].co.z += 0.25
    vg = ob.vertex_groups.new(name="Weights")
    for v in ob.data.vertices:
        vg.add([v.index], round(0.1 + abs(v.co.x) * 0.4, 3), "REPLACE")
    weights0 = sorted((tuple(round(c, 5) for c in v.co), round(vg.weight(v.index), 4)) for v in ob.data.vertices)
    uv0 = sorted(tuple(round(c, 5) for c in d.uv) for d in ob.data.uv_layers.active.data)
    edit(ob)
    pick(ob, lambda c, n: abs(c.x) < 0.5 and abs(c.y) < 0.5)
    before = snapshot(ob)
    got = S.inset_start(ob)
    S.inset_to(ob, got[0], 0.2)
    S.inset_undo(ob, *got)
    check(snapshot(ob) == before, "Escape puts every point and polygon back")
    bpy.ops.object.mode_set(mode="OBJECT")
    weights = sorted((tuple(round(c, 5) for c in v.co), round(vg.weight(v.index), 4)) for v in ob.data.vertices)
    uv = sorted(tuple(round(c, 5) for c in d.uv) for d in ob.data.uv_layers.active.data)
    check(weights == weights0, "vertex group weights survive Escape")
    check(uv == uv0, "the UV map survives Escape")
    up = sum(1 for a, b in zip(ob.data.shape_keys.key_blocks["Lift"].data, ob.data.vertices) if a.co.z - b.co.z > 0.2)
    check(up == len(lifted), f"the second shape key survives Escape ({up} of {len(lifted)} lifted)")
    edit(ob)
    pick(ob, lambda c, n: abs(c.x) < 0.5 and abs(c.y) < 0.5)
    bpy.ops.blenda4d.symmetry_inset("EXEC_DEFAULT", thickness=0.2)
    bpy.ops.object.mode_set(mode="OBJECT")
    up = sum(1 for a, b in zip(ob.data.shape_keys.key_blocks["Lift"].data, ob.data.vertices) if a.co.z - b.co.z > 0.2)
    check(up >= len(lifted), f"the second shape key keeps its lifted points after an inset ({up} of {len(lifted)} or more)")
    check(len(ob.data.uv_layers) == 1 and len(ob.vertex_groups) == 1, "the UV map and vertex group are still there")


for test in (mirrored_selection, extrude_drag, extrude_typed, inset_basic, inset_rounded, inset_keeps_data):
    try:
        test()
    except Exception:
        traceback.print_exc()
        fails.append(test.__name__ + " raised")
print("\n" + (f"{len(fails)} FAILED: " + "; ".join(fails) if fails else "ALL PASSED"), flush=True)
sys.exit(1 if fails else 0)
