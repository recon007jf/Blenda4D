# SPDX-License-Identifier: GPL-3.0-or-later
"""Drag and drop from the Material Manager: drag a material onto an object's row in the Object Manager, or onto an
object in the 3D view, to give that object the material.

How it is wired: a CLICK_DRAG keymap item in the Property Editor starts blenda4d.mm_drag while the mouse is in the
Material Manager (the same way the Asset Browser's drag into the viewport and the Object Manager's own re-parent drag
work). The operator finds the material under the press, follows the mouse, and while it is over the Object Manager
highlights the row under it (a draw handler, like the Object Manager's own row highlights). Releasing over a row puts
the material in that object's first slot (a new slot when the object has none); releasing over the 3D view ray-casts
the surface under the mouse (like the Asset Browser's drop) and puts the material on the object hit — the same rule as
Shift-clicking a material in the list.

While the drag runs, the cursor is a + cross (Blender's CROSSHAIR cursor; COPY would be the arrow-with-plus badge, but
Windows renders it as a plain arrow) when the release would land on an object that takes a material, and the stop sign
(STOP) when it would not.
"""

import bpy

from . import managers, matman, roles

LIST_TOP = 4.9          # units from the panel's top to the first material row in the list and layer views (title,
#                         menus, tool row — the same head the icon view's GRID_TOP covers): measured in
#                         tools/tests/matdrag_ui.py


def _row_h(context):
    """Height of one material row in the list and layer views, in pixels: its preview plus the row padding.

    context: the UI context; reads the UI scale, pixel size and the preview-size setting from it.
    Returns the row height in pixels.
    """
    ui = context.preferences.system.ui_scale
    s = max(1.0, min(context.window_manager.b4d_mm_px, 80) / 20)
    return s * 20 * ui + 2 * context.preferences.system.pixel_size


def mat_at(context, x, y, region=None):
    """The material under a point in the Material Manager.

    context: the UI context; the current view (icons, list, layers), preview size and search filter decide the layout.
    x, y: the point in region coordinates (as event.mouse_region_x, event.mouse_region_y).
    region: the Material Manager's window region to map the point through; defaults to context.region.
    Returns the Material under the point, or None on empty space, the head, or outside the list.
    """
    wm = context.window_manager
    region = region or context.region
    if region is None or region.type != "WINDOW":
        return None
    if wm.b4d_mm_view == "ICONS":
        mat, _part = matman.tile_at(context, x, y)
        return mat
    mats = matman.materials(context)
    if not mats:
        return None
    unit = 20 * context.preferences.system.ui_scale
    _vx, vy = region.view2d.region_to_view(x, y)
    down = -vy                                  # view y runs down from 0 at the panel's top
    top = LIST_TOP * unit
    row_h = _row_h(context)
    tex_h = managers.row_height()
    for m in mats:
        h = row_h
        if wm.b4d_mm_view == "LAYERS":          # a layer-view row also holds the material's texture rows
            h += max(1, len(matman._textures(m))) * tex_h
        if top <= down < top + h:
            return m
        top += h
    return None


def _can_take(ob):
    """Whether an object can receive a material at all (its data has a material-slots list).

    ob: the Object to test (None is allowed).
    Returns True when assign() would accept the object; False for None and for objects whose data has no slots
    (lights, cameras, ...).
    """
    return ob is not None and hasattr(getattr(ob, "data", None), "materials")


def assign(ob, mat):
    """Give an object a material: mat goes into its first slot, or a new slot is made when it has none.

    ob: the Object to receive the material (None is allowed and refused).
    mat: the Material to assign (None is allowed and refused).
    Returns True when the material was put on the object, False when the object takes no material.
    """
    if mat is None or not _can_take(ob):
        return False
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    return True


def _region_under(context, match, x, y):
    """The WINDOW region of the first area matching a predicate, under a window position.

    context: the UI context; its window's screen holds the areas to search (a None window gives None).
    match: a predicate area -> bool that picks the areas to search (e.g. roles.role(area) == "OBJECTS").
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns the area's WINDOW region under the point, or None.
    """
    if context.window is None:
        return None
    for area in context.window.screen.areas:
        if not match(area):
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return region
    return None


def _role_under(context, role, x, y):
    """The window region of a role area (e.g. "MATERIALS") under a window position.

    context: the UI context; its window's screen holds the areas to search.
    role: the role the area must have (roles.role(area) == role).
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns the area's WINDOW region under the point, or None.
    """
    return _region_under(context, lambda area: roles.role(area) == role, x, y)


def _om_under(context, x, y):
    """The Object Manager's window region under a window position.

    context: the UI context; its window's screen holds the areas to search.
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns the Object Manager's WINDOW region under the point, or None.
    """
    return _region_under(context, lambda area: roles.role(area) == "OBJECTS", x, y)


def _target(context, event):
    """The object whose Object Manager row is under the mouse.

    context: the UI context; the Object Manager search filter decides which rows exist.
    event: the mouse event; its window position (mouse_x, mouse_y) is mapped to a row.
    Returns the row object's name, or "" when the mouse is over no row.
    """
    region = _om_under(context, event.mouse_x, event.mouse_y)
    if region is None:
        return ""
    rows = managers.visible_rows(context)
    i = managers.row_at(context, region, event.mouse_y)
    return rows[i][0].name if 0 <= i < len(rows) else ""


def _view_under(context, x, y):
    """A 3D view's window region under a window position.

    context: the UI context; its window's screen holds the areas to search.
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns a 3D view's WINDOW region under the point, or None.
    """
    return _region_under(context, lambda area: area.type == "VIEW_3D", x, y)


def _view_target(context, event):
    """The object under the mouse in a 3D view: a ray-cast surface hit, like the Asset Browser's drop.

    context: the UI context; its scene and evaluated depsgraph are used for the ray cast.
    event: the mouse event; its window position (mouse_x, mouse_y) picks the ray.
    Returns the Object hit (the original, not an instance), or None on empty space or outside a 3D view.
    """
    from . import assets
    region = _view_under(context, event.mouse_x, event.mouse_y)
    if region is None:
        return None
    _loc, ob = assets.drop_point(context, region, event.mouse_x, event.mouse_y)
    return ob


class BLENDA4D_OT_mm_drag(bpy.types.Operator):
    bl_idname = "blenda4d.mm_drag"
    bl_label = "Drag Material"
    bl_description = "Drag a material onto an object in the Object Manager or the 3D view to give the object that material"
    bl_options = {"UNDO", "INTERNAL"}
    mat_name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        """The drag starts only while the mouse is in the Material Manager.

        cls: the operator class; context: the UI context whose area must have role "MATERIALS".
        Returns True when the drag may run.
        """
        return roles.role(context.area) == "MATERIALS"

    def invoke(self, context, event):
        """Start the drag from the material under the press.

        context: the UI context; event: the CLICK_DRAG event. CLICK_DRAG invokes on the first move, so the material
        is looked up at the press position (event.mouse_prev_press_x/y), not at the current mouse position.
        Returns {"PASS_THROUGH"} when no material is under the press (the press falls through to a click),
        otherwise {"RUNNING_MODAL"} with the modal handler added and the hand cursor set.
        """
        # CLICK_DRAG invokes on the first move, so the press position is where the material is looked up
        region = _role_under(context, "MATERIALS", event.mouse_prev_press_x, event.mouse_prev_press_y)
        mat = None
        if region is not None:
            mat = mat_at(context, event.mouse_prev_press_x - region.x, event.mouse_prev_press_y - region.y, region)
        if mat is None:
            return {"PASS_THROUGH"}
        self.mat_name = mat.name                # by name: the material could be deleted while dragging
        context.window_manager.b4d_mat_drop = ""
        context.window.cursor_modal_set("HAND")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _end(self, context):
        """Finish the drag: clear the drop highlight, restore the cursor, redraw every area.

        context: the UI context; its window manager holds the drop-target property and its screen the areas.
        """
        context.window_manager.b4d_mat_drop = ""
        context.window.cursor_modal_restore()
        for a in context.window.screen.areas:
            a.tag_redraw()

    def modal(self, context, event):
        """Follow the mouse while dragging.

        context: the UI context; event: the current event. On mouse moves the Object Manager row under the mouse
        is stored in wm.b4d_mat_drop (so the draw handler highlights it) and the cursor is set to a + cross (CROSSHAIR)
        when the release would land on an object that takes a material, to the stop sign (STOP) when it would not. On release
        the material is assigned to that row's object, or to the object under the mouse in a 3D view. ESC, right-click
        and a fresh press cancel.
        Returns {"RUNNING_MODAL"} while the drag continues, {"FINISHED"} after a drop, {"CANCELLED"} otherwise.
        """
        wm = context.window_manager
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            t = _target(context, event)
            if t != wm.b4d_mat_drop:
                wm.b4d_mat_drop = t
                for a in context.window.screen.areas:
                    a.tag_redraw()
            ob = bpy.data.objects.get(t) if t else _view_target(context, event)
            # CROSSHAIR is a clear +; COPY would be the arrow-with-plus badge, but Windows renders it as a plain arrow
            context.window.cursor_modal_set("CROSSHAIR" if _can_take(ob) else "STOP")
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            t = _target(context, event)
            ob = bpy.data.objects.get(t) if t else _view_target(context, event)
            self._end(context)
            if ob is None or not assign(ob, bpy.data.materials.get(self.mat_name)):
                return {"CANCELLED"}
            wm.b4d_material = self.mat_name
            matman._tag_redraw()
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} or (event.type == "LEFTMOUSE" and event.value == "PRESS"):
            self._end(context)                  # a fresh press while dragging: cancel, never stay modal
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


_draw = []


def _draw_drop():
    """Draw handler: highlight in the Object Manager the row a dragged material would land on.

    Takes no arguments (a draw handler); reads bpy.context. Draws nothing unless wm.b4d_mat_drop names a visible
    row, like the Object Manager's own row highlights in managers._draw_rows.
    """
    context = bpy.context
    if roles.role(context.area) != "OBJECTS":
        return
    name = context.window_manager.b4d_mat_drop
    if not name:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    region = context.region
    rows = managers.visible_rows(context)
    i = next((i for i, (ob, _d) in enumerate(rows) if ob.name == name), None)
    if i is None or region is None:
        return
    h = managers.row_height()
    top = region.view2d.view_to_region(0, -(managers.rows_top() + i) * h, clip=False)[1]
    bottom = region.view2d.view_to_region(0, -(managers.rows_top() + i + 1) * h, clip=False)[1]
    c = context.preferences.themes[0].user_interface.wcol_regular.inner_sel
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ADDITIVE")            # lightens the row behind the text instead of covering it
    batch = batch_for_shader(shader, "TRIS", {"pos": [(0, bottom), (region.width, bottom), (region.width, top), (0, top)]},
                             indices=[(0, 1, 2), (0, 2, 3)])
    shader.uniform_float("color", (c[0] * 0.95, c[1] * 0.95, c[2] * 0.95, 1.0))
    batch.draw(shader)
    gpu.state.blend_set("NONE")


_keys = []

classes = (BLENDA4D_OT_mm_drag,)


def register():
    """Register the module: the operator class, the drop-target property, the highlight draw handler and the
    CLICK_DRAG keymap item (called by kinds.register when Blenda mode goes on). Takes no arguments."""
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.b4d_mat_drop = bpy.props.StringProperty(
        description="The Object Manager row a material dragged from the Material Manager would land on")
    _draw.append(bpy.types.SpaceProperties.draw_handler_add(_draw_drop, (), "WINDOW", "POST_PIXEL"))
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES")
        _keys.append((km.name, km.keymap_items.new("blenda4d.mm_drag", "LEFTMOUSE", "CLICK_DRAG").idname))


def unregister():
    """Take everything register() added back out: the keymap item, the draw handler, the property and the class
    (called by kinds.unregister when Blenda mode goes off, so the switch restores everything). No arguments."""
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:                           # looked up fresh: held keymap items can be freed at quit
        for name, idname in _keys:
            km = kc.keymaps.get(name)
            if km is not None:
                for kmi in list(km.keymap_items):
                    if kmi.idname == idname:
                        km.keymap_items.remove(kmi)
    _keys.clear()
    for h in _draw:
        bpy.types.SpaceProperties.draw_handler_remove(h, "WINDOW")
    _draw.clear()
    W = bpy.types.WindowManager
    if hasattr(W, "b4d_mat_drop"):
        delattr(W, "b4d_mat_drop")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
