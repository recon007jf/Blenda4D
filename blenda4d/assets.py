# SPDX-License-Identifier: GPL-3.0-or-later
"""The Asset Browser manager: tabs, a navigation and search row, the libraries' folders on the left and the assets of
the open folder as a grid of previews on the right, all drawn with Blender's own UI elements.

- Right-click the empty space under the folder list: Create New Folder (a folder of the library, kept in its
  blender_assets.cats.txt, so it belongs to the library and not to one scene). The new folder opens.
- Drop files from the Finder or the desktop onto the browser: each becomes an asset in the open folder, with a preview,
  made by a background Blender (assets_worker.py); the open scene is never touched. Create > Add Files... does the same
  from a file browser.
- Drag an asset's picture into the viewport to add it there (a material goes onto the object under the mouse);
  double-click its name to add it at the 3D cursor (a material goes onto the selected objects)."""
import json
import os
import time

import bpy

from . import assets_library as lib
from . import roles

TABS = (("AUTO", "Auto"), ("ALL", "All"), ("MODELS", "Models"), ("MATERIALS", "Materials"), ("MEDIA", "Media"),
        ("NODES", "Nodes"), ("OPERATORS", "Operators"), ("SCENES", "Scenes"), ("PRESETS", "Presets"),
        ("HDRIS", "HDRIs"), ("POSES", "Poses"), ("BRUSHES", "Brushes"))
GREY_TABS = {"MEDIA", "OPERATORS", "PRESETS"}
HOME = (("MATERIAL", "Materials", "MATERIALS"), ("MESH_CUBE", "Models", "MODELS"), ("WORLD", "HDRIs", "HDRIS"),
        ("FILE_BLEND", "Templates", "SCENES"), ("ARMATURE_DATA", "Motion Capture", "POSES"), ("NODETREE", "Nodes", "NODES"),
        ("BRUSH_DATA", "Brushes", "BRUSHES"), ("ASSET_MANAGER", "All Assets", "ALL"))
SMART = (("@FAV", "FUND", "Favorites"), ("@FEATURED", "VIEWZOOM", "Featured Content"), ("@KEYWORDS", "BOOKMARKS", "Keywords"),
         ("@NEW", "NEWFOLDER", "New Assets"), ("@OTHER", "FILE_FOLDER", "Other"), ("@CREATED", "TIME", "Recently Created"),
         ("@USED", "TIME", "Recently Used"))
GREY_SMART = {"@FEATURED", "@KEYWORDS", "@OTHER"}
UNCAT = "@UNCAT"
SPLIT = 0.48

# Geometry of the grid, so a drag that starts on a picture knows which asset it is (a picture is a label and lets the
# press through to the keymap). In row units from the top of the area; measured in tools/tests/assets_ui.py.
TOP_UNITS = 5.25          # menu row, two rows of tabs, navigation row, then the folder list and the grid start
HEAD_UNITS = 2.2          # the grid's title and item count
GAP_UNITS = 0.25          # between two rows of tiles

_st = {"home": True, "folder": None, "open": set(), "sel": "", "hist": [], "fut": [], "last_tab": None,
       "new": [], "click": ("", 0.0), "smart_open": True, "geom": None}
_previews = []


# --- small helpers --------------------------------------------------------------------------------------------------

def _icon_value(name):
    return bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items[name].value


def _unit():
    from . import roles
    return roles.widget_unit()                      # Blender's row height (a tile's icon scale is counted in it)


def _pcoll():
    if not _previews:
        from bpy.utils import previews
        _previews.append(previews.new())
    return _previews[0]


def _preview_icon(a):
    p = a.get("preview")
    if p and os.path.exists(p):
        key = f"{p}|{os.path.getmtime(p)}"
        pc = _pcoll()
        item = pc.get(key) or pc.load(key, p, "IMAGE")
        return item.icon_id
    return _icon_value(lib.TYPE_ICON.get(a["type"], "ASSET_MANAGER"))


def _marks_file():
    return os.path.join(lib.cache_root(), "marks.json")


_marks_cache = [None, None]


def _marks():
    """Favorites and when each asset was last added to a scene (kept beside the index, not in any .blend)."""
    file = _marks_file()
    try:
        mt = os.path.getmtime(file)
    except OSError:
        mt = None
    if _marks_cache[0] == mt and _marks_cache[1] is not None:
        return json.loads(json.dumps(_marks_cache[1]))
    try:
        with open(file, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    m.setdefault("favorites", [])
    m.setdefault("used", {})
    _marks_cache[:] = [mt, m]
    return json.loads(json.dumps(m))


def _save_marks(m):
    tmp = _marks_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f)
    os.replace(tmp, _marks_file())
    _marks_cache[:] = [None, None]


def _redraw():
    wm = bpy.context.window_manager
    for w in wm.windows:
        for a in w.screen.areas:
            if roles.role(a) == "ASSETS":
                a.tag_redraw()


def _shown_libraries(context):
    pick = context.window_manager.b4d_ab_library
    libs = lib.libraries()
    return libs if pick == "ALL" else [x for x in libs if x[0] == pick]


def _catalog_paths(libs):
    """{library path: {uuid: catalog path}}"""
    return {path: {u: p for u, p, _s in lib.read_catalogs(path)} for _n, path, _w in libs}


_indexed = set()


def _ensure_indexed(libs):
    for _n, path, _w in libs:
        if path not in _indexed:
            _indexed.add(path)
            lib.index_library(path)


# --- what the grid shows ----------------------------------------------------------------------------------------------

def shown_assets(context):
    wm = context.window_manager
    libs = _shown_libraries(context)
    cats = _catalog_paths(libs)
    rows = [a for _n, path, _w in libs for a in lib.assets(path)]
    tab = wm.b4d_ab_tab
    if tab in lib.TAB_TYPES:
        rows = [a for a in rows if a["type"] in lib.TAB_TYPES[tab]]
    folder = _st["folder"]
    if folder == "@FAV":
        fav = set(_marks()["favorites"])
        rows = [a for a in rows if lib.key_of(a) in fav]
    elif folder == "@NEW":
        new = set(_st["new"])
        rows = [a for a in rows if a["blend"] in new]
    elif folder == "@CREATED":
        rows = sorted(rows, key=lambda a: -a["mtime"])[:40]
    elif folder == "@USED":
        used = _marks()["used"]
        rows = sorted([a for a in rows if lib.key_of(a) in used], key=lambda a: -used[lib.key_of(a)])[:40]
    elif folder == UNCAT:
        rows = [a for a in rows if not cats.get(a["library"], {}).get(a["catalog"])]
    elif folder:
        rows = [a for a in rows if (cats.get(a["library"], {}).get(a["catalog"]) or "\0") == folder
                or (cats.get(a["library"], {}).get(a["catalog"]) or "\0").startswith(folder + "/")]
    needle = wm.b4d_ab_search.strip().lower()
    if needle:
        rows = [a for a in rows if needle in a["name"].lower() or any(needle in t.lower() for t in a.get("tags", ()))]
    return rows


def _title(context):
    folder = _st["folder"]
    if folder is None:
        return dict(TABS).get(context.window_manager.b4d_ab_tab, "All")
    if folder == UNCAT:
        return "Uncategorized"
    for key, _i, label in SMART:
        if key == folder:
            return label
    return folder.rsplit("/", 1)[-1]


def _go(folder=None, home=False):
    _st["hist"].append((_st["folder"], _st["home"]))
    del _st["hist"][:-30]
    _st["fut"].clear()
    _st["folder"], _st["home"] = folder, home


# --- drawing --------------------------------------------------------------------------------------------------------

def _draw_tree(col, context, libs):
    r = col.row(align=True)
    r.alignment = "LEFT"
    r.operator("blenda4d.ab_fold", text="", emboss=False,
               icon="DISCLOSURE_TRI_DOWN" if _st["smart_open"] else "DISCLOSURE_TRI_RIGHT").folder = "@SMART"
    r.label(text="Smart Searches", icon="ASSET_MANAGER")
    if _st["smart_open"]:
        for key, icon, label in SMART:
            r = col.row(align=True)
            r.alignment = "LEFT"
            r.enabled = key not in GREY_SMART
            r.separator(factor=3.0)
            r.operator("blenda4d.ab_open", text=label, icon=icon, emboss=_st["folder"] == key and not _st["home"],
                       depress=_st["folder"] == key).folder = key
    col.separator()
    paths = sorted({p for _n, path, _w in libs for _u, p, _s in lib.read_catalogs(path)}, key=str.lower)
    have = set(paths)
    for p in paths:
        parts = p.split("/")
        if any("/".join(parts[:i]) not in _st["open"] for i in range(1, len(parts))):
            continue                                  # under a folded folder
        kids = any(q.startswith(p + "/") for q in have)
        r = col.row(align=True)
        r.alignment = "LEFT"
        r.separator(factor=1.5 * (len(parts) - 1))
        if kids:
            r.operator("blenda4d.ab_fold", text="", emboss=False,
                       icon="DISCLOSURE_TRI_DOWN" if p in _st["open"] else "DISCLOSURE_TRI_RIGHT").folder = p
        else:
            r.label(text="", icon="BLANK1")
        sel = _st["folder"] == p and not _st["home"]
        r.operator("blenda4d.ab_open", text=parts[-1], icon="FILE_FOLDER", emboss=sel, depress=sel).folder = p
    r = col.row(align=True)
    r.alignment = "LEFT"
    r.label(text="", icon="BLANK1")
    sel = _st["folder"] == UNCAT and not _st["home"]
    r.operator("blenda4d.ab_open", text="Uncategorized", icon="FILE_FOLDER", emboss=sel, depress=sel).folder = UNCAT


def _columns(context, scale):
    u = _unit()
    width = context.region.width * (1 - SPLIT) - u
    return max(1, int(width // (scale * u + 0.25 * u)))


def _draw_home(right, context):
    right.label(text="Home")
    sub = right.row()
    sub.enabled = False
    sub.label(text=f"Asset Types ({len(HOME)} Items)")
    grid = right.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True)
    for icon, label, tab in HOME:
        c = grid.column(align=True)
        c.scale_y = 3.0
        c.operator("blenda4d.ab_show", text=label, icon=icon).tab = tab
    _st["geom"] = None


def _draw_grid(right, context):
    wm = context.window_manager
    rows = shown_assets(context)
    right.label(text=_title(context))
    sub = right.row()
    sub.enabled = False
    sub.label(text=f"{len(rows)} {'Item' if len(rows) == 1 else 'Items'}")
    if not rows:
        right.separator()
        hint = right.column()
        hint.enabled = False
        if lib.busy():
            hint.label(text="Reading the library...")
        else:
            hint.label(text="Drop files here to add them")
        _st["geom"] = None
        return
    if wm.b4d_ab_view == "LIST":
        col = right.column(align=True)
        for a in rows:
            r = col.row(align=True)
            r.alignment = "LEFT"
            k = lib.key_of(a)
            r.label(text="", icon_value=_preview_icon(a))
            r.operator("blenda4d.ab_pick", text=a["name"], emboss=k == _st["sel"], depress=k == _st["sel"]).key = k
        _st["geom"] = None
        return
    scale = wm.b4d_ab_size
    n = _columns(context, scale)
    keys = []
    for i in range(0, len(rows), n):
        line = right.row()
        for j in range(n):
            c = line.column(align=True)
            if i + j >= len(rows):
                c.label(text="")
                continue
            a = rows[i + j]
            k = lib.key_of(a)
            keys.append(k)
            c.template_icon(icon_value=_preview_icon(a), scale=scale)
            c.operator("blenda4d.ab_pick", text=a["name"], depress=k == _st["sel"]).key = k
        right.separator(factor=0.2)
    _st["geom"] = {"cols": n, "keys": keys, "scale": scale, "area": context.area.as_pointer()}


def draw(layout, context):
    wm = context.window_manager
    libs = _shown_libraries(context)
    _ensure_indexed(libs)
    if _st["last_tab"] != wm.b4d_ab_tab:              # a tab was clicked: show its assets
        if _st["last_tab"] is not None:
            _st["home"] = False
        _st["last_tab"] = wm.b4d_ab_tab
    bar = layout.row(align=True)
    menus = bar.row(align=True)
    menus.alignment = "LEFT"
    try:
        menus.emboss = "PULLDOWN_MENU"
    except (AttributeError, TypeError):
        pass
    for m in MENUS:
        menus.menu(m.bl_idname, text=m.bl_label)
    tail = bar.row(align=True)
    tail.alignment = "RIGHT"
    tail.prop(wm, "b4d_ab_library", text="")
    tail.operator("blenda4d.ab_refresh", text="", icon="FILE_REFRESH", emboss=False)
    tail.operator("blenda4d.ab_library_prefs", text="", icon="PREFERENCES", emboss=False)
    tail.operator("screen.screen_full_area", text="", icon="FULLSCREEN_ENTER", emboss=False)
    grid = layout.grid_flow(row_major=True, columns=6, even_columns=True, align=True)
    for key, label in TABS:
        cell = grid.row(align=True)
        cell.enabled = key not in GREY_TABS
        cell.prop_enum(wm, "b4d_ab_tab", key, text=label)
    nav = layout.row(align=True)
    sub = nav.row(align=True)
    sub.enabled = bool(_st["hist"])
    sub.operator("blenda4d.ab_back", text="", icon="BACK")
    sub = nav.row(align=True)
    sub.enabled = bool(_st["fut"])
    sub.operator("blenda4d.ab_forward", text="", icon="FORWARD")
    nav.operator("blenda4d.ab_home", text="", icon="HOME", depress=_st["home"])
    fav = _st["sel"] in _marks()["favorites"] if _st["sel"] else False
    sub = nav.row(align=True)
    sub.enabled = bool(_st["sel"])
    sub.operator("blenda4d.ab_favorite", text="", icon="SOLO_ON" if fav else "SOLO_OFF")
    nav.prop(wm, "b4d_ab_search", text="", icon="VIEWZOOM")
    nav.operator("blenda4d.ab_add_files", text="", icon="IMPORT")
    split = layout.split(factor=SPLIT)
    tree = split.column(align=True)
    _draw_tree(tree, context, libs)
    right = split.column()
    if _st["home"] and not wm.b4d_ab_search:
        _draw_home(right, context)
    else:
        _draw_grid(right, context)
    layout.separator()
    line = lib.status()
    if line:
        layout.label(text=line, icon="TIME")
    elif lib.failures():
        layout.label(text=f"{len(lib.failures())} could not be added (see the console)", icon="ERROR")
    bottom = layout.row(align=True)
    views = bottom.row(align=True)
    views.prop(wm, "b4d_ab_view", expand=True, icon_only=True)
    size = bottom.row(align=True)
    size.enabled = wm.b4d_ab_view == "GRID" and not (_st["home"] and not wm.b4d_ab_search)
    size.prop(wm, "b4d_ab_size", text="Size", slider=True)


# --- operators --------------------------------------------------------------------------------------------------------

class _Op:
    bl_options = {"INTERNAL"}

    def _done(self):
        _redraw()
        return {"FINISHED"}


class BLENDA4D_OT_ab_open(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_open"
    bl_label = "Open Folder"
    bl_description = "Show the assets in this folder"
    folder: bpy.props.StringProperty()

    def execute(self, context):
        _go(self.folder)
        return self._done()


class BLENDA4D_OT_ab_fold(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_fold"
    bl_label = "Fold"
    bl_description = "Show or hide what is inside"
    folder: bpy.props.StringProperty()

    def execute(self, context):
        if self.folder == "@SMART":
            _st["smart_open"] = not _st["smart_open"]
        else:
            _st["open"].symmetric_difference_update({self.folder})
        return self._done()


class BLENDA4D_OT_ab_show(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_show"
    bl_label = "Show Asset Type"
    bl_description = "Show every asset of this type"
    tab: bpy.props.StringProperty()

    def execute(self, context):
        _go(None)
        context.window_manager.b4d_ab_tab = self.tab
        _st["last_tab"] = self.tab
        return self._done()


class BLENDA4D_OT_ab_home(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_home"
    bl_label = "Home"
    bl_description = "Back to the Home page"

    def execute(self, context):
        _go(None, home=True)
        context.window_manager.b4d_ab_tab = "ALL"
        _st["last_tab"] = "ALL"
        return self._done()


class BLENDA4D_OT_ab_back(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_back"
    bl_label = "Back"
    bl_description = "The page shown before"

    def execute(self, context):
        if _st["hist"]:
            _st["fut"].append((_st["folder"], _st["home"]))
            _st["folder"], _st["home"] = _st["hist"].pop()
        return self._done()


class BLENDA4D_OT_ab_forward(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_forward"
    bl_label = "Forward"
    bl_description = "The page shown after this one"

    def execute(self, context):
        if _st["fut"]:
            _st["hist"].append((_st["folder"], _st["home"]))
            _st["folder"], _st["home"] = _st["fut"].pop()
        return self._done()


class BLENDA4D_OT_ab_favorite(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_favorite"
    bl_label = "Favorite"
    bl_description = "Add the selected asset to Favorites, or take it out"

    def execute(self, context):
        if not _st["sel"]:
            return {"CANCELLED"}
        m = _marks()
        if _st["sel"] in m["favorites"]:
            m["favorites"].remove(_st["sel"])
        else:
            m["favorites"].append(_st["sel"])
        _save_marks(m)
        return self._done()


class BLENDA4D_OT_ab_refresh(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_refresh"
    bl_label = "Refresh Libraries"
    bl_description = "Read the asset libraries again (files added or changed outside Blender)"

    def execute(self, context):
        for _n, path, _w in _shown_libraries(context):
            lib.index_library(path)
        return self._done()


class BLENDA4D_OT_ab_library_prefs(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_library_prefs"
    bl_label = "Asset Libraries..."
    bl_description = "Add or remove asset library folders in the Preferences"

    def execute(self, context):
        bpy.ops.screen.userpref_show(section="FILE_PATHS")
        return {"FINISHED"}


class BLENDA4D_OT_ab_pick(_Op, bpy.types.Operator):
    bl_idname = "blenda4d.ab_pick"
    bl_label = "Select Asset"
    bl_description = "Select this asset. Double-click to add it to the scene, or drag its picture into the viewport"
    bl_options = {"UNDO", "INTERNAL"}
    key: bpy.props.StringProperty()

    def execute(self, context):
        last, t = _st["click"]
        now = time.monotonic()
        _st["click"] = (self.key, now)
        _st["sel"] = self.key
        if last == self.key and now - t < 0.45:
            _st["click"] = ("", 0.0)
            a = lib.find(self.key)
            if a is not None:
                try:
                    place(context, a)
                except Exception as ex:
                    self.report({"WARNING"}, f"Could not add {a['name']}: {ex}")
                    return {"CANCELLED"}
        return self._done()


class BLENDA4D_OT_ab_add_to_scene(bpy.types.Operator):
    bl_idname = "blenda4d.ab_add_to_scene"
    bl_label = "Add to Scene"
    bl_description = "Add the selected asset to the scene at the 3D cursor (a material goes onto the selected objects)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(_st["sel"])

    def execute(self, context):
        a = lib.find(_st["sel"])
        if a is None:
            return {"CANCELLED"}
        place(context, a)
        return {"FINISHED"}


# --- adding an asset to the scene -------------------------------------------------------------------------------------

def _local(a):
    """An earlier copy of this asset in the file, for materials, worlds and node groups (reused, not doubled)."""
    if a["type"] not in ("materials", "worlds", "node_groups", "brushes"):
        return None
    key = lib.key_of(a)
    return next((b for b in getattr(bpy.data, a["type"]) if b.get("b4d_asset") == key and b.library is None), None)


def _load(a):
    name = next((n for n, p, _w in lib.libraries() if p == a["library"]), "")
    method = lib.import_method(name)
    if method != "APPEND":                           # reuse (Blender's default) and pack both bring one copy
        have = _local(a)
        if have is not None:
            return have
    link = method == "LINK"
    with bpy.data.libraries.load(a["blend"], link=link, assets_only=True) as (src, dst):
        if a["name"] not in getattr(src, a["type"]):
            raise ValueError("the asset is no longer in its file")
        setattr(dst, a["type"], [a["name"]])
    block = getattr(dst, a["type"])[0]
    if block is None:
        raise ValueError("the asset could not be read")
    if not link:
        if block.asset_data is not None:
            block.asset_clear()
        block["b4d_asset"] = lib.key_of(a)
    return block


def _give_material(ob, mat):
    if ob is None or not hasattr(ob.data, "materials"):
        return False
    if ob.material_slots:
        ob.material_slots[ob.active_material_index].material = mat
    else:
        ob.data.materials.append(mat)
    return True


def place(context, a, location=None, target=None):
    """Bring an asset into the scene. location: where an object goes (else the 3D cursor); target: the object a
    material, node group or animation goes onto (else the selected objects)."""
    block = _load(a)
    scene = context.scene
    coll = context.collection or scene.collection
    from mathutils import Vector
    where = Vector(location) if location is not None else scene.cursor.location.copy()
    kind = a["type"]
    out = block
    if kind == "objects":
        if block.name not in coll.objects:
            coll.objects.link(block)
        block.location = where
        if location is not None:                     # dropped: stand it on the surface instead of half inside it
            context.view_layer.update()
            from mathutils import Vector as V
            low = min((block.matrix_world @ V(c)).z for c in block.bound_box)
            block.location.z += where.z - low
        _select(context, [block])
    elif kind == "collections":
        if block.library is not None:
            empty = bpy.data.objects.new(block.name, None)
            empty.instance_type = "COLLECTION"
            empty.instance_collection = block
            empty.location = where
            coll.objects.link(empty)
            _select(context, [empty])
            out = empty
        else:
            if block.name not in coll.children:
                coll.children.link(block)
            roots = [o for o in block.all_objects if o.parent is None]
            for o in roots:
                o.location = o.location + where
            _select(context, roots)
    elif kind == "materials":
        obs = [target] if target is not None else list(context.selected_objects)
        for ob in obs:
            _give_material(ob, block)
    elif kind == "worlds":
        scene.world = block
    elif kind == "node_groups":
        obs = [target] if target is not None else list(context.selected_objects)
        if getattr(block, "bl_idname", "") == "GeometryNodeTree":
            for ob in obs:
                if ob is not None and ob.type in ("MESH", "CURVE", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"):
                    ob.modifiers.new(block.name, "NODES").node_group = block
    elif kind == "actions":
        ob = target or context.view_layer.objects.active
        if ob is not None:
            ob.animation_data_create()
            ob.animation_data.action = block
    m = _marks()
    m["used"][lib.key_of(a)] = time.time()
    _save_marks(m)
    return out


def _select(context, obs):
    for o in context.view_layer.objects.selected:
        o.select_set(False)
    for o in obs:
        try:
            o.select_set(True)
        except RuntimeError:
            pass
    if obs:
        context.view_layer.objects.active = obs[0]


# --- dragging a picture into the viewport ----------------------------------------------------------------------------

def asset_at(context, x, y):
    """The asset whose tile is under a window position in the browser, or None (see TOP_UNITS)."""
    g = _st["geom"]
    region = context.region
    if g is None or region is None or context.area.as_pointer() != g["area"]:
        return None
    u = _unit()
    vx, vy = region.view2d.region_to_view(x - region.x, y - region.y)
    left = region.width * SPLIT
    if vx < left:
        return None
    colw = (region.width - left) / g["cols"]
    col = int((vx - left) // colw)
    tile_h = (g["scale"] + 1 + GAP_UNITS) * u
    row = int((-vy - (TOP_UNITS + HEAD_UNITS) * u) // tile_h)
    if row < 0 or not 0 <= col < g["cols"]:
        return None
    i = row * g["cols"] + col
    return g["keys"][i] if i < len(g["keys"]) else None


def _viewport_under(context, x, y):
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return area, region
    return None, None


def drop_point(context, region, x, y):
    """(location, object) under a window position in a viewport: the surface hit, else the ground, else the cursor."""
    from bpy_extras import view3d_utils
    rv3d = region.data
    co = (x - region.x, y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, co)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, co)
    hit, loc, _n, _i, ob, _m = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction)
    if hit:
        return loc, (ob.original if ob is not None else None)
    if abs(direction.z) > 1e-6:
        t = -origin.z / direction.z
        if t > 0:
            return origin + direction * t, None
    return context.scene.cursor.location.copy(), None


class BLENDA4D_OT_ab_drag(bpy.types.Operator):
    bl_idname = "blenda4d.ab_drag"
    bl_label = "Drag Asset"
    bl_description = "Drag an asset into the viewport to add it there"
    bl_options = {"UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == "ASSETS"

    def invoke(self, context, event):
        self.key = asset_at(context, event.mouse_prev_press_x, event.mouse_prev_press_y)
        if not self.key:
            return {"PASS_THROUGH"}
        _st["sel"] = self.key
        _redraw()
        context.window.cursor_modal_set("HAND_CLOSED")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            context.window.cursor_modal_restore()
            area, region = _viewport_under(context, event.mouse_x, event.mouse_y)
            a = lib.find(self.key)
            if area is None or a is None:
                return {"CANCELLED"}
            loc, ob = drop_point(context, region, event.mouse_x, event.mouse_y)
            try:
                place(context, a, location=loc, target=ob)
            except Exception as ex:
                self.report({"WARNING"}, f"Could not add {a['name']}: {ex}")
                return {"CANCELLED"}
            area.tag_redraw()
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.window.cursor_modal_restore()
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


# --- folders ------------------------------------------------------------------------------------------------------

def _folder_library(context):
    """The library a folder command works on: the shown library when it can be written, else the User Library."""
    return lib.target_library(context.window_manager.b4d_ab_library)


def _real_folder():
    f = _st["folder"]
    return f if f and not f.startswith("@") and not _st["home"] else ""


class BLENDA4D_OT_ab_new_folder(bpy.types.Operator):
    bl_idname = "blenda4d.ab_new_folder"
    bl_label = "Create New Folder"
    bl_description = "A new folder in the asset library, opened and ready for files dropped in"
    bl_options = {"INTERNAL"}
    name: bpy.props.StringProperty(name="Name", default="New Folder")
    inside: bpy.props.BoolProperty(name="Inside the Open Folder", default=False,
                                   description="Make it a folder inside the one that is open")

    def invoke(self, context, event):
        _n, path = _folder_library(context)
        self.name = lib.unique_folder(path).rsplit("/", 1)[-1]
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        self.layout.prop(self, "name")
        if _real_folder():
            self.layout.prop(self, "inside")

    def execute(self, context):
        lib_name, path = _folder_library(context)
        parent = _real_folder() if self.inside else ""
        base = self.name.replace("/", "-").replace(":", "-").strip() or "New Folder"
        folder = lib.unique_folder(path, base, parent)
        lib.add_catalog(path, folder)
        os.makedirs(os.path.join(path, *folder.split("/")), exist_ok=True)
        wm = context.window_manager
        if wm.b4d_ab_library not in ("ALL", lib_name):
            wm.b4d_ab_library = lib_name
        if parent:
            _st["open"].add(parent)
        _go(folder)
        self.report({"INFO"}, f"Folder {folder} made in {lib_name}")
        _redraw()
        return {"FINISHED"}


class BLENDA4D_OT_ab_rename_folder(bpy.types.Operator):
    bl_idname = "blenda4d.ab_rename_folder"
    bl_label = "Rename Folder"
    bl_description = "Rename the open folder"
    bl_options = {"INTERNAL"}
    name: bpy.props.StringProperty(name="Name")

    @classmethod
    def poll(cls, context):
        return bool(_real_folder())

    def invoke(self, context, event):
        self.name = _real_folder().rsplit("/", 1)[-1]
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        old = _real_folder()
        new = old
        for _n, path, ok in _shown_libraries(context):
            if ok and any(p == old for _u, p, _s in lib.read_catalogs(path)):
                new = lib.rename_catalog(path, old, self.name)
        _st["folder"] = new
        _redraw()
        return {"FINISHED"}


class BLENDA4D_OT_ab_delete_folder(bpy.types.Operator):
    bl_idname = "blenda4d.ab_delete_folder"
    bl_label = "Delete Folder"
    bl_description = "Take the open folder out of the list. Its assets stay in the library, under Uncategorized"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(_real_folder())

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, message=f"Delete the folder {_real_folder()}? "
                                                     "Its assets stay in the library.")

    def execute(self, context):
        old = _real_folder()
        for _n, path, ok in _shown_libraries(context):
            if ok and any(p == old for _u, p, _s in lib.read_catalogs(path)):
                lib.delete_catalog(path, old)
        _go(UNCAT)
        _redraw()
        return {"FINISHED"}


class BLENDA4D_MT_ab_folder(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_ab_folder"
    bl_label = "Folders"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = "INVOKE_DEFAULT"
        lay.operator("blenda4d.ab_new_folder", text="Create New Folder", icon="NEWFOLDER")
        lay.operator("blenda4d.ab_rename_folder", text="Rename Folder...")
        lay.operator("blenda4d.ab_delete_folder", text="Delete Folder...")


class BLENDA4D_OT_ab_folder_menu(bpy.types.Operator):
    bl_idname = "blenda4d.ab_folder_menu"
    bl_label = "Folders"
    bl_description = "Right-click the empty space under the folder list"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == "ASSETS" and context.region is not None and context.region.type == "WINDOW"

    def invoke(self, context, event):
        if event.mouse_region_x > context.region.width * SPLIT:
            return {"PASS_THROUGH"}
        bpy.ops.wm.call_menu(name=BLENDA4D_MT_ab_folder.bl_idname)
        return {"FINISHED"}


# --- files added from the Finder ----------------------------------------------------------------------------------

def add_paths(context, files):
    """Queue files to become assets in the open folder (of the shown library, else the User Library).
    Returns (count queued, where)."""
    files = [f for f in files if os.path.isfile(f) and os.path.splitext(f)[1].lower() in lib.EXTENSIONS]
    if not files:
        return 0, ""
    lib_name, path = _folder_library(context)
    folder = _real_folder()
    cid = ""
    if folder:
        cid = next((u for u, p, _s in lib.read_catalogs(path) if p == folder), "") or lib.add_catalog(path, folder)
    out_dir = os.path.join(path, *folder.split("/")) if folder else path
    lib.add_files(files, path, out_dir, cid)
    wm = context.window_manager
    if wm.b4d_ab_library not in ("ALL", lib_name):
        wm.b4d_ab_library = lib_name
    if _st["home"]:
        _go(folder or "@NEW")
    return len(files), folder or lib_name


class BLENDA4D_OT_ab_add_files(bpy.types.Operator):
    bl_idname = "blenda4d.ab_add_files"
    bl_label = "Add Files to Library"
    bl_description = ("Add files to the asset library, each as an asset in the open folder: models, pictures "
                      "(materials), .hdr/.exr (worlds), .blend files and OpenVDB volumes")
    bl_options = {"INTERNAL"}
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE", "HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={"SKIP_SAVE", "HIDDEN"})
    filter_glob: bpy.props.StringProperty(default=";".join("*" + e for e in lib.EXTENSIONS), options={"HIDDEN"})

    def invoke(self, context, event):
        if self.files and self.directory:            # dropped
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        files = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        n, where = add_paths(context, files)
        if not n:
            self.report({"WARNING"}, "None of these files can become assets")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Adding {n} {'file' if n == 1 else 'files'} to {where}")
        _redraw()
        return {"FINISHED"}


class BLENDA4D_FH_asset_drop(bpy.types.FileHandler):
    bl_idname = "BLENDA4D_FH_asset_drop"
    bl_label = "Add to Asset Library"
    bl_import_operator = "blenda4d.ab_add_files"
    bl_file_extensions = ";".join(lib.EXTENSIONS)

    @classmethod
    def poll_drop(cls, context):
        return roles.role(context.area) == "ASSETS"


# --- menus ----------------------------------------------------------------------------------------------------------

class BLENDA4D_MT_ab_create(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_ab_own_create"
    bl_label = "Create"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = "INVOKE_DEFAULT"
        lay.operator("blenda4d.ab_new_folder", text="Create New Folder", icon="NEWFOLDER")
        lay.operator("blenda4d.ab_add_files", text="Add Files...", icon="IMPORT")
        lay.separator()
        lay.operator("blenda4d.ab_add_to_scene", text="Add to Scene", icon="ADD")


class BLENDA4D_MT_ab_edit(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_ab_own_edit"
    bl_label = "Edit"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = "INVOKE_DEFAULT"
        lay.operator("blenda4d.ab_rename_folder", text="Rename Folder...")
        lay.operator("blenda4d.ab_delete_folder", text="Delete Folder...")
        lay.separator()
        lay.operator("blenda4d.ab_favorite", text="Favorite", icon="SOLO_OFF")


class BLENDA4D_MT_ab_view(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_ab_own_view"
    bl_label = "View"

    def draw(self, context):
        lay = self.layout
        wm = context.window_manager
        lay.prop_enum(wm, "b4d_ab_view", "GRID")
        lay.prop_enum(wm, "b4d_ab_view", "LIST")
        lay.separator()
        lay.operator("blenda4d.ab_home", text="Home", icon="HOME")


class BLENDA4D_MT_ab_libraries(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_ab_own_libraries"
    bl_label = "Libraries"

    def draw(self, context):
        lay = self.layout
        lay.prop(context.window_manager, "b4d_ab_library", expand=True)
        lay.separator()
        lay.operator("blenda4d.ab_refresh", text="Refresh", icon="FILE_REFRESH")
        lay.operator("blenda4d.ab_library_prefs", text="Asset Libraries...", icon="PREFERENCES")


MENUS = (BLENDA4D_MT_ab_create, BLENDA4D_MT_ab_edit, BLENDA4D_MT_ab_view, BLENDA4D_MT_ab_libraries)
classes = (BLENDA4D_OT_ab_open, BLENDA4D_OT_ab_fold, BLENDA4D_OT_ab_show, BLENDA4D_OT_ab_home, BLENDA4D_OT_ab_back,
           BLENDA4D_OT_ab_forward, BLENDA4D_OT_ab_favorite, BLENDA4D_OT_ab_refresh, BLENDA4D_OT_ab_library_prefs,
           BLENDA4D_OT_ab_pick, BLENDA4D_OT_ab_add_to_scene, BLENDA4D_OT_ab_drag, BLENDA4D_OT_ab_new_folder,
           BLENDA4D_OT_ab_rename_folder, BLENDA4D_OT_ab_delete_folder, BLENDA4D_MT_ab_folder, BLENDA4D_OT_ab_folder_menu,
           BLENDA4D_OT_ab_add_files, BLENDA4D_FH_asset_drop, *MENUS)

_lib_items = []


def _library_items(self, context):
    _lib_items[:] = [("ALL", "All", "Every asset library")] + [(n, n, p) for n, p, _w in lib.libraries()]
    return _lib_items


def _on_change():
    _redraw()


_keys = []


def register():
    for c in classes:
        bpy.utils.register_class(c)
    W = bpy.types.WindowManager
    W.b4d_ab_library = bpy.props.EnumProperty(name="Library", items=_library_items,
                                              description="Which asset library the browser shows")
    W.b4d_ab_view = bpy.props.EnumProperty(name="View", items=[("GRID", "Grid", "Previews in a grid", "IMGDISPLAY", 0),
                                                               ("LIST", "List", "Names in a list", "LONGDISPLAY", 1)])
    W.b4d_ab_size = bpy.props.FloatProperty(name="Preview Size", default=4.0, min=2.5, max=8.0,
                                            description="How large the asset previews are")
    from . import kinds
    kinds.panel("ASSETS", draw)
    lib._listeners.append(_on_change)
    lib.resume()
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES")
        for idname, key, value in (("blenda4d.ab_drag", "LEFTMOUSE", "CLICK_DRAG"),
                                   ("blenda4d.ab_folder_menu", "RIGHTMOUSE", "PRESS")):
            km.keymap_items.new(idname, key, value, head=True)
            _keys.append((km.name, idname))


def unregister():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:                               # looked up fresh: held keymap items can be freed at quit
        for name, idname in _keys:
            km = kc.keymaps.get(name)
            if km is not None:
                for kmi in list(km.keymap_items):
                    if kmi.idname == idname:
                        km.keymap_items.remove(kmi)
    _keys.clear()
    lib.pause()
    if _on_change in lib._listeners:
        lib._listeners.remove(_on_change)
    from . import kinds
    kinds.PANELS.pop("ASSETS", None)
    W = bpy.types.WindowManager
    for n in ("b4d_ab_library", "b4d_ab_view", "b4d_ab_size"):
        if hasattr(W, n):
            delattr(W, n)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    from bpy.utils import previews
    while _previews:
        previews.remove(_previews.pop())
    _indexed.clear()
