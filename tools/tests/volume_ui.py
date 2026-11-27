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
    from blenda4d import volume as V
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, -1.2))
    bpy.context.object.name = "Floor"
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
    box = bpy.context.object
    box.name = "Box"
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.9, location=(0.9, -0.9, 0.9))
    hole = bpy.context.object
    hole.name = "Hole"
    cu = bpy.data.curves.new("Handle", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(1)
    for bp, co in zip(sp.bezier_points, ((-1.0, 0.0, 1.0), (-1.0, 0.0, -1.0))):
        bp.co = co
        bp.handle_left = (co[0] - 1.2, 0.0, co[2])
        bp.handle_right = (co[0] - 1.2, 0.0, co[2])
    handle = bpy.data.objects.new("Handle", cu)
    bpy.context.collection.objects.link(handle)
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.5, location=(0.0, 1.4, 0.0))
    knob = bpy.context.object
    knob.name = "Knob"
    inner = add("volume_builder", [knob])
    inner.name = "Knob Volume"
    vb = add("volume_builder", [box, hole, handle, inner])
    vb.name = "Volume Builder"
    for r in vb.b4d_vol_items:
        if r.obj == hole:
            r.mode = "SUBTRACT"
            r.smooth = 2
        if r.obj == handle:
            r.radius = 18.0
    # the box first, then the hole, the handle and the knob
    order = [box, hole, handle, inner]
    for want, ob in enumerate(order):
        i = next(k for k, r in enumerate(vb.b4d_vol_items) if r.obj == ob)
        if i != want:
            vb.b4d_vol_items.move(i, want)
    V.rebuild(vb)
    V.put(vb, "Rounding", 3)
    vm = add("volume_mesher", [vb])
    vm.name = "Volume Mesher"
    vm.data.materials.append(material("Clay", (0.85, 0.45, 0.3, 1)))
    V.put(vm, "Smoothing", 2)
    bpy.ops.mesh.primitive_torus_add(location=(4.5, 0, 0))
    ring = bpy.context.object
    ring.name = "Ring"
    alone = add("volume_builder", [ring])
    alone.name = "Bare Volume"
    alone.b4d_vol_fog = True                          # rendered as fog, so Material Preview shows it
    alone["b4d_fog_color"] = (0.4, 0.7, 1.0)
    cu = bpy.data.curves.new("Word", "FONT")
    cu.body = "VOL"
    word = bpy.data.objects.new("Word", cu)
    word.location = (-1.5, -4.0, -0.5)
    word.rotation_euler = (math.radians(90), 0, 0)
    bpy.context.collection.objects.link(word)
    letters = add("volume_builder", [word])
    letters.name = "Letters"
    lm = add("volume_mesher", [letters])
    lm.name = "Letters Mesher"
    lm.data.materials.append(material("Mint", (0.3, 0.8, 0.6, 1)))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0.0, -1.5, -0.6))
    bpy.context.object.name = "Pebble"
    from blenda4d import primitives as P
    gem = P.add_primitive(bpy.context, "platonic")    # its faces come from its modifier: Auto must still fill it
    gem.location = (4.5, 3.5, 0.0)
    gv = add("volume_builder", [gem])
    gv.name = "Gem Volume"
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(-5.0, 3.0, 0.0))
    slab = bpy.context.object
    slab.name = "Slab"
    lv = add("volume_builder", [slab])
    lv.name = "Layered Volume"
    lv.b4d_vol_index = 0
    bpy.ops.blenda4d.volume_add_layer(owner=lv.name, effect="GROW")
    lv.b4d_vol_items[1].grow = 40.0
    bpy.ops.blenda4d.volume_add_layer(owner=lv.name, effect="SMOOTH")
    lv.b4d_vol_items[2].smooth = 4
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.ops.blenda4d.add_kind(kind="fd_sphere")
    fld = bpy.context.view_layer.objects.active
    fld.name = "Grow Zone"
    fld.location = (-4.0, 3.0, 1.0)
    fld.b4d_fd_radius = 90.0
    lv.b4d_vol_items[1].fields.add().obj = fld
    V.rebuild(lv)
    blenda4d.volume.sync_all()
    log("SCENE", [o.name for o in bpy.data.objects])


def frame():
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    area.spaces[0].shading.type = "MATERIAL"
    r3d = area.spaces[0].region_3d
    r3d.view_perspective = "PERSP"
    r3d.view_rotation = Euler((math.radians(62), 0.0, math.radians(28))).to_quaternion()
    r3d.view_location = (1.8, 0.0, 0.0)
    r3d.view_distance = 14.0


def select(name, row=None):
    ob = bpy.data.objects[name]
    only([ob])
    bpy.context.window_manager.b4d_am_tab = "OBJECT"
    if row is not None:
        ob.b4d_vol_index = row


def om_region():
    from blenda4d import roles
    a = roles.areas(window().screen, "OBJECTS")[0]
    return a, next(r for r in a.regions if r.type == "WINDOW")


def row_y(name):
    from blenda4d import managers
    _a, r = om_region()
    rows = [o.name for o, _d in managers.visible_rows(bpy.context)]
    h = managers.row_height()
    vy = -(managers.rows_top() + rows.index(name) + 0.5) * h
    return r.y + int(r.view2d.view_to_region(0, vy, clip=False)[1])


def ev(t, v, x, y):
    window().event_simulate(t, v, x=x, y=y)


_drag = {}


def drag_steps(src, owner):
    """Press on src's row in the Object Manager, move to the middle of the Attribute Manager (showing owner), let go."""
    from blenda4d import roles

    def show_row():
        only([bpy.data.objects[src]])
        a, r = om_region()
        with bpy.context.temp_override(window=window(), area=a, region=r):
            bpy.ops.blenda4d.om_scroll_active()

    def press():
        only([bpy.data.objects[owner]])
        bpy.context.window_manager.b4d_am_tab = "OBJECT"
        _a, r = om_region()
        am = roles.areas(window().screen, "ATTRIBUTES")[0]
        _drag.update(x0=r.x + 90, y0=row_y(src), x1=am.x + am.width // 2, y1=am.y + am.height // 2)
        ev("MOUSEMOVE", "NOTHING", _drag["x0"], _drag["y0"])
        ev("LEFTMOUSE", "PRESS", _drag["x0"], _drag["y0"])
    steps = [show_row, lambda: None, lambda: None, press]
    for k in range(1, 9):
        steps.append(lambda k=k: ev("MOUSEMOVE", "NOTHING", _drag["x0"] + (_drag["x1"] - _drag["x0"]) * k // 8,
                                    _drag["y0"] + (_drag["y1"] - _drag["y0"]) * k // 8))
    steps += [lambda: ev("LEFTMOUSE", "RELEASE", _drag["x1"], _drag["y1"]), lambda: None,
              lambda: log("DROP", src, "->", owner, "parent", getattr(bpy.data.objects[src].parent, "name", None),
                          "rows", [r.obj.name for r in bpy.data.objects[owner].b4d_vol_items if r.obj])]
    return steps


def set_filter(name, row, f):
    bpy.data.objects[name].b4d_vol_items[row].filter = f
    bpy.data.objects[name].b4d_vol_items[row].smooth = 4


def set_mode(name, row, mode):
    bpy.data.objects[name].b4d_vol_items[row].mode = mode


def after_off():
    log("OFF", "kinds", [k for k in ("volume_builder", "volume_mesher") if k in blenda4d.kinds.KINDS],
        "prop", hasattr(bpy.types.Object, "b4d_vol_items"),
        "faces", len(bpy.data.objects["Volume Mesher"].evaluated_get(bpy.context.evaluated_depsgraph_get()).data.polygons))


W = [lambda: None]
PLAN = W * 5 + [scene] + W * 2 + [frame] + W * 3
def shading(kind):
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    area.spaces[0].shading.type = kind
    ob = bpy.data.objects["Volume Mesher"]
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    log("SHADING", kind, "mesher faces", len(ev.data.polygons), "display", ob.display_type,
        "visible", ob.visible_get(), "mats", [m.name for m in ob.data.materials])


def hide_volumes(on):
    for n in ("Volume Builder", "Knob Volume", "Bare Volume"):
        bpy.data.objects[n].hide_viewport = on
    log("VOLUMES HIDDEN", on)


PLAN += [lambda: select("Volume Mesher")] + W * 3 + [lambda: shot("mesher_page")]
PLAN += [lambda: shading("SOLID")] + W * 3 + [lambda: shot("mesher_solid")] + [lambda: shading("MATERIAL")] + W * 4
PLAN += [lambda: shot("mesher_material_later")]
PLAN += [lambda: hide_volumes(True)] + W * 4 + [lambda: shot("mesher_material_no_volumes"), lambda: hide_volumes(False)]
PLAN += [lambda: select("Volume Builder", 1)] + W * 3 + [lambda: shot("builder_page_hole_row")]
PLAN += [lambda: select("Volume Builder", 2)] + W * 2 + [lambda: shot("builder_page_spline_row")]
PLAN += [lambda: set_mode("Volume Builder", 1, "INTERSECT")] + W * 3 + [lambda: shot("builder_hole_intersect")]
PLAN += [lambda: set_mode("Volume Builder", 1, "SUBTRACT")] + W * 2
PLAN += [lambda: set_filter("Volume Builder", 0, "CURVATURE")] + W * 3 + [lambda: select("Volume Builder", 0)] + W * 2
PLAN += [lambda: shot("builder_box_row_round_filter")]
def gem(attr, v):
    ob = bpy.data.objects["Gem Volume"]
    if attr == "view":
        ob.b4d_vol_view = v
    else:
        setattr(ob.b4d_vol_items[0], attr, v)
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    log("GEM", attr, v, "faces", len(ev.data.polygons) if ev.data else -1)


PLAN += [lambda: select("Gem Volume", 0)] + W * 3 + [lambda: shot("gem_surface_material")]
PLAN += [lambda: shading("SOLID")] + W * 3 + [lambda: shot("gem_surface_solid")]
PLAN += [lambda: gem("view", "VOXELS")] + W * 3 + [lambda: shot("gem_voxels")]
PLAN += [lambda: gem("view", "FOG")] + W * 3 + [lambda: shot("gem_fog_view")]
PLAN += [lambda: gem("view", "SURFACE"), lambda: gem("source", "POINTS")] + W * 3 + [lambda: shot("gem_from_points")]
PLAN += [lambda: gem("source", "EDGES")] + W * 3 + [lambda: shot("gem_from_edges")]
PLAN += [lambda: gem("source", "SURFACE")] + W * 3 + [lambda: shot("gem_from_surface")]
PLAN += [lambda: gem("source", "AUTO"), lambda: shading("MATERIAL")] + W * 3
def layered(what):
    ob = bpy.data.objects["Layered Volume"]
    if what == "fine":
        V_ = blenda4d.volume
        V_.put(ob, "Voxel Size", 2.0)
    elif what == "move":
        bpy.data.objects["Grow Zone"].location = (-6.0, 3.0, -1.0)
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    log("LAYERED", what, "faces", len(ev.data.polygons) if ev.data else -1, "rows", [r.layer or r.obj.name for r in ob.b4d_vol_items])


def look_at(loc, dist):
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    area.spaces[0].region_3d.view_location = loc
    area.spaces[0].region_3d.view_distance = dist


PLAN += [lambda: shading("SOLID"), lambda: look_at((-5.0, 3.0, 0.0), 8.0), lambda: select("Layered Volume", 1)] + W * 4 + [lambda: layered("start"), lambda: shot("layer_grow_with_field")]
PLAN += [lambda: select("Layered Volume", 2)] + W * 3 + [lambda: shot("layer_smooth_page")]
PLAN += [lambda: layered("move")] + W * 4 + [lambda: layered("moved"), lambda: shot("layer_field_moved")]
PLAN += [lambda: layered("fine")] + W * 6 + [lambda: layered("fine done"), lambda: shot("layer_voxel_2cm")]
PLAN += [lambda: shading("MATERIAL"), lambda: frame()] + W * 2
def reference():
    """One of the author's own pages (Extrude), for comparing the volume pages with the approved look."""
    bpy.ops.curve.primitive_bezier_circle_add(radius=0.5, location=(-8.0, 0.0, 0.0))
    ex = add("extrude", [bpy.context.object])
    ex.name = "Reference Extrude"


PLAN += [reference, lambda: select("Reference Extrude")] + W * 3 + [lambda: shot("reference_extrude_page")]
PLAN += [lambda: select("Bare Volume")] + W * 3 + [lambda: shot("bare_volume_fog")]
PLAN += [lambda: select("Letters", 0)] + W * 3 + [lambda: shot("letters_builder")]
PLAN += drag_steps("Pebble", "Volume Builder") + W * 3 + [lambda: shot("drop_pebble_into_builder")]
def extra(what):
    V_ = blenda4d.volume
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    if what == "blend":
        vb = bpy.data.objects["Volume Builder"]
        for r in vb.b4d_vol_items:
            if r.obj is not None and r.obj.name == "Handle":
                r.blend = 25.0
                vb.b4d_vol_index = list(vb.b4d_vol_items).index(r)
        vb.update_tag()
    elif what == "noise":
        bv = bpy.data.objects["Bare Volume"]
        bv["b4d_fog_noise"] = 0.85
        bv["b4d_fog_noise_scale"] = 35.0
        bv.update_tag()
    elif what == "quads":
        vm = bpy.data.objects["Volume Mesher"]
        vm.b4d_vq_faces = 2500
        vm.b4d_vq_sym_x = True
        with bpy.context.temp_override(window=w, area=area):
            r = bpy.ops.blenda4d.volume_quad_remesh(owner=vm.name)
        area.spaces[0].overlay.show_wireframes = True
        log("QUADS", r, len(vm.data.polygons), {len(p.vertices) for p in vm.data.polygons})
    elif what == "live":
        vm = bpy.data.objects["Volume Mesher"]
        bpy.ops.blenda4d.volume_quad_live(owner=vm.name)
        area.spaces[0].overlay.show_wireframes = False
        log("LIVE", len(vm.data.polygons))


PLAN += [lambda: shading("MATERIAL"), frame, lambda: extra("blend"), lambda: select("Volume Builder")] + W * 5 + [lambda: shot("soft_blend_handle")]
PLAN += [lambda: extra("noise"), lambda: select("Bare Volume")] + W * 5 + [lambda: shot("fog_noise")]
PLAN += [lambda: select("Volume Mesher"), lambda: extra("quads")] + W * 5 + [lambda: shot("mesher_quads_symmetry_x")]
PLAN += [lambda: extra("live")] + W * 3
PLAN += [lambda: select("Knob Volume")] + W * 2 + [lambda: shot("nested_builder")]
PLAN += [lambda: blenda4d.switch.set_mode(False)] + W * 6 + [after_off, lambda: shot("off")]
PLAN += [lambda: blenda4d.switch.set_mode(True)] + W * 8 + [lambda: select("Volume Mesher"), *W * 2, lambda: shot("on_again")]
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
