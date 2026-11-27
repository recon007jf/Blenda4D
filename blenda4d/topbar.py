# SPDX-License-Identifier: GPL-3.0-or-later
"""The right half of the command palette: Axis, Snapping, Workplane, Soft Selection, Symmetry, Solo, Render View,
Render to Render Viewer and Render Settings, each on a Blender setting or operator. bars.BLENDA4D_PT_palette draws
them with draw(). Every tool setting changed here is remembered the first time and put back when Blenda mode goes
off (unregister)."""
import bpy
from mathutils import Matrix, Vector

from . import bars, roles

_orig = {}          # (owner, attr) -> value before Blenda first changed it
_state = {"workplane": None, "render_view": None}


def _remember(owner, attr):
    key = (owner, attr)
    if key not in _orig:
        v = getattr(owner, attr)
        _orig[key] = set(v) if isinstance(v, set) else v


def _set(owner, attr, value):
    _remember(owner, attr)
    setattr(owner, attr, value)


def main_view(context):
    """The main 3D viewport (area, region, space): the largest 3D view that is not one of Blenda's panels."""
    screen = context.window.screen if context.window else context.screen
    best = None
    for a in screen.areas:
        if a.type == "VIEW_3D" and roles.role(a) is None:
            if best is None or a.width * a.height > best.width * best.height:
                best = a
    if best is None:
        return None, None, None
    region = next((r for r in best.regions if r.type == "WINDOW"), None)
    return best, region, best.spaces.active


def _in_view(context, fn):
    area, region, _sp = main_view(context)
    if area is None:
        return None
    with context.temp_override(window=context.window, area=area, region=region):
        return fn()


def _snap_elements():
    return {i.identifier for i in bpy.types.ToolSettings.bl_rna.properties["snap_elements"].enum_items}


# --- 1 Axis ---------------------------------------------------------------------------------------------------------
class BLENDA4D_OT_tb_axis(bpy.types.Operator):
    bl_idname = "blenda4d.tb_axis"
    bl_label = "Axis"
    bl_description = "Axis (Affect Only Origins in Blender): move and rotate the object's axis instead of the object"
    bl_options = {"UNDO"}

    def execute(self, context):
        ts = context.tool_settings
        _set(ts, "use_transform_data_origin", not ts.use_transform_data_origin)
        return {"FINISHED"}


# --- 2 Snapping -----------------------------------------------------------------------------------------------------
class BLENDA4D_OT_tb_snap(bpy.types.Operator):
    bl_idname = "blenda4d.tb_snap"
    bl_label = "Snapping"
    bl_description = "Snapping (Snap in Blender): turn snapping on or off. Press and hold to choose what to snap to"
    bl_options = {"UNDO"}

    def execute(self, context):
        ts = context.tool_settings
        _set(ts, "use_snap", not ts.use_snap)
        return {"FINISHED"}


class BLENDA4D_OT_tb_snap_to(bpy.types.Operator):
    bl_idname = "blenda4d.tb_snap_to"
    bl_label = "Snap To"
    bl_description = "Snap to this kind of element as well (or not any more)"
    bl_options = {"UNDO"}
    element: bpy.props.StringProperty()

    def execute(self, context):
        ts = context.tool_settings
        if self.element == "CLOSEST":
            _set(ts, "snap_target", "CENTER" if ts.snap_target == "CLOSEST" else "CLOSEST")
            return {"FINISHED"}
        if self.element not in _snap_elements():
            return {"CANCELLED"}
        _remember(ts, "snap_elements")
        cur = set(ts.snap_elements)
        cur ^= {self.element}
        if not cur:
            cur = {"INCREMENT"}
        ts.snap_elements = cur
        if self.element == "INCREMENT" and "INCREMENT" in cur:
            _set(ts, "use_snap_grid_absolute", True)
        return {"FINISHED"}


SNAP_ITEMS = (("Point", "VERTEX"), ("Edge", "EDGE"), ("Polygon", "FACE"), ("Nearest", "CLOSEST"), ("Grid", "INCREMENT"),
              ("Mid Point", "EDGE_MIDPOINT"), ("Perpendicular", "EDGE_PERPENDICULAR"), ("Volume", "VOLUME"))


class BLENDA4D_MT_tb_snap(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tb_snap"
    bl_label = "Snapping"
    bl_description = "Snap to points, edges, polygons or the grid while moving"

    def draw(self, context):
        ts = context.tool_settings
        have = _snap_elements()
        layout = self.layout
        layout.operator("blenda4d.tb_snap", text="Enable Snapping", icon="CHECKBOX_HLT" if ts.use_snap else "CHECKBOX_DEHLT")
        layout.separator()
        for label, el in SNAP_ITEMS:
            if el == "FACE" and el not in have:
                el = "FACE_PROJECT" if "FACE_PROJECT" in have else el
            on = (ts.snap_target == "CLOSEST") if el == "CLOSEST" else (el in ts.snap_elements)
            row = layout.row()
            row.enabled = el == "CLOSEST" or el in have
            row.operator("blenda4d.tb_snap_to", text=label, icon="CHECKBOX_HLT" if on else "CHECKBOX_DEHLT").element = el


# --- 3 Workplane (the 3D cursor) ------------------------------------------------------------------------------------
class BLENDA4D_OT_tb_workplane(bpy.types.Operator):
    bl_idname = "blenda4d.tb_workplane"
    bl_label = "Workplane"
    bl_description = ("Workplane (the 3D Cursor in Blender): move, rotate and scale along the workplane and around it. "
                      "Press and hold to place the workplane")
    bl_options = {"UNDO"}

    def execute(self, context):
        scene = context.scene
        ts = scene.tool_settings
        slot = scene.transform_orientation_slots[0]
        if _state["workplane"] is None:
            _state["workplane"] = (slot.type, ts.transform_pivot_point)
            slot.type = "CURSOR"
            ts.transform_pivot_point = "CURSOR"
        else:
            kind, pivot = _state["workplane"]
            _state["workplane"] = None
            try:
                slot.type = kind
                ts.transform_pivot_point = pivot
            except TypeError:
                pass
        return {"FINISHED"}


# shown axis -> the Blender axis that is the workplane's normal (Blenda shows Y up: shown Y = Blender Z)
_PLANE_NORMAL = {"X": Vector((1, 0, 0)), "Y": Vector((0, 0, 1)), "Z": Vector((0, 1, 0))}


def _facing(normal):
    """A rotation whose Z axis points along `normal`."""
    return normal.to_track_quat("Z", "Y").to_euler()


class BLENDA4D_OT_tb_workplane_set(bpy.types.Operator):
    bl_idname = "blenda4d.tb_workplane_set"
    bl_label = "Place Workplane"
    bl_description = "Place the workplane"
    bl_options = {"UNDO"}
    how: bpy.props.EnumProperty(items=[("PLANAR", "Planar", "Lay the workplane on the world plane the view looks at most"),
                                       ("CAMERA", "Camera", "Turn the workplane to face the view"),
                                       ("X", "Locked X", "The world plane facing X"),
                                       ("Y", "Locked Y", "The world floor plane, facing Y (up)"),
                                       ("Z", "Locked Z", "The world plane facing Z"),
                                       ("TO_SELECTION", "Align Workplane to Selection", "Put the workplane on the selection, turned like the active object"),
                                       ("SELECTION_TO", "Align Selection to Workplane", "Move and turn the selected objects onto the workplane")])

    @classmethod
    def description(cls, context, props):
        return {i.identifier: i.description for i in cls.bl_rna.properties["how"].enum_items}.get(props.how, "")

    def execute(self, context):
        cur = context.scene.cursor
        _area, _region, sp = main_view(context)
        r3d = sp.region_3d if sp else None
        if self.how in ("X", "Y", "Z"):
            cur.rotation_mode = "XYZ"
            cur.rotation_euler = _facing(_PLANE_NORMAL[self.how])
        elif self.how == "CAMERA" and r3d:
            cur.rotation_mode = "XYZ"
            cur.rotation_euler = r3d.view_rotation.to_euler()
        elif self.how == "PLANAR" and r3d:
            look = r3d.view_rotation @ Vector((0, 0, 1))          # from the scene toward the viewer
            axis = max(range(3), key=lambda i: abs(look[i]))
            n = Vector((0, 0, 0))
            n[axis] = 1.0 if look[axis] >= 0 else -1.0
            cur.rotation_mode = "XYZ"
            cur.rotation_euler = _facing(n)
        elif self.how == "TO_SELECTION":
            if not context.selected_objects:
                self.report({"INFO"}, "Select something first")
                return {"CANCELLED"}
            _in_view(context, lambda: bpy.ops.view3d.snap_cursor_to_selected())
            ob = context.active_object
            if ob is not None:
                cur.rotation_mode = "XYZ"
                cur.rotation_euler = ob.matrix_world.to_euler()
        elif self.how == "SELECTION_TO":
            m = cur.matrix
            for ob in context.selected_objects:
                scale = ob.matrix_world.to_scale()
                ob.matrix_world = Matrix.LocRotScale(m.to_translation(), m.to_quaternion(), scale)
        return {"FINISHED"}


class BLENDA4D_MT_tb_workplane(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tb_workplane"
    bl_label = "Workplane"
    bl_description = "The plane new objects and the grid sit on"

    def draw(self, context):
        layout = self.layout
        layout.operator("blenda4d.tb_workplane", text="Workplane Mode",
                        icon="CHECKBOX_HLT" if _state["workplane"] is not None else "CHECKBOX_DEHLT")
        layout.separator()
        for how, label, icon in (("PLANAR", "Planar", "VIEW_PERSPECTIVE"), ("CAMERA", "Camera", "VIEW_CAMERA"),
                                 ("X", "Locked X", "AXIS_SIDE"), ("Y", "Locked Y", "AXIS_TOP"), ("Z", "Locked Z", "AXIS_FRONT")):
            layout.operator("blenda4d.tb_workplane_set", text=label, icon=icon).how = how
        layout.separator()
        layout.operator("blenda4d.tb_workplane_set", text="Align Workplane to Selection", icon="PIVOT_CURSOR").how = "TO_SELECTION"
        layout.operator("blenda4d.tb_workplane_set", text="Align Selection to Workplane", icon="RESTRICT_SELECT_OFF").how = "SELECTION_TO"


# --- 4 Soft Selection -----------------------------------------------------------------------------------------------
def _soft_attr(context):
    return "use_proportional_edit_objects" if context.mode == "OBJECT" else "use_proportional_edit"


class BLENDA4D_OT_tb_soft(bpy.types.Operator):
    bl_idname = "blenda4d.tb_soft"
    bl_label = "Soft Selection"
    bl_description = "Soft Selection (Proportional Editing in Blender): moving something also moves what is near it, fading with distance"
    bl_options = {"UNDO"}

    def execute(self, context):
        ts = context.tool_settings
        attr = _soft_attr(context)
        _set(ts, attr, not getattr(ts, attr))
        return {"FINISHED"}


# --- 5 Symmetry -----------------------------------------------------------------------------------------------------
_MIRROR = {"X": "use_mirror_x", "Y": "use_mirror_z", "Z": "use_mirror_y"}     # shown axis -> Blender's (Y up)


class BLENDA4D_OT_tb_symmetry(bpy.types.Operator):
    bl_idname = "blenda4d.tb_symmetry"
    bl_label = "Symmetry"
    bl_description = "Symmetry (Mesh Symmetry in Blender): edits on one side of the active mesh are made on the other side too"
    bl_options = {"UNDO"}
    axis: bpy.props.StringProperty(default="X")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        me = context.active_object.data
        attr = _MIRROR.get(self.axis, "use_mirror_x")
        setattr(me, attr, not getattr(me, attr))
        return {"FINISHED"}


class BLENDA4D_MT_tb_symmetry(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tb_symmetry"
    bl_label = "Symmetry"
    bl_description = "Edit both sides of a mirrored object at once"

    def draw(self, context):
        ob = context.active_object
        me = ob.data if ob is not None and ob.type == "MESH" else None
        for a in ("X", "Y", "Z"):
            on = bool(me) and getattr(me, _MIRROR[a])
            self.layout.operator("blenda4d.tb_symmetry", text=a, icon="CHECKBOX_HLT" if on else "CHECKBOX_DEHLT").axis = a


def symmetry_on(context):
    ob = context.active_object
    return ob is not None and ob.type == "MESH" and any(getattr(ob.data, a) for a in _MIRROR.values())


def _mesh(context):
    ob = context.active_object
    return ob.data if ob is not None and ob.type == "MESH" else None


def _sym_get(wm):
    return symmetry_on(bpy.context)


def _sym_set(wm, on):
    me = _mesh(bpy.context)
    if me is None:
        return
    if on:                                          # back to the planes it had before it was switched off (X at first)
        for a in me.get("_b4d_sym_axes", "X"):
            setattr(me, _MIRROR[a], True)
    else:
        me["_b4d_sym_axes"] = "".join(a for a, attr in _MIRROR.items() if getattr(me, attr)) or "X"
        for attr in _MIRROR.values():
            setattr(me, attr, False)


def _axis_prop(axis):
    def get(wm):
        me = _mesh(bpy.context)
        return bool(me) and getattr(me, _MIRROR[axis])

    def put(wm, v):
        me = _mesh(bpy.context)
        if me is not None:
            setattr(me, _MIRROR[axis], v)
    return bpy.props.BoolProperty(name=axis, get=get, set=put, description=f"Mirror across the plane square to {axis}")


def _type_get(wm):
    me = _mesh(bpy.context)
    return 1 if me is not None and me.use_mirror_topology else 0


def _type_set(wm, v):
    me = _mesh(bpy.context)
    if me is not None and v in (0, 1):
        me.use_mirror_topology = v == 1


SYM_PROPS = {
    "b4d_sym_on": bpy.props.BoolProperty(name="Symmetry", get=_sym_get, set=_sym_set,
                                         description="Edits on one side of the active mesh are made on the other side too"),
    "b4d_sym_planes": bpy.props.BoolProperty(name="Show Planes", default=True,
                                             description="Draw the mirror planes and the mirror image of the selection in the viewport"),
    "b4d_sym_type": bpy.props.EnumProperty(name="Type", get=_type_get, set=_type_set, items=(
        ("PLANAR", "Planar", "Mirror across the planes, finding each point's partner by its position", 0),
        ("TOPOLOGY", "Topology", "Find each point's partner by how the mesh is connected, so it still works once the shape is no longer exactly symmetrical (Blender: Topology Mirror)", 1))),
    "b4d_sym_x": _axis_prop("X"), "b4d_sym_y": _axis_prop("Y"), "b4d_sym_z": _axis_prop("Z"),
}


class BLENDA4D_PT_tb_symmetry(bpy.types.Panel):
    bl_idname = "BLENDA4D_PT_tb_symmetry"
    bl_label = "Symmetry Hub"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 12

    def draw(self, context):
        wm = context.window_manager
        col = self.layout.column()
        if _mesh(context) is None:
            col.label(text="Select a polygon object", icon="INFO")
            col = col.column()
            col.enabled = False

        def line(label):                            # label on the left, the control on the right
            sp = col.split(factor=0.3)
            sp.label(text=label)
            return sp.row(align=True)

        line("Symmetry").prop(wm, "b4d_sym_on", text="")
        line("Show Planes").prop(wm, "b4d_sym_planes", text="")
        row = line("Type")
        row.prop_enum(wm, "b4d_sym_type", "PLANAR")
        row.prop_enum(wm, "b4d_sym_type", "TOPOLOGY")
        col.separator()
        for a in "XYZ":
            line(a).prop(wm, "b4d_sym_" + a.lower(), text="")



# --- 6 Solo ---------------------------------------------------------------------------------------------------------
def solo_on(context):
    from . import solo
    return solo.is_on(context.scene)


class BLENDA4D_OT_tb_solo(bpy.types.Operator):
    bl_idname = "blenda4d.tb_solo"
    bl_label = "Solo"
    bl_description = ("Solo: show only the selected objects and what is under them; the camera does not move. Press "
                      "again to show everything. Press and hold for more")

    def execute(self, context):
        from . import solo
        if not solo.run(context, "TOGGLE"):
            self.report({"INFO"}, "Select an object first")
            return {"CANCELLED"}
        solo.redraw(context)
        return {"FINISHED"}


class BLENDA4D_MT_tb_solo(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tb_solo"
    bl_label = "Solo"
    bl_description = "Show only the selected objects"

    def draw(self, context):
        from . import solo
        for mode, label, _d in solo.MODES:
            self.layout.operator("blenda4d.solo", text=label).mode = mode


# --- 7 Render View --------------------------------------------------------------------------------------------------
class BLENDA4D_OT_tb_render_view(bpy.types.Operator):
    bl_idname = "blenda4d.tb_render_view"
    bl_label = "Render View"
    bl_description = ("Render View (Rendered viewport shading in Blender): render the scene live in the viewport; press "
                      "again to go back. Press and hold for more")
    how: bpy.props.EnumProperty(items=[("VIEW", "Render View", ""),
                                       ("SELECTION", "Render Selection", "Render only the selected objects (to the Render Viewer)"),
                                       ("REGION", "Render Region", "Draw a box in the viewport: renders render only that part"),
                                       ("INTERACTIVE", "Live Render Region", "Draw a box in the viewport and render it live")],
                                options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        if props.how == "VIEW":
            return cls.bl_description
        return {i.identifier: i.description for i in cls.bl_rna.properties["how"].enum_items}[props.how]

    def execute(self, context):
        area, region, sp = main_view(context)
        if self.how in ("VIEW", "INTERACTIVE") and sp is not None:
            if sp.shading.type == "RENDERED" and self.how == "VIEW":
                bars.set_shading(sp, _state["render_view"] or "SOLID")
                _state["render_view"] = None
            elif sp.shading.type != "RENDERED":
                _state["render_view"] = sp.shading.type
                bars.set_shading(sp, "RENDERED")
        if self.how in ("REGION", "INTERACTIVE") and area is not None:
            from . import magnify
            magnify.leave(area)
            _set(context.scene.render, "use_border", True)
            _state["live_region"] = self.how == "INTERACTIVE"
            with context.temp_override(window=context.window, area=area, region=region):
                bpy.ops.view3d.render_border("INVOKE_DEFAULT")
        if self.how == "SELECTION":
            return _render_selection(context, self)
        return {"FINISHED"}


_hidden = []


def _put_back(*_args):
    for ob in _hidden:
        try:
            ob.hide_render = False
        except ReferenceError:
            pass
    _hidden.clear()
    for h in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        if _put_back in h:
            h.remove(_put_back)


def _render_selection(context, op):
    sel = set(context.selected_objects)
    if not sel:
        op.report({"INFO"}, "Select something first")
        return {"CANCELLED"}
    _put_back()
    for ob in context.scene.objects:
        if ob not in sel and ob.type not in ("LIGHT", "CAMERA") and not ob.hide_render:
            ob.hide_render = True
            _hidden.append(ob)
    bpy.app.handlers.render_complete.append(_put_back)
    bpy.app.handlers.render_cancel.append(_put_back)
    try:
        res = bpy.ops.render.render("EXEC_DEFAULT" if bpy.app.background else "INVOKE_DEFAULT")
    except RuntimeError as ex:
        _put_back()
        op.report({"ERROR"}, str(ex))
        return {"CANCELLED"}
    if bpy.app.background or "RUNNING_MODAL" not in res:
        _put_back()
    return {"FINISHED"}


class BLENDA4D_MT_tb_render_view(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tb_render_view"
    bl_label = "Render View"
    bl_description = "Render in the viewport"

    def draw(self, context):
        for how, label in (("VIEW", "Render View"), ("SELECTION", "Render Selection"), ("REGION", "Render Region"),
                           ("INTERACTIVE", "Live Render Region")):
            self.layout.operator("blenda4d.tb_render_view", text=label).how = how
        self.layout.separator()
        self.layout.operator("blenda4d.region_resume", icon="PLAY")
        self.layout.operator("blenda4d.region_pause", icon="PAUSE")
        self.layout.operator("blenda4d.region_close", icon="X")
        self.layout.separator()
        self.layout.prop(context.scene.render, "use_border", text="Use Render Region")


# --- 8 Render to Render Viewer --------------------------------------------------------------------------------------
class BLENDA4D_OT_tb_later(bpy.types.Operator):
    bl_idname = "blenda4d.tb_later"
    bl_label = "Not available yet"
    bl_description = "Not available yet"

    def execute(self, context):
        return {"CANCELLED"}


class BLENDA4D_MT_tb_render(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tb_render"
    bl_label = "Render"
    bl_description = "Render a still or an animation"

    def draw(self, context):
        layout = self.layout
        layout.operator("blenda4d.render", text="Render to Render Viewer", icon="RENDER_STILL").animation = False
        layout.operator("blenda4d.render", text="Render Animation", icon="RENDER_ANIMATION").animation = True
        layout.separator()
        for label in ("Add to Render Queue", "Render Queue"):
            row = layout.row()
            row.enabled = False
            row.operator("blenda4d.tb_later", text=label)



# --- drawing (called by bars.BLENDA4D_PT_palette) ---------------------------------------------------------------------
def _hold(row, op, menu, icon, depress=False, **props):
    o = row.operator_menu_hold(op, text="", icon=icon, menu=menu, depress=depress)
    for k, v in props.items():
        setattr(o, k, v)
    return o


def groups(context):
    """The command bar's groups drawn here: each a list of (width in buttons, draw(row)). One entry is one button."""
    ts = context.tool_settings
    _a, _r, sp = main_view(context)
    return [
        [(1, lambda g: g.operator("blenda4d.tb_axis", text="", icon="EMPTY_ARROWS", depress=ts.use_transform_data_origin))],
        [(1, lambda g: _hold(g, "blenda4d.tb_snap", "BLENDA4D_MT_tb_snap", "SNAP_ON" if ts.use_snap else "SNAP_OFF", depress=ts.use_snap))],
        [(1, lambda g: _hold(g, "blenda4d.tb_workplane", "BLENDA4D_MT_tb_workplane", "GRID", depress=_state["workplane"] is not None))],
        [(1, lambda g: g.operator("blenda4d.tb_soft", text="", icon="PROP_ON", depress=getattr(ts, _soft_attr(context))))],
        [(1, lambda g: _hold(g, "blenda4d.tb_symmetry", "BLENDA4D_MT_tb_symmetry", "MOD_MIRROR", depress=symmetry_on(context), axis="X")),
         (1, lambda g: g.popover("BLENDA4D_PT_tb_symmetry", text="", icon="PREFERENCES"))],
        [(1, lambda g: _hold(g, "blenda4d.tb_solo", "BLENDA4D_MT_tb_solo", "SELECT_INTERSECT", depress=solo_on(context)))],
        [(1, lambda g: _hold(g, "blenda4d.tb_render_view", "BLENDA4D_MT_tb_render_view", "SHADING_RENDERED",
                             depress=bool(sp and sp.shading.type == "RENDERED"))),
         (1, lambda g: _hold(g, "blenda4d.render", "BLENDA4D_MT_tb_render", "RENDER_STILL")),
         (1, lambda g: g.operator("blenda4d.render_settings", text="", icon="SCENE"))],
    ]


classes = (BLENDA4D_OT_tb_axis, BLENDA4D_OT_tb_snap, BLENDA4D_OT_tb_snap_to, BLENDA4D_MT_tb_snap, BLENDA4D_OT_tb_workplane,
           BLENDA4D_OT_tb_workplane_set, BLENDA4D_MT_tb_workplane, BLENDA4D_OT_tb_soft, BLENDA4D_OT_tb_symmetry,
           BLENDA4D_MT_tb_symmetry, BLENDA4D_PT_tb_symmetry, BLENDA4D_OT_tb_solo, BLENDA4D_MT_tb_solo, BLENDA4D_OT_tb_render_view,
           BLENDA4D_MT_tb_render_view, BLENDA4D_OT_tb_later, BLENDA4D_MT_tb_render)
_registered = [False]


def registered():
    return _registered[0]


def restore():
    """Put back every tool setting the palette changed and leave workplane mode."""
    if _state["workplane"] is not None:
        kind, pivot = _state["workplane"]
        _state["workplane"] = None
        for scene in bpy.data.scenes:
            try:
                if scene.transform_orientation_slots[0].type == "CURSOR":
                    scene.transform_orientation_slots[0].type = kind
                if scene.tool_settings.transform_pivot_point == "CURSOR":
                    scene.tool_settings.transform_pivot_point = pivot
            except (TypeError, ReferenceError):
                pass
    for (owner, attr), v in list(_orig.items()):
        try:
            setattr(owner, attr, v)
        except (TypeError, ValueError, ReferenceError, AttributeError):
            pass
    _orig.clear()
    _put_back()
    _state["render_view"] = None


def register():
    for c in classes:
        bpy.utils.register_class(c)
    for k, v in SYM_PROPS.items():
        setattr(bpy.types.WindowManager, k, v)
    from . import symmetry_draw
    symmetry_draw.register()
    _registered[0] = True


def unregister():
    _registered[0] = False
    from . import symmetry_draw
    symmetry_draw.unregister()
    for k in SYM_PROPS:
        if hasattr(bpy.types.WindowManager, k):
            delattr(bpy.types.WindowManager, k)
    restore()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
