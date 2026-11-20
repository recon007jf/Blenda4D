# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone: the Cloner, which lays out copies of the objects under it, and the effectors that change those copies.

Cloner: a mesh object in the Object Manager with one Geometry Nodes modifier (moclone_nodes.py). The objects under it
are what it copies; with several, the copies use them in turn or pick at random. Modes: Linear (a row, each copy one
step further), Grid (a block of rows), Radial (a ring or an arc) and Object (along a spline, on the points of a mesh or
scattered over its surface). The children show as a wire while the Cloner is on, so they stay selectable.

Effectors (Random, Step, Target, Time): Nulls with their own settings. A Cloner lists the effectors that act on it on
its Effectors page, in order; making an effector with a Cloner selected adds it to that Cloner's list. Random moves,
turns, sizes and tints each copy by a different random amount; Step does it more and more from the first copy to the
last; Time does it more and more as the animation plays; Target turns the copies to face the effector.

The group is built again when the children or the effector list change (settings kept). An effector's settings are
custom properties (b4d_eff_*) read by drivers in the Cloner's group, so files keep working with Blenda mode off.
sync() runs after every scene update and keeps all of this in step."""
import bpy
from mathutils import Matrix

from . import kinds
from . import moclone_nodes as mn

CLONER = "cloner"
MOD = "Blenda Cloner"
CONSUMED = "b4d_cloned"                  # on a child the Cloner copies: how it looked before, to give it back
SIG = "b4d_clone_sig"                    # what the Cloner's group was built from

# kind -> (label, icon, tooltip, starting values)
EFFECTORS = {
    "random_effector": ("Random Effector", "FORCE_TURBULENCE", "Move, turn, size and tint each copy by a different random amount",
                        {"b4d_eff_position": (50.0, 50.0, 50.0)}),
    "step_effector": ("Step Effector", "IPO_CONSTANT", "Change the copies more and more from the first to the last",
                      {"b4d_eff_scale": (100.0, 100.0, 100.0)}),
    "target_effector": ("Target Effector", "TRACKER", "Turn the copies so they face this effector", {}),
    "time_effector": ("Time Effector", "TIME", "Change the copies more and more as the animation plays (amounts per second)",
                      {"b4d_eff_rotation": (0.0, 1.5707963, 0.0)}),
}
EFFECTOR_ORDER = ("random_effector", "step_effector", "target_effector", "time_effector")

# setting -> (default, how the field shows)
SETTINGS = {
    "b4d_eff_strength": (100.0, dict(subtype="PERCENTAGE", soft_min=0.0, soft_max=100.0, precision=1,
                                     description="How much of the effect the copies get")),
    "b4d_eff_position": ((0.0, 0.0, 0.0), dict(soft_min=-10000.0, soft_max=10000.0, precision=1, step=100,
                                               description="How far the copies move, in centimetres, along their own axes")),
    "b4d_eff_rotation": ((0.0, 0.0, 0.0), dict(subtype="EULER", description="How far the copies turn about their own axes")),
    "b4d_eff_scale": ((0.0, 0.0, 0.0), dict(soft_min=-100.0, soft_max=1000.0, precision=1,
                                            description="How much the copies grow (or shrink, below 0), in percent")),
    "b4d_eff_use_color": (False, dict(description="Tint the copies; a material shows it through an Attribute node "
                                                  f"reading \"{mn.COLOR_ATTR}\"")),
    "b4d_eff_color": ((1.0, 0.25, 0.05), dict(subtype="COLOR", min=0.0, max=1.0, description="The tint")),
    "b4d_eff_seed": (0, dict(min=0, max=1000000, description="Pick a different random pattern")),
}
KIND_SETTINGS = {
    "random_effector": ("b4d_eff_strength", "b4d_eff_position", "b4d_eff_rotation", "b4d_eff_scale", "b4d_eff_use_color",
                        "b4d_eff_color", "b4d_eff_seed"),
    "step_effector": ("b4d_eff_strength", "b4d_eff_position", "b4d_eff_rotation", "b4d_eff_scale", "b4d_eff_use_color",
                      "b4d_eff_color"),
    "target_effector": ("b4d_eff_strength",),
    "time_effector": ("b4d_eff_strength", "b4d_eff_position", "b4d_eff_rotation", "b4d_eff_scale"),
}


def is_cloner(ob):
    return ob is not None and ob.get("b4d_type") == CLONER


def effector_kind(ob):
    k = ob.get("b4d_type") if ob is not None else None
    return k if k in EFFECTORS else None


def enabled(ob):
    return bool(ob.get("_b4d_enabled", True))


def kids_of(cloner):
    """The objects the Cloner copies: its children with geometry, in Object Manager order (by name)."""
    return [c for c in sorted(cloner.children, key=lambda c: c.name)
            if c.type in ("MESH", "CURVE", "FONT") and effector_kind(c) is None]


def effectors_of(cloner):
    """[(effector, kind)] in list order; empty slots and objects that are no longer effectors are skipped."""
    out = []
    for link in getattr(cloner, "b4d_effectors", ()):
        ob = link.object
        k = effector_kind(ob)
        if k is not None and ob.name in bpy.data.objects and (ob, k) not in out:
            out.append((ob, k))
    return out


def stamp(ob, kind, start=None):
    """Give the effector every setting its kind reads (a missing one would break the drivers)."""
    if "_b4d_enabled" not in ob:
        ob["_b4d_enabled"] = True
    for key in KIND_SETTINGS[kind]:
        if key in ob:
            continue
        default, ui = SETTINGS[key]
        v = (start or {}).get(key, default)
        ob[key] = list(v) if isinstance(v, tuple) else v
        ob.id_properties_ui(key).update(default=list(default) if isinstance(default, tuple) else default, **ui)


# --- the Cloner's modifier ----------------------------------------------------------------------------------------
def mod_of(ob):
    return ob.modifiers.get(MOD) if ob is not None else None


def slot(ob, name):
    """(owner, attribute) of one of the Cloner's settings, or None."""
    from .primitives import input_slot
    mod = mod_of(ob)
    if mod is None or mod.node_group is None or name not in mod.node_group.interface.items_tree:
        return None
    try:
        return input_slot(mod, mod.node_group.interface.items_tree[name].identifier)
    except (KeyError, AttributeError):
        return None


def get(ob, name):
    s = slot(ob, name)
    return getattr(*s) if s else None


def put(ob, name, v):
    s = slot(ob, name)
    if s is not None:
        setattr(*s, v)
        ob.update_tag()


def _signature(cloner):
    return "|".join([cloner.name, ",".join(o.name for o in kids_of(cloner)), ",".join(f"{o.name}:{k}" for o, k in effectors_of(cloner))])


def rebuild(cloner):
    mod = mod_of(cloner)
    if mod is None:
        mod = cloner.modifiers.new(MOD, "NODES")
    old = {}
    if mod.node_group is not None:
        for it in mod.node_group.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT":
                v = get(cloner, it.name)
                old[it.name] = tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v   # copied: the swap frees it
    tree = mn.make_group(f"Blenda Cloner [{cloner.name}]", kids_of(cloner), effectors_of(cloner), cloner.name)
    mod.node_group = tree
    for name, v in old.items():
        if name in tree.interface.items_tree:
            try:
                put(cloner, name, v)
            except (TypeError, AttributeError, ValueError):
                pass
    cloner[SIG] = _signature(cloner)
    cloner.update_tag()


def _needs_rebuild(cloner):
    mod = mod_of(cloner)
    if mod is None or mod.node_group is None or mod.node_group.get("b4d_owner") != cloner.name:
        return True
    return cloner.get(SIG) != _signature(cloner)


def _consume(ob):
    if CONSUMED in ob:
        return
    ob[CONSUMED] = {"display": ob.display_type, "render": int(ob.hide_render)}
    ob.display_type = "WIRE"
    ob.hide_render = True


def _release(ob):
    was = ob.get(CONSUMED)
    if was is None:
        return
    try:                                         # copy the values out before the property (and `was`) is deleted
        display, render = str(was.get("display", "TEXTURED")), bool(was.get("render", 0))
    except (TypeError, AttributeError):
        display, render = "TEXTURED", False
    del ob[CONSUMED]
    try:
        ob.display_type = display
    except TypeError:
        ob.display_type = "TEXTURED"
    ob.hide_render = render


_busy = [False]


def sync(scene):
    if _busy[0] or scene is None:
        return
    _busy[0] = True
    try:
        keep = set()
        for ob in scene.objects:
            if effector_kind(ob) is not None:
                stamp(ob, effector_kind(ob))
            if not is_cloner(ob):
                continue
            if _needs_rebuild(ob):
                rebuild(ob)
            if enabled(ob):
                for k in kids_of(ob):
                    keep.add(k.name)
                    _consume(k)
        for ob in scene.objects:
            if CONSUMED in ob and ob.name not in keep:
                _release(ob)
    finally:
        _busy[0] = False


def sync_all():
    sync(bpy.context.scene)


@bpy.app.handlers.persistent       # opening a file drops handlers that are not persistent
def _on_update(scene, depsgraph=None):
    try:
        sync(scene)
    except Exception:
        import traceback
        traceback.print_exc()


# --- making them ---------------------------------------------------------------------------------------------------
def create_cloner(context):
    from .generators import _selection, wrap
    from .primitives import tidy_name
    sel = [o for o in _selection(context) if effector_kind(o) is None]
    cloner = bpy.data.objects.new("Cloner", bpy.data.meshes.new("Cloner"))
    context.collection.objects.link(cloner)
    cloner["b4d_type"] = CLONER
    tidy_name(cloner)
    if sel:
        wrap(cloner, sel)
    else:
        cloner.location = context.scene.cursor.location
    rebuild(cloner)
    sync_all()
    return cloner


def add_to(cloner, effector):
    if any(link.object == effector for link in cloner.b4d_effectors):
        return
    cloner.b4d_effectors.add().object = effector
    cloner.b4d_effector_index = len(cloner.b4d_effectors) - 1


def create_effector(context, kind):
    from .primitives import tidy_name
    label, _icon, _tip, start = EFFECTORS[kind]
    cloners = [o for o in context.selected_objects if is_cloner(o)]
    ob = bpy.data.objects.new(label, None)
    ob.empty_display_type = "SPHERE" if kind == "target_effector" else "PLAIN_AXES"
    ob.empty_display_size = 0.25
    context.collection.objects.link(ob)
    ob["b4d_type"] = kind
    tidy_name(ob)
    stamp(ob, kind, start)
    if cloners:
        ob.matrix_world = Matrix.Translation(cloners[0].matrix_world.translation)
        if kind == "target_effector":
            ob.location.z += 3.0                   # above the copies, so turning to face it shows
        for c in cloners:
            add_to(c, ob)
    else:
        ob.location = context.scene.cursor.location
    sync_all()
    return ob


# --- the Cloner's effector list ----------------------------------------------------------------------------------
def _is_effector(self, ob):
    return effector_kind(ob) is not None


def _list_changed(self, context):
    sync_all()


class BLENDA4D_PG_effector_link(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object, name="Effector", poll=_is_effector, update=_list_changed,
                                      description="An effector that changes this Cloner's copies")


class BLENDA4D_UL_effectors(bpy.types.UIList):
    bl_idname = "BLENDA4D_UL_effectors"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        ob = item.object
        if ob is None:                                   # an empty row: pick the effector in it
            row.prop(item, "object", text="", icon="QUESTION")
            return
        row.label(text=ob.name, icon=EFFECTORS[effector_kind(ob)][1] if effector_kind(ob) else "ERROR")
        if hasattr(ob, "b4d_enabled"):
            row.prop(ob, "b4d_enabled", text="", emboss=False, icon="CHECKMARK" if ob.b4d_enabled else "X")


class BLENDA4D_OT_effector_slot(bpy.types.Operator):
    bl_idname = "blenda4d.effector_slot"
    bl_label = "Effector List"
    bl_description = "Add an empty row to the list, or take the selected row out of it"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    action: bpy.props.EnumProperty(items=(("ADD", "Add", "Add an empty row; pick the effector in it"),
                                          ("REMOVE", "Remove", "Take the selected effector out of the list"),
                                          ("UP", "Up", "Act earlier"), ("DOWN", "Down", "Act later")))

    @classmethod
    def poll(cls, context):
        return is_cloner(context.view_layer.objects.active)

    def execute(self, context):
        ob = context.view_layer.objects.active
        lst, i = ob.b4d_effectors, ob.b4d_effector_index
        if self.action == "ADD":
            lst.add()
            ob.b4d_effector_index = len(lst) - 1
        elif 0 <= i < len(lst):
            if self.action == "REMOVE":
                lst.remove(i)
                ob.b4d_effector_index = max(0, i - 1)
            else:
                j = i - 1 if self.action == "UP" else i + 1
                if 0 <= j < len(lst):
                    lst.move(i, j)
                    ob.b4d_effector_index = j
        sync_all()
        return {"FINISHED"}


# --- Attribute Manager pages ---------------------------------------------------------------------------------------
def _rows(col, ob, rows):
    """rows: (setting, label) or (setting, label, shown-when(value)); None leaves a gap."""
    def value(name):
        return get(ob, name)
    for r in rows:
        if r is None:
            col.separator()
            continue
        if len(r) > 2 and not r[2](value):
            continue
        s = slot(ob, r[0])
        if s is None:
            continue
        owner, attr = s
        v = getattr(owner, attr)
        if hasattr(v, "__len__") and not isinstance(v, str):
            sub = col.column(align=True)
            for i, axis in enumerate("XYZ"):
                sub.prop(owner, attr, index=i, text=f"{r[1]} . {axis}")
        else:
            col.prop(owner, attr, text=r[1])


def page_cloner(col, ob):
    if mod_of(ob) is None or mod_of(ob).node_group is None:
        col.label(text="This Cloner's nodes are missing", icon="ERROR")
        return
    if not kids_of(ob):
        col.label(text="Put objects under the Cloner to copy them", icon="INFO")
    mode = get(ob, "Mode")

    def is_(*modes):
        return lambda v: v("Mode") in modes
    _rows(col, ob, [
        ("Mode", "Mode"),
        ("Clone Order", "Clones"),
        ("Seed", "Seed", lambda v: v("Clone Order") == "Random" or
         (v("Mode") == "Object" and v("Distribution") == "Surface")),
        None,
        ("Object", "Object", is_("Object")),
        ("Distribution", "Distribution", is_("Object")),
        ("Count", "Count", lambda v: v("Mode") in ("Linear", "Radial") or
         (v("Mode") == "Object" and v("Distribution") != "Points")),
        ("Offset", "Offset", is_("Linear")),
        ("Step Rotation", "Step Rotation", is_("Linear")),
        ("Step Size", "Step Size %", is_("Linear")),
        ("Count X", "Count . X", is_("Grid")), ("Count Y", "Count . Y", is_("Grid")), ("Count Z", "Count . Z", is_("Grid")),
        ("Spacing", "Spacing", is_("Grid")),
        ("Radius", "Radius", is_("Radial")), ("Plane", "Plane", is_("Radial")),
        ("Start Angle", "Start Angle", is_("Radial")), ("End Angle", "End Angle", is_("Radial")),
        ("Align", "Align", is_("Radial", "Object")),
        None,
        ("Keep Instances", "Keep as Instances"),
    ])
    if mode == "Object":
        target = get(ob, "Object")
        if target is None:
            col.label(text="Pick a spline or a polygon object", icon="INFO")
        elif target.type != "MESH" and get(ob, "Distribution") != "Along Spline":
            col.label(text="Points and Surface need a polygon object", icon="INFO")


def page_effectors(col, ob):
    col.use_property_split = False
    col.label(text="Effectors act on the copies in this order")
    row = col.row()
    row.template_list("BLENDA4D_UL_effectors", "", ob, "b4d_effectors", ob, "b4d_effector_index", rows=4)
    side = row.column(align=True)
    side.operator("blenda4d.effector_slot", text="", icon="ADD").action = "ADD"
    side.operator("blenda4d.effector_slot", text="", icon="REMOVE").action = "REMOVE"
    side.separator()
    side.operator("blenda4d.effector_slot", text="", icon="TRIA_UP").action = "UP"
    side.operator("blenda4d.effector_slot", text="", icon="TRIA_DOWN").action = "DOWN"
    if not len(ob.b4d_effectors):
        col.label(text="Select the Cloner, then make an effector to add it here", icon="INFO")


def _vec(col, ob, key, label):
    sub = col.column(align=True)
    for i, a in enumerate("XYZ"):
        sub.prop(ob, f'["{key}"]', index=i, text=f"{label} . {a}")


def page_effector(col, ob):
    kind = effector_kind(ob)
    keys = KIND_SETTINGS[kind]
    col.prop(ob, '["b4d_eff_strength"]', text="Strength")
    if kind == "target_effector":
        col.label(text="Copies turn their Z axis toward this effector", icon="INFO")
    else:
        col.separator()
        per = " / s" if kind == "time_effector" else ""
        _vec(col, ob, "b4d_eff_position", "Position" + per)
        _vec(col, ob, "b4d_eff_rotation", "Rotation" + per)
        _vec(col, ob, "b4d_eff_scale", "Size %" + per)
        if "b4d_eff_use_color" in keys:
            col.separator()
            col.prop(ob, '["b4d_eff_use_color"]', text="Color")
            r = col.row()
            r.active = bool(ob.get("b4d_eff_use_color"))
            r.prop(ob, '["b4d_eff_color"]', text="Tint")
        if "b4d_eff_seed" in keys:
            col.prop(ob, '["b4d_eff_seed"]', text="Seed")
    users = [c.name for c in bpy.data.objects if is_cloner(c) and any(o == ob for o, _k in effectors_of(c))]
    col.separator()
    col.label(text=("Acts on: " + ", ".join(users)) if users else "Not in any Cloner's Effectors list",
              icon="LINKED" if users else "INFO")


# --- registration ----------------------------------------------------------------------------------------------------
classes = (BLENDA4D_PG_effector_link, BLENDA4D_UL_effectors, BLENDA4D_OT_effector_slot)
PROPS = ("b4d_effectors", "b4d_effector_index")
_saved = {}
_STAND_INS = ("Cloner", "Effectors")    # the MoClone menu's greyed entries that the live ones below take over


def _take_over_menus():
    """Remember the create column groups and the MoClone menu as they were; they come back on unregister."""
    from . import bars, menus
    for g in ("moclone", "effectors"):
        if bars.GROUPS.get(g) is not None:
            _saved.setdefault(g, list(bars.GROUPS[g]))
    items = menus.MAIN.get("MoClone")
    if items is not None:
        _saved.setdefault("menu", list(items))
        items[:] = [it for it in items if not (isinstance(it, tuple) and it[0] in _STAND_INS and it[1] is None)]
        while items and items[-1] == menus.SEP:
            items.pop()


def _give_back_menus():
    from . import bars, menus
    for g in ("moclone", "effectors"):
        if g in _saved and bars.GROUPS.get(g) is not None:
            bars.GROUPS[g][:] = _saved.pop(g)
    if "menu" in _saved and menus.MAIN.get("MoClone") is not None:
        menus.MAIN["MoClone"][:] = _saved.pop("menu")
    ours = (CLONER,) + EFFECTOR_ORDER
    kinds._MENU["MoClone"] = [e for e in kinds._MENU.get("MoClone", []) if e[1] not in ours]


def register():
    _take_over_menus()
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.b4d_effectors = bpy.props.CollectionProperty(type=BLENDA4D_PG_effector_link)
    bpy.types.Object.b4d_effector_index = bpy.props.IntProperty(name="Effector", min=0)
    kinds.add(CLONER, "Cloner Object", "MOD_ARRAY", create=create_cloner,
              tabs=[("OBJECT", "Object"), ("EFFECTORS", "Effectors")],
              pages={"OBJECT": page_cloner, "EFFECTORS": page_effectors},
              titles={"OBJECT": "Object Properties", "EFFECTORS": "Effectors"},
              describe="Lay out copies of the objects under it (selected objects go under it)")
    kinds.create_button("moclone", "Cloner", CLONER)
    kinds.menu_item("MoClone", "Cloner", CLONER)
    for k in EFFECTOR_ORDER:
        label, icon, tip, _start = EFFECTORS[k]
        kinds.add(k, label, icon, create=(lambda k: lambda context: create_effector(context, k))(k),
                  tabs=[("OBJECT", "Effector")], pages={"OBJECT": page_effector}, titles={"OBJECT": label},
                  describe=tip + " (with a Cloner selected, it is added to that Cloner)")
        kinds.create_button("effectors", label, k)
        kinds.menu_item("MoClone", label, k)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)


def unregister():
    if _on_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_update)
    for k in (CLONER,) + EFFECTOR_ORDER:
        kinds.KINDS.pop(k, None)
    _give_back_menus()
    for n in PROPS:
        if hasattr(bpy.types.Object, n):
            delattr(bpy.types.Object, n)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
