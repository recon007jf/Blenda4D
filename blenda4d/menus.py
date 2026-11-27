# SPDX-License-Identifier: GPL-3.0-or-later
"""Blenda's menus, drawn with Blender's own menu widgets.

A menu is a list of items: (label, operator, {props}, icon) runs a Blender or Blenda operator; (label, None, ...)
is shown greyed (nothing behind it yet); "-" is a separator; ("menu", label, idname) opens a sub-menu (Blender's
own lists such as Open Recent and Import are used as they are, being lists of files and formats, not layout)."""
import math

import bpy

SEP = "-"


def item(label, op=None, icon="NONE", **props):
    return (label, op, props, icon)


def sub(label, idname, icon="NONE"):
    return ("menu", label, idname, icon)


MENU_ICON_SCALE = 0.7      # Blender draws a tool shape larger than a menu row; its menu copy is drawn this much smaller
_menu_icons = {}


def _shape_file(name, model_tool):
    """(path of the tool shape's triangles, whether Blender's accents need Blenda's colours) or (None, False)."""
    import os
    from . import icons as _icons, modeltools
    try:
        own = next((f for f in os.listdir(_icons.DIR) if f.endswith(".dat") and f.split("__")[0] == name), None)
    except OSError:
        own = None
    if own:
        return os.path.join(_icons.DIR, own), False
    return modeltools.blender_icon_file(name), model_tool


def menu_icon(name, model_tool=False):
    """icon_value of a tool shape redrawn at a menu row's size: the same triangles, scaled toward the left middle of
    the square Blender draws them in, so they line up with the menu's other icons and leave the label alone. 0 when
    the shape can't be read."""
    key = (name, model_tool)
    if key not in _menu_icons:
        iv = 0
        path, recol = _shape_file(name, model_tool)
        try:
            with open(path, "rb") as f:
                b = f.read()
            if b[:3] == b"VCO":
                w, h = b[4] or 256, b[5] or 256
                n = (len(b) - 8) // 18
                co = bytearray(b[8:8 + n * 6])
                k = MENU_ICON_SCALE
                for i in range(0, len(co), 2):
                    co[i] = min(255, round(co[i] * k))
                    co[i + 1] = min(255, round(co[i + 1] * k + h * (1 - k) / 2))
                cols = b[8 + n * 6:8 + n * 18]
                if recol:
                    from . import modeltools
                    cols = modeltools.recolour(cols)
                iv = bpy.app.icons.new_triangles((w, h), bytes(co), cols)
        except (OSError, TypeError, ValueError):
            iv = 0
        _menu_icons[key] = iv
    return _menu_icons[key]


def draw_items(layout, items):
    for it in items:
        if it == SEP:
            layout.separator()
            continue
        if it[0] == "menu":
            layout.menu(it[2], text=it[1], icon=it[3])
            continue
        label, op, props, icon = it
        if op == "blenda4d.check_updates":                 # found a newer version: the item installs it
            from . import updates
            new = updates.available()
            if new:
                layout.operator("blenda4d.update", text=f"Update Blenda 4D to {new}", icon="IMPORT")
                continue
        if op is None:
            col = layout.column()
            col.enabled = False
            col.operator("blenda4d.noop", text=label, icon=icon)
            continue
        if isinstance(icon, str) and icon.startswith("ops."):     # one of Blender's tool icons, as in the tool column
            from . import bars, icons as _icons
            from . import modeltools
            iv = menu_icon(icon, op == "blenda4d.model_tool")
            if not iv:
                iv = _icons.tool_shape(icon) or (modeltools.tool_icon(icon) if op == "blenda4d.model_tool" else 0) or bars.tool_icon(icon)
            if iv and op == "wm.tool_set_by_id":          # Blender widens a tool switch's icon slot: go through our own
                op = "blenda4d.menu_tool"                    # operator so the row lines up with the menu's others
            o = layout.operator(op, text=label, icon_value=iv) if iv else layout.operator(op, text=label)
        else:
            o = layout.operator(op, text=label, icon=icon)
        for k, v in props.items():
            try:
                setattr(o, k, v)
            except (AttributeError, TypeError):
                pass


class BLENDA4D_OT_title(bpy.types.Operator):
    """A tab's name (the open file, a manager): it shows where you are; clicking it does nothing"""
    bl_idname = "blenda4d.title"
    bl_label = "Title"
    bl_options = {"INTERNAL"}
    what: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return properties.what or "Where you are"

    def execute(self, context):
        return {"CANCELLED"}


class BLENDA4D_OT_noop(bpy.types.Operator):
    bl_idname = "blenda4d.noop"
    bl_label = "Not available yet"
    bl_description = "Not available yet"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        return {"CANCELLED"}


def _m(label, which, icon):
    """A modeling tool or command (modeltools.py)."""
    return item(label, "blenda4d.model_tool", icon, which=which)


MAIN = {
    "File": [item("New", "wm.read_homefile", "FILE_NEW"), item("Open...", "wm.open_mainfile", "FILE_FOLDER"),
             sub("Open Recent", "TOPBAR_MT_file_open_recent"), SEP,
             item("Save", "wm.save_mainfile", "FILE_TICK"), item("Save As...", "wm.save_as_mainfile"),
             item("Save Copy...", "wm.save_as_mainfile", copy=True), item("Revert", "wm.revert_mainfile"), SEP,
             sub("Import", "TOPBAR_MT_file_import", "IMPORT"), sub("Export", "TOPBAR_MT_file_export", "EXPORT"), SEP,
             item("Quit", "wm.quit_blender", "QUIT")],
    "Edit": [item("Undo", "ed.undo", "LOOP_BACK"), item("Redo", "ed.redo", "LOOP_FORWARDS"),
             item("Undo History...", "ed.undo_history"), SEP,
             item("Copy", "blenda4d.copy", "COPYDOWN"), item("Paste", "blenda4d.paste", "PASTEDOWN"),
             item("Delete", "object.delete", "X"), SEP,
             item("Select All", "object.select_all", action="SELECT"), item("Deselect All", "object.select_all", action="DESELECT"),
             SEP, item("Preferences...", "screen.userpref_show", "PREFERENCES")],
    "Create": [item("Cube", "blenda4d.add_primitive", "MESH_CUBE", kind="cube"), item("Sphere", "blenda4d.add_primitive", "MESH_UVSPHERE", kind="sphere"),
               item("Cylinder", "blenda4d.add_primitive", "MESH_CYLINDER", kind="cylinder"), item("Cone", "blenda4d.add_primitive", "MESH_CONE", kind="cone"),
               item("Torus", "blenda4d.add_primitive", "MESH_TORUS", kind="torus"), item("Plane", "blenda4d.add_primitive", "MESH_PLANE", kind="plane"),
               item("Disc", "blenda4d.add_primitive", "MESH_CIRCLE", kind="disc"), item("Pyramid", "blenda4d.add_primitive", "MESH_CONE", kind="pyramid"),
               item("Tube", "blenda4d.add_primitive", "MESH_CYLINDER", kind="tube"), item("Capsule", "blenda4d.add_primitive", "MESH_CAPSULE", kind="capsule"),
               item("Oil Tank", "blenda4d.add_primitive", "MESH_CAPSULE", kind="oiltank"), item("Platonic", "blenda4d.add_primitive", "MESH_ICOSPHERE", kind="platonic"),
               item("Landscape", "blenda4d.add_primitive", "RNDCURVE", kind="landscape"), item("Relief", "blenda4d.add_primitive", "IMAGE_DATA", kind="relief"),
               item("Figure", "blenda4d.add_primitive", "ARMATURE_DATA", kind="figure"), item("Bezier", "blenda4d.add_primitive", "SURFACE_NSURFACE", kind="bezier"),
               item("Cyc Wall", "blenda4d.add_primitive", "MESH_GRID", kind="cyc"), SEP,
               item("Spline", "curve.primitive_bezier_curve_add", "CURVE_BEZCURVE"), item("Circle", "curve.primitive_bezier_circle_add", "CURVE_BEZCIRCLE"),
               item("Text", "object.text_add", "OUTLINER_OB_FONT"), SEP,
               item("Null", "object.empty_add", "OUTLINER_OB_EMPTY"), item("Camera", "blenda4d.add_camera", "OUTLINER_OB_CAMERA"),
               item("Light", "object.light_add", "OUTLINER_OB_LIGHT", type="AREA")],
    "Modes": [item("Model", "object.mode_set", "OBJECT_DATAMODE", mode="OBJECT"), item("Points", "blenda4d.set_mode", "VERTEXSEL", mode="POINTS"),
              item("Edges", "blenda4d.set_mode", "EDGESEL", mode="EDGES"), item("Polygons", "blenda4d.set_mode", "FACESEL", mode="POLYGONS"),
              SEP, item("Model / Edit Toggle", "object.editmode_toggle", "EDITMODE_HLT")],
    "Select": [item("Select All", "object.select_all", action="SELECT"), item("Deselect All", "object.select_all", action="DESELECT"),
               item("Invert Selection", "object.select_all", action="INVERT"), SEP,
               item("Live Selection", "wm.tool_set_by_id", "ops.generic.select_circle", name="builtin.select_circle"),
               item("Rectangle Selection", "wm.tool_set_by_id", "ops.generic.select_box", name="builtin.select_box"),
               item("Lasso Selection", "wm.tool_set_by_id", "ops.generic.select_lasso", name="builtin.select_lasso"), SEP,
               item("Phong Break Selection", "blenda4d.phong_break_selection")],
    "Tools": [item("Move", "wm.tool_set_by_id", "ops.transform.translate", name="builtin.move"),
              item("Scale", "wm.tool_set_by_id", "ops.transform.resize", name="builtin.scale"),
              item("Rotate", "wm.tool_set_by_id", "ops.transform.rotate", name="builtin.rotate"), SEP,
              item("Measure", "wm.tool_set_by_id", "ops.view3d.ruler", name="builtin.measure")],
    "Spline": [item("Pen", "wm.tool_set_by_id", "ops.curve.pen", name="builtin.pen"),
               item("Sketch", "wm.tool_set_by_id", "ops.curve.draw", name="builtin.draw")],
    "Mesh": [item("Make Editable", "blenda4d.make_editable", "MESH_DATA"), item("Current State to Object", "blenda4d.current_state", "FREEZE"), SEP,
             item("Extrude", "wm.tool_set_by_id", "ops.mesh.extrude_region_move", name="builtin.extrude_region"),
             item("Inset", "wm.tool_set_by_id", "ops.mesh.inset", name="builtin.inset_faces"),
             item("Bevel", "wm.tool_set_by_id", "ops.mesh.bevel", name="builtin.bevel"),
             item("Loop Cut", "wm.tool_set_by_id", "ops.mesh.loopcut_slide", name="builtin.loop_cut"),
             item("Knife", "wm.tool_set_by_id", "ops.mesh.knife_tool", name="builtin.knife"),
             item("Polygon Pen", "wm.tool_set_by_id", "ops.mesh.polybuild_hover", name="builtin.poly_build"),
             item("Bridge", "mesh.bridge_edge_loops", "LINKED"),
             item("Move Along Normal", "blenda4d.move_along_normal", "ops.transform.shrink_fatten"), SEP,
             item("Edge to Spline", "blenda4d.edge_to_spline", "CURVE_DATA"), SEP,
             _m("Plane Cut", "builtin.bisect", "ops.mesh.bisect"), _m("Offset Edge Loop Cut", "builtin.offset_edge_loop_cut", "ops.mesh.offset_edge_loops_slide"),
             _m("Spin", "builtin.spin", "ops.mesh.spin"), _m("Smooth", "builtin.smooth", "ops.mesh.vertices_smooth"),
             _m("Edge Slide", "builtin.edge_slide", "ops.transform.edge_slide"), _m("Vertex Slide", "builtin.vertex_slide", "ops.transform.vert_slide"),
             _m("Shear", "builtin.shear", "ops.transform.shear"), _m("To Sphere", "builtin.to_sphere", "ops.transform.tosphere"),
             _m("Rip", "builtin.rip_region", "ops.mesh.rip"), SEP,
             _m("Close Polygon Hole", "mesh.edge_face_add", "SNAP_FACE"), _m("Weld", "mesh.merge:CENTER", "AUTOMERGE_ON"),
             _m("Optimize", "mesh.remove_doubles", "AUTOMERGE_OFF"), _m("Subdivide", "mesh.subdivide", "MOD_SUBSURF"),
             _m("Triangulate", "mesh.quads_convert_to_tris", "MOD_TRIANGULATE"), _m("Untriangulate", "mesh.tris_convert_to_quads", "MESH_GRID")],
    "Volume": [item("Volume Builder", "blenda4d.add_kind", "VOLUME_DATA", kind="volume_builder"),
               item("Volume Mesher", "blenda4d.add_kind", "MESH_DATA", kind="volume_mesher")],
    "MoClone": [item("Cloner", "blenda4d.add_kind", "MOD_ARRAY", kind="cloner"), item("Matrix", "blenda4d.add_kind", "LIGHTPROBE_VOLUME", kind="matrix"), item("Fracture", "blenda4d.add_kind", "MOD_EXPLODE", kind="fracture"), item("Voronoi Fracture", "blenda4d.add_kind", "MOD_EXPLODE", kind="voronoi"), SEP,
                item("MoText", "blenda4d.add_kind", "OUTLINER_OB_FONT", kind="motext"), item("MoInstance", "blenda4d.add_kind", "TRACKING_BACKWARDS", kind="moinstance"), item("MoSpline", "blenda4d.add_kind", "OUTLINER_OB_CURVES", kind="mospline"),
                item("Tracer", "blenda4d.add_kind", "CURVE_PATH", kind="tracer"), SEP,
                item("PolyFX", "blenda4d.add_kind", "MOD_TRIANGULATE", kind="polyfx"), item("MoExtrude", "blenda4d.add_kind", "MOD_SOLIDIFY", kind="moextrude"), SEP, sub("Effectors", "BLENDA4D_MT_fx_add", "FORCE_TURBULENCE"), sub("Fields", "BLENDA4D_MT_field_add", "SPHERE")],
    "Character": [item("Joint", "object.armature_add", "BONE_DATA")],
    "Animate": [item("Record Active Objects", "blenda4d.tl_record", "KEYFRAME_HLT"), item("Autokeying", "blenda4d.tl_autokey", "REC"),
                item("Delete Keyframes", "anim.keyframe_delete_v3d", "X"), SEP,
                item("Play Forwards / Stop", "screen.animation_play", "PLAY"), item("Go to Start", "blenda4d.tl_go", "REW", to="START"),
                item("Go to Previous Key", "blenda4d.tl_go", "PREV_KEYFRAME", to="PREV_KEY"), item("Go to Previous Frame", "blenda4d.tl_go", "FRAME_PREV", to="PREV"),
                item("Go to Next Frame", "blenda4d.tl_go", "FRAME_NEXT", to="NEXT"), item("Go to Next Key", "blenda4d.tl_go", "NEXT_KEYFRAME", to="NEXT_KEY"),
                item("Go to End", "blenda4d.tl_go", "FF", to="END")],
    "Simulate": [item("Rigid Body", "rigidbody.object_add"), item("Cloth", "object.modifier_add", type="CLOTH")],
    "Tracker": [item("Motion Tracker")],
    "Render": [item("Render View", "blenda4d.render_still", "RENDER_STILL"), item("Render to Render Viewer", "blenda4d.render", "RENDER_RESULT"),
               item("Render Animation", "blenda4d.render", "RENDER_ANIMATION", animation=True), SEP,
               item("Render Viewer", "blenda4d.render_viewer", "IMAGE"), item("Render Settings...", "blenda4d.render_settings", "SCENE"), SEP],
    "Add-ons": [item("Get Extensions...", "screen.userpref_show", "PLUGIN", section="EXTENSIONS"),
                item("Add-on Preferences...", "screen.userpref_show", "PREFERENCES", section="ADDONS"),
                item("Check for Blenda 4D Updates...", "blenda4d.check_updates", "FILE_REFRESH"), SEP,
                item("Add Menu Items...", "blenda4d.addons_menu", "ADD", menu="BLENDA4D_MT_addons_add"),
                item("Object Menu Items...", "blenda4d.addons_menu", "OBJECT_DATA", menu="BLENDA4D_MT_addons_object"),
                item("Add-on Panels", "blenda4d.addon_panels", "MENU_PANEL"),
                item("Blender Properties...", "blenda4d.blender_properties", "PROPERTIES")],
    "Window": [item("Material Manager", "blenda4d.toggle_column", "MATERIAL", name="MATERIALS"),
               item("Asset Browser", "blenda4d.toggle_column", "ASSET_MANAGER", name="ASSETS"), SEP,
               item("Timeline (Dope Sheet)", "blenda4d.tl_dock", "ACTION", mode="KEYS"), item("Timeline (F-Curves)", "blenda4d.tl_dock", "FCURVE", mode="CURVES"), SEP,
               sub("Layouts", "BLENDA4D_MT_layouts", "WORKSPACE"), SEP,
               item("New Window", "wm.window_new"), item("Toggle Full Screen", "wm.window_fullscreen_toggle")],
    "Help": [item("Blender Manual", "wm.url_open_preset", "HELP", type="MANUAL"), item("About Blender", "wm.splash_about", "BLENDER")],
}



MENU_TIPS = {
    "main": {"File": "Open, save, import and export scenes", "Edit": "Undo, redo, copy, paste and the preferences",
             "Create": "Add objects: primitives, splines, generators, deformers, lights, cameras and more",
             "Modes": "Work on whole objects, or on their points, edges or polygons",
             "Select": "Selection tools and commands", "Tools": "Move, rotate, scale and measure",
             "Spline": "Draw and edit splines", "Mesh": "Modelling tools for polygon objects",
             "Volume": "Volume objects", "MoClone": "Clone objects in arrays, grids and patterns",
             "Character": "Joints for rigging characters", "Animate": "Keyframes for the selected objects",
             "Simulate": "Physics: rigid bodies and cloth", "Tracker": "Motion tracking",
             "Render": "Render a still or an animation, and the render settings",
             "Add-ons": "Commands from your other Blender add-ons", "Window": "Open editors and windows",
             "Help": "Manuals, support and information about Blenda 4D and Blender"},
    "om": {"File": "Bring in objects from other files", "Edit": "Undo, copy, paste, rename and delete objects",
           "View": "Fold or unfold the object list", "Object": "Group, duplicate or make objects editable",
           "Tags": "Add tags (material, smoothing) to the selected objects", "Bookmarks": "Saved places in the list"},
    "am": {"Mode": "What the Attribute Manager shows", "Edit": "Copy and paste settings",
           "User Data": "Your own settings added to an object"},
    "tl": {"Create": "Make keys and markers", "Edit": "Copy, paste, delete and select keys", "Filter": "Which tracks are listed",
           "View": "Dope Sheet or F-Curves, and the list", "Frame": "Which frames are in view", "Functions": "Tidy tracks and keys",
           "Key": "How the selected keys are interpolated", "F-Curve": "The selected keys' tangents", "Marker": "Markers on the ruler"},
    "mm": {"Create": "Make new materials", "Edit": "Copy, paste and delete materials", "View": "How materials are listed",
           "Select": "Select materials", "Material": "Commands for the selected material"},
    "ab": {"Create": "Add assets", "Edit": "Edit assets", "View": "How assets are listed", "Libraries": "Asset libraries"},
}


def _make(label, items, prefix):
    idname = f"BLENDA4D_MT_{prefix}_" + "".join(c for c in label.lower() if c.isalnum())
    tip = MENU_TIPS.get(prefix, {}).get(label, f"{label} commands")

    def draw(self, context):
        draw_items(self.layout, items)
        from . import kinds
        extra = kinds.menu_items(label)
        if extra:
            self.layout.separator()
            from . import icons
            for text, kind, icon in extra:
                kw = icons.kw(icon, "environment") if icon == "WORLD" else {"icon": icon}     # the Sky's own dome
                self.layout.operator("blenda4d.add_kind", text=text, **kw).kind = kind
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": label, "bl_description": tip, "draw": draw})


MAIN_CLASSES = [_make(k, v, "main") for k, v in MAIN.items()]
from .viewmenus import OPS as VIEW_OPS, VIEW_CLASSES  # noqa: E402  the viewport's own menus (viewmenus.py)


def _text_width(text):
    """A widget label's width in pixels, as Blender's layout measures it."""
    import blf
    prefs = bpy.context.preferences
    blf.size(0, prefs.ui_styles[0].widget.points * prefs.system.ui_scale)
    return blf.dimensions(0, text)[0]


def _menu_px(name):
    """A panel menu button's width in pixels: its text plus Blender's 1.25 units of padding (text_pad_compact in
    interface_layout.cc)."""
    return _text_width(name) + math.ceil(20 * bpy.context.preferences.system.ui_scale * 1.25)


def fit_count(names, avail):
    """How many menus fit side by side in `avail` pixels, leaving room for the » menu when some do not fit."""
    more = 20 * bpy.context.preferences.system.ui_scale * 1.35          # the icon-only » button
    widths = [_menu_px(n) for n in names]
    if sum(widths) <= avail:
        return len(names)
    used, n = more, 0
    for w in widths:
        if used + w > avail:
            break
        used += w
        n += 1
    return n


_overflow = {}               # first menu's idname -> the menus its » lists, set each time the bar draws
_more = {}                   # first menu's idname -> that bar's » menu class


def make_more(classes, name=None):
    """The » menu for a bar of these menus (register the class it returns with the bar's menus)."""
    key = classes[0].bl_idname
    name = name or key.rpartition("_MT_")[2]

    def draw(self, context):
        for cls in _overflow.get(key, ()):
            self.layout.menu(cls.bl_idname, text=cls.bl_label)

    cls = type("BLENDA4D_MT_more_" + name, (bpy.types.Menu,),
               {"bl_idname": "BLENDA4D_MT_more_" + name, "bl_label": "More",
                "bl_description": "The menus that do not fit in the bar", "draw": draw})
    _more[key] = cls
    return cls


def menu_bar(layout, classes, labels=None, avail=None):
    """The menus side by side. With `avail` (pixels), menus that would not fit go into a » menu at the end, as the
    names are never cut short."""
    shown = [c for c in classes if labels is None or c.bl_label in labels]
    n = fit_count([c.bl_label for c in shown], avail) if avail else len(shown)
    row = layout.row(align=True)
    row.alignment = "LEFT"
    try:
        row.emboss = "PULLDOWN_MENU"
    except (AttributeError, TypeError):
        pass
    for cls in shown[:n]:
        row.menu(cls.bl_idname, text=cls.bl_label)
    if n < len(shown):
        key = classes[0].bl_idname
        _overflow[key] = shown[n:]
        if key in _more:
            row.menu(_more[key].bl_idname, text="", icon="RIGHTARROW_THIN")
    return row


def panel_width(share=1.0, reserve=0.0):
    """Pixels free for a line of buttons in the current panel: the region less Blender's panel insets, times `share`
    (a split's factor), less `reserve` pixels."""
    region = bpy.context.region
    if region is None:
        return None
    s = bpy.context.preferences.system.ui_scale
    return (region.width - 2 * 8 * s - 4 * s) * share - reserve


def simple_menu(label, items, manager="mgr"):
    """A manager's own menu (Object Manager File / Edit ..., Attribute Manager Mode / Edit ...)."""
    return _make(label, items, manager)


class BLENDA4D_OT_menu_tool(bpy.types.Operator):
    bl_idname = "blenda4d.menu_tool"
    bl_label = "Tool"
    bl_options = {"INTERNAL"}
    name: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, props):
        n = props.name.rpartition(".")[2].replace("_", " ")
        return f"Use the {n} tool in the viewport"

    def execute(self, context):
        from . import topbar
        area, region, _sp = topbar.main_view(context)
        if area is None:
            return {"CANCELLED"}
        with context.temp_override(window=context.window, area=area, region=region):
            return bpy.ops.wm.tool_set_by_id(name=self.name)


classes = (BLENDA4D_OT_title, BLENDA4D_OT_menu_tool, BLENDA4D_OT_noop, *VIEW_OPS, *MAIN_CLASSES, *VIEW_CLASSES, make_more(MAIN_CLASSES), make_more(VIEW_CLASSES))


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
