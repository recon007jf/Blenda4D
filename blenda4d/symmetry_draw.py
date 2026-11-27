# SPDX-License-Identifier: GPL-3.0-or-later
"""Symmetry you can see, on top of Blender's mesh symmetry (which only mirrors moves of existing points).

While a mesh is edited with Symmetry on:
- the selection is kept mirrored: picking an element also selects its partner on the other side, so every tool
  (extrude, inset, bevel, delete, ...) works on both sides; Blender moves the two sides as mirror images;
- Extrude grows each picked group straight out along its own normal, on both sides;
- a see-through plane marks each mirror, in its axis colour, and the partners of what was picked are drawn in blue.

With or without Symmetry, Extrude (D) and Inset (I) drag from anywhere in the view: right raises the
offset, left lowers it and goes negative. Inset shrinks each group as a whole and flares it out when negative.
"""
import itertools
import math
import traceback

import bmesh
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

# Blender's mirror switch, the local axis it flips, the colour of the axis as Blenda shows it (Blender's Y is Blenda's Z)
AXES = (("use_mirror_x", 0, (0.95, 0.27, 0.27)), ("use_mirror_y", 1, (0.27, 0.5, 0.98)), ("use_mirror_z", 2, (0.4, 0.85, 0.35)))
TWIN = (0.3, 0.62, 1.0)
TOO_MANY = 250000            # points; past this the selection isn't mirrored, to keep editing quick
REGION_EXTRUDE, NORMAL_EXTRUDE, INSET = "builtin.extrude_region", "builtin.extrude_along_normals", "builtin.inset_faces"

_handle = []
_state = {"sig": None, "side": {}, "swapped": False, "pivot": None, "gizmo": {}, "watching": False}


def axes_on(me):
    return [i for attr, i, _ in AXES if getattr(me, attr)]


def _flips(axes):
    """Every combination of the switched-on mirrors, as the per-axis signs a point is multiplied by."""
    out = []
    for n in range(1, len(axes) + 1):
        for combo in itertools.combinations(axes, n):
            s = [1.0, 1.0, 1.0]
            for i in combo:
                s[i] = -1.0
            out.append(Vector(s))
    return out


def _size(ob):
    box = [Vector(c) for c in ob.bound_box]
    return max(max(c[k] for c in box) - min(c[k] for c in box) for k in range(3)) or 1.0


def _centre(e):
    if isinstance(e, bmesh.types.BMFace):
        return e.calc_center_median()
    if isinstance(e, bmesh.types.BMVert):
        return Vector(e.co)
    return (e.verts[0].co + e.verts[1].co) / 2


def mirror_selection(ob, select_mode):
    """Select the partner of every selected element. Returns the side (per axis, +1 or -1) the fresh picks are on."""
    me = ob.data
    axes = axes_on(me)
    bm = bmesh.from_edit_mesh(me)
    if not axes or len(bm.verts) > TOO_MANY:
        return None
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    kd = KDTree(len(bm.verts))
    for v in bm.verts:
        kd.insert(v.co, v.index)
    kd.balance()
    tol = max(_size(ob) * 1e-4, 1e-6)

    def partner(v, s):
        co, i, d = kd.find(Vector(v.co) * s)
        return bm.verts[i] if i is not None and d <= tol else None

    def twin(e, s):
        if isinstance(e, bmesh.types.BMVert):
            return partner(e, s)
        ps = [partner(v, s) for v in e.verts]
        if None in ps:
            return None
        if isinstance(e, bmesh.types.BMEdge):
            return bm.edges.get(ps)
        common = set(ps[0].link_faces)
        for p in ps[1:]:
            common &= set(p.link_faces)
        return next((f for f in common if len(f.verts) == len(ps)), None)

    flips = _flips(axes)
    if select_mode[2]:
        picked = [f for f in bm.faces if f.select]
    elif select_mode[1]:
        picked = [e for e in bm.edges if e.select]
    else:
        picked = [v for v in bm.verts if v.select]
    fresh, add = [], []
    for e in picked:
        alone = False
        for s in flips:
            other = twin(e, s)
            if other is not None and other is not e and not other.select:
                alone = True
                add.append(other)
        if alone:
            fresh.append(e)
    for e in add:
        e.select_set(True)
    if add:
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    if not fresh:
        return None
    mid = sum((_centre(e) for e in fresh), Vector()) / len(fresh)
    hist = bm.select_history
    if not isinstance(hist.active, type(fresh[0])) or hist.active not in fresh:
        hist.add(min(fresh, key=lambda e: (_centre(e) - mid).length))   # the handles sit on the picked side
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return tuple(1.0 if mid[i] >= 0 else -1.0 for i in range(3))


# --- keeping things in step while editing ---------------------------------------------------------------------------
def _viewport():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                r = next((r for r in a.regions if r.type == "WINDOW"), None)
                if r is not None:
                    return w, a, r
    return None


def _busy():
    """Something is being dragged (our own drag watcher doesn't count)."""
    for w in bpy.context.window_manager.windows:
        for op in getattr(w, "modal_operators", ()):
            if getattr(op, "bl_idname", "") not in ("BLENDA4D_OT_symmetry_drag_watch", "blenda4d.symmetry_drag_watch"):
                return True
    return False


def _set_tool(name):
    vp = _viewport()
    if vp is None:
        return
    w, a, r = vp
    with bpy.context.temp_override(window=w, area=a, region=r):
        bpy.ops.wm.tool_set_by_id(name=name)


def _tool(ctx):
    """The active Edit Mesh tool. A timer has no workspace in its context, so it is read through the window."""
    ws = ctx.workspace
    if ws is None:
        vp = _viewport()
        ws = vp[0].workspace if vp else None
    try:
        return ws.tools.from_space_view3d_mode("EDIT_MESH", create=False).idname
    except Exception:
        return ""


def _redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                a.tag_redraw()


def _tick():
    try:
        ctx = bpy.context
        ob = ctx.edit_object
        editing = ob is not None and ob.type == "MESH" and ctx.mode == "EDIT_MESH"
        on = editing and bool(axes_on(ob.data))
        if not _busy():                                   # never in the middle of a drag
            if on:
                me = ob.data
                sig = lambda: (ob.name, me.total_vert_sel, me.total_edge_sel, me.total_face_sel, len(me.vertices))
                if sig() != _state["sig"]:
                    side = mirror_selection(ob, ctx.tool_settings.mesh_select_mode)
                    if side is not None:
                        _state["side"][ob.name] = side
                    _state["sig"] = sig()
                    _redraw()
                if _tool(ctx) == REGION_EXTRUDE:
                    _set_tool(NORMAL_EXTRUDE)
                    _state["swapped"] = True
                _hide_handle(_state["swapped"] and _tool(ctx) == NORMAL_EXTRUDE)

                ts = ctx.scene.tool_settings
                if ts.transform_pivot_point != "ACTIVE_ELEMENT":    # handles on the picked side, not on the plane
                    _state["pivot"] = ts.transform_pivot_point
                    ts.transform_pivot_point = "ACTIVE_ELEMENT"
            else:
                _state["sig"] = None
                if _state["swapped"] and editing:
                    if _tool(ctx) == NORMAL_EXTRUDE:
                        _set_tool(REGION_EXTRUDE)
                    _state["swapped"] = False
                _restore_pivot(ctx)
                _hide_handle(False)
        if not _busy() and editing and standing_in(ctx) and not _state["watching"]:
            vp = _viewport()                              # Extrude and Inset drag anywhere, with or without Symmetry
            if vp is not None:
                with bpy.context.temp_override(window=vp[0], area=vp[1], region=vp[2]):
                    bpy.ops.blenda4d.symmetry_drag_watch("INVOKE_DEFAULT")
    except Exception:
        traceback.print_exc()                                 # keep the timer alive; the console shows what broke
    return 0.15


def _spaces():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                yield a.spaces.active


def _hide_handle(hide):
    """The stand-in extrude's handle points along the selection's average normal, which for two mirrored sides lies
    in the plane, so it is hidden while it stands in; the extrude is dragged anywhere in the view."""
    if hide:
        for sp in _spaces():
            key = sp.as_pointer()
            if key not in _state["gizmo"]:
                _state["gizmo"][key] = (sp.show_gizmo_tool, sp.show_gizmo_context)
            if sp.show_gizmo_tool or sp.show_gizmo_context:
                sp.show_gizmo_tool = sp.show_gizmo_context = False
    else:
        for sp in _spaces():
            was = _state["gizmo"].pop(sp.as_pointer(), None)
            if was is not None:
                sp.show_gizmo_tool, sp.show_gizmo_context = was
        _state["gizmo"].clear()


def _restore_pivot(ctx):
    if _state["pivot"] is not None:
        ts = ctx.scene.tool_settings
        if ts.transform_pivot_point == "ACTIVE_ELEMENT":
            ts.transform_pivot_point = _state["pivot"]
        _state["pivot"] = None


def shown_tool(name):
    """The tool the toolbar should show pressed: Extrude while Extrude Along Normals is standing in for it."""
    return REGION_EXTRUDE if name == NORMAL_EXTRUDE and _state["swapped"] else name


# --- drawing --------------------------------------------------------------------------------------------------------
def geometry(ob, select_mode, side=None):
    """(planes, twin) in world space. planes: [(colour, quad corners)]; twin: (triangles, lines, points) of the
    selected elements on the far side from where they were picked."""
    me = ob.data
    on = [(i, col) for attr, i, col in AXES if getattr(me, attr)]
    if not on:
        return [], ([], [], [])
    mw = ob.matrix_world
    box = [Vector(c) for c in ob.bound_box]
    lo = Vector([min(c[k] for c in box) for k in range(3)])
    hi = Vector([max(c[k] for c in box) for k in range(3)])
    size = max(max(hi - lo), 1e-4)
    pad = size * 0.15
    planes = []
    for i, col in on:
        j, k = [a for a in range(3) if a != i]
        quad = []
        for a, b in ((lo[j] - pad, lo[k] - pad), (hi[j] + pad, lo[k] - pad), (hi[j] + pad, hi[k] + pad), (lo[j] - pad, hi[k] + pad)):
            v = Vector((0.0, 0.0, 0.0))
            v[j], v[k] = a, b
            quad.append(mw @ v)
        planes.append((col, quad))

    tris, lines, points = [], [], []
    bm = bmesh.from_edit_mesh(me)
    if len(bm.verts) > TOO_MANY:
        return planes, (tris, lines, points)
    side = side or (1.0, 1.0, 1.0)
    eps = size * 1e-4
    far = lambda c: any(c[i] * side[i] < -eps for i, _ in on)
    lift = size * 0.002                                  # just off the surface, so the twin isn't lost in it
    if select_mode[2]:
        for f in bm.faces:
            if f.select and far(f.calc_center_median()):
                vs = [mw @ (Vector(v.co) + f.normal * lift) for v in f.verts]
                tris += [p for t in range(1, len(vs) - 1) for p in (vs[0], vs[t], vs[t + 1])]
                lines += [p for a, b in zip(vs, vs[1:] + vs[:1]) for p in (a, b)]
    elif select_mode[1]:
        for e in bm.edges:
            if e.select and far((e.verts[0].co + e.verts[1].co) / 2):
                lines += [mw @ Vector(v.co) for v in e.verts]
    else:
        for v in bm.verts:
            if v.select and far(v.co):
                points.append(mw @ Vector(v.co))
    return planes, (tris, lines, points)


def _draw():
    ctx = bpy.context
    ob = ctx.edit_object
    if ob is None or ob.type != "MESH" or ctx.mode != "EDIT_MESH" or not axes_on(ob.data):
        return
    planes, (tris, lines, points) = geometry(ob, ctx.tool_settings.mesh_select_mode, _state["side"].get(ob.name))
    if not getattr(ctx.window_manager, "b4d_sym_planes", True):
        planes = []
    region = ctx.region
    flat = gpu.shader.from_builtin("UNIFORM_COLOR")
    wide = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set("LESS_EQUAL")
    for col, quad in planes:
        flat.uniform_float("color", (*col, 0.16))
        batch_for_shader(flat, "TRIS", {"pos": quad}, indices=((0, 1, 2), (0, 2, 3))).draw(flat)
        wide.uniform_float("viewportSize", (region.width, region.height))
        wide.uniform_float("lineWidth", 1.5)
        wide.uniform_float("color", (*col, 0.8))
        batch_for_shader(wide, "LINES", {"pos": [p for a, b in zip(quad, quad[1:] + quad[:1]) for p in (a, b)]}).draw(wide)
    if tris:
        flat.uniform_float("color", (*TWIN, 0.55))
        batch_for_shader(flat, "TRIS", {"pos": tris}).draw(flat)
    if lines:
        wide.uniform_float("viewportSize", (region.width, region.height))
        wide.uniform_float("lineWidth", 2.0)
        wide.uniform_float("color", (*TWIN, 1.0))
        batch_for_shader(wide, "LINES", {"pos": lines}).draw(wide)
    if points:
        dots = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
        gpu.state.point_size_set(7.0)
        dots.uniform_float("color", (*TWIN, 1.0))
        batch_for_shader(dots, "POINTS", {"pos": points}).draw(dots)
        gpu.state.point_size_set(1.0)
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set("NONE")


# --- extruding both sides -------------------------------------------------------------------------------------------
def extrude_regions(ob):
    """Extrude the selected polygons. Returns (moves, new point numbers, original polygon numbers): moves are
    (point number, start place, normal of its region). Each connected region moves along its own normal, so mirrored
    regions move as mirror images. Numbers, not BMesh items, so nothing goes stale if the edit mesh is rebuilt."""
    bm = bmesh.from_edit_mesh(ob.data)
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return None
    ret = bmesh.ops.extrude_face_region(bm, geom=faces)
    tops = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
    new_verts = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    for f in faces:
        f.select_set(False)
    for f in tops:
        f.select_set(True)
    left, moves = set(tops), []
    while left:
        stack, region = [left.pop()], []
        while stack:
            f = stack.pop()
            region.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g in left:
                        left.discard(g)
                        stack.append(g)
        n = sum((f.normal for f in region), Vector())
        n = n.normalized() if n.length > 1e-9 else Vector((0.0, 0.0, 1.0))
        for v in {v for f in region for v in f.verts}:
            moves.append((v, v.co.copy(), n))
    bm.select_flush_mode()
    bm.verts.index_update()
    bm.faces.index_update()
    got = ([(v.index, start, n, len(bm.verts)) for v, start, n in moves], [v.index for v in new_verts], [f.index for f in faces])
    bmesh.update_edit_mesh(ob.data)
    return got


def place(ob, moves, d):
    """Move the extruded points; False if the edit mesh no longer has them."""
    bm = bmesh.from_edit_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    if not moves or moves[0][3] != len(bm.verts):       # reloaded underneath: these numbers mean other points now
        return False
    for i, start, n, _ in moves:
        bm.verts[i].co = start + n * d
    bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=False)
    return True


class BLENDA4D_OT_symmetry_extrude(bpy.types.Operator):
    bl_idname = "blenda4d.symmetry_extrude"
    bl_label = "Extrude"
    bl_description = "Extrude the selected polygons and their mirror images straight out along their normals: drag right for more, left for less"
    bl_options = {"REGISTER", "UNDO", "GRAB_CURSOR", "BLOCKING"}
    offset: bpy.props.FloatProperty(name="Offset", subtype="DISTANCE", default=0.0)

    @classmethod
    def poll(cls, context):
        ob = context.edit_object
        return ob is not None and ob.type == "MESH" and context.mode == "EDIT_MESH"

    def execute(self, context):                       # the redo panel: extrude again by the typed offset
        ob = context.edit_object
        got = extrude_regions(ob)
        if got is None:
            return {"CANCELLED"}
        place(ob, got[0], self.offset)               # placed while the point count still matches, then tidied
        self._finish(ob, got)
        return {"FINISHED"}

    def invoke(self, context, event):
        if not context.tool_settings.mesh_select_mode[2]:      # points and edges: Blender's own extrude
            return bpy.ops.mesh.extrude_region_shrink_fatten("INVOKE_DEFAULT")
        ob = context.edit_object
        got = extrude_regions(ob)
        if got is None:
            return {"CANCELLED"}
        self._got = got
        mw = ob.matrix_world
        bm = bmesh.from_edit_mesh(ob.data)
        e = bm.select_history.active
        moves = got[0]
        ids = {v.index for v in getattr(e, "verts", ())} if e is not None else set()
        pick = next((m for m in moves if m[0] in ids), moves[0])
        n_world = mw.to_3x3() @ pick[2]
        self._at = mw @ pick[1]
        self._axis = n_world.normalized()
        self._scale = max(n_world.length, 1e-9)        # world length of one local unit along the normal
        # dragging anywhere in the view: mouse movement along the arrow's direction on screen, a pixel for a pixel
        # at the arrow's depth (right or up when the arrow points at the viewer)
        from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
        region, rv3d = context.region, context.region_data
        xy = location_3d_to_region_2d(region, rv3d, self._at)
        self._dir, self._px = Vector((0.7071, 0.7071)), 0.01
        if xy is not None:
            p0 = region_2d_to_location_3d(region, rv3d, xy, self._at)
            p1 = region_2d_to_location_3d(region, rv3d, xy + Vector((1.0, 0.0)), self._at)
            self._px = max((p1 - p0).length, 1e-9)
            tip = location_3d_to_region_2d(region, rv3d, self._at + self._axis * self._px * 40.0)
            if tip is not None and (tip - xy).length > 12.0:    # under about 70 degrees to the view: follow the arrow
                self._dir = (tip - xy).normalized()
        self._mouse0 = Vector((event.mouse_x, event.mouse_y))
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        ob = context.edit_object
        if event.type == "MOUSEMOVE":
            # like an Offset slider: right is more, left is less (and then in), whichever way the polygons face
            self.offset = (event.mouse_x - self._mouse0.x) * self._px / self._scale
            if event.ctrl:
                self.offset = round(self.offset / 0.1) * 0.1
            if not place(ob, self._got[0], self.offset):
                context.area.header_text_set(None)
                return {"CANCELLED"}
            context.area.header_text_set(f"Extrude {bpy.utils.units.to_string(context.scene.unit_settings.system, 'LENGTH', self.offset * context.scene.unit_settings.scale_length)}")
        elif event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value in {"PRESS", "RELEASE"}:
            if event.type != "LEFTMOUSE" or event.value == "RELEASE" or event.value == "PRESS":
                self._finish(ob, self._got)
                context.area.header_text_set(None)
                return {"FINISHED"}
        elif event.type in {"RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            moves, new_verts, faces = self._got
            bm = bmesh.from_edit_mesh(ob.data)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            originals = [bm.faces[i] for i in faces if i < len(bm.faces)]
            bmesh.ops.delete(bm, geom=[bm.verts[i] for i in new_verts if i < len(bm.verts)], context="VERTS")
            for f in originals:
                if f.is_valid:
                    f.select_set(True)
            bm.select_flush_mode()
            bmesh.update_edit_mesh(ob.data)
            context.area.header_text_set(None)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    @staticmethod
    def _finish(ob, got):
        """The original polygons now sit inside the extrusion: take them out."""
        bm = bmesh.from_edit_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        # FACES, not FACES_ONLY: the group's inner edges and middle points go too (only its outline is still used)
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in got[2] if i < len(bm.faces)], context="FACES")
        bmesh.update_edit_mesh(ob.data)


def _groups(faces):
    left, out = set(faces), []
    while left:
        group, stack = set(), [left.pop()]
        while stack:
            f = stack.pop()
            group.add(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g in left:
                        left.discard(g)
                        stack.append(g)
        out.append(group)
    return out


def _inset_moves(faces, t):
    """Where every point of the selection goes: the outline slides t along its own polygons (in when t is
    positive, out when negative) at an even width, and the points inside follow smoothly so each group shrinks or
    grows as a whole instead of the outline running underneath it."""
    moves = {}
    for group in _groups(faces):
        n = sum((f.normal * f.calc_area() for f in group), Vector())
        n = n.normalized() if n.length > 1e-12 else Vector((0.0, 0.0, 1.0))
        u = n.orthogonal().normalized()
        w = n.cross(u)
        sides, outline = {}, []
        for f in group:
            for l in f.loops:
                e = l.edge
                if sum(g in group for g in e.link_faces) != 1:
                    continue
                a, b = l.vert, l.link_loop_next.vert              # face winding, so every loop runs the same way
                outline.append((a, b))
                d = b.co - a.co
                if d.length < 1e-12:
                    continue
                side = f.normal.cross(d.normalized())
                if side.dot(f.calc_center_median() - a.co) < 0:
                    side = -side
                for v in (a, b):
                    sides.setdefault(v, []).append(side)
        shift = {}
        for v, ss in sides.items():
            m = sum(ss, Vector())
            if m.length < 1e-9:
                shift[v] = Vector()
                continue
            m.normalize()
            cos = max(min(x.dot(m) for x in ss), 0.25)              # even width at corners, never more than 4x
            shift[v] = m * (t / cos)
        rise = sum((d.dot(n) for d in shift.values()), 0.0) / max(len(shift), 1)
        flat2 = lambda co: Vector((co.dot(u), co.dot(w)))
        inside = list(dict.fromkeys(v for f in group for v in f.verts if v not in shift))
        for v in inside:                                          # the inside follows the outline smoothly
            x = flat2(v.co)
            total, acc = 0.0, Vector()
            for a, b in outline:
                pa, pb = flat2(a.co) - x, flat2(b.co) - x
                la, lb = pa.length, pb.length
                if la < 1e-9 or lb < 1e-9:
                    continue
                ang = math.atan2(pa.x * pb.y - pa.y * pb.x, pa.dot(pb))
                tan = math.tan(ang / 2.0)
                for c, l in ((a, la), (b, lb)):
                    wt = tan / l
                    total += wt
                    acc += (shift[c] - n * shift[c].dot(n)) * wt
            flat = acc / total if abs(total) > 1e-12 else Vector()
            shift[v] = flat + n * rise                            # and rides with it, keeping its shape
        for v, d in shift.items():
            moves[v] = (v.co.copy(), d)
    return moves


def inset_start(ob):
    """Build the inset ring once, at no width, and say how each inner point moves: [(index, start, move per unit)],
    {new point: the point it came from}, the inset polygons. Nothing is cleared or rebuilt afterwards, so shape keys,
    UV maps and vertex groups stay as they were."""
    bm = bmesh.from_edit_mesh(ob.data)
    faces = [f for f in bm.faces if f.select]
    if not faces:
        return None
    unit = _inset_moves(faces, 1.0)
    places = [p for p, _ in unit.values()]
    dirs = [d for _, d in unit.values()]
    before = set(bm.verts)
    ring = bmesh.ops.inset_region(bm, faces=faces, thickness=0.0, depth=0.0, use_even_offset=False,
                                  use_interpolate=True, use_boundary=True)["faces"]
    ring = set(ring)
    inner = [f for f in bm.faces if f.select and f not in ring]
    bm.verts.index_update()
    bm.faces.index_update()
    kd = KDTree(len(places))
    for i, p in enumerate(places):
        kd.insert(p, i)
    kd.balance()
    moving = []
    for v in {v for f in inner for v in f.verts}:
        _co, i, d = kd.find(v.co)
        if i is not None and d < 1e-5:
            moving.append((v.index, places[i].copy(), dirs[i].copy()))
    old = KDTree(len(before))
    olds = list(before)
    for i, v in enumerate(olds):
        old.insert(v.co, i)
    old.balance()
    weld = {}
    for v in bm.verts:
        if v not in before:
            _co, i, d = old.find(v.co)
            if i is not None and d < 1e-5:
                weld[v.index] = olds[i].index
    for e in bm.edges:
        e.select = False
    for f in bm.faces:
        f.select = False
    for v in bm.verts:
        v.select = False
    for f in inner:                                       # only the inset polygons stay picked, not the outline
        f.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data)
    return moving, weld


def inset_to(ob, moving, t):
    bm = bmesh.from_edit_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    for i, start, d in moving:
        if i < len(bm.verts):
            bm.verts[i].co = start + d * t
    bm.normal_update()                                    # the ring was made at no width, with no normals to shade by
    bmesh.update_edit_mesh(ob.data)


def inset_undo(ob, moving, weld):
    """Escape: the points back where they were and the ring welded away."""
    inset_to(ob, moving, 0.0)
    bm = bmesh.from_edit_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.weld_verts(bm, targetmap={bm.verts[a]: bm.verts[b] for a, b in weld.items()})
    bmesh.update_edit_mesh(ob.data)


class BLENDA4D_OT_symmetry_inset(bpy.types.Operator):
    bl_idname = "blenda4d.symmetry_inset"
    bl_label = "Inset"
    bl_description = "Inset the selected polygons and their mirror images: drag right to inset more, left for less and then to flare them out"
    bl_options = {"REGISTER", "UNDO", "GRAB_CURSOR", "BLOCKING"}
    thickness: bpy.props.FloatProperty(name="Offset", subtype="DISTANCE", default=0.0)

    @classmethod
    def poll(cls, context):
        ob = context.edit_object
        return ob is not None and ob.type == "MESH" and context.mode == "EDIT_MESH"

    def execute(self, context):
        ob = context.edit_object
        got = inset_start(ob)
        if got is None:
            return {"CANCELLED"}
        inset_to(ob, got[0], self.thickness)
        return {"FINISHED"}

    def invoke(self, context, event):
        ob = context.edit_object
        if not ob.data.total_face_sel:
            return {"CANCELLED"}
        from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
        bm = bmesh.from_edit_mesh(ob.data)
        sel = [f.calc_center_median() for f in bm.faces if f.select]
        at = ob.matrix_world @ (sum(sel, Vector()) / max(len(sel), 1))
        self._got = inset_start(ob)
        if self._got is None:
            return {"CANCELLED"}
        region, rv3d = context.region, context.region_data
        xy = location_3d_to_region_2d(region, rv3d, at)
        self._px = 0.01
        if xy is not None:
            p0 = region_2d_to_location_3d(region, rv3d, xy, at)
            p1 = region_2d_to_location_3d(region, rv3d, xy + Vector((1.0, 0.0)), at)
            self._px = max((p1 - p0).length, 1e-9) / max(ob.matrix_world.to_scale().length / 1.7320508, 1e-9)
        self._x0 = event.mouse_x
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        ob = context.edit_object
        if event.type == "MOUSEMOVE":
            self.thickness = (event.mouse_x - self._x0) * self._px          # right: more inset, left: less, then flared
            if event.ctrl:
                self.thickness = round(self.thickness / 0.05) * 0.05
            inset_to(ob, self._got[0], self.thickness)
            us = context.scene.unit_settings
            context.area.header_text_set(f"Inset {bpy.utils.units.to_string(us.system, 'LENGTH', self.thickness * us.scale_length)}")
        elif event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value in {"PRESS", "RELEASE"}:
            context.area.header_text_set(None)
            return {"FINISHED"}
        elif event.type in {"RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            inset_undo(ob, *self._got)
            context.area.header_text_set(None)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


def standing_in(context):
    """The tool a drag anywhere in the view runs, with or without Symmetry: "extrude", "inset" or None."""
    ob = context.edit_object
    if ob is None or ob.type != "MESH" or context.mode != "EDIT_MESH":
        return None
    tool = _tool(context)
    if tool == REGION_EXTRUDE or (_state["swapped"] and tool == NORMAL_EXTRUDE):
        return "extrude"
    return "inset" if tool == INSET else None


def _view_under(window, x, y):
    for a in window.screen.areas:
        if a.type == "VIEW_3D" and a.x <= x < a.x + a.width and a.y <= y < a.y + a.height:
            for r in a.regions:
                if r.type == "WINDOW" and r.x <= x < r.x + r.width and r.y <= y < r.y + r.height:
                    return a, r
    return None


class BLENDA4D_OT_symmetry_drag_watch(bpy.types.Operator):
    """While the stand-in Extrude is on, a drag anywhere in the view extrudes. Blender's select would act on
    the press already (a press on empty space deselects), so the press is taken here: a drag extrudes, a click
    without moving selects as usual. Shift, Ctrl and Alt presses go to Blender untouched."""
    bl_idname = "blenda4d.symmetry_drag_watch"
    bl_label = "Symmetry Extrude Drag"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        self._press = None
        context.window_manager.modal_handler_add(self)
        _state["watching"] = True
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not _state["watching"] or not standing_in(context):
            _state["watching"] = False
            return {"FINISHED", "PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS" and not (event.shift or event.ctrl or event.alt or event.oskey):
            hit = _view_under(context.window, event.mouse_x, event.mouse_y)
            if hit:
                self._press = (event.mouse_x, event.mouse_y, hit)
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if self._press is not None:
            x0, y0, (a, r) = self._press
            if event.type == "MOUSEMOVE":
                limit = context.preferences.inputs.drag_threshold_mouse
                if abs(event.mouse_x - x0) + abs(event.mouse_y - y0) > limit:
                    self._press = None
                    if context.edit_object.data.total_face_sel:
                        with context.temp_override(area=a, region=r, space_data=a.spaces.active):
                            if standing_in(context) == "inset":
                                bpy.ops.blenda4d.symmetry_inset("INVOKE_DEFAULT")
                            else:
                                bpy.ops.blenda4d.symmetry_extrude("INVOKE_DEFAULT")
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                self._press = None
                with context.temp_override(area=a, region=r, space_data=a.spaces.active):
                    bpy.ops.view3d.select(location=(x0 - r.x, y0 - r.y), deselect_all=True)
                bpy.ops.ed.undo_push(message="Select")            # a click is its own undo step, as in Blender
                return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}


class BLENDA4D_GGT_symmetry_extrude(bpy.types.GizmoGroup):
    """The stand-in extrude's handle: an arrow on the picked side, along the picked element's normal; dragging it
    extrudes along normals, so both mirrored sides grow outward."""
    bl_idname = "BLENDA4D_GGT_symmetry_extrude"
    bl_label = "Symmetry Extrude"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        ob = context.edit_object
        return (_state["swapped"] and ob is not None and ob.type == "MESH" and context.mode == "EDIT_MESH"
                and axes_on(ob.data) and _tool(context) == NORMAL_EXTRUDE and ob.data.total_vert_sel > 0)

    def setup(self, context):
        gz = self.gizmos.new("GIZMO_GT_arrow_3d")
        gz.target_set_operator("blenda4d.symmetry_extrude")
        try:
            gz.length = 1.0
        except (AttributeError, TypeError):
            pass
        gz.color = (1.0, 0.86, 0.3)
        gz.alpha = 0.9
        gz.color_highlight = (1.0, 1.0, 1.0)
        gz.alpha_highlight = 1.0
        gz.scale_basis = 1.6
        self.arrow = gz

    def draw_prepare(self, context):
        """In the middle of the selection on the picked side, pointing along its average normal."""
        ob = context.edit_object
        bm = bmesh.from_edit_mesh(ob.data)
        mode = context.tool_settings.mesh_select_mode
        picked = ([f for f in bm.faces if f.select] if mode[2] else
                  [e for e in bm.edges if e.select] if mode[1] else [v for v in bm.verts if v.select])
        if not picked:
            self.arrow.hide = True
            return
        side = _state["side"].get(ob.name, (1.0, 1.0, 1.0))
        axes = axes_on(ob.data)
        near = [e for e in picked if all(_centre(e)[i] * side[i] >= -1e-6 for i in axes)] or picked
        at = sum((_centre(e) for e in near), Vector()) / len(near)

        def normal(e):
            if isinstance(e, bmesh.types.BMEdge):
                return e.verts[0].normal + e.verts[1].normal
            return Vector(e.normal)
        n = sum((normal(e) for e in near), Vector())
        self.arrow.hide = False
        mw = ob.matrix_world
        n = mw.to_3x3().inverted_safe().transposed() @ n
        n = n.normalized() if n.length > 1e-9 else Vector((0.0, 0.0, 1.0))
        self.arrow.matrix_basis = Matrix.Translation(mw @ at) @ n.to_track_quat("Z", "Y").to_matrix().to_4x4()


def register():
    bpy.utils.register_class(BLENDA4D_OT_symmetry_extrude)
    bpy.utils.register_class(BLENDA4D_OT_symmetry_inset)
    bpy.utils.register_class(BLENDA4D_OT_symmetry_drag_watch)
    bpy.utils.register_class(BLENDA4D_GGT_symmetry_extrude)
    if not _handle:
        _handle.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW"))
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)


def unregister():
    _state["watching"] = False
    for c in (BLENDA4D_GGT_symmetry_extrude, BLENDA4D_OT_symmetry_drag_watch, BLENDA4D_OT_symmetry_inset,
              BLENDA4D_OT_symmetry_extrude):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), "WINDOW")
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _state["swapped"]:
        try:
            if _tool(bpy.context) == NORMAL_EXTRUDE:
                _set_tool(REGION_EXTRUDE)
        except Exception:
            pass
    try:
        _restore_pivot(bpy.context)
        _hide_handle(False)
    except Exception:
        pass
    _state.update(sig=None, swapped=False)
