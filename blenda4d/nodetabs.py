# SPDX-License-Identifier: GPL-3.0-or-later
"""The node tabs (Shading, Geometry Nodes, Compositing): the Node Editor under the viewport, with the list of nodes at
its left and the picked node's settings at its right, and beside the viewport what that work needs: the spreadsheet for
Geometry Nodes, the result for Compositing. All three are Blender's own editors with Blenda's header.

The list is Blender's own Add menu, read from its menus, so it has what this Blender has: click a node and it is put on
the canvas, where there is room. Shading follows the active object's material, or the one clicked in the Material Manager."""
import bpy

from . import nodewin, own_draw, roles

LIST = "ND_LIST"
LIST_PX = 170
NODES = 0.56                 # the share of the viewport's height the Node Editor takes
#            kind: (Blender's node tree, its add menu, the editor beside the viewport, its share of the width)
KINDS = {"SHADER": ("ShaderNodeTree", "NODE_MT_shader_node_add_all", "", 0.0),
         "GEOMETRY": ("GeometryNodeTree", "NODE_MT_geometry_node_add_all", "SPREADSHEET", 0.34),
         "COMPOSITE": ("CompositorNodeTree", "NODE_MT_compositor_node_add_all", "IMAGE_EDITOR", 0.58)}
EMPTY = {"SHADER": "Pick an object, then New", "GEOMETRY": "Pick an object, then New", "COMPOSITE": "Press New to start"}
_open = set()                # the categories that are unfolded
_state = {}                  # node editor area -> {"tree", "ob", "mat"}: what it showed last
_handles = []
_own = {}


# --- the areas --------------------------------------------------------------------------------------------------------
def editor(screen):
    """The Node Editor docked in Blenda's layout."""
    if screen is None or screen.get(nodewin.KEY):
        return None
    return next((a for a in screen.areas if a.type == "NODE_EDITOR"), None)


def beside(screen):
    return [a for a in screen.areas if a.type in {"SPREADSHEET", "IMAGE_EDITOR"}]


def kind_of(screen):
    from . import layouts
    k = layouts.spec_of(screen)["editors"]
    return k if k in KINDS else ""


def docked(context):
    """Is this the Node Editor (or the editor beside the viewport) of one of the node tabs?"""
    s = context.screen
    return s is not None and not s.get(nodewin.KEY) and bool(roles.areas(s, "OBJECTS")) and bool(kind_of(s))


def intact(screen, kind):
    """Are exactly the areas this kind has there?"""
    want = KINDS.get(kind)
    if len([a for a in screen.areas if a.type == "NODE_EDITOR"]) != bool(want) or len(roles.areas(screen, LIST)) != bool(want):
        return False
    side = beside(screen)
    if kind == "UV":                                       # its editor is the UV tab's (uvtab.py)
        return True
    return [a.type for a in side] == ([want[2]] if want and want[2] else [])


def _region(area, kind="WINDOW"):
    if not roles.alive(area):                              # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == kind), None)


def _dress(window, area, kind):
    sp = area.spaces.active
    sp.show_region_header = True
    sp.show_region_toolbar = False
    if area.type == "NODE_EDITOR":
        area.ui_type = KINDS[kind][0]
        sp = area.spaces.active
        sp.show_region_header, sp.show_region_toolbar, sp.show_region_ui = True, False, True
        if kind == "SHADER":
            sp.shader_type = "OBJECT"
        sp.overlay.show_previews = True
        if hasattr(sp.overlay, "preview_shape"):
            sp.overlay.preview_shape = "3D"
        if hasattr(sp.overlay, "show_context_path"):
            sp.overlay.show_context_path = False
        try:                                               # the list has the nodes; Blender's shelf would repeat them
            sp.show_region_asset_shelf = False
        except (AttributeError, TypeError):                # this kind of nodes has none
            pass
    elif area.type == "IMAGE_EDITOR":
        sp.show_region_ui = False
        sp.show_gizmo = False                              # no zoom and pan buttons over the picture
    elif area.type == "SPREADSHEET":
        sp.show_region_ui = False
    head = _region(area, "HEADER")
    if head is not None and head.alignment != "TOP":
        try:
            with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=head):
                bpy.ops.screen.region_flip()
        except RuntimeError:
            pass


def add_steps(window, low, kind, sizes):
    """The area under the viewport becomes the Node Editor with its list; the editor beside the viewport goes in."""
    from . import build
    low.type = "NODE_EDITOR"
    low.ui_type = KINDS[kind][0]
    build.lay_out(window, low)
    _dress(window, low, kind)
    build.lay_out(window, low)
    width = build.px(sizes.get("list", LIST_PX)) + build.EDGE
    side = yield from build.split(window, low, "VERTICAL", min(width, round(low.width * 0.3)), "LEFT")
    yield from build.make_role(window, side, LIST)
    other, share = KINDS[kind][2], sizes.get("beside", KINDS[kind][3])
    if other:
        view = build.biggest_view(window.screen)
        new = yield from build.split(window, view, "VERTICAL", round(view.width * min(0.8, max(0.15, share))), "RIGHT")
        new.type = other
        build.lay_out(window, new)
        _dress(window, new, kind)
    area = editor(window.screen)
    if area is not None:
        _state.pop(area.as_pointer(), None)
        bpy.app.timers.register(lambda: _category(area), first_interval=0.1)


def remove_steps(window):
    from . import build, quadview
    screen = window.screen
    for a in beside(screen):
        yield from build._into_view(window, a)
    area = editor(screen)
    for a in roles.areas(screen, LIST):
        if area is not None:
            yield from quadview._join(window, a, area)
    for a in [a for a in screen.areas if a.type == "NODE_EDITOR"]:
        yield from build._into_view(window, a)


def sizes_of(screen, sizes):
    """The sizes a saved layout keeps."""
    from . import build
    area = editor(screen)
    lists = roles.areas(screen, LIST)
    views = [a for a in screen.areas if a.type == "VIEW_3D"]
    if area is None or not views:
        return
    high = sum(a.height for a in views if abs(a.x - views[0].x) < 8)
    sizes["nodes"] = round((area.height + 1) / max(1, area.height + high + build.EDGE), 3)
    if lists:
        sizes["list"] = round(lists[0].width / build._scale(), 1)
    for a in beside(screen):
        wide = max(v.x + v.width for v in views) - min(v.x for v in views)
        sizes["beside"] = round((a.width + 1) / max(1, a.width + wide + build.EDGE), 3)


def _category(area, tries=[20]):
    """The sidebar opens on Blenda's page."""
    if not roles.alive(area):
        return None
    try:
        side = _region(area, "UI")
        if side is not None and side.width > 1:
            side.active_panel_category = nodewin.CATEGORY
            area.tag_redraw()
            return None
    except (TypeError, ValueError, AttributeError, ReferenceError):
        return None
    return 0.1


# --- what it shows, kept current -----------------------------------------------------------------------------------------
def _material(sp):
    idb = sp.id
    return idb if isinstance(idb, bpy.types.Material) else None


def material_of(screen):
    """The material on the docked Node Editor's canvas."""
    area = editor(screen)
    if area is None:
        return None
    sp = area.spaces.active
    if sp.tree_type != "ShaderNodeTree":
        return None
    if sp.pin and sp.node_tree is not None:
        return next((m for m in bpy.data.materials if m.node_tree == sp.node_tree), None)
    return _material(sp)


def _watch():
    context = bpy.context
    area, window = context.area, context.window
    if area is None or window is None or not docked(context):
        return
    sp, st = area.spaces.active, _state.setdefault(area.as_pointer(), {"tree": None, "ob": "", "mat": None})
    ob = context.view_layer.objects.active
    now = (sp.edit_tree.as_pointer() if sp.edit_tree else 0, ob.name if ob else "", context.window_manager.b4d_material)
    if st["mat"] is None:
        st["ob"], st["mat"] = now[1], now[2]
    if now == (st["tree"], st["ob"], st["mat"]) or st.get("waiting"):
        return
    st["waiting"] = True
    bpy.app.timers.register(lambda: _follow(window, area, st), first_interval=0.0)


def _follow(window, area, st):
    """The material picked in the Material Manager is shown; a canvas with another tree is framed."""
    if not roles.alive(area):
        st["waiting"] = False
        return None
    try:
        sp = area.spaces.active
        ob = window.view_layer.objects.active
        picked = bpy.context.window_manager.b4d_material
        name = ob.name if ob else ""
        if sp.tree_type == "ShaderNodeTree":
            mat = bpy.data.materials.get(picked)
            if name != st["ob"]:
                sp.pin = False
            elif picked != st["mat"] and mat is not None and mat != _material(sp):
                slot = next((i for i, s in enumerate(getattr(ob, "material_slots", ())) if s.material == mat), None) if ob else None
                if slot is not None:
                    sp.pin = False
                    ob.active_material_index = slot
                elif mat.node_tree is not None:            # no object picked that has it: shown all the same
                    sp.pin = True
                    sp.node_tree = mat.node_tree
            shown = material_of(window.screen)
            if shown is not None and shown.node_tree is not None:
                nodewin._previews_on(shown.node_tree)
                nodewin._keep_previews()
        elif sp.pin:
            sp.pin = False
        tree = sp.edit_tree.as_pointer() if sp.edit_tree else 0
        if tree and tree != st["tree"]:
            frame(window, area)
            bpy.app.timers.register(lambda: frame(window, area, sp.tree_type == "ShaderNodeTree"), first_interval=0.6)
        st["tree"], st["ob"], st["mat"] = tree, name, picked
    except (ReferenceError, AttributeError, RuntimeError):
        pass
    finally:
        st["waiting"] = False
    for a in window.screen.areas:
        if roles.role(a) == LIST or a.type == "NODE_EDITOR":
            a.tag_redraw()
    return None


def _ui():
    prefs = bpy.context.preferences.system
    return max(0.5, prefs.ui_scale * prefs.pixel_size)


def _rects(tree, previews):
    """Where the nodes are on the canvas, the preview above a node too."""
    out, s = [], _ui()
    for n in tree.nodes:
        if n.type == "FRAME":
            continue
        loc = getattr(n, "location_absolute", n.location)
        w, h = max(n.width, n.dimensions.x / s), max(40.0, n.dimensions.y / s)
        up = w if previews and getattr(n, "show_preview", False) and not n.hide else 0.0
        out.append((loc.x, loc.y - h, loc.x + w, loc.y + up))
    return out


def frame(window, area, room=False):
    """All the nodes in sight (room: for the previews above them, which Blender's framing leaves out)."""
    if not roles.alive(area):
        return None
    try:
        region = _region(area)
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
            bpy.ops.node.view_all()
            tree = area.spaces.active.edit_tree
            if not room or tree is None or not len(tree.nodes):
                return None
            rects, s = _rects(tree, True), _ui()
            y0, y1 = min(r[1] for r in rects) * s, max(r[3] for r in rects) * s
            v2d = region.view2d
            for _ in range(10):
                low, high = v2d.view_to_region(0, y0, clip=False)[1], v2d.view_to_region(0, y1, clip=False)[1]
                if high - low <= region.height - 24:
                    break
                bpy.ops.view2d.zoom_out()
            low, high = v2d.view_to_region(0, y0, clip=False)[1], v2d.view_to_region(0, y1, clip=False)[1]
            bpy.ops.view2d.pan(deltax=0, deltay=round((low + high - region.height) / 2))
    except (ReferenceError, RuntimeError, TypeError):
        pass
    return None


def _result(context):
    """Compositing: the result beside the viewport is the viewer's picture, or the render."""
    area = context.area
    if area is None or not docked(context) or kind_of(context.screen) != "COMPOSITE":
        return
    sp = area.spaces.active
    if sp.image is None and not _state.get("result") and any(i.type in {"RENDER_RESULT", "COMPOSITING"} for i in bpy.data.images):
        _state["result"] = True

        def put():
            _state["result"] = False
            if not roles.alive(area):
                return None
            try:
                if sp.image is None:
                    sp.image = viewer() or rendered()
                    area.tag_redraw()
            except (ReferenceError, AttributeError):
                pass
            return None
        bpy.app.timers.register(put, first_interval=0.0)


def rendered():
    return next((i for i in bpy.data.images if i.type == "RENDER_RESULT"), None)


def viewer():
    return next((i for i in bpy.data.images if i.type == "COMPOSITING"), None)


# --- the list of nodes: Blender's Add menu, read by drawing it on paper ----------------------------------------------------
class _Props:
    """What a menu sets on the operator it draws."""

    def __init__(self):
        self.__dict__["settings"] = _Settings()
        self.__dict__["use_transform"] = False


class _Settings(list):
    def add(self):
        row = type("Setting", (), {"name": "", "value": ""})()
        self.append(row)
        return row


class _Paper:
    """A layout that writes down what is drawn on it."""

    def __init__(self, out, seen):
        self.out, self.seen = out, seen

    def operator(self, idname, text="", **_kw):
        props = _Props()
        self.out.append(("item", text, idname, props))
        return props

    def menu(self, idname, text="", **_kw):
        cls = getattr(bpy.types, idname, None)
        if cls is None or idname in self.seen:
            return
        sub = []
        _read(cls, sub, self.seen | {idname})
        if sub:
            self.out.append(("menu", text or cls.bl_label, sub))

    def menu_contents(self, idname, **_kw):
        cls = getattr(bpy.types, idname, None)
        if cls is not None and idname not in self.seen:
            _read(cls, self.out, self.seen | {idname})

    def __getattr__(self, name):
        return lambda *a, **k: self


class _Menu:
    def __init__(self, cls, paper):
        self.__dict__.update(_cls=cls, layout=paper)

    def __getattr__(self, name):
        return getattr(self.__dict__["_cls"], name)


def _read(cls, out, seen):
    try:
        cls.draw(_Menu(cls, _Paper(out, seen)), bpy.context)
    except Exception as ex:                                # an add-on's menu that needs a real layout
        if cls.__name__ not in _failed:
            _failed.add(cls.__name__)
            print("Blenda 4D: node menu not read:", cls.__name__, ex)


_failed = set()
_items = {}                  # item id -> (label, operator, props)
_cache = {"key": None, "rows": []}


def catalog(context, area, kind):
    """[(id, depth, title, is a category)] of every node this editor can add."""
    sp = area.spaces.active
    key = (kind, getattr(sp, "shader_type", ""), context.scene.render.engine, sp.edit_tree.as_pointer() if sp.edit_tree else 0,
           tuple(g.name for g in bpy.data.node_groups))
    if _cache["key"] == key:
        return _cache["rows"]
    out, rows = [], []
    with context.temp_override(window=context.window, screen=context.screen, area=area, region=_region(area)):
        cls = getattr(bpy.types, KINDS[kind][1], None)
        if kind == "SHADER" and not context.scene.render.engine.startswith(("BLENDER_", "CYCLES")):
            cls = bpy.types.NODE_MT_add                    # another renderer's own nodes
        if cls is not None:
            _read(cls, out, frozenset())
    _items.clear()

    def walk(entries, depth, path):
        for n, e in enumerate(entries):
            if e[0] == "menu":
                rows.append((f"{path}/{e[1]}", depth, e[1], True))
                walk(e[2], depth + 1, f"{path}/{e[1]}")
            elif e[1] and e[2].startswith("node.add"):
                iid = f"{path}/{n}:{e[1]}"
                _items[iid] = (e[1], e[2], e[3])
                rows.append((iid, depth, e[1], False))
    walk(out, 0, "")
    _cache.update(key=key, rows=rows)
    return rows


class BLENDA4D_OT_nd_fold(bpy.types.Operator):
    bl_idname = "blenda4d.nd_fold"
    bl_label = "Open or Close"
    bl_description = "Show or hide the nodes in this group"
    bl_options = {"INTERNAL"}
    key: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        _open.symmetric_difference_update({self.key})
        context.area.tag_redraw()
        return {"FINISHED"}


def _free_spot(region, sp, wide):
    """The place nearest the middle of the canvas where a new node covers no other."""
    s = _ui()
    cx, cy = (v / s for v in region.view2d.region_to_view(region.width / 2, region.height / 2))
    previews = sp.tree_type == "ShaderNodeTree"
    up, down, gap = (170 if previews else 0), 220, 20
    rects = _rects(sp.edit_tree, previews)

    def free(x, y):
        return not any(x < r[2] + gap and x + wide > r[0] - gap and y - down < r[3] + gap and y + up > r[1] - gap for r in rects)
    x0, y0 = cx - wide / 2, cy + (down - up) / 2
    spots = sorted(((dx * 60, dy * 60) for dx in range(-12, 13) for dy in range(-12, 13)), key=lambda d: d[0] ** 2 + d[1] ** 2)
    dx, dy = next((d for d in spots if free(x0 + d[0], y0 + d[1])), (0, 0))
    return x0 + dx, y0 + dy


class BLENDA4D_OT_nd_add(bpy.types.Operator):
    bl_idname = "blenda4d.nd_add"
    bl_label = "Add Node"
    bl_description = "Put this node on the Node Editor's canvas"
    bl_options = {"REGISTER", "UNDO"}
    key: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def description(cls, context, props):
        item = _items.get(props.key)
        return f"Put {item[0]} on the Node Editor's canvas" if item else cls.bl_description

    def execute(self, context):
        item, area = _items.get(self.key), editor(context.screen)
        if item is None or area is None or area.spaces.active.edit_tree is None:
            return {"CANCELLED"}
        _label, idname, props = item
        region, sp = _region(area), area.spaces.active
        x, y = _free_spot(region, sp, 420 if "zone" in idname else 170)
        kw = {k: v for k, v in vars(props).items() if k not in {"settings", "use_transform"}}
        if props.settings:
            kw["settings"] = [{"name": r.name, "value": r.value} for r in props.settings]
        mod, name = idname.split(".")
        op = getattr(getattr(bpy.ops, mod), name)
        if "use_transform" in {p.identifier for p in op.get_rna_type().properties}:
            kw["use_transform"] = False
        sp.cursor_location = (x, y)
        try:
            with context.temp_override(window=context.window, screen=context.screen, area=area, region=region):
                done = op("EXEC_DEFAULT", **kw)
        except (RuntimeError, TypeError) as ex:
            self.report({"WARNING"}, str(ex))
            return {"CANCELLED"}
        area.tag_redraw()
        return {"FINISHED"} if "FINISHED" in done else {"CANCELLED"}


class BLENDA4D_PT_nd_list(roles.RolePanel, bpy.types.Panel):
    bl_label = "Nodes"
    role = LIST

    def draw(self, context):
        lay = self.layout
        area, kind = editor(context.screen), kind_of(context.screen)
        if area is None or not kind:
            return
        wm = context.window_manager
        lay.prop(wm, "b4d_nd_search", text="", icon="VIEWZOOM")
        ready = area.spaces.active.edit_tree is not None
        if not ready:
            lay.label(text=EMPTY[kind], icon="INFO")
        rows = catalog(context, area, kind)
        find = wm.b4d_nd_search.strip().lower()
        col = lay.column(align=True)
        if find:
            seen = set()
            for key, _d, title, cat in rows:
                if not cat and find in title.lower() and title not in seen:
                    seen.add(title)
                    self._item(col, key, title, 0, ready)
            if not seen:
                col.label(text="Nothing found")
            return
        hidden = None                                      # inside a closed group, down to its depth
        for key, depth, title, cat in rows:
            if hidden is not None and depth > hidden:
                continue
            hidden = None
            if cat:
                unfolded = key in _open
                row = self._row(col, depth)
                row.emboss = "PULLDOWN_MENU"
                row.operator("blenda4d.nd_fold", text=title, icon="DOWNARROW_HLT" if unfolded else "RIGHTARROW").key = key
                if not unfolded:
                    hidden = depth
            else:
                self._item(col, key, title, depth, ready)

    @staticmethod
    def _row(col, depth):
        row = col.row(align=True)
        row.alignment = "LEFT"
        if depth:
            row.separator(factor=1.2 * depth)
        return row

    def _item(self, col, key, title, depth, ready):
        row = self._row(col, depth)
        row.enabled = ready
        row.emboss = "PULLDOWN_MENU"
        row.operator("blenda4d.nd_add", text=title).key = key


# --- headers ------------------------------------------------------------------------------------------------------------------
def node_header(self, context):
    """The docked Node Editor's row: its menus, what is on the canvas, search."""
    lay, sp, scene, ob = self.layout, context.space_data, context.scene, context.object
    row = lay.row(align=True)
    row.menu("NODE_MT_add", text="Create")
    row.menu("BLENDA4D_MT_nodewin_edit", text="Edit")
    row.menu("NODE_MT_view", text="View")
    row.menu("NODE_MT_node", text="Node")
    row.menu("NODE_MT_select", text="Select")
    lay.separator()
    kind = sp.tree_type
    if kind == "ShaderNodeTree":
        sub = lay.row(align=True)
        sub.ui_units_x = 5
        sub.prop(sp, "shader_type", text="")
        if sp.pin and material_of(context.screen) is not None:
            m = material_of(context.screen)
            lay.label(text=m.name, icon_value=lay.icon(m))
        elif sp.shader_type == "WORLD":
            lay.template_ID(scene, "world", new="world.new")
        elif ob is not None and ob.type != "LIGHT":
            owner = sp.id_from or ob
            if hasattr(owner, "active_material"):
                lay.template_ID(owner, "active_material", new="material.new")
        elif ob is not None:
            lay.label(text=ob.name, icon="LIGHT")
    elif kind == "GeometryNodeTree":
        mod = ob.modifiers.active if ob is not None else None
        if mod is not None and mod.type == "NODES":
            lay.template_ID(mod, "node_group", new="object.geometry_node_tree_copy_assign" if mod.node_group else
                            "node.new_geometry_node_group_assign")
        elif ob is not None:
            lay.template_ID(sp, "node_tree", new="node.new_geometry_nodes_modifier")
    elif kind == "CompositorNodeTree":
        effects = getattr(scene, "compositor_effects", None)
        if effects is not None:                            # Blender 5.3
            act = effects.active
            if act is not None:
                lay.template_ID(act, "node_group", new="scene.duplicate_compositor_effect_node_group" if act.node_group else
                                "scene.new_compositor_effect_node_group")
            else:
                lay.template_ID(sp, "node_tree", new="scene.new_compositor_effect_node_group")
        else:
            lay.template_ID(scene, "compositing_node_group", new="node.duplicate_compositing_node_group" if
                            scene.compositing_node_group else "node.new_compositing_node_group")
    lay.separator_spacer()
    if len(sp.path) > 1:
        lay.operator("node.tree_path_parent", text="", icon="FILE_PARENT")
    if kind == "CompositorNodeTree":
        lay.prop(sp, "show_backdrop", text="", icon="IMAGE_BACKGROUND", toggle=True)
    lay.operator("node.find_node", text="Search", icon="VIEWZOOM")


def _image_header(self, context):
    from . import uvtab
    if uvtab.docked(context):
        return uvtab.header(self, context)
    if not docked(context):
        return _own["IMAGE_HT_header"](self, context)
    lay, sp = self.layout, context.space_data
    lay.label(text="Result", icon="IMAGE_DATA")
    row = lay.row(align=True)
    row.menu("IMAGE_MT_view", text="View")
    row.menu("IMAGE_MT_image", text="Image")
    lay.separator_spacer()
    row = lay.row(align=True)
    row.operator("blenda4d.nd_result", text="Viewer", depress=sp.image is not None and sp.image.type == "COMPOSITING").what = "VIEWER"
    row.operator("blenda4d.nd_result", text="Render", depress=sp.image is not None and sp.image.type == "RENDER_RESULT").what = "RENDER"
    lay.operator("blenda4d.render_still", text="", icon="RENDER_STILL")


def _sheet_header(self, context):
    if not docked(context):
        return _own["SPREADSHEET_HT_header"](self, context)
    lay, sp = self.layout, context.space_data
    lay.label(text="Spreadsheet", icon="SPREADSHEET")
    lay.menu("SPREADSHEET_MT_view", text="View")
    for attr in ("geometry_component_type", "attribute_domain"):
        if hasattr(sp, attr):
            sub = lay.row()
            sub.ui_units_x = 5
            sub.prop(sp, attr, text="")
    lay.separator_spacer()
    row = lay.row(align=True)
    row.prop(sp, "show_only_selected", text="")
    row.prop(sp, "use_filter", toggle=True, icon="FILTER_FILLED" if sp.use_filter else "FILTER", icon_only=True)


class BLENDA4D_OT_nd_result(bpy.types.Operator):
    bl_idname = "blenda4d.nd_result"
    bl_label = "Show Result"
    bl_description = "Show this picture"
    bl_options = {"INTERNAL"}
    what: bpy.props.EnumProperty(items=[("VIEWER", "Viewer", ""), ("RENDER", "Render", "")], options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return ("Show what the Viewer node shows" if props.what == "VIEWER" else "Show the finished render")

    def execute(self, context):
        sp = context.space_data
        img = viewer() if self.what == "VIEWER" else rendered()
        if img is None:
            self.report({"INFO"}, "Add a Viewer node first" if self.what == "VIEWER" else "Render a picture first")
            return {"CANCELLED"}
        sp.image = img
        return {"FINISHED"}


def node_panel(lay, context):
    """The docked Node Editor's right side when it is not a material: the picked node's settings."""
    from . import matpage
    sp = context.space_data
    tree = sp.edit_tree
    node = tree.nodes.active if tree is not None else None
    if node is None or not node.select:
        lay.label(text=tree.name if tree is not None else EMPTY.get(kind_of(context.screen), ""), icon="NODETREE")
        if tree is not None:
            lay.label(text="Pick a node to see its settings")
        return
    lay.label(text=node.label or node.name, icon="NODE")
    matpage.draw_node(lay, context, node)


classes = (BLENDA4D_OT_nd_fold, BLENDA4D_OT_nd_add, BLENDA4D_OT_nd_result, BLENDA4D_PT_nd_list)


@bpy.app.handlers.persistent
def _loaded(*_args):
    _state.clear()
    _cache["key"] = None


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.b4d_nd_search = bpy.props.StringProperty(
        name="Search", description="Find a node by its name", options={"TEXTEDIT_UPDATE"})
    _own["IMAGE_HT_header"] = own_draw.swap("IMAGE_HT_header", _image_header)
    _own["SPREADSHEET_HT_header"] = own_draw.swap("SPREADSHEET_HT_header", _sheet_header)
    _handles.append((bpy.types.SpaceNodeEditor, bpy.types.SpaceNodeEditor.draw_handler_add(_watch, (), "WINDOW", "POST_PIXEL")))
    _handles.append((bpy.types.SpaceImageEditor, bpy.types.SpaceImageEditor.draw_handler_add(
        lambda: _result(bpy.context), (), "WINDOW", "POST_PIXEL")))
    bpy.app.handlers.load_post.append(_loaded)
    _loaded()


def unregister():
    for space, h in _handles:
        space.draw_handler_remove(h, "WINDOW")
    _handles.clear()
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    own_draw.restore("IMAGE_HT_header", _image_header)
    own_draw.restore("SPREADSHEET_HT_header", _sheet_header)
    _own.clear()
    if hasattr(bpy.types.WindowManager, "b4d_nd_search"):
        del bpy.types.WindowManager.b4d_nd_search
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
