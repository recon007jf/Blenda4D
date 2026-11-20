# SPDX-License-Identifier: GPL-3.0-or-later
"""The bars and strips: main menu bar, viewport menu bar and tabs, timeline transport row, document tabs, command
palette, modes column and create column. Header draws are replaced only while Blenda mode is on (switch.py puts
Blender's back)."""
import bpy

from . import icons, menus, roles


def tool_icon(name):
    """icon_value of one of Blender's large tool icons ("ops.transform.translate")."""
    try:
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        return ToolSelectPanelHelper._icon_value_from_icon_handle(name)
    except Exception:
        return 0


def active_tool(context):
    try:
        return context.workspace.tools.from_space_view3d_mode(context.mode, create=False).idname
    except Exception:
        return ""


# --- operators the bars use ---------------------------------------------------------------------------------------
class BLENDA4D_OT_set_mode(bpy.types.Operator):
    bl_idname = "blenda4d.set_mode"
    bl_label = "Mode"
    bl_options = {"REGISTER", "UNDO"}
    mode: bpy.props.EnumProperty(items=[("MODEL", "Model", ""), ("POINTS", "Points", ""), ("EDGES", "Edges", ""), ("POLYGONS", "Polygons", "")])

    def execute(self, context):
        ob = context.active_object
        if self.mode == "MODEL":
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            return {"FINISHED"}
        if ob is None or ob.type not in ("MESH", "CURVE"):
            self.report({"INFO"}, "Select a mesh or spline first")
            return {"CANCELLED"}
        if context.mode == "OBJECT":
            bpy.ops.object.mode_set(mode="EDIT")
        if ob.type == "MESH":
            bpy.ops.mesh.select_mode(type={"POINTS": "VERT", "EDGES": "EDGE", "POLYGONS": "FACE"}[self.mode])
        return {"FINISHED"}


class BLENDA4D_OT_shading(bpy.types.Operator):
    bl_idname = "blenda4d.shading"
    bl_label = "Display"
    mode: bpy.props.StringProperty()

    def execute(self, context):
        sp = context.space_data if context.space_data and context.space_data.type == "VIEW_3D" else None
        if sp is None:
            area = next((a for a in context.screen.areas if a.type == "VIEW_3D"), None)
            sp = area.spaces.active if area else None
        if sp:
            sp.shading.type = self.mode
        return {"FINISHED"}


class BLENDA4D_OT_overlay(bpy.types.Operator):
    bl_idname = "blenda4d.overlay"
    bl_label = "Viewport Option"
    what: bpy.props.StringProperty()

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                ov = area.spaces.active.overlay
                if hasattr(ov, self.what):
                    setattr(ov, self.what, not getattr(ov, self.what))
                area.tag_redraw()
        return {"FINISHED"}


class BLENDA4D_OT_axis_lock(bpy.types.Operator):
    bl_idname = "blenda4d.axis_lock"
    bl_label = "Axis"
    bl_description = "Lock or unlock moving, scaling and rotating along this axis"
    axis: bpy.props.IntProperty()

    def execute(self, context):
        locks = context.window_manager.b4d_axis
        locks[self.axis] = not locks[self.axis]
        return {"FINISHED"}


class BLENDA4D_OT_toggle_column(bpy.types.Operator):
    bl_idname = "blenda4d.toggle_column"
    bl_label = "Show / Hide"
    bl_description = "Show or hide this manager"
    name: bpy.props.StringProperty()

    def execute(self, context):
        from . import build
        shown = bool(roles.areas(context.window.screen, self.name))
        build.toggle(context.window, self.name, not shown)
        return {"FINISHED"}


# --- header draws --------------------------------------------------------------------------------------------------
def topbar_left(self, context):
    layout = self.layout
    row = layout.row(align=True)
    row.operator("ed.undo", text="", icon="LOOP_BACK", emboss=False)
    row.operator("ed.redo", text="", icon="LOOP_FORWARDS", emboss=False)
    layout.separator(factor=0.5)
    menus.menu_bar(layout, menus.MAIN_CLASSES)


def topbar_right(self, context):
    from . import layouts
    layout = self.layout
    row = layout.row(align=True)
    row.label(text="Layout:")
    row.menu(layouts.BLENDA4D_MT_layouts.bl_idname, text=layouts.current_name())
    layout.separator(factor=1.0)
    sw = layout.row(align=True)
    sw.operator("blenda4d.switch", text="Blenda 4D", depress=True).on = True
    sw.operator("blenda4d.switch", text="Blender").on = False


def view_header(self, context):
    layout = self.layout
    layout.label(text="", icon="COLLAPSEMENU")
    menus.menu_bar(layout, menus.VIEW_CLASSES)
    layout.separator_spacer()
    sh = context.space_data.shading
    row = layout.row(align=True)
    for mode, icon in (("WIREFRAME", "SHADING_WIRE"), ("SOLID", "SHADING_SOLID"), ("MATERIAL", "SHADING_TEXTURE"), ("RENDERED", "SHADING_RENDERED")):
        row.operator("blenda4d.shading", text="", icon=icon, depress=(sh.type == mode)).mode = mode
    layout.separator(factor=1.0)
    row = layout.row(align=True)
    row.operator("view3d.view_all", text="", icon="VIEW_PAN", emboss=False)
    row.operator("view3d.zoom_border", text="", icon="VIEW_ZOOM", emboss=False)
    row.operator("view3d.view_persportho", text="", icon="ORIENTATION_GIMBAL", emboss=False)
    row.operator("blenda4d.quad_view", text="", icon="FULLSCREEN_EXIT" if sum(a.type == "VIEW_3D" for a in context.screen.areas) > 1 else "FULLSCREEN_ENTER", emboss=False)


def view_tabs(self, context):
    """The viewport's tab row: View | Render Settings | Render Viewer."""
    layout = self.layout
    row = layout.row(align=True)
    row.operator("blenda4d.noop", text="View", depress=True)
    row.operator("blenda4d.render_settings", text="Render Settings")
    row.operator("render.view_show", text="Render Viewer")


def timeline_header(self, context):
    if context.area is None or context.area.ui_type != "TIMELINE":
        return _saved["DOPESHEET_HT_header"](self, context)
    scene = context.scene
    layout = self.layout
    row = layout.row(align=True)
    row.prop(scene, "frame_start", text="")
    layout.separator_spacer()
    row = layout.row(align=True)
    row.operator("screen.frame_jump", text="", icon="REW").end = False
    row.operator("screen.keyframe_jump", text="", icon="PREV_KEYFRAME").next = False
    row.operator("screen.animation_play", text="", icon="PLAY_REVERSE").reverse = True
    row.operator("screen.animation_play", text="", icon="PLAY")
    row.operator("screen.keyframe_jump", text="", icon="NEXT_KEYFRAME").next = True
    row.operator("screen.frame_jump", text="", icon="FF").end = True
    layout.prop(scene, "frame_current", text="")
    layout.prop(scene.tool_settings, "use_keyframe_insert_auto", text="", icon="REC")
    layout.separator_spacer()
    layout.prop(scene, "frame_end", text="")


_saved = {}
OVERRIDES = (("TOPBAR_HT_upper_bar", "draw_left", topbar_left), ("TOPBAR_HT_upper_bar", "draw_right", topbar_right),
             ("VIEW3D_HT_header", "draw", view_tabs), ("VIEW3D_HT_tool_header", "draw", view_header),
             ("DOPESHEET_HT_header", "draw", timeline_header))


def override():
    for cls_name, attr, fn in OVERRIDES:
        cls = getattr(bpy.types, cls_name)
        key = f"{cls_name}.{attr}" if attr != "draw" else cls_name
        if key not in _saved:
            _saved[key] = getattr(cls, attr)
        setattr(cls, attr, fn)


def restore():
    for cls_name, attr, _fn in OVERRIDES:
        cls = getattr(bpy.types, cls_name)
        key = f"{cls_name}.{attr}" if attr != "draw" else cls_name
        if key in _saved:
            setattr(cls, attr, _saved.pop(key))


# --- strips: document tabs, command palette, modes column, create column ----------------------------------------
class BLENDA4D_PT_doc_tabs(roles.RolePanel, bpy.types.Panel):
    bl_label = "Documents"
    role = "DOC_TABS"

    def draw(self, context):
        row = self.layout.row(align=True)
        row.alignment = "LEFT"
        name = bpy.path.basename(bpy.data.filepath) or "Untitled"
        b = row.row(align=True)
        b.ui_units_x = 16
        b.operator("blenda4d.noop", text=name, depress=True)
        row.operator("wm.read_homefile", text="", icon="ADD", emboss=False)


def _palette_button(row, op, icon=None, icon_value=0, depress=False, **props):
    kw = {"icon_value": icon_value} if icon_value else {"icon": icon}
    o = row.operator(op, text="", depress=depress, **kw)
    for k, v in props.items():
        setattr(o, k, v)
    return o


class BLENDA4D_PT_palette(roles.RolePanel, bpy.types.Panel):
    bl_label = "Command Palette"
    role = "PALETTE"

    def draw(self, context):
        layout = self.layout
        whole = layout.row(align=False)
        top = whole.row(align=False)
        top.alignment = "LEFT"
        top.scale_y = 1.2
        top.scale_x = 1.2
        screen = context.window.screen
        g = top.row(align=True)
        _palette_button(g, "blenda4d.toggle_column", "ASSET_MANAGER", depress=bool(roles.areas(screen, "ASSETS")), name="ASSETS")
        top.separator(factor=0.6)
        tool = active_tool(context)
        g = top.row(align=True)
        _palette_button(g, "wm.tool_set_by_id", icon_value=tool_icon("ops.generic.select_box"), depress=tool.startswith("builtin.select"), name="builtin.select_box", space_type="VIEW_3D")
        top.separator(factor=0.6)
        g = top.row(align=True)
        locks = context.window_manager.b4d_axis
        for i, letter in enumerate(("X", "Y", "Z")):
            b = g.row(align=True)
            b.ui_units_x = 1.6
            iv = icons.icon("axis_" + letter.lower(), "axis")        # the letter with its axis colour under it
            o = b.operator("blenda4d.axis_lock", text="" if iv else letter, depress=locks[i], **({"icon_value": iv} if iv else {}))
            o.axis = i
        g.prop(context.scene.transform_orientation_slots[0], "type", text="", icon_only=True)
        top.separator(factor=0.6)
        g = top.row(align=True)
        mode = context.mode
        sel = context.tool_settings.mesh_select_mode if mode == "EDIT_MESH" else (False, False, False)
        _palette_button(g, "blenda4d.set_mode", "VERTEXSEL", depress=sel[0], mode="POINTS")
        _palette_button(g, "blenda4d.set_mode", "OBJECT_DATAMODE", depress=(mode == "OBJECT"), mode="MODEL")
        _palette_button(g, "blenda4d.set_mode", "FACESEL", depress=sel[2], mode="POLYGONS")
        _palette_button(g, "blenda4d.set_mode", "EDGESEL", depress=sel[1], mode="EDGES")
        top.separator(factor=0.6)
        from . import topbar
        if topbar.registered():          # Axis, Snapping, Workplane, Soft Selection, Symmetry, Solo, Render (topbar.py)
            topbar.draw(top, context)
        end = whole.row(align=True)
        end.alignment = "RIGHT"
        end.scale_y = 1.5
        end.scale_x = 1.5
        g = end.row(align=True)
        _palette_button(g, "blenda4d.toggle_column", "MATERIAL", depress=bool(roles.areas(screen, "MATERIALS")), name="MATERIALS")
        _palette_button(g, "screen.userpref_show", "PREFERENCES")


MODES_TOOLS = ("builtin.select_box", "builtin.move", "builtin.rotate", "builtin.scale", None, "builtin.extrude_region",
               "builtin.inset_faces", "builtin.bevel", None, "builtin.pen", "builtin.draw", "builtin.knife", None,
               "builtin.annotate", "builtin.measure", "builtin.cursor")
TOOL_ICONS = {"builtin.select_box": "ops.generic.select_box", "builtin.move": "ops.transform.translate",
              "builtin.rotate": "ops.transform.rotate", "builtin.scale": "ops.transform.resize",
              "builtin.extrude_region": "ops.mesh.extrude_region_move", "builtin.inset_faces": "ops.mesh.inset",
              "builtin.bevel": "ops.mesh.bevel", "builtin.pen": "ops.curve.pen", "builtin.draw": "ops.curve.draw",
              "builtin.knife": "ops.mesh.knife_tool", "builtin.annotate": "ops.gpencil.draw",
              "builtin.measure": "ops.view3d.ruler", "builtin.cursor": "ops.generic.cursor"}


CREATE_SCALE = 1.35          # Blender's 16 px icons: shorter buttons, more zoom (build.TOOL_ZOOM) = larger icons


def _column(layout, scale=1.9):
    col = layout.column(align=True)
    col.scale_y = scale
    col.scale_x = scale
    return col


class BLENDA4D_PT_modes(roles.RolePanel, bpy.types.Panel):
    bl_label = "Tools"
    role = "MODES"

    def draw(self, context):
        col = _column(self.layout)
        col.operator("view3d.zoom_border", text="", icon="VIEWZOOM")
        tool = active_tool(context)
        for t in MODES_TOOLS:
            if t is None:
                col.separator(factor=1.2)
                continue
            iv = icons.any_icon(TOOL_ICONS.get(t, "")) or tool_icon(TOOL_ICONS.get(t, ""))   # tinted accent, else Blender's
            op = col.operator("wm.tool_set_by_id", text="", icon_value=iv, depress=(tool == t))
            op.name, op.space_type = t, "VIEW_3D"          # the tool belongs to the viewport, not this panel


def _p(label, icon, kind):
    return (label, icon, "blenda4d.add_primitive", {"kind": kind})


# The create column: each entry is one button; a group's button runs its current member on a click and opens the
# whole group on press-and-hold (Blender's hold-menu button, with its corner triangle). Members with no operator yet
# are listed greyed. Picking a member from the menu makes it the group's button.
CREATE_GROUPS = (
    ("null", [("Null", "EMPTY_AXIS", "object.empty_add", {"type": "PLAIN_AXES"})]),
    ("splines", [("Bezier Curve", "CURVE_BEZCURVE", "curve.primitive_bezier_curve_add", {}),
                 ("Circle", "CURVE_BEZCIRCLE", "curve.primitive_bezier_circle_add", {}),
                 ("NURBS Curve", "CURVE_NCURVE", "curve.primitive_nurbs_curve_add", {}),
                 ("NURBS Circle", "CURVE_NCIRCLE", "curve.primitive_nurbs_circle_add", {}),
                 ("Path", "CURVE_PATH", "curve.primitive_nurbs_path_add", {})]),
    ("shapes", [_p("Cube", "MESH_CUBE", "cube"), _p("Cylinder", "MESH_CYLINDER", "cylinder"), _p("Plane", "MESH_PLANE", "plane"),
                _p("Cyc Wall", "MESH_GRID", "cyc"), _p("Disc", "MESH_CIRCLE", "disc"), _p("Sphere", "MESH_UVSPHERE", "sphere"),
                _p("Capsule", "MESH_CAPSULE", "capsule"), _p("Cone", "MESH_CONE", "cone"), _p("Figure", "ARMATURE_DATA", "figure"),
                _p("Landscape", "RNDCURVE", "landscape"), _p("Oil Tank", "MESH_CAPSULE", "oiltank"), _p("Pyramid", "MESH_CONE", "pyramid"),
                _p("Platonic", "MESH_ICOSPHERE", "platonic"), _p("Tube", "MESH_CYLINDER", "tube"), _p("Torus", "MESH_TORUS", "torus"),
                _p("Bezier Patch", "SURFACE_NSURFACE", "bezier"), _p("Relief", "IMAGE_DATA", "relief")]),
    ("text", [("Text", "OUTLINER_OB_FONT", "object.text_add", {})]),
    None,
    ("generators", [(n, i, None, {}) for n, i in (("Subdivision Surface", "MOD_SUBSURF"), ("Extrude", "MOD_SOLIDIFY"),
                    ("Lathe", "MOD_SCREW"), ("Loft", "MOD_SKIN"), ("Sweep", "MOD_CURVE"), ("Boolean", "MOD_BOOLEAN"),
                    ("Connect", "AUTOMERGE_OFF"), ("Symmetry", "MOD_MIRROR"), ("Instance", "OUTLINER_OB_GROUP_INSTANCE"),
                    ("Array", "MOD_ARRAY"), ("Remesh", "MOD_REMESH"), ("Reduce Polygons", "MOD_DECIM"),
                    ("Metaball", "META_BALL"))]),
    ("volume", [(n, i, None, {}) for n, i in (("Volume Builder", "VOLUME_DATA"), ("Volume Mesher", "MOD_VOLUME_TO_MESH"))]),
    ("moclone", [(n, i, None, {}) for n, i in (("Cloner", "MOD_ARRAY"), ("Matrix", "LIGHTPROBE_VOLUME"), ("Fracture", "MOD_EXPLODE"),
                 ("Voronoi Fracture", "MOD_EXPLODE"), ("Tracer", "CURVE_PATH"))]),
    None,
    ("deformers", [(n, i, None, {}) for n, i in (("Bend", "MOD_SIMPLEDEFORM"), ("Bulge", "MOD_CAST"), ("Shear", "MOD_SIMPLEDEFORM"),
                   ("Taper", "MOD_SIMPLEDEFORM"), ("Twist", "MOD_SIMPLEDEFORM"), ("Lattice", "MOD_LATTICE"),
                   ("Shrinkwrap", "MOD_SHRINKWRAP"), ("Smooth", "MOD_SMOOTH"), ("Displace", "MOD_DISPLACE"), ("Wave", "MOD_WAVE"))]),
    ("effectors", [(n, i, None, {}) for n, i in (("Random Effector", "MOD_NOISE"), ("Delay Effector", "IPO_EASE_IN_OUT"),
                   ("Step Effector", "IPO_CONSTANT"), ("Target Effector", "CON_TRACKTO"), ("Time Effector", "PREVIEW_RANGE"))]),
    None,
    ("fields", [(n, i, None, {}) for n, i in (("Linear Field", "IPO_LINEAR"), ("Spherical Field", "MESH_UVSPHERE"),
                ("Box Field", "MESH_CUBE"), ("Random Field", "RNDCURVE"))]),
    None,
    ("environment", [(n, i, None, {}) for n, i in (("Sky", "WORLD"), ("Floor", "MESH_PLANE"), ("Background", "IMAGE_BACKGROUND"))]),
    ("camera", [("Camera", "OUTLINER_OB_CAMERA", "object.camera_add", {})]),
    ("lights", [("Area Light", "LIGHT_AREA", "object.light_add", {"type": "AREA"}),
                ("Point Light", "LIGHT_POINT", "object.light_add", {"type": "POINT"}),
                ("Spot Light", "LIGHT_SPOT", "object.light_add", {"type": "SPOT"}),
                ("Sun Light", "LIGHT_SUN", "object.light_add", {"type": "SUN"})]),
)
GROUPS = {g[0]: g[1] for g in CREATE_GROUPS if g}
_head = {}                                   # group -> index of the member last picked (shown as the button)


def _run(op, props):
    mod, fn = op.split(".")
    getattr(getattr(bpy.ops, mod), fn)("INVOKE_DEFAULT", **props)


class BLENDA4D_OT_create(bpy.types.Operator):
    bl_idname = "blenda4d.create"
    bl_label = "Create"
    bl_options = {"REGISTER", "UNDO"}
    group: bpy.props.StringProperty(options={"SKIP_SAVE"})
    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        members = GROUPS.get(props.group, [])
        i = props.index if props.index >= 0 else _head.get(props.group, 0)
        if not members:
            return ""
        tip = members[min(i, len(members) - 1)][0]
        return tip + ("\nPress and hold for more" if len(members) > 1 and props.index < 0 else "")

    def execute(self, context):
        members = GROUPS.get(self.group)
        if not members:
            return {"CANCELLED"}
        i = self.index if self.index >= 0 else _head.get(self.group, 0)
        label, icon, op, props = members[min(i, len(members) - 1)]
        if op is None:
            self.report({"INFO"}, label + ": not available yet")
            return {"CANCELLED"}
        if self.index >= 0:
            _head[self.group] = self.index
        _run(op, props)
        return {"FINISHED"}


def _group_menu(group):
    idname = "BLENDA4D_MT_create_" + group

    def draw(self, context):
        for i, (label, icon, op, props) in enumerate(GROUPS[group]):
            row = self.layout.row()
            row.enabled = op is not None
            o = row.operator("blenda4d.create", text=label, **icons.kw(icon, group))
            o.group, o.index = group, i
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": group.title(), "draw": draw})


GROUP_MENUS = [_group_menu(g) for g in GROUPS]


class BLENDA4D_PT_create(roles.RolePanel, bpy.types.Panel):
    bl_label = "Create"
    role = "CREATE"

    def draw(self, context):
        col = _column(self.layout, CREATE_SCALE)
        for g in CREATE_GROUPS:
            if g is None:
                col.separator(factor=0.8)
                continue
            name, members = g
            label, icon, op, props = members[min(_head.get(name, 0), len(members) - 1)]
            cell = col.row(align=True)
            cell.active = op is not None                   # nothing behind it yet: shown dimmed, menu still opens
            if len(members) > 1:
                o = cell.operator_menu_hold("blenda4d.create", text="", menu="BLENDA4D_MT_create_" + name, **icons.kw(icon, name))
            else:
                o = cell.operator("blenda4d.create", text="", **icons.kw(icon, name))
            o.group = name


classes = (BLENDA4D_OT_set_mode, BLENDA4D_OT_shading, BLENDA4D_OT_overlay, BLENDA4D_OT_axis_lock, BLENDA4D_OT_toggle_column,
           BLENDA4D_OT_create, *GROUP_MENUS, BLENDA4D_PT_doc_tabs, BLENDA4D_PT_palette, BLENDA4D_PT_modes, BLENDA4D_PT_create)


def register():
    icons.register()
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.b4d_axis = bpy.props.BoolVectorProperty(size=3, default=(True, True, True))
    override()


def unregister():
    restore()
    del bpy.types.WindowManager.b4d_axis
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    icons.unregister()
