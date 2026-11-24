# Headless test of material drag and drop (matdrag.py): the drop puts the material in the object's first slot (a new
# slot when it has none) and an object that takes no material refuses it, a small render shows the change, every
# Material Manager setting (view, preview size, search) changes what a drag can pick up, and the Blenda 4D | Blender
# switch takes everything the module registered back out and puts it back on the way in.
#   BLENDER_USER_CONFIG=<scratch> Blender -b --factory-startup --python tools/tests/matdrag_engine.py
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import blenda4d  # noqa: E402
from blenda4d import managers, matdrag, matman, switch  # noqa: E402

OUT = os.environ.get("B4D_OUT", "/tmp")
FAIL = []


def check(cond, what):
    """Record one test result.

    cond: the condition that must hold; what: the description printed (and kept on failure).
    """
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAIL.append(what)


def emission_mat(name, rgba):
    """A material that renders as a flat colour (an emission node), so a render needs no light.

    name: the material's name; rgba: its colour. Returns the new Material.
    """
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = rgba
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def render(ob):
    """Render one object alone at 32x32 and read the pixels back.

    ob: the only object left visible for the render. Returns the flat list of RGBA pixels.
    """
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o != ob
    sc = bpy.context.scene
    sc.render.filepath = os.path.join(OUT, "matdrag_render.png")
    bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(sc.render.filepath, check_existing=False)
    px = list(im.pixels)
    bpy.data.images.remove(im)
    return px


def diff(a, b):
    """Mean absolute difference between two pixel lists.

    a, b: the pixel lists to compare. Returns a value near 0 when they match.
    """
    return sum(abs(x - y) for x, y in zip(a, b)) / max(len(a), 1)


def main():
    """Run the whole headless test: registration in Blenda mode, the drop semantics, the settings, the switch.

    No arguments; prints one line per check and the final MATDRAG RESULT.
    """
    blenda4d.register()
    switch.set_mode(True)
    wm = bpy.context.window_manager

    # --- the module is in while Blenda mode is on -----------------------------------------------------------
    kc = wm.keyconfigs.addon
    km = kc.keymaps.get("Property Editor") if kc else None
    check(hasattr(bpy.types.WindowManager, "b4d_mat_drop"), "Blenda mode on: the drop-target property is there")
    check(hasattr(bpy.types, "BLENDA4D_OT_mm_drag"), "Blenda mode on: the drag operator is registered")
    check(km is not None and any(k.idname == "blenda4d.mm_drag" for k in km.keymap_items),
          "Blenda mode on: blenda4d.mm_drag is on CLICK_DRAG in the Property Editor keymap")
    check(len(matdrag._draw) == 1, "Blenda mode on: the drop highlight draw handler is in")

    # --- scene: two planes and a light, three materials ------------------------------------------------------
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_plane_add(size=2)
    a = bpy.context.object
    a.name = "A"
    bpy.ops.mesh.primitive_plane_add(size=2)
    b = bpy.context.object
    b.name = "B"
    b.location = (3, 0, 0)
    bpy.ops.object.light_add(type="POINT", location=(0, 0, 5))
    light = bpy.context.object
    red = emission_mat("Red", (1, 0, 0, 1))
    blue = emission_mat("Blue", (0, 0, 1, 1))
    green = emission_mat("Green", (0, 1, 0, 1))
    bpy.data.materials.new(".Hidden")                       # dot-named materials stay out of the manager
    a.data.materials.append(red)

    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 3.0
    cam.location = (0, 0, 5)
    bpy.context.scene.collection.objects.link(cam)
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 8
    sc.cycles.use_denoising = False
    sc.render.resolution_x = sc.render.resolution_y = 32
    sc.render.film_transparent = True

    # --- the drop itself -------------------------------------------------------------------------------------
    check(matdrag.assign(a, blue), "drop on an object with a slot: accepted")
    check(a.data.materials[0] == blue and len(a.material_slots) == 1, "the first slot is replaced, no slot added")
    check(matdrag.assign(b, red), "drop on an object without slots: accepted")
    check(len(b.material_slots) == 1 and b.data.materials[0] == red, "a first slot is made")
    check(not matdrag.assign(light, green), "a light takes no material: the drop is refused")
    check(not matdrag.assign(None, green) and not matdrag.assign(a, None), "missing object or material: refused")
    check(matdrag._can_take(a) and not matdrag._can_take(light) and not matdrag._can_take(None),
          "_can_take: the cursor's drop-possible test matches what assign accepts")

    base = render(a)
    matdrag.assign(a, red)
    check(diff(render(a), base) > 0.01, "a small render shows the dropped material (slot 0 changed)")
    matdrag.assign(a, blue)

    # --- every Material Manager setting changes what a drag can pick up --------------------------------------
    listed = matman.materials(bpy.context)
    all_ok = [m for m in bpy.data.materials if not m.is_grease_pencil and not m.name.startswith(".")]
    check([m.name for m in listed] == [m.name for m in all_ok][::-1], "the manager lists the scene's materials, newest first")
    check(all(not m.name.startswith(".") for m in listed), "dot-named materials stay out of the list")
    views = []
    for v in ("LIST", "ICONS", "LAYERS"):
        wm.b4d_mm_view = v
        views.append(wm.b4d_mm_view)
    check(views == ["LIST", "ICONS", "LAYERS"], "every view (list, icons, layers) is a setting that sticks")
    import types
    stub = types.SimpleNamespace(preferences=types.SimpleNamespace(system=types.SimpleNamespace(ui_scale=1.0, pixel_size=1.0)),
                                 window_manager=types.SimpleNamespace(b4d_mm_px=64))
    h64 = matdrag._row_h(stub)
    stub.window_manager.b4d_mm_px = 120
    h120 = matdrag._row_h(stub)
    check(h120 > h64, f"the preview size changes the list rows' height ({h64:.1f} -> {h120:.1f})")
    wm.b4d_mm_px = 64
    wm.b4d_mm_search = True
    wm.b4d_mm_filter = "blu"
    check([m.name for m in matman.materials(bpy.context)] == ["Blue"], "the search filter changes the listed materials")
    wm.b4d_mm_filter = ""
    wm.b4d_mm_search = False
    check(len(matman.materials(bpy.context)) == len(all_ok), "search off lists all again")
    wm.b4d_om_search = "b"
    check([o.name for o, _d in managers.visible_rows(bpy.context)] == ["B"], "the Object Manager search changes the drop targets")
    wm.b4d_om_search = ""

    # --- the switch restores everything -----------------------------------------------------------------------
    switch.set_mode(False)
    km = kc.keymaps.get("Property Editor") if kc else None
    check(not hasattr(bpy.types.WindowManager, "b4d_mat_drop"), "switch off: the drop-target property is gone")
    check(not hasattr(bpy.types, "BLENDA4D_OT_mm_drag"), "switch off: the drag operator is unregistered")
    check(km is None or all(k.idname != "blenda4d.mm_drag" for k in km.keymap_items), "switch off: the keymap item is gone")
    check(len(matdrag._draw) == 0 and len(matdrag._keys) == 0, "switch off: the draw handler and keymap bookkeeping are cleared")
    check(a.data.materials[0] == blue, "switch off: the dropped material stays on the object (plain Blender data)")
    check(diff(render(a), base) < 1e-4, "switch off: the render is unchanged, the file keeps working")

    switch.set_mode(True)
    km = kc.keymaps.get("Property Editor") if kc else None
    check(hasattr(bpy.types.WindowManager, "b4d_mat_drop") and hasattr(bpy.types, "BLENDA4D_OT_mm_drag")
          and km is not None and any(k.idname == "blenda4d.mm_drag" for k in km.keymap_items)
          and len(matdrag._draw) == 1, "switch on again: everything is registered again")


main()
print("MATDRAG RESULT", "PASS" if not FAIL else f"FAIL {len(FAIL)}: {FAIL}", flush=True)
