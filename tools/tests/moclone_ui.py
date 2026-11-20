# One UI run of the MoClone module (window mode): screenshots of the viewport and the Attribute Manager with a Cloner
# in each mode, its Effectors page, each effector's page, and the layout after switching Blenda mode off and on.
#   B4D_OUT=<scratch> BLENDER_USER_CONFIG=<scratch>/config Blender --factory-startup --window-geometry 100 60 1700 1000 \
#       --python tools/tests/moclone_ui.py
# Writes B4D_OUT/moclone_ui.log with what it checked; pop-up menus never show in Blender's screenshots.
import math
import os
import sys
import traceback

import bpy
from mathutils import Euler

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
OUT = os.environ.get("B4D_OUT", "/tmp")
os.makedirs(OUT, exist_ok=True)
import blenda4d  # noqa: E402

blenda4d.register()
LOG = open(os.path.join(OUT, "moclone_ui.log"), "w")


def log(*a):
    print("B4D", *a, flush=True)
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def shot(name):
    w = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=w, screen=w.screen, area=w.screen.areas[0]):
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
        bpy.ops.screen.screenshot(filepath=os.path.join(OUT, name + ".png"))
    log("SHOT", name)


def only(objs):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0] if objs else None


def add(kind, objs):
    only(objs)
    bpy.ops.blenda4d.add_kind(kind=kind)
    return bpy.context.view_layer.objects.active


def material(name, rgba, clone_color=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = rgba
    m.diffuse_color = rgba
    if clone_color:                                  # the copies' tint, read the way a person would set it up
        attr = m.node_tree.nodes.new("ShaderNodeAttribute")
        attr.attribute_type = "GEOMETRY"
        attr.attribute_name = "Clone Color"
        mix = m.node_tree.nodes.new("ShaderNodeMix")
        mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        mix.inputs[6].default_value = rgba
        m.node_tree.links.new(attr.outputs["Color"], mix.inputs[7])
        m.node_tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return m


def scene():
    from blenda4d import moclone as M
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_plane_add(size=40)
    bpy.context.object.name = "Floor"
    # a grid of boxes, as in the approved look
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
    cube = bpy.context.object
    cube.name = "Cube"
    cube.data.materials.append(material("Orange", (0.9, 0.45, 0.15, 1)))
    grid = add("cloner", [cube])
    grid.name = "Cloner"
    M.put(grid, "Mode", "Grid")
    # a ring of spheres and cubes, tinted at random
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.35, location=(0, 0, 0.35))
    ball = bpy.context.object
    ball.name = "Ball"
    ball.data.materials.append(material("Tinted", (1, 1, 1, 1), clone_color=True))
    bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0, 0, 0.25))
    small = bpy.context.object
    small.name = "Block"
    small.data.materials.append(material("Tinted.1", (1, 1, 1, 1), clone_color=True))
    ring = add("cloner", [ball, small])
    ring.name = "Ring"
    ring.location = (-6, 0, 0)
    M.put(ring, "Mode", "Radial")
    M.put(ring, "Count", 12)
    M.put(ring, "Radius", 250.0)
    rnd = add("random_effector", [ring])
    rnd["b4d_eff_use_color"] = True
    rnd["b4d_eff_position"] = [20.0, 40.0, 20.0]
    # a row turned by a Step Effector
    bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=1.2, location=(0, 0, 0.6))
    cyl = bpy.context.object
    cyl.name = "Post"
    cyl.data.materials.append(material("Green", (0.2, 0.7, 0.3, 1)))
    row = add("cloner", [cyl])
    row.name = "Row"
    row.location = (0, -5, 0)
    M.put(row, "Count", 8)
    M.put(row, "Offset", (90.0, 0.0, 0.0))
    stp = add("step_effector", [row])
    stp["b4d_eff_rotation"] = [0.0, 0.0, 1.2]
    # copies along a spline, facing a target
    bpy.ops.curve.primitive_bezier_circle_add(radius=2.0, location=(7, 0, 0.3))
    path = bpy.context.object
    path.name = "Path"
    bpy.ops.mesh.primitive_cone_add(radius1=0.25, depth=0.8, location=(0, 0, 0))
    cone = bpy.context.object
    cone.name = "Cone"
    cone.data.materials.append(material("Blue", (0.25, 0.45, 0.9, 1)))
    along = add("cloner", [cone])
    along.name = "Along"
    M.put(along, "Mode", "Object")
    M.put(along, "Object", path)
    M.put(along, "Count", 16)
    tgt = add("target_effector", [along])
    tgt.location = (7, 0, 3)
    add("time_effector", [])
    blenda4d.moclone.sync_all()
    log("OBJECTS", [(o.name, o.get("b4d_type"), o.parent and o.parent.name) for o in bpy.context.scene.objects])
    log("CREATE moclone", [(m[0], m[2]) for m in blenda4d.bars.GROUPS["moclone"]])
    log("CREATE effectors", [(m[0], m[2]) for m in blenda4d.bars.GROUPS["effectors"]])
    log("MENU MoClone", [it[0] for it in blenda4d.menus.MAIN["MoClone"] if isinstance(it, tuple)],
        [e[0] for e in blenda4d.kinds.menu_items("MoClone")])


def select(name, tab="OBJECT"):
    only([bpy.data.objects[name]])
    bpy.context.window_manager.b4d_am_tab = tab


def frame():
    w = bpy.context.window_manager.windows[0]
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    reg = next(r for r in area.regions if r.type == "WINDOW")
    area.spaces[0].shading.type = "MATERIAL"
    r3d = area.spaces[0].region_3d                   # a view from the front and above, like the approved look
    r3d.view_perspective = "PERSP"
    r3d.view_rotation = Euler((math.radians(62), 0.0, math.radians(20))).to_quaternion()
    r3d.view_location = (0.5, 0.0, 0.5)
    r3d.view_distance = 20.0


def mode(name):
    from blenda4d import moclone as M
    M.put(bpy.data.objects["Cloner"], "Mode", name)


def switch(on):
    blenda4d.switch.set_mode(on)


def after_off():
    log("OFF kinds", [k for k in ("cloner", "random_effector") if k in blenda4d.kinds.KINDS],
        "prop", hasattr(bpy.types.Object, "b4d_effectors"),
        "copies", len(bpy.data.objects["Cloner"].evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices))


W = [lambda: None]
PLAN = W * 5 + [scene] + W * 2 + [frame] + W * 3
for name, tab, m in (("Cloner", "OBJECT", "Grid"), ("Cloner", "OBJECT", "Linear"), ("Cloner", "OBJECT", "Radial"),
                     ("Cloner", "OBJECT", "Object"), ("Cloner", "OBJECT", "Grid"), ("Ring", "EFFECTORS", None),
                     ("Random Effector", "OBJECT", None), ("Step Effector", "OBJECT", None),
                     ("Target Effector", "OBJECT", None), ("Time Effector", "OBJECT", None)):
    if m:
        PLAN += [lambda m=m: mode(m)]
    PLAN += [lambda n=name, t=tab: select(n, t)] + W * 2 + \
        [lambda n=name, t=tab, m=m: shot(f"am_{n.replace(' ', '_')}_{t}" + (f"_{m}" if m and n == 'Cloner' else ""))]
PLAN += [lambda: switch(False)] + W * 6 + [after_off, lambda: shot("off")]
PLAN += [lambda: switch(True)] + W * 8 + [lambda: select("Cloner"), *W * 2, lambda: shot("on_again")]
PLAN += [lambda: open(os.path.join(OUT, "done.txt"), "w").write("ok"), lambda: LOG.close(), lambda: bpy.ops.wm.quit_blender()]
_i = [0]


def tick():
    try:
        PLAN[_i[0]]()
    except Exception:
        log("ERROR", traceback.format_exc())
    _i[0] += 1
    return 0.6 if _i[0] < len(PLAN) else None


bpy.app.timers.register(tick, first_interval=1.5)
