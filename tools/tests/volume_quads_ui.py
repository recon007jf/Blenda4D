# One UI run of the volume module (window mode): a Volume Mesher over a Volume Builder made of a box, a ball cut out
# of it, a spline tube and a nested Volume Builder; screenshots of the viewport and the Attribute Manager for both
# objects, with a row chosen and its mode changed; a second Volume Builder left on its own to show how a bare volume
# looks; then Blenda mode switched off and on.
#   B4D_OUT=<scratch> BLENDER_USER_CONFIG=<scratch>/config Blender --factory-startup --enable-event-simulate \
#       --window-geometry 100 60 1700 1000 --python tools/tests/volume_ui.py
# Writes B4D_OUT/volume_ui.log (every step, and a crash trace in fault.log).
import faulthandler
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
FAULT = open(os.path.join(OUT, "fault.log"), "w")
faulthandler.enable(FAULT)
import blenda4d  # noqa: E402

blenda4d.register()
LOG = open(os.path.join(OUT, "volume_ui.log"), "w")


def log(*a):
    print("B4D", *a, flush=True)
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def window():
    return bpy.context.window_manager.windows[0]


def shot(name):
    w = window()
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


def material(name, rgba):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = rgba
    m.diffuse_color = rgba
    return m



def scene():
    from blenda4d import primitives as P
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    c = bpy.context.object
    b = P.add_primitive(bpy.context, "platonic")
    b.location = (0.9, -0.9, -0.5)
    b.name = "Bump"
    vb = add("volume_builder", [c, b])
    vm = add("volume_mesher", [vb])
    vm.name = "Volume Mesher"
    V = blenda4d.volume
    V.put(vb, "Voxel Size", 0.7)
    V.put(vm, "Threshold", 2.0)
    vm.b4d_vq_faces = 5000
    vm.b4d_vq_sym_x = vm.b4d_vq_sym_y = True
    V.sync_all()


def state(tag):
    vm = bpy.data.objects["Volume Mesher"]
    ev = vm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mod = blenda4d.volume.mod_of(vm)
    log("STATE", tag, "flag", vm.b4d_vq_on, "base", len(vm.data.polygons), "eval", len(ev.data.polygons),
        "tree", mod.node_group.name if mod and mod.node_group else None, "nodes", len(mod.node_group.nodes) if mod and mod.node_group else 0,
        "msg", vm.get("b4d_vq_msg"), "mesh", vm.data.name)


def press(op, **kw):
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    vm = bpy.data.objects["Volume Mesher"]
    only([vm])
    with bpy.context.temp_override(window=w, area=area, region=area.regions[-1]):
        r = getattr(bpy.ops.blenda4d, op)("INVOKE_DEFAULT", owner=vm.name, **kw)
    log("PRESS", op, r)


def undo_push():
    bpy.ops.ed.undo_push(message="test step")


def move_bump():
    bpy.data.objects["Bump"].location.x += 0.3


W = [lambda: None]
PLAN = W * 4 + [scene] + W * 3 + [lambda: state("live")]
PLAN += [lambda: press("volume_quad_remesh")] + W * 6 + [lambda: state("after first")]
PLAN += [lambda: press("volume_quad_remesh")] + W * 6 + [lambda: state("after second")]
PLAN += [move_bump] + W * 3 + [lambda: press("volume_quad_remesh")] + W * 6 + [lambda: state("after update")]
PLAN += [lambda: press("volume_quad_live")] + W * 4 + [lambda: state("after live")]
PLAN += [lambda: press("volume_quad_remesh")] + W * 6 + [lambda: state("after remesh again")]
PLAN += [lambda: setattr(bpy.data.objects["Volume Mesher"], "b4d_vq_sym_x", False), lambda: press("volume_quad_remesh")] + W * 6 + [lambda: state("after sym y only")]
PLAN += [lambda: only([bpy.data.objects["Volume Mesher"]])] + W * 3 + [lambda: shot("quads_end")]
PLAN += [lambda: open(os.path.join(OUT, "done.txt"), "w").write("ok"), lambda: LOG.close(), lambda: bpy.ops.wm.quit_blender()]
_i = [0]


def tick():
    fn = PLAN[_i[0]]
    log("STEP", _i[0], getattr(fn, "__name__", ""), getattr(bpy.context.view_layer.objects.active, "name", ""))
    try:
        fn()
    except Exception:
        log("ERROR", traceback.format_exc())
    _i[0] += 1
    return 0.6 if _i[0] < len(PLAN) else None


bpy.app.timers.register(tick, first_interval=1.5)
