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
    V = blenda4d.volume
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 60
    sc.frame_set(1)
    # smoke: a domain over a ball letting smoke in
    bpy.ops.mesh.primitive_cube_add(size=4, location=(0, 0, 2))
    dom = bpy.context.object
    dom.name = "Smoke Domain"
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0, 0, 0.6))
    flow = bpy.context.object
    flow.name = "Smoke Source"
    fm = dom.modifiers.new("Fluid", "FLUID")
    fm.fluid_type = "DOMAIN"
    ds = fm.domain_settings
    ds.domain_type, ds.resolution_max = "GAS", 48
    ds.cache_directory = os.path.join(OUT, "smoke_cache")
    ds.cache_type = "REPLAY"
    ds.cache_frame_start, ds.cache_frame_end = 1, 60
    ff = flow.modifiers.new("Fluid", "FLUID")
    ff.fluid_type = "FLOW"
    ff.flow_settings.flow_type, ff.flow_settings.flow_behavior = "SMOKE", "INFLOW"
    flow.display_type = "WIRE"
    sb = add("volume_builder", [dom])
    sb.name = "Smoke Volume"
    sb.b4d_vol_items[0].smooth = 2
    sm = add("volume_mesher", [sb])
    sm.name = "Smoke Mesher"
    sm.data.materials.append(bpy.data.materials.new("Smoke Clay"))
    sm.data.materials[0].diffuse_color = (0.9, 0.6, 0.4, 1)
    # particles
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(4.0, 0, 0))
    em = bpy.context.object
    em.name = "Emitter"
    em.modifiers.new("Particles", "PARTICLE_SYSTEM")
    st = em.particle_systems[0].settings
    st.count, st.frame_start, st.frame_end, st.lifetime = 200, 1, 40, 200
    st.normal_factor, st.effector_weights.gravity = 2.0, 0.0
    pb = add("volume_builder", [em])
    pb.name = "Particle Volume"
    pb.b4d_vol_items[0].radius = 12.0
    # metaball and a NURBS surface melted together
    bpy.ops.object.metaball_add(type="BALL", location=(-4.0, 0, 0.5))
    mb = bpy.context.object
    bpy.ops.surface.primitive_nurbs_surface_torus_add(location=(-4.0, 0, 0.5))
    nt = bpy.context.object
    ob = add("volume_builder", [mb, nt])
    ob.name = "Meta Volume"
    ob.b4d_vol_items[1].blend = 20.0
    V.sync_all()
    log("SCENE", [o.name for o in bpy.data.objects])


def frame():
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    area.spaces[0].shading.type = "SOLID"
    r3d = area.spaces[0].region_3d
    r3d.view_perspective = "PERSP"
    r3d.view_rotation = Euler((math.radians(70), 0.0, math.radians(15))).to_quaternion()
    r3d.view_location = (0.0, 0.0, 1.5)
    r3d.view_distance = 16.0


def step(n):
    sc = bpy.context.scene
    sc.frame_set(n)


def state(tag):
    for name in ("Smoke Domain", "Emitter"):
        src = bpy.data.objects[name]
        feed = bpy.data.objects.get(f"Blenda Volume Feed [{name}]")
        log("FEED", tag, name, len(feed.data.vertices) if feed else None)
    for name in ("Smoke Volume", "Smoke Mesher", "Particle Volume", "Meta Volume"):
        o = bpy.data.objects[name]
        ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        vs = [ev.matrix_world @ v.co for v in me.vertices]
        b = ([round(min(v[k] for v in vs), 2) for k in range(3)], [round(max(v[k] for v in vs), 2) for k in range(3)]) if vs else None
        log("BOUNDS", tag, name, len(me.polygons), b)
        ev.to_mesh_clear()


from mathutils import Euler  # noqa: E402
W = [lambda: None]
PLAN = W * 4 + [scene] + W * 3 + [frame]
for n in range(1, 41):
    PLAN.append((lambda n: lambda: step(n))(n))
    if n in (10, 25, 40):
        PLAN += W * 2 + [(lambda n: lambda: state(f"frame {n}"))(n), (lambda n: lambda: shot(f"sources_frame_{n}"))(n)]
PLAN += [lambda: only([bpy.data.objects["Smoke Volume"]]), lambda: setattr(bpy.context.window_manager, "b4d_am_tab", "OBJECT"),
         lambda: setattr(bpy.data.objects["Smoke Volume"], "b4d_vol_index", 0)] + W * 3 + [lambda: shot("smoke_row_page")]
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
