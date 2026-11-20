# One UI run of the MoClone module (window mode): screenshots of the viewport and the Attribute Manager for every
# MoClone object, effector and Field, the Effectors and Fields lists (with a row left out), an effector dragged from
# the Object Manager into a Cloner's Effectors page, the Object Manager's selection at three interface sizes, and the
# layout after switching Blenda mode off and on.
#   B4D_OUT=<scratch> BLENDER_USER_CONFIG=<scratch>/config Blender --factory-startup --enable-event-simulate \
#       --window-geometry 100 60 1700 1000 --python tools/tests/moclone_ui.py
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


def mesh(kind, name, mat, **kw):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(**kw)
    ob = bpy.context.object
    ob.name = name
    ob.data.materials.append(mat)
    return ob


def scene():
    from blenda4d import moclone as M
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_plane_add(size=60)
    bpy.context.object.name = "Floor"
    # a grid of boxes, as in the approved look, lifted and tinted where a Spherical Field lets a Plain Effector act
    cube = mesh("cube", "Cube", material("Orange", (0.9, 0.45, 0.15, 1), clone_color=True), size=1.0, location=(0, 0, 0.5))
    grid = add("cloner", [cube])
    grid.name = "Cloner"
    M.put(grid, "Mode", "Grid")
    plain = add("plain_effector", [grid])
    plain["b4d_eff_position"] = [0.0, 120.0, 0.0]
    plain["b4d_eff_use_color"] = True
    ball_field = add("spherical_field", [plain])
    ball_field.location = (-2.5, 0.0, 0.0)
    ball_field["b4d_fld_radius"] = 260.0
    ball_field["b4d_fld_falloff"] = 60.0
    # a ring of balls and blocks, tinted at random
    ball = mesh("uv_sphere", "Ball", material("Tinted", (1, 1, 1, 1), clone_color=True), radius=0.35, location=(0, 0, 0.35))
    block = mesh("cube", "Block", material("Tinted.1", (1, 1, 1, 1), clone_color=True), size=0.5, location=(0, 0, 0.25))
    ring = add("cloner", [ball, block])
    ring.name = "Ring"
    ring.location = (-7, 0, 0)
    M.put(ring, "Mode", "Radial")
    M.put(ring, "Count", 12)
    M.put(ring, "Radius", 250.0)
    rnd = add("random_effector", [ring])
    rnd["b4d_eff_use_color"] = True
    rnd["b4d_eff_position"] = [20.0, 40.0, 20.0]
    # a honeycomb of posts grown by a Step Effector
    post = mesh("cylinder", "Post", material("Green", (0.2, 0.7, 0.3, 1)), radius=0.2, depth=1.2, location=(0, 0, 0.6))
    comb = add("cloner", [post])
    comb.name = "Comb"
    comb.location = (0, -6, 0)
    M.put(comb, "Mode", "Honeycomb")
    M.put(comb, "Count X", 7)
    M.put(comb, "Spacing", (90.0, 100.0, 80.0))
    stp = add("step_effector", [comb])
    stp["b4d_eff_scale"] = [0.0, 100.0, 0.0]
    # cones along a spline, facing a target; a Tracer follows the target
    bpy.ops.curve.primitive_bezier_circle_add(radius=2.0, location=(7, 0, 0.3))
    path = bpy.context.object
    path.name = "Path"
    cone = mesh("cone", "Cone", material("Blue", (0.25, 0.45, 0.9, 1)), radius1=0.25, depth=0.8)
    along = add("cloner", [cone])
    along.name = "Along"
    M.put(along, "Mode", "Object")
    M.put(along, "Object", path)
    M.put(along, "Count", 16)
    tgt = add("target_effector", [along])
    tgt.location = (7, 0, 3)
    add("time_effector", [])
    add("delay_effector", [])
    # a Matrix, a Fracture and a Voronoi Fracture
    m = add("matrix", [])
    m.location = (0, 7, 0)
    M.put(m, "Mode", "Linear")
    M.put(m, "Count", 6)
    a = mesh("cube", "Piece A", material("Grey", (0.6, 0.6, 0.6, 1)), size=0.8, location=(-4, 7, 0.4))
    b = mesh("cube", "Piece B", material("Grey.1", (0.6, 0.6, 0.6, 1)), size=0.8, location=(-3, 7, 0.4))
    fr = add("fracture", [a, b])
    fr.name = "Fracture"
    stone = mesh("cube", "Block Of Stone", material("Stone", (0.75, 0.7, 0.6, 1)), size=2.0, location=(5, 7, 1.0))
    vor = add("voronoi_fracture", [stone])
    vor["b4d_vor_count"] = 12
    vor["b4d_vor_seed"] = 3
    vor_rnd = add("random_effector", [vor])
    vor_rnd["b4d_eff_position"] = [30.0, 30.0, 30.0]
    for k in ("linear_field", "box_field", "random_field", "cylinder_field", "capsule_field", "cone_field",
              "torus_field", "radial_field", "shader_field", "wave_field"):
        add(k, [])
    # the Plain Effector's Fields: the ball, minus a box (a row with its own way of combining)
    cut = add("box_field", [plain])
    cut.name = "Cut Box"
    cut.location = (-3.0, 0.0, 0.0)
    plain.b4d_fields[1].blend = "SUBTRACT"
    # a wave through the honeycomb, a pattern on the ring
    wave = add("wave_effector", [comb])
    wave["b4d_eff_position"] = [0.0, 40.0, 0.0]
    shade = add("shader_effector", [ring])
    shade["b4d_eff_pattern"] = 1
    tr = add("tracer", [tgt])
    tr.name = "Tracer"
    blenda4d.moclone.sync_all()
    log("OBJECTS", [(o.name, o.get("b4d_type"), o.parent and o.parent.name) for o in bpy.context.scene.objects])
    for g in ("moclone", "effectors", "fields"):
        log("CREATE", g, [(m[0], m[2]) for m in blenda4d.bars.GROUPS[g]])
    log("MENU MoClone", [it[0] for it in blenda4d.menus.MAIN["MoClone"] if isinstance(it, tuple)],
        [e[0] for e in blenda4d.kinds.menu_items("MoClone")])


def select(name, tab="OBJECT"):
    only([bpy.data.objects[name]])
    bpy.context.window_manager.b4d_am_tab = tab


def frame():
    w = window()
    area = max((a for a in w.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    area.spaces[0].shading.type = "MATERIAL"
    r3d = area.spaces[0].region_3d                   # a view from the front and above, like the approved look
    r3d.view_perspective = "PERSP"
    r3d.view_rotation = Euler((math.radians(58), 0.0, math.radians(18))).to_quaternion()
    r3d.view_location = (0.0, 1.0, 0.5)
    r3d.view_distance = 30.0


def put(name, setting, value):
    from blenda4d import moclone as M
    M.put(bpy.data.objects[name], setting, value)


# --- the Object Manager: rows, selection at a size, a drag into the Attribute Manager ------------------------------
def om_region():
    from blenda4d import roles
    a = roles.areas(window().screen, "OBJECTS")[0]
    return a, next(r for r in a.regions if r.type == "WINDOW")


def row_y(name):
    from blenda4d import managers
    _a, r = om_region()
    rows = [o.name for o, _d in managers.visible_rows(bpy.context)]
    h = managers.row_height()
    vy = -(managers.ROWS_TOP_UNITS + rows.index(name) + 0.5) * h
    return r.y + int(r.view2d.view_to_region(0, vy, clip=False)[1])


def ev(t, v, x, y):
    window().event_simulate(t, v, x=x, y=y)


def ui_scale(s):
    bpy.context.preferences.view.ui_scale = s
    log("UI SCALE", s, "row height", blenda4d.managers.row_height(), "system scale", bpy.context.preferences.system.ui_scale)


def scroll_to(name):
    only([bpy.data.objects[name]])
    a, r = om_region()
    with bpy.context.temp_override(window=window(), area=a, region=r):
        bpy.ops.blenda4d.om_scroll_active()


def click_row(name):
    """A real click on the row's name (the press and release the Object Manager's keymap reads)."""
    _a, r = om_region()
    x, y = r.x + 90, row_y(name)
    ev("MOUSEMOVE", "NOTHING", x, y)
    ev("LEFTMOUSE", "PRESS", x, y)
    ev("LEFTMOUSE", "RELEASE", x, y)


def check_click(name):
    act = bpy.context.view_layer.objects.active
    log("CLICK", name, "-> active", act.name if act else None, "OK" if act and act.name == name else "WRONG")


_drag = {}


def drag_steps(src, owner):
    """Press on src's row in the Object Manager and move to the middle of the Attribute Manager, then let go."""
    from blenda4d import roles

    def show_row():                                  # scroll the Object Manager so the dragged row is in sight
        scroll_to(src)

    def press():
        only([bpy.data.objects[owner]])               # the Attribute Manager shows the owner; the list stays put
        bpy.context.window_manager.b4d_am_tab = "EFFECTORS"
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
              lambda: log("DROP", src, "->", owner, [l.object.name for l in bpy.data.objects[owner].b4d_effectors if l.object],
                          "parent", getattr(bpy.data.objects[src].parent, "name", None))]
    return steps


def untick(owner, i):
    bpy.data.objects[owner].b4d_effectors[i].use = False


def after_off():
    log("OFF kinds", [k for k in ("cloner", "random_effector", "box_field") if k in blenda4d.kinds.KINDS],
        "prop", hasattr(bpy.types.Object, "b4d_effectors"),
        "copies", len(bpy.data.objects["Cloner"].evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices))


W = [lambda: None]
PLAN = W * 5 + [scene] + W * 2 + [frame] + W * 3
for name, tab, setting in (
        ("Cloner", "OBJECT", ("Mode", "Linear")), ("Cloner", "OBJECT", ("Mode", "Radial")),
        ("Cloner", "OBJECT", ("Mode", "Honeycomb")), ("Cloner", "OBJECT", ("Mode", "Object")),
        ("Cloner", "OBJECT", ("Mode", "Grid")), ("Cloner", "OBJECT", ("Form", "Sphere")),
        ("Cloner", "OBJECT", ("Form", "Box")), ("Cloner", "EFFECTORS", None),
        ("Matrix", "OBJECT", None), ("Matrix", "EFFECTORS", None), ("Fracture", "OBJECT", None),
        ("Voronoi Fracture", "OBJECT", None), ("Voronoi Fracture", "EFFECTORS", None), ("Tracer", "OBJECT", None),
        ("Random Effector", "OBJECT", None), ("Plain Effector", "OBJECT", None), ("Plain Effector", "FIELDS", None),
        ("Delay Effector", "OBJECT", None), ("Step Effector", "OBJECT", None), ("Target Effector", "OBJECT", None),
        ("Time Effector", "OBJECT", None), ("Shader Effector", "OBJECT", None), ("Wave Effector", "OBJECT", None),
        ("Linear Field", "OBJECT", None), ("Spherical Field", "OBJECT", None),
        ("Box Field", "OBJECT", None), ("Random Field", "OBJECT", None), ("Cylinder Field", "OBJECT", None),
        ("Capsule Field", "OBJECT", None), ("Cone Field", "OBJECT", None), ("Torus Field", "OBJECT", None),
        ("Radial Field", "OBJECT", None), ("Shader Field", "OBJECT", None), ("Wave Field", "OBJECT", None)):
    if setting:
        PLAN += [lambda n=name, s=setting: put(n, *s)]
    tag = f"_{setting[0]}_{setting[1]}".replace(" ", "") if setting else ""
    PLAN += [lambda n=name, t=tab: select(n, t)] + W * 2 + [lambda n=name, t=tab, g=tag: shot(f"am_{n.replace(' ', '_')}_{t}{g}")]
# a drag from the Object Manager into the Cloner's Effectors page, then a row left out with its check box
PLAN += drag_steps("Time Effector", "Cloner") + W * 2 + [lambda: shot("drop_time_effector_into_cloner")]
PLAN += [lambda: untick("Cloner", 0)] + W * 2 + [lambda: shot("cloner_effectors_row_unticked")]
# the Object Manager's selection lined up with its rows at three interface sizes; a click picks the row under it
for s in (1.0, 1.25, 1.5):
    # bring the row into sight, then select another object (without scrolling) so the click has to do the work
    PLAN += [lambda s=s: ui_scale(s)] + W * 3 + [lambda: scroll_to("Random Field"), lambda: only([bpy.data.objects["Floor"]])] + W * 2
    PLAN += [lambda: click_row("Random Field")] + W + [lambda: check_click("Random Field")] + W * 2
    PLAN += [lambda s=s: shot(f"om_select_scale_{s}")]
PLAN += [lambda: ui_scale(1.0)] + W * 2
PLAN += [lambda: blenda4d.switch.set_mode(False)] + W * 6 + [after_off, lambda: shot("off")]
PLAN += [lambda: blenda4d.switch.set_mode(True)] + W * 8 + [lambda: select("Cloner"), *W * 2, lambda: shot("on_again")]
PLAN += [lambda: open(os.path.join(OUT, "done.txt"), "w").write("ok"), lambda: LOG.close(), lambda: bpy.ops.wm.quit_blender()]
_i = [0]


def tick():
    fn = PLAN[_i[0]]
    if fn.__name__ != "<lambda>" or _i[0] % 5 == 0:
        log("STEP", _i[0], getattr(fn, "__name__", ""))          # the last step logged is where a crash happened
    try:
        fn()
    except Exception:
        log("ERROR", traceback.format_exc())
    _i[0] += 1
    return 0.6 if _i[0] < len(PLAN) else None


bpy.app.timers.register(tick, first_interval=1.5)
