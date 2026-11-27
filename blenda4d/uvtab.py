# SPDX-License-Identifier: GPL-3.0-or-later
"""The UV Editing tab: the viewport at the left, the UV Editor at the right with a row of UV tools below it, and the UV
page in the Attribute Manager with their settings. What is selected is selected in both, and the tools column's Move,
Rotate, Scale and selection tools work in both.

The editor is Blender's own with Blenda's header. A command works on the selected polygons, or on all of them when none
is selected."""
import math

import bmesh
import bpy

from . import roles

KIND, BAR = "UV", "UV_BAR"
SHARE = 0.5                  # the UV Editor's share of the width
_handles = []
BOTH = {"builtin.select_box", "builtin.select_circle", "builtin.select_lasso", "builtin.move", "builtin.rotate", "builtin.scale",
        "builtin.transform", "builtin.cursor"}          # the tools the viewport and the UV Editor both have


# --- the areas ------------------------------------------------------------------------------------------------------------
def editor(screen):
    """The UV Editor of the tab."""
    if screen is None or not roles.areas(screen, BAR):
        return None
    return next((a for a in screen.areas if a.type == "IMAGE_EDITOR" and a.ui_type == "UV"), None)


def docked(context):
    s = context.screen
    return s is not None and context.area is not None and editor(s) == context.area


def intact(screen, kind):
    want = kind == KIND
    if len(roles.areas(screen, BAR)) != want:
        return False
    return not want or len([a for a in screen.areas if a.type == "IMAGE_EDITOR"]) == 1


def _region(area, kind="WINDOW"):
    if not roles.alive(area):                              # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == kind), None)


def _dress(window, area):
    sp = area.spaces.active
    sp.show_region_header, sp.show_region_toolbar, sp.show_region_ui = True, False, False
    for attr, v in (("show_region_tool_header", False), ("show_region_asset_shelf", False), ("show_region_hud", False),
                    ("show_gizmo_navigate", False)):
        try:
            setattr(sp, attr, v)
        except (AttributeError, TypeError):
            pass
    head = _region(area, "HEADER")
    if head is not None and head.alignment != "TOP":
        try:
            with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=head):
                bpy.ops.screen.region_flip()
        except RuntimeError:
            pass


def add_steps(window, view, sizes):
    from . import build
    share = min(0.75, max(0.2, sizes.get("uv", SHARE)))
    area = yield from build.split(window, view, "VERTICAL", round(view.width * share), "RIGHT")
    area.type = "IMAGE_EDITOR"
    area.ui_type = "UV"
    build.lay_out(window, area)
    bar = yield from build.split(window, area, "HORIZONTAL", min(build.px(build.UV_BAR_PX) + build.EDGE, round(area.height * 0.3)), "BOTTOM")
    yield from build.make_role(window, bar, BAR)
    area = next((a for a in window.screen.areas if a.type == "IMAGE_EDITOR"), None)
    if area is not None:
        _dress(window, area)
        yield
        frame(window, area)


def remove_steps(window):
    from . import build, quadview
    screen = window.screen
    area = editor(screen)
    for bar in roles.areas(screen, BAR):
        if area is not None:
            yield from quadview._join(window, bar, area)
        else:
            yield from build._into_view(window, bar)
    for a in [a for a in screen.areas if a.type == "IMAGE_EDITOR" and area is not None]:
        yield from build._into_view(window, a)


def sizes_of(screen, sizes):
    from . import build
    area = editor(screen)
    views = [a for a in screen.areas if a.type == "VIEW_3D"]
    if area is not None and views:
        wide = max(v.x + v.width for v in views) - min(v.x for v in views)
        sizes["uv"] = round((area.width + 1) / max(1, area.width + wide + build.EDGE), 3)


def frame(window, area):
    """The whole tile, with a little room around it."""
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=_region(area)):
            bpy.ops.image.view_all(fit_view=True)
    except (RuntimeError, TypeError):
        pass


def mirror_tool(window, tool):
    """The tool picked for the viewport is the UV Editor's too."""
    area = editor(window.screen)
    if area is None or tool not in BOTH:
        return
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=_region(area)):
            bpy.ops.wm.tool_set_by_id(name=tool, space_type="IMAGE_EDITOR")
    except (RuntimeError, TypeError):
        pass


# --- what can be edited ------------------------------------------------------------------------------------------------------
def why_not(context):
    """Why there are no UVs to work on, or ""."""
    ob = context.view_layer.objects.active
    if ob is None or ob.type != "MESH":
        return "Pick a polygon object"
    if "b4d_type" in ob:
        return "Make the object editable first (C)"
    if context.mode != "EDIT_MESH":
        return "Go to Polygons to edit its UVs"
    return ""


def _meshes(context):
    return [ob for ob in getattr(context, "objects_in_mode_unique_data", ()) if ob.type == "MESH"]


# --- the settings ------------------------------------------------------------------------------------------------------------
class BLENDA4D_PG_uv(bpy.types.PropertyGroup):
    method: bpy.props.EnumProperty(name="Method", description="How the polygons are flattened", default="ANGLE_BASED", items=[
        ("ANGLE_BASED", "Angle Based", "Keeps the angles: good for organic shapes"),
        ("CONFORMAL", "Conformal", "Quick, good for simple shapes"),
        ("MINIMUM_STRETCH", "Least Stretch", "Keeps sizes and angles as close as it can, and folds nothing over")])
    fill_holes: bpy.props.BoolProperty(name="Fill Holes", description="Act as if holes were closed, so that shapes do not fold into them", default=True)
    margin: bpy.props.FloatProperty(name="Gap", description="The space left between islands", default=0.005, min=0.0, max=1.0, precision=3, step=0.1)
    iterations: bpy.props.IntProperty(name="Iterations", description="How long Relax keeps going", default=40, min=1, max=1000)
    angle: bpy.props.FloatProperty(name="Angle", description="Polygons that meet at more than this are cut apart", default=math.radians(66), min=0.0,
                                   max=math.radians(89), subtype="ANGLE")
    area_weight: bpy.props.FloatProperty(name="Area Weight", description="How much larger polygons decide the directions", default=0.0, min=0.0, max=1.0,
                                         subtype="FACTOR")
    rotate: bpy.props.BoolProperty(name="Rotate", description="Turn islands so that they fit better", default=True)
    scale: bpy.props.BoolProperty(name="Scale", description="Scale the islands to fill the tile", default=True)
    shape: bpy.props.EnumProperty(name="Shape", description="How closely the islands' outlines are followed when packed", default="CONCAVE", items=[
        ("CONCAVE", "Exact", "Follow the outline, hollows too"), ("CONVEX", "Convex", "Follow the outline without its hollows"),
        ("AABB", "Box", "Use the box around each island")])
    projection: bpy.props.EnumProperty(name="Projection", description="The shape the UVs are projected from", default="CUBE", items=[
        ("CUBE", "Cubic", "From the six sides of a cube"), ("CYLINDER", "Cylindrical", "From a cylinder around the object"),
        ("SPHERE", "Spherical", "From a sphere around the object"), ("VIEW", "From View", "From the viewport, as you see it now")])
    tiles: bpy.props.EnumProperty(name="UDIM Tile", description="Which UDIM tile the islands are packed into", default="CLOSEST_UDIM", items=[
        ("CLOSEST_UDIM", "Nearest UDIM Tile", "The UDIM tile nearest the islands (Blender: Closest UDIM)"),
        ("ACTIVE_UDIM", "UDIM Tile at the 2D Cursor", "The UDIM tile the UV editor's 2D cursor is on (Blender: Active UDIM)"),
        ("ORIGINAL_AABB", "Where They Are", "Each group stays in the space it already takes up (Blender: Original Bounding Box)")])
    tiles_x: bpy.props.IntProperty(name="UDIM Tiles Across", description="How many UDIM tiles the UV view shows across, and a new UDIM "
                                   "texture gets", default=1, min=1, max=10, update=lambda self, c: _grid(c))
    tiles_y: bpy.props.IntProperty(name="UDIM Tiles Down", description="How many rows of UDIM tiles the UV view shows, and a new UDIM "
                                   "texture gets", default=1, min=1, max=10, update=lambda self, c: _grid(c))
    tile_size: bpy.props.EnumProperty(name="Tile Size", description="Pixels per side of each UDIM tile of a new UDIM texture", default="2048",
                                      items=[(v, v, "") for v in ("1024", "2048", "4096")])
    angle_step: bpy.props.FloatProperty(name="Step", description="How far Rotate turns", default=math.radians(90), min=0.0, max=math.pi, subtype="ANGLE")


# --- the commands --------------------------------------------------------------------------------------------------------------
def _flat(meshes, everything):
    """Do the UVs worked on cover no area at all (all on one spot)?"""
    for ob in meshes:
        bm = bmesh.from_edit_mesh(ob.data)
        lay = bm.loops.layers.uv.active
        if lay is None:
            continue
        us = [lo[lay].uv[:] for f in bm.faces if (everything or f.select) and not f.hide for lo in f.loops]
        if us and (max(u for u, _v in us) - min(u for u, _v in us) > 1e-6 or max(v for _u, v in us) - min(v for _u, v in us) > 1e-6):
            return False
    return True


def _op(name, **kw):
    mod, op = name.split(".")
    return getattr(getattr(bpy.ops, mod), op)("EXEC_DEFAULT", False, **kw)


def _transform(kind, value):
    def run(context, s):
        v = value(s) if callable(value) else value
        kw = {"orient_axis": "Z"} if kind == "rotate" else {}
        return _op("transform." + kind, value=v, **kw)
    return run


def _project(context, s):
    if s.projection == "VIEW":
        return _op("uv.project_from_view", correct_aspect=True, scale_to_bounds=False)
    return _op({"CUBE": "uv.cube_project", "CYLINDER": "uv.cylinder_project", "SPHERE": "uv.sphere_project"}[s.projection])


def _fit(keep):
    """The UVs fill the tile: in proportion (keep) or stretched to all four sides."""
    def run(context, s):
        done = False
        for ob in _meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            lay = bm.loops.layers.uv.active
            loops = [lo for f in bm.faces if f.select and not f.hide for lo in f.loops] if lay else []
            if not loops:
                continue
            us, vs = [lo[lay].uv.x for lo in loops], [lo[lay].uv.y for lo in loops]
            u0, v0, w, h = min(us), min(vs), max(us) - min(us), max(vs) - min(vs)
            fu, fv = 1 / w if w > 1e-9 else 1.0, 1 / h if h > 1e-9 else 1.0
            if keep:
                fu = fv = min(f for f in (fu, fv))
            du, dv = ((1 - w * fu) / 2, (1 - h * fv) / 2) if keep else (0.0, 0.0)
            for lo in loops:
                uv = lo[lay].uv
                uv.x, uv.y = (uv.x - u0) * fu + du, (uv.y - v0) * fv + dv
            bmesh.update_edit_mesh(ob.data)
            done = True
        return {"FINISHED"} if done else {"CANCELLED"}
    return run


def _disconnect(context, s):
    """The selected polygons come off their neighbors, with the page's gap between them."""
    done = False
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        lay = bm.loops.layers.uv.active
        left = {f for f in bm.faces if f.select and not f.hide} if lay else set()
        while left:
            group, todo = set(), [left.pop()]
            while todo:                                    # polygons that stay together
                f = todo.pop()
                group.add(f)
                for e in f.edges:
                    for g in e.link_faces:
                        if g in left:
                            left.discard(g)
                            todo.append(g)
            loops = [lo for f in group for lo in f.loops]
            us, vs = [lo[lay].uv.x for lo in loops], [lo[lay].uv.y for lo in loops]
            cu, cv, size = (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2, max(max(us) - min(us), max(vs) - min(vs))
            if size < 1e-9:
                continue
            k = max(0.5, 1 - 2 * max(s.margin, 0.0005) / size)
            for lo in loops:
                uv = lo[lay].uv
                uv.x, uv.y = cu + (uv.x - cu) * k, cv + (uv.y - cv) * k
            done = True
        bmesh.update_edit_mesh(ob.data)
    return {"FINISHED"} if done else {"CANCELLED"}


def _pinned(context, s):
    if not context.scene.tool_settings.use_uv_select_sync:
        return _op("uv.select_pinned")
    bpy.ops.mesh.select_mode(type="VERT")                  # one selection: the points the pins are on
    done = False
    for ob in _meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        lay = bm.loops.layers.uv.active
        for f in bm.faces if lay else ():
            for lo in f.loops:
                if lo[lay].pin_uv and not lo.vert.hide:
                    lo.vert.select = done = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data)
    return {"FINISHED"} if done else {"CANCELLED"}


def _unwrap(context, s):
    kw = {"method": s.method, "fill_holes": s.fill_holes, "margin": s.margin}
    if s.method == "MINIMUM_STRETCH":
        kw["iterations"] = s.iterations
    return _op("uv.unwrap", **kw)


# key: (name, Blender's name, icon, what it does, where: UV / VIEW, needs polygons selected (all when none is), function)
C = {
    "SEAM": ("Mark Seam", "", "EDGESEL", "Cut the UVs apart along the selected edges when they are unwrapped", "VIEW", False, lambda c, s: _op("mesh.mark_seam", clear=False)),
    "CLEAR_SEAM": ("Clear Seam", "", "X", "The selected edges are no seams any more", "VIEW", False, lambda c, s: _op("mesh.mark_seam", clear=True)),
    "ISLAND_SEAMS": ("Islands to Seams", "Seams from Islands", "MOD_EDGESPLIT", "Make seams of the outlines of the UV islands", "UV", True, lambda c, s: _op("uv.seams_from_islands")),
    "UNWRAP": ("Unwrap", "", "UV", "Unfold the polygons along their seams", "UV", True, _unwrap),
    "RELAX": ("Relax", "Minimize Stretch", "MOD_SMOOTH", "Even out what is stretched. Pinned points stay where they are", "UV", True,
              lambda c, s: _op("uv.minimize_stretch", fill_holes=s.fill_holes, iterations=s.iterations)),
    "AUTO": ("Automatic UV", "Smart UV Project", "MOD_UVPROJECT", "UVs for any shape, without seams of your own", "UV", True,
             lambda c, s: _op("uv.smart_project", angle_limit=s.angle, island_margin=s.margin, area_weight=s.area_weight)),
    "PROJECT": ("UV Projection", "", "PROP_PROJECTED", "Project the UVs from the shape chosen on the UV page", "VIEW", True, _project),
    "SPLIT": ("Disconnect UVs", "", "UNLINKED", "Cut the selected polygons off their neighbors in the UVs, with the gap set on the UV page", "UV", False, _disconnect),
    "STITCH": ("Sew UVs", "Stitch", "LINKED", "Bring UV islands together along the selected edges", "UV", False,
               lambda c, s: _op("uv.stitch", use_limit=False, snap_islands=True, clear_seams=True, mode="EDGE" if c.tool_settings.mesh_select_mode[1] else "VERTEX")),
    "WELD": ("Weld UVs", "Weld", "AUTOMERGE_ON", "Put the selected UV points on one spot", "UV", False, lambda c, s: _op("uv.weld")),
    "STRAIGHTEN": ("Straighten", "Align, Straighten", "IPO_LINEAR", "Put the selected edges on a straight line", "UV", False, lambda c, s: _op("uv.align", axis="ALIGN_S")),
    "ALIGN": ("Align Island", "Align Rotation", "ALIGN_JUSTIFY", "Turn the islands so that their edges run straight up or across", "UV", True, lambda c, s: _op("uv.align_rotation")),
    "RECT": ("Rectangularize", "Follow Active Quads", "MESH_GRID", "Lay the four-sided polygons out as an even grid, from the one picked last", "UV", True,
             lambda c, s: _op("uv.follow_active_quads")),
    "PIN": ("Add Pins", "Pin", "PINNED", "Unwrap and Relax leave the selected UV points where they are", "UV", False, lambda c, s: _op("uv.pin", clear=False)),
    "UNPIN": ("Remove Pins", "Unpin", "UNPINNED", "Let the selected UV points move again", "UV", False, lambda c, s: _op("uv.pin", clear=True)),
    "PACK": ("Pack", "Pack Islands", "PACKAGE", "Arrange the islands to fill the tile", "UV", True,
             lambda c, s: _op("uv.pack_islands", rotate=s.rotate, scale=s.scale, margin=s.margin, shape_method=s.shape,
                              udim_source=s.tiles)),
    "AVERAGE": ("Even Scale", "Average Islands Scale", "FULLSCREEN_EXIT", "Give all islands the same texture size", "UV", True, lambda c, s: _op("uv.average_islands_scale")),
    "MAX": ("Max UV", "", "FULLSCREEN_ENTER", "Enlarge the UVs until they touch the sides of the tile", "UV", True, _fit(True)),
    "FIT": ("Fit to Canvas", "", "CON_SIZELIKE", "Stretch the UVs to all four sides of the tile", "UV", True, _fit(False)),
    "LEFT": ("Rotate Left", "", "LOOP_BACK", "Turn the selected UVs to the left", "UV", True, _transform("rotate", lambda s: -s.angle_step)),
    "RIGHT": ("Rotate Right", "", "LOOP_FORWARDS", "Turn the selected UVs to the right", "UV", True, _transform("rotate", lambda s: s.angle_step)),
    "FLIP_U": ("Flip U", "Mirror X", "EVENT_U", "Flip the selected UVs from left to right", "UV", True, _transform("resize", (-1.0, 1.0, 1.0))),
    "FLIP_V": ("Flip V", "Mirror Y", "EVENT_V", "Flip the selected UVs upside down", "UV", True, _transform("resize", (1.0, -1.0, 1.0))),
    "TILE_L": ("Tile Left", "", "TRIA_LEFT", "Move the selected UVs to the UDIM tile at the left", "UV", True, _transform("translate", (-1.0, 0.0, 0.0))),
    "TILE_R": ("Tile Right", "", "TRIA_RIGHT", "Move the selected UVs to the UDIM tile at the right", "UV", True, _transform("translate", (1.0, 0.0, 0.0))),
    "TILE_U": ("Tile Up", "", "TRIA_UP", "Move the selected UVs to the UDIM tile above", "UV", True, _transform("translate", (0.0, 1.0, 0.0))),
    "TILE_D": ("Tile Down", "", "TRIA_DOWN", "Move the selected UVs to the UDIM tile below", "UV", True, _transform("translate", (0.0, -1.0, 0.0))),
    "LINKED": ("Select Connected UV", "Select Linked", "SNAP_FACE", "Select the whole islands of what is selected", "UV", False, lambda c, s: _op("uv.select_linked")),
    "OVERLAP": ("Select Overlapping", "", "SELECT_INTERSECT", "Select UVs that lie on top of each other", "UV", False, lambda c, s: _op("uv.select_overlap")),
    "PINNED": ("Select Pinned", "", "PINNED", "Select the pinned UV points", "UV", False, _pinned),
}
ROW = [["SEAM", "CLEAR_SEAM"], ["UNWRAP", "RELAX", "AUTO", "PROJECT"], ["SPLIT", "STITCH", "WELD"], ["STRAIGHTEN", "ALIGN", "RECT"],
       ["PIN", "UNPIN"], ["PACK", "AVERAGE", "MAX", "FIT"], ["LEFT", "RIGHT", "FLIP_U", "FLIP_V"], ["LINKED", "OVERLAP"]]
if bpy.app.version < (5, 3, 0):  # Blender 5.2 itself crashes on this one
    C.pop("OVERLAP")
    ROW[-1].remove("OVERLAP")


# --- UDIM tiles: a texture made of numbered tiles (1001, 1002, ... ten per row), the UVs spread over them -----------------------
def _grid(context):
    """Show the chosen number of tiles as a grid in the UV view."""
    area = editor(context.screen) if context.screen else None
    if area is not None:
        s = context.scene.blenda4d_uv
        area.spaces.active.uv_editor.tile_grid_shape = (s.tiles_x, s.tiles_y)
        try:                                          # frame every UDIM tile
            with context.temp_override(window=context.window, area=area, region=_region(area)):
                bpy.ops.image.view_all(fit_view=True)
        except RuntimeError:
            pass
        area.tag_redraw()


def tile_numbers(across, down):
    return [1001 + u + 10 * v for v in range(down) for u in range(across)]


def _shown_image(context):
    area = editor(context.screen)
    return area, (area.spaces.active.image if area is not None else None)


def _use_on_material(ob, img):
    """Put the UDIM texture in the object's material as its Color (a new material when it has none)."""
    mat = ob.active_material
    if mat is None:
        mat = bpy.data.materials.new("UDIM Material")
        ob.data.materials.append(mat)
    mat.use_nodes = True
    tree = mat.node_tree
    shader = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    tex = next((n for n in tree.nodes if n.type == "TEX_IMAGE" and n.image is not None and n.image.source == "TILED"), None)
    if tex is None:
        tex = tree.nodes.new("ShaderNodeTexImage")
        if shader is not None:
            tex.location = shader.location.x - 320, shader.location.y
            if not shader.inputs["Base Color"].is_linked:
                tree.links.new(tex.outputs["Color"], shader.inputs["Base Color"])
    tex.image = img
    tree.nodes.active = tex


def _add_tiles(context, area, img, numbers, size):
    have = {t.number for t in img.tiles}
    with context.temp_override(window=context.window, area=area, region=_region(area)):
        for n in numbers:
            if n not in have:
                bpy.ops.image.tile_add(number=n, count=1, fill=True, generated_type="UV_GRID", width=size, height=size)
    return len([n for n in numbers if n not in have])


class BLENDA4D_OT_uv_tiles(bpy.types.Operator):
    bl_idname = "blenda4d.uv_tiles"
    bl_label = "UDIM Tiles"
    bl_options = {"REGISTER", "UNDO"}
    what: bpy.props.EnumProperty(items=[("NEW", "New UDIM Texture", ""), ("FILL", "Add Missing UDIM Tiles", "")], options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return {"NEW": "Make a UDIM texture with as many UDIM tiles as Across and Down, a test grid on each, and use it as "
                       "the material's color (Blender: Tiled image)",
                "FILL": "Give the UDIM texture shown a UDIM tile for every square of the grid that has none"}[props.what]

    @classmethod
    def poll(cls, context):
        return editor(context.screen) is not None and context.view_layer.objects.active is not None \
            and context.view_layer.objects.active.type == "MESH"

    def execute(self, context):
        s = context.scene.blenda4d_uv
        size = int(s.tile_size)
        area, img = _shown_image(context)
        if self.what == "NEW":
            ob = context.view_layer.objects.active
            with context.temp_override(window=context.window, area=area, region=_region(area)):
                bpy.ops.image.new(name=f"{ob.name} UDIM", width=size, height=size, generated_type="UV_GRID", tiled=True)
            img = area.spaces.active.image
            _add_tiles(context, area, img, tile_numbers(s.tiles_x, s.tiles_y), size)
            _use_on_material(ob, img)
            _state.pop("key", None)
        else:
            if img is None or img.source != "TILED":
                self.report({"INFO"}, "The texture shown has no UDIM tiles: make a New UDIM Texture first")
                return {"CANCELLED"}
            n = _add_tiles(context, area, img, tile_numbers(s.tiles_x, s.tiles_y), size)
            self.report({"INFO"}, f"{n} UDIM tile{'s' if n != 1 else ''} added")
        _grid(context)
        return {"FINISHED"}


class BLENDA4D_OT_uv_do(bpy.types.Operator):
    bl_idname = "blenda4d.uv_do"
    bl_label = "UV Command"
    bl_options = {"REGISTER", "UNDO"}
    what: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and editor(context.screen) is not None

    @classmethod
    def description(cls, context, props):
        c = C.get(props.what)
        return f"{c[0]}{f' ({c[1]})' if c[1] else ''}: {c[3]}" if c else cls.bl_label

    def execute(self, context):
        from . import build
        c, s = C.get(self.what), context.scene.blenda4d_uv
        if c is None:
            return {"CANCELLED"}
        meshes = _meshes(context)
        for ob in meshes:                                  # an object without UVs gets its first ones
            if not ob.data.uv_layers:
                ob.data.uv_layers.new(name="UVMap")
        everything = c[5] and not any(ob.data.total_face_sel for ob in meshes)
        if self.what in {"PACK", "AVERAGE", "MAX", "FIT"} and _flat(meshes, everything):
            self.report({"INFO"}, f"{c[0]}: the UVs lie on one spot; unwrap them first")   # Blender itself can crash on these
            return {"CANCELLED"}
        area = build.biggest_view(context.screen) if c[4] == "VIEW" else editor(context.screen)
        try:
            with context.temp_override(window=context.window, area=area, region=_region(area)):
                if everything:
                    bpy.ops.mesh.select_all(action="SELECT")
                done = c[6](bpy.context, s)
        except RuntimeError as ex:
            self.report({"WARNING"}, f"{c[0]}: " + str(ex).strip().splitlines()[0].replace("Error: ", ""))
            done = {"CANCELLED"}
        if everything:
            with context.temp_override(window=context.window, area=area, region=_region(area)):
                bpy.ops.mesh.select_all(action="DESELECT")
        for a in context.screen.areas:
            a.tag_redraw()
        return {"FINISHED"} if "FINISHED" in done else {"CANCELLED"}


def _button(row, key, text=""):
    c = C[key]
    row.operator("blenda4d.uv_do", text=text, icon=c[2]).what = key


# --- the row of tools below the UV Editor ----------------------------------------------------------------------------------------
BUTTON, GAP = 1.3, 0.45      # in Blender's button units


def _more(self, context):
    for key in _rest:
        _button(self.layout, key, C[key][0])


_rest = []


class BLENDA4D_MT_uv_more(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_uv_more"
    bl_label = "More UV Tools"
    bl_description = "The UV tools that do not fit in the row"
    draw = _more


class BLENDA4D_PT_uv_bar(roles.RolePanel, bpy.types.Panel):
    bl_label = "UV Tools"
    role = BAR

    def draw(self, context):
        row = self.layout.row(align=False)
        row.alignment = "LEFT"
        row.scale_y = 1.3
        why = why_not(context)
        if why:
            row.label(text=why, icon="INFO")
            ob = context.view_layer.objects.active
            if ob is not None and ob.type == "MESH":
                if "b4d_type" in ob:
                    row.operator("blenda4d.make_editable", text="Make Editable", icon="MESH_DATA")
                else:
                    row.operator("blenda4d.set_mode", text="Polygons", icon="FACESEL").mode = "POLYGONS"
            return
        free = context.region.width / (20.0 * context.preferences.system.ui_scale) - 1.2
        total = sum(len(g) for g in ROW) * BUTTON + GAP * (len(ROW) - 1)
        fits, used, rest = [], (0 if total <= free else BUTTON + GAP), []
        for g in ROW:
            need = len(g) * BUTTON + GAP
            if rest or used + need - (GAP if total <= free else 0) > free:
                rest += g
            else:
                fits.append(g)
                used += need
        _rest[:] = rest
        for g in fits:
            part = row.row(align=True)
            part.scale_x = BUTTON
            for key in g:
                _button(part, key)
        if rest:
            part = row.row(align=True)
            part.emboss = "NONE"
            part.menu(BLENDA4D_MT_uv_more.bl_idname, text="", icon="RIGHTARROW_THIN")


# --- the editor's header ------------------------------------------------------------------------------------------------------------
class BLENDA4D_MT_uv_tools(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_uv_tools"
    bl_label = "UV"
    bl_description = "The UV commands"

    def draw(self, context):
        for n, g in enumerate(ROW + [["TILE_L", "TILE_R", "TILE_U", "TILE_D"]]):
            if n:
                self.layout.separator()
            for key in g:
                _button(self.layout, key, C[key][0])
        self.layout.separator()
        _button(self.layout, "ISLAND_SEAMS", C["ISLAND_SEAMS"][0])
        self.layout.operator("uv.export_layout", text="Export UV Layout...", icon="EXPORT")


class BLENDA4D_MT_uv_select(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_uv_select"
    bl_label = "Select"
    bl_description = "Select UVs"

    def draw(self, context):
        lay = self.layout
        lay.operator("uv.select_all", text="Select All").action = "SELECT"
        lay.operator("uv.select_all", text="Deselect All").action = "DESELECT"
        lay.operator("uv.select_all", text="Invert").action = "INVERT"
        lay.separator()
        for key in ("LINKED", "OVERLAP", "PINNED"):
            if key in C:
                _button(lay, key, C[key][0])
        lay.separator()
        lay.operator("uv.select_more", text="Grow Selection")
        lay.operator("uv.select_less", text="Shrink Selection")


class BLENDA4D_MT_uv_file(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_uv_file"
    bl_label = "File"
    bl_description = "The texture behind the UVs"

    def draw(self, context):
        lay = self.layout
        lay.operator("image.open", text="Open Texture...", icon="FILE_FOLDER")
        lay.operator("image.new", text="New Texture...", icon="ADD")
        lay.operator("image.save", text="Save Texture", icon="FILE_TICK")
        lay.operator("image.save_as", text="Save Texture as...")
        lay.separator()
        lay.operator("uv.export_layout", text="Export UV Layout...", icon="EXPORT")


class BLENDA4D_MT_uv_view(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_uv_view"
    bl_label = "View"
    bl_description = "What the UV Editor shows"

    def draw(self, context):
        lay, uv = self.layout, context.space_data.uv_editor
        lay.operator("image.view_all", text="Frame Tile").fit_view = True
        lay.operator("image.view_selected", text="Frame Selected Elements")
        lay.operator("image.view_zoom_ratio", text="100%").ratio = 1.0
        lay.separator()
        for attr, text in (("show_stretch", "Show Distortion"), ("show_modified_edges", "Show Deformed UVs"), ("show_faces", "Show Polygons"),
                           ("show_pixel_coords", "Pixel Coordinates")):
            if hasattr(uv, attr):
                lay.prop(uv, attr, text=text)
        if hasattr(uv, "tile_grid_shape"):
            lay.prop(uv, "tile_grid_shape", text="Tiles", index=0)
            lay.prop(uv, "tile_grid_shape", text="Tiles Up", index=1)
        lay.separator()
        lay.prop(context.scene.tool_settings, "use_uv_select_sync", text="Same Selection as the Viewport")


def header(self, context):
    lay, sp, ts = self.layout, context.space_data, context.scene.tool_settings
    lay.label(text="UV", icon="UV")
    row = lay.row(align=True)
    for m in (BLENDA4D_MT_uv_file, BLENDA4D_MT_uv_view, BLENDA4D_MT_uv_select, BLENDA4D_MT_uv_tools):
        row.menu(m.bl_idname, text=m.bl_label)
    if context.mode == "EDIT_MESH" and not ts.use_uv_select_sync:
        sub = lay.row(align=True)
        sub.prop(ts, "uv_select_mode", text="", expand=True)
    lay.separator_spacer()
    sub = lay.row(align=True)
    sub.ui_units_x = 6
    sub.template_ID(sp, "image", open="image.open")
    lay.prop(sp.uv_editor, "show_stretch", text="", icon="MOD_UVPROJECT", toggle=True)
    lay.prop(ts, "use_uv_select_sync", text="", icon="UV_SYNC_SELECT", toggle=True)


# --- the UV page in the Attribute Manager --------------------------------------------------------------------------------------------
def page(col, context, ob):
    s = context.scene.blenda4d_uv
    ready = not why_not(context)
    me = ob.data

    def line(*keys):
        row = col.row(align=True)
        row.enabled = ready
        for k in keys:
            _button(row, k, C[k][0])
    col.use_property_split = False
    col.label(text="UV Sets")
    row = col.row()
    row.template_list("MESH_UL_uvmaps", "b4d_uv", me, "uv_layers", me.uv_layers, "active_index", rows=2)
    side = row.column(align=True)
    side.operator("mesh.uv_texture_add", text="", icon="ADD")
    side.operator("mesh.uv_texture_remove", text="", icon="REMOVE")
    col.use_property_split = True
    col.use_property_decorate = False
    col.separator()
    col.label(text="Unwrap and Relax")
    col.prop(s, "method")
    col.prop(s, "fill_holes")
    col.prop(s, "iterations")
    col.prop(s, "margin")
    line("UNWRAP", "RELAX")
    col.separator()
    col.label(text="Automatic UV")
    col.prop(s, "angle")
    col.prop(s, "area_weight")
    line("AUTO")
    col.separator()
    col.label(text="UV Projection")
    col.prop(s, "projection")
    line("PROJECT")
    col.separator()
    col.label(text="Pack")
    col.prop(s, "shape")
    col.prop(s, "rotate")
    col.prop(s, "scale")
    col.prop(s, "tiles", text="Pack Into")
    line("PACK", "AVERAGE")
    col.separator()
    col.label(text="UDIM Tiles")
    col.prop(s, "tiles_x", text="Across")
    col.prop(s, "tiles_y", text="Down")
    col.prop(s, "tile_size")
    row = col.row(align=True)
    row.operator("blenda4d.uv_tiles", text="New UDIM Texture", icon="IMAGE").what = "NEW"
    row.operator("blenda4d.uv_tiles", text="Add Missing UDIM Tiles", icon="ADD").what = "FILL"
    _area, img = _shown_image(context)
    if img is not None and img.source == "TILED":
        nums = sorted(t.number for t in img.tiles)
        col.label(text=f"{img.name}: {len(nums)} UDIM tile{'s' if len(nums) != 1 else ''}, {nums[0]} to {nums[-1]}", icon="IMAGE")
    col.separator()
    col.label(text="Transform")
    col.prop(s, "angle_step")
    line("LEFT", "RIGHT")
    line("FLIP_U", "FLIP_V")
    line("TILE_L", "TILE_R")
    line("TILE_U", "TILE_D")
    line("MAX", "FIT")


# --- the texture behind the UVs: the active material's picture -------------------------------------------------------------------------
_state = {}


def _picture(ob):
    mat = ob.active_material if ob is not None and ob.type == "MESH" else None
    tree = mat.node_tree if mat is not None else None
    if tree is None:
        return None
    images = [n for n in tree.nodes if n.type == "TEX_IMAGE" and n.image is not None]
    pick = next((n for n in images if n == tree.nodes.active), None) or next(
        (n for n in images if any(lk.to_socket.name == "Base Color" for o in n.outputs for lk in o.links)), None) or (images[0] if images else None)
    return pick.image if pick is not None else None


def _watch():
    context = bpy.context
    if not docked(context):
        return
    ob, sp = context.view_layer.objects.active, context.space_data
    key = (ob.name if ob else "", ob.active_material.name if ob is not None and getattr(ob, "active_material", None) else "")
    if _state.get("key") == key:
        return
    _state["key"] = key
    img = _picture(ob)
    if img is None or sp.image == img or sp.use_image_pin:
        return

    area = context.area

    def put():
        if not roles.alive(area):
            return None
        try:
            sp.image = img
        except (ReferenceError, AttributeError):
            pass
        return None
    bpy.app.timers.register(put, first_interval=0.0)


@bpy.app.handlers.persistent
def _loaded(*_args):
    _state.clear()


classes = (BLENDA4D_PG_uv, BLENDA4D_OT_uv_do, BLENDA4D_OT_uv_tiles, BLENDA4D_MT_uv_more, BLENDA4D_PT_uv_bar, BLENDA4D_MT_uv_tools, BLENDA4D_MT_uv_select,
           BLENDA4D_MT_uv_file, BLENDA4D_MT_uv_view)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.blenda4d_uv = bpy.props.PointerProperty(type=BLENDA4D_PG_uv)
    _handles.append(bpy.types.SpaceImageEditor.draw_handler_add(_watch, (), "WINDOW", "POST_PIXEL"))
    bpy.app.handlers.load_post.append(_loaded)


def unregister():
    while _handles:
        bpy.types.SpaceImageEditor.draw_handler_remove(_handles.pop(), "WINDOW")
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    if hasattr(bpy.types.Scene, "blenda4d_uv"):
        del bpy.types.Scene.blenda4d_uv
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
