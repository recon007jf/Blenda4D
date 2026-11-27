# SPDX-License-Identifier: GPL-3.0-or-later
"""Volumes: the Volume Builder and the Volume Mesher.

- Volume Builder: a mesh object whose Geometry Nodes group turns the objects under it into one volume (a distance
  grid named "distance": negative inside, positive outside). Each object is a row in its Objects list, where it is
  added to, subtracted from or intersected with the rows above, in list order, with its own Grow / Shrink and
  Smoothing. Meshes with faces are filled; meshes without faces (points) and splines become balls and tubes of the
  row's Radius. A Volume Builder under another one is used as it is. Objects under it show as a wire and don't render.
- Volume Mesher: a mesh object that turns the Volume Builder under it back into a surface (Threshold, Adaptivity,
  Smoothing). The Volume Builder under it shows as a wire.

Both groups are built for their object; their own settings are group inputs (animatable, kept when the group is
built again), the rows' settings reach the nodes through drivers, so files work with the add-on off. sync() runs after
every scene update: it keeps the Objects list in step with the children and builds the groups again when the
objects, their order, their mode or their kind change. Lengths are in cm (1 cm = 0.01 m)."""
import bpy

from . import generators as g
from . import kinds
from .primitives import input_slot, set_input, tidy_name

MOD = "Blenda Volume"
SCALE = 0.01
LABELS = {"volume_builder": "Volume Builder", "volume_mesher": "Volume Mesher"}
ICONS = {"volume_builder": "VOLUME_DATA", "volume_mesher": "MESH_DATA"}
TIPS = {"volume_builder": "Turns the objects under it into one volume: added, subtracted or intersected in list order",
        "volume_mesher": "Turns the Volume Builder under it into a mesh"}
GRID = "distance"

# kind -> [(socket, type, default, min, max, description)]
INPUTS = {
    "volume_builder": [
        ("Voxel Size", "FLOAT", 5.0, 0.1, 1000.0, "The size of one cell of the volume (cm): smaller is finer and slower"),
        ("Grow / Shrink", "FLOAT", 0.0, -1000.0, 1000.0, "Make the whole volume thicker (positive) or thinner (cm)"),
        ("Smoothing", "INT", 0, 0, 50, "Round the whole volume off: how many passes"),
        ("Rounding", "INT", 0, 0, 50, "Fill in hollows and creases only, leaving the rest: how many passes"),
        ("Fog Edge", "FLOAT", 5.0, 0.0, 1000.0, "With Render as Fog: how far the fog fades out across the surface (cm)"),
    ],
    "volume_mesher": [
        ("Threshold", "FLOAT", 0.0, -1000.0, 1000.0, "Where the surface is taken: positive lies outside the volume's edge (cm)"),
        ("Adaptivity", "FLOAT", 0.0, 0.0, 1.0, "Use fewer, larger polygons where the surface is flat (0 to 1)"),
        ("Smoothing", "INT", 0, 0, 50, "Relax the new surface: how many passes"),
        ("Smooth Shading", "BOOL", True, None, None, "Shade the surface smooth instead of faceted"),
    ],
}
MODES = [("ADD", "Add", "Join this object to the volume above it", "ADD", 0),
         ("SUBTRACT", "Subtract", "Cut this object out of the volume above it", "REMOVE", 1),
         ("INTERSECT", "Intersect", "Keep only where this object and the volume above it overlap", "SELECT_INTERSECT", 2)]
BOOLEAN = {"ADD": "UNION", "SUBTRACT": "DIFFERENCE", "INTERSECT": "INTERSECT"}
INPUT_TYPES = ("MESH", "CURVE", "POINTCLOUD", "FONT", "META", "SURFACE", "GREASEPENCIL", "VOLUME", "EMPTY")
# the per-row filter: (key, label, tip, node, has Width)
FILTERS = [("MEAN", "Smooth", "Average the shape out: softens everything", "GeometryNodeSDFGridMean", True),
           ("MEDIAN", "Clean", "Take off small bumps and specks, keep larger edges", "GeometryNodeSDFGridMedian", True),
           ("LAPLACIAN", "Relax", "Let the surface settle evenly, like a soap film", "GeometryNodeSDFGridLaplacian", False),
           ("CURVATURE", "Round", "Round off sharp corners and fill thin grooves first", "GeometryNodeSDFGridMeanCurvature", False)]
FOG_MATERIAL = "Blenda Volume Fog"


def kind(ob):
    k = ob.get("b4d_type") if ob is not None else None
    return k if k in LABELS else None


def enabled(ob):
    return bool(ob.get("_b4d_enabled", True))


def mod_of(ob):
    return ob.modifiers.get(MOD) if ob is not None else None


def slot(ob, name):
    mod = mod_of(ob)
    if mod is None or mod.node_group is None or name not in mod.node_group.interface.items_tree:
        return None
    try:
        return input_slot(mod, mod.node_group.interface.items_tree[name].identifier)
    except (KeyError, AttributeError):
        return None


def value(ob, name):
    s = slot(ob, name)
    return getattr(*s) if s else None


def put(ob, name, v):
    mod = mod_of(ob)
    set_input(mod, mod.node_group.interface.items_tree[name].identifier, v)
    ob.update_tag()


def usable(ob):
    """An object a Volume Builder can read: a mesh (with its particles, or a smoke domain), a spline, text, a point
    cloud, a metaball, a NURBS surface, Grease Pencil, a volume (VDB), an empty showing a collection, or another
    Volume Builder."""
    if ob is None or FEED in ob:
        return False
    if kind(ob) == "volume_builder":
        return True
    if ob.type == "EMPTY":
        return ob.instance_type == "COLLECTION" and ob.instance_collection is not None and kind(ob) is None
    return ob.type in INPUT_TYPES and kind(ob) is None


def rows(builder):
    """The Objects list's rows that are switched on and still under the builder, in list order."""
    kids = set(g.kids_of(builder))
    return [r for r in builder.b4d_vol_items if r.use and r.obj is not None and r.obj in kids and usable(r.obj)]


def builder_of(mesher):
    return next((c for c in g.kids_of(mesher) if kind(c) == "volume_builder"), None)


# filter layers: rows in the Objects list that change everything made by the rows above them, where their fields reach
# key: (label, tip, node, has Width, icon)
LAYERS = {
    "SMOOTH": ("Smooth", "Soften the volume made so far", "GeometryNodeSDFGridMean", True, "MOD_SMOOTH"),
    "CLEAN": ("Clean", "Take away small bumps and specks, keeping edges", "GeometryNodeSDFGridMedian", True, "BRUSH_DATA"),
    "RELAX": ("Relax", "Even out the surface gently", "GeometryNodeSDFGridLaplacian", False, "MOD_SMOOTH"),
    "ROUND": ("Round", "Round off sharp ridges and points", "GeometryNodeSDFGridMeanCurvature", False, "SPHERECURVE"),
    "FILLET": ("Fillet", "Fill in inner corners and creases", "GeometryNodeSDFGridFillet", False, "MOD_BEVEL"),
    "GROW": ("Grow / Shrink", "Make the volume made so far thicker (positive) or thinner", "GeometryNodeSDFGridOffset", False, "FULLSCREEN_ENTER"),
}


def _emits(ob):
    """True when a mesh has a particle system that emits (not hair)."""
    return ob.type == "MESH" and any(ps.settings is not None and ps.settings.type == "EMITTER" for ps in ob.particle_systems)


def _smoke_domain(ob):
    """The smoke (gas) domain settings of a mesh, or None."""
    for m in getattr(ob, "modifiers", []):
        if m.type == "FLUID" and m.fluid_type == "DOMAIN" and m.domain_settings is not None and m.domain_settings.domain_type == "GAS":
            return m.domain_settings
    return None


SOURCES = [
    ("AUTO", "Auto", "Pick from the object: closed meshes are filled, splines become tubes, flat text a shell, loose points balls"),
    ("FILLED", "Filled", "The whole inside of a closed mesh (needs a mesh without holes)"),
    ("SURFACE", "Surface", "A shell of Radius over the faces: for open, flat or single-sided shapes"),
    ("POINTS", "Points", "A ball of Radius on every point"),
    ("EDGES", "Edges", "A tube of Radius along every edge or spline"),
    ("PARTICLES", "Particles", "A ball on every live particle of the object's particle systems (Radius times the particle's size)"),
    ("DENSITY", "Smoke / Density", "The smoke of a smoke domain, or the density of a volume (VDB), where it is thicker than Density"),
]
SHAPE = {"FILLED": "solid", "SURFACE": "text", "POINTS": "points", "EDGES": "tube", "PARTICLES": "particles"}


def _auto_shape(ob):
    if ob.type == "VOLUME":
        return "fog"
    if _smoke_domain(ob) is not None:
        return "smoke"
    if _emits(ob):
        return "particles"
    if ob.type in ("META", "SURFACE", "EMPTY"):
        return "solid"
    if ob.type in ("CURVE", "GREASEPENCIL"):
        return "tube"
    if ob.type == "FONT":                             # flat letters have no inside: they become a shell
        cu = ob.data
        return "solid" if (cu.extrude > 0 or cu.bevel_depth > 0) else "text"
    if ob.type == "POINTCLOUD":
        return "points"
    if ob.type == "MESH" and len(ob.data.polygons) == 0:
        if any(m.show_viewport for m in ob.modifiers):  # made by a modifier (a Platonic, a Cube...): its faces come later
            return "solid"
        return "tube" if len(ob.data.edges) else "points"
    return "solid"


def _input_shape(ob, row=None):
    """How an object is turned into a volume: 'builder', 'solid' (filled), 'text' (shell over the faces),
    'points' (balls) or 'tube' (along edges and splines)."""
    if kind(ob) == "volume_builder":
        return "builder"
    src = getattr(row, "source", "AUTO") if row is not None else "AUTO"
    if src == "DENSITY":
        return "fog" if ob.type == "VOLUME" else ("smoke" if _smoke_domain(ob) is not None else _auto_shape(ob))
    if src == "PARTICLES" and not _emits(ob):
        return _auto_shape(ob)
    if src == "AUTO" or (ob.type == "VOLUME" and src != "DENSITY"):
        return _auto_shape(ob)
    if src == "FILLED" and ob.type == "CURVE":       # a spline has no inside of its own: fill it flat and shell it
        return "text"
    return SHAPE[src]


# --- node groups -----------------------------------------------------------------------------------------------

class _G:
    def __init__(self, tree):
        self.t, self.n, self.l = tree, tree.nodes, tree.links

    def node(self, idname, **props):
        nd = self.n.new(idname)
        for k, v in props.items():
            setattr(nd, k, v)
        return nd

    def put(self, v, sock):
        if hasattr(v, "is_output"):
            self.l.new(v, sock)
        else:
            sock.default_value = v

    def m(self, op, a, b=None):
        nd = self.node("ShaderNodeMath", operation=op)
        self.put(a, nd.inputs[0])
        if b is not None:
            self.put(b, nd.inputs[1])
        return nd.outputs[0]

    def cm(self, sock):
        return self.m("MULTIPLY", sock, SCALE)

    def driven(self, owner, path, default):
        """A number that follows owner's property at `path` through a driver."""
        v = self.node("ShaderNodeValue")
        v.outputs[0].default_value = default
        fc = v.outputs[0].driver_add("default_value")
        d = fc.driver
        d.type = "AVERAGE"
        var = d.variables.new()
        var.name = "v"
        var.targets[0].id_type = "OBJECT"
        var.targets[0].id = owner
        var.targets[0].data_path = path
        return v.outputs[0]

    def info(self, ob):
        nd = self.node("GeometryNodeObjectInfo", transform_space="RELATIVE")
        nd.inputs["Object"].default_value = ob
        return nd


def _new_tree(name, k, owner):
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old)
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.is_modifier = True
    tree["b4d_owner"] = owner.name
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for sname, stype, default, lo, hi, tip in INPUTS[k]:
        s = tree.interface.new_socket(sname, in_out="INPUT", socket_type={"FLOAT": "NodeSocketFloat", "INT": "NodeSocketInt",
                                                                            "BOOL": "NodeSocketBool"}[stype])
        s.default_value = default
        s.description = tip
        if lo is not None:
            s.min_value, s.max_value = lo, hi
    return tree


# --- particles and smoke: fed in as points ---------------------------------------------------------------------
# Geometry nodes can't read particle systems or a smoke domain's smoke, but Python can: a hidden mesh of points
# (not in the scene; the builder's nodes keep it) is kept up to date with them on every frame and change, each point
# with its size in the "b4d_r" attribute.

FED = ("particles", "smoke")
FEED = "b4d_vol_feed"                                 # marks the hidden mesh, holding the name of the object it follows


def _feed_object(src):
    name = f"Blenda Volume Feed [{src.name}]"
    ob = bpy.data.objects.get(name)
    if ob is None or ob.type != "MESH":
        ob = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        ob[FEED] = src.name
    return ob


ALIVE_VALUE = bpy.types.Particle.bl_rna.properties["alive_state"].enum_items["ALIVE"].value


def _particle_points(src, depsgraph):
    import numpy as np
    ev = src.evaluated_get(depsgraph)
    cos, sizes = [], []
    for ps in ev.particle_systems:
        if ps.settings is None or ps.settings.type != "EMITTER":
            continue
        n = len(ps.particles)
        if not n:
            continue
        co = np.empty(n * 3, dtype=np.float32)
        ps.particles.foreach_get("location", co)
        sz = np.empty(n, dtype=np.float32)
        ps.particles.foreach_get("size", sz)
        state = np.empty(n, dtype=np.int32)           # read in one go: foreach_get gives each state's enum value
        ps.particles.foreach_get("alive_state", state)
        keep = state == ALIVE_VALUE
        cos.append(co.reshape(-1, 3)[keep])
        sizes.append(sz[keep])
    if not cos:
        return np.zeros((0, 3), dtype=np.float32), np.zeros(0, dtype=np.float32)
    co, sz = np.concatenate(cos), np.concatenate(sizes)
    mean = float(sz.mean()) if len(sz) else 1.0
    return co, (sz / mean if mean > 0 else np.ones_like(sz))     # particles move in world space already


def _smoke_points(src, row, depsgraph):
    """A point on every smoke cell thicker than Density, in world space, each as big as a cell."""
    import numpy as np
    from mathutils import Matrix
    ev = src.evaluated_get(depsgraph)
    ds = next((m.domain_settings for m in ev.modifiers if m.type == "FLUID" and m.fluid_type == "DOMAIN"), None)
    empty = np.zeros((0, 3), dtype=np.float32), np.zeros(0, dtype=np.float32)
    if ds is None:
        return empty
    dens = np.array(ds.density_grid[:], dtype=np.float32)
    res = np.array(ds.domain_resolution[:], dtype=np.int64)
    if not dens.size or res.prod() <= 0:
        return empty
    up = round((dens.size / res.prod()) ** (1.0 / 3.0))  # with noise the grid is finer by the noise scale
    res = res * max(1, up)
    if res.prod() != dens.size:
        return empty
    grid = dens.reshape(res[2], res[1], res[0])         # x changes fastest
    z, y, x = np.nonzero(grid > row.density)
    if not len(x):
        return empty
    lo = np.array([min(c[k] for c in src.bound_box) for k in range(3)], dtype=np.float32)
    hi = np.array([max(c[k] for c in src.bound_box) for k in range(3)], dtype=np.float32)
    cell = (hi - lo) / res.astype(np.float32)
    local = lo + (np.stack([x, y, z], axis=1).astype(np.float32) + 0.5) * cell
    mw = np.array(src.matrix_world, dtype=np.float32)
    world = local @ mw[:3, :3].T + mw[:3, 3]
    big = float(np.max(np.abs(np.array(Matrix(src.matrix_world).to_3x3().to_scale())) * cell)) * 0.9
    return world, np.full(len(world), big, dtype=np.float32)


def _feed(src, row, depsgraph):
    """Bring the hidden points of one particle or smoke row up to date."""
    shape = _input_shape(src, row)
    if shape not in FED:
        return
    co, r = _particle_points(src, depsgraph) if shape == "particles" else _smoke_points(src, row, depsgraph)
    ob = _feed_object(src)
    me = ob.data
    key = (len(co), float(co.sum()) if len(co) else 0.0, float(r.sum()) if len(r) else 0.0)
    if tuple(ob.get("b4d_feed_key", ())) == key:
        return
    ob["b4d_feed_key"] = key
    me.clear_geometry()
    me.vertices.add(len(co))
    if len(co):
        me.vertices.foreach_set("co", co.astype("float32").ravel())
    at = me.attributes.get("b4d_r") or me.attributes.new("b4d_r", "FLOAT", "POINT")
    if len(r):
        at.data.foreach_set("value", r.astype("float32"))
    me.update()


def feed_all(scene, depsgraph=None, only=None):
    """Update the fed points of every Volume Builder's particle and smoke rows (only those following `only`)."""
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    for b in [o for o in scene.objects if kind(o) == "volume_builder"]:
        for r in rows(b):
            if only is None or r.obj.name in only:
                try:
                    _feed(r.obj, r, depsgraph)
                except Exception:
                    import traceback
                    traceback.print_exc()


@bpy.app.handlers.persistent
def _on_frame(scene, depsgraph=None):
    feed_all(scene, depsgraph)


def _row_grid(G, builder, i, row, voxel):
    """The distance grid of one row, with its Grow / Shrink and Smoothing."""
    ob = row.obj
    shape = _input_shape(ob, row)
    geo = G.info(_feed_object(ob) if shape in FED else ob).outputs["Geometry"]
    if shape in FED:                                  # particles or smoke, fed in as points with their own sizes
        pts = G.node("GeometryNodeMeshToPoints")
        G.l.new(geo, pts.inputs["Mesh"])
        size = G.node("GeometryNodeInputNamedAttribute", data_type="FLOAT")
        size.inputs["Name"].default_value = "b4d_r"
        r = size.outputs["Attribute"]
        if shape == "particles":                       # Radius times each particle's size (1 = the average size)
            r = G.m("MULTIPLY", r, G.cm(G.driven(builder, f"b4d_vol_items[{i}].radius", row.radius)))
        sdf = G.node("GeometryNodePointsToSDFGrid")
        G.l.new(pts.outputs[0], sdf.inputs["Points"])
        G.l.new(r, sdf.inputs["Radius"])
        G.l.new(voxel, sdf.inputs["Voxel Size"])
        if "Band Width" in sdf.inputs:
            sdf.inputs["Band Width"].default_value = 3
        grid = sdf.outputs[0]
    elif shape == "fog":                              # a volume (VDB): its surface where it is thicker than Density
        get = G.node("GeometryNodeGetNamedGrid", data_type="FLOAT")
        G.l.new(geo, get.inputs["Volume"])
        get.inputs["Name"].default_value = row.grid or "density"
        surf = G.node("GeometryNodeGridToMesh")
        G.l.new(get.outputs["Grid"], surf.inputs["Grid"])
        G.l.new(G.driven(builder, f"b4d_vol_items[{i}].density", row.density), surf.inputs["Threshold"])
        sdf = G.node("GeometryNodeMeshToSDFGrid")
        G.l.new(surf.outputs["Mesh"], sdf.inputs["Mesh"])
        G.l.new(voxel, sdf.inputs["Voxel Size"])
        if "Band Width" in sdf.inputs:
            sdf.inputs["Band Width"].default_value = 3
        grid = sdf.outputs[0]
    elif shape == "builder":
        get = G.node("GeometryNodeGetNamedGrid", data_type="FLOAT")
        G.l.new(geo, get.inputs["Volume"])
        get.inputs["Name"].default_value = GRID
        grid = get.outputs["Grid"]
    else:
        real = G.node("GeometryNodeRealizeInstances")
        G.l.new(geo, real.inputs["Geometry"])
        geo = real.outputs[0]
        radius = G.cm(G.driven(builder, f"b4d_vol_items[{i}].radius", row.radius))
        if shape == "tube":
            circle = G.node("GeometryNodeCurvePrimitiveCircle", mode="RADIUS")
            circle.inputs["Resolution"].default_value = 12
            G.l.new(radius, circle.inputs["Radius"])
            edges = G.node("GeometryNodeMeshToCurve")    # a mesh's edges become splines; splines pass through
            G.l.new(geo, edges.inputs["Mesh"])
            strokes = G.node("GeometryNodeGreasePencilToCurves")   # Grease Pencil strokes become splines too
            G.l.new(geo, strokes.inputs["Grease Pencil"])
            flat = G.node("GeometryNodeRealizeInstances")       # the strokes come out as instances
            G.l.new(strokes.outputs[0], flat.inputs["Geometry"])
            both = G.node("GeometryNodeJoinGeometry")
            G.l.new(geo, both.inputs[0])
            G.l.new(edges.outputs[0], both.inputs[0])
            G.l.new(flat.outputs[0], both.inputs[0])
            tube = G.node("GeometryNodeCurveToMesh")
            G.l.new(both.outputs[0], tube.inputs["Curve"])
            G.l.new(circle.outputs["Curve"], tube.inputs["Profile Curve"])
            tube.inputs["Fill Caps"].default_value = True
            sdf = G.node("GeometryNodeMeshToSDFGrid")
            G.l.new(tube.outputs["Mesh"], sdf.inputs["Mesh"])
            G.l.new(voxel, sdf.inputs["Voxel Size"])
        elif shape == "text":                         # points spread over the letters, each a ball of Radius
            fill = G.node("GeometryNodeFillCurve")       # splines are filled flat first
            G.l.new(geo, fill.inputs["Curve"])
            both = G.node("GeometryNodeJoinGeometry")
            G.l.new(geo, both.inputs[0])
            G.l.new(fill.outputs[0], both.inputs[0])
            spread = G.node("GeometryNodeDistributePointsOnFaces", distribute_method="RANDOM")
            G.l.new(both.outputs[0], spread.inputs["Mesh"])
            G.l.new(G.m("DIVIDE", 4.0, G.m("MULTIPLY", voxel, voxel)), spread.inputs["Density"])
            sdf = G.node("GeometryNodePointsToSDFGrid")
            G.l.new(spread.outputs["Points"], sdf.inputs["Points"])
            G.l.new(radius, sdf.inputs["Radius"])
            G.l.new(voxel, sdf.inputs["Voxel Size"])
        elif shape == "points":
            pts = G.node("GeometryNodeMeshToPoints")
            G.l.new(geo, pts.inputs["Mesh"])
            cpts = G.node("GeometryNodeCurveToPoints", mode="EVALUATED")
            G.l.new(geo, cpts.inputs["Curve"])
            join = G.node("GeometryNodeJoinGeometry")    # a point cloud object passes straight through
            G.l.new(pts.outputs[0], join.inputs[0])
            G.l.new(cpts.outputs["Points"], join.inputs[0])
            G.l.new(geo, join.inputs[0])
            sdf = G.node("GeometryNodePointsToSDFGrid")
            G.l.new(join.outputs[0], sdf.inputs["Points"])
            G.l.new(radius, sdf.inputs["Radius"])
            G.l.new(voxel, sdf.inputs["Voxel Size"])
        else:
            sdf = G.node("GeometryNodeMeshToSDFGrid")
            G.l.new(geo, sdf.inputs["Mesh"])
            G.l.new(voxel, sdf.inputs["Voxel Size"])
        if "Band Width" in sdf.inputs:
            sdf.inputs["Band Width"].default_value = 3
        grid = sdf.outputs[0]
    off = G.node("GeometryNodeSDFGridOffset")         # positive Distance grows the surface
    G.l.new(grid, off.inputs["Grid"])
    G.l.new(G.cm(G.driven(builder, f"b4d_vol_items[{i}].grow", row.grow)), off.inputs["Distance"])
    _key, _label, _tip, idname, width = next(f for f in FILTERS if f[0] == row.filter)
    smooth = G.node(idname)
    G.l.new(off.outputs[0], smooth.inputs["Grid"])
    if width:
        smooth.inputs["Width"].default_value = 1
    G.l.new(G.m("ROUND", G.driven(builder, f"b4d_vol_items[{i}].smooth", row.smooth)), smooth.inputs["Iterations"])
    return smooth.outputs[0]


def _fields(row):
    from . import moclone_fx as fx
    return [(j, f) for j, f in enumerate(row.fields) if f.obj is not None and fx.is_field(f.obj)]


def _layer(G, builder, i, row, grid, voxel):
    """A filter layer: its effect on the volume made so far. With fields, it works only as strongly as they say at each
    voxel: the volume before and after are blended voxel by voxel, then made a clean distance volume again."""
    _label, _tip, idname, width, _icon = LAYERS[row.layer]
    nd = G.node(idname)
    G.l.new(grid, nd.inputs["Grid"])
    if row.layer == "GROW":
        G.l.new(G.cm(G.driven(builder, f"b4d_vol_items[{i}].grow", row.grow)), nd.inputs["Distance"])
    else:
        if width:
            nd.inputs["Width"].default_value = 1
        G.l.new(G.m("ROUND", G.driven(builder, f"b4d_vol_items[{i}].smooth", row.smooth)), nd.inputs["Iterations"])
    after = nd.outputs[0]
    fs = _fields(row)
    if not fs:
        return after
    from . import moclone_fx as fx
    w = _field_weight(G, builder, i, fs)
    return _regrid(G, grid, after, voxel, lambda before, later: _mix(G, w, before, later))


FIELD_MIX = [("MAX", "Max", "Take the stronger of this field and the ones above it"),
             ("NORMAL", "Normal", "Lay this field over the ones above it"),
             ("MIN", "Min", "Take the weaker of this field and the ones above it"),
             ("ADD", "Add", "Add this field to the ones above it"),
             ("SUBTRACT", "Subtract", "Take this field away from the ones above it"),
             ("MULTIPLY", "Multiply", "Multiply the ones above it by this field")]


def _mix(G, t, a, b):
    nd = G.node("ShaderNodeMix", data_type="FLOAT", clamp_factor=True)
    G.put(t, nd.inputs[0])
    G.put(a, nd.inputs[2])
    G.put(b, nd.inputs[3])
    return nd.outputs[0]


def _field_weight(G, builder, i, fs):
    """How strongly a filter layer works at each voxel: its fields in list order, each mixed onto the ones above it by
    its Mix mode, as much as its switch and Opacity say."""
    from . import moclone_fx as fx
    w = 0.0
    for j, f in fs:
        on = G.driven(builder, f"b4d_vol_items[{i}].fields[{j}].on", float(f.on))
        op = G.m("MULTIPLY", G.driven(builder, f"b4d_vol_items[{i}].fields[{j}].opacity", f.opacity), 0.01)
        v = fx.field_value(G.n, G.l, f.obj)
        mode = f.mix
        if mode == "NORMAL":
            r = v
        elif mode == "MIN":
            r = G.m("MINIMUM", w, v)
        elif mode == "ADD":
            r = G.m("ADD", w, v)
        elif mode == "SUBTRACT":
            r = G.m("SUBTRACT", w, v)
        elif mode == "MULTIPLY":
            r = G.m("MULTIPLY", w, v)
        else:
            r = G.m("MAXIMUM", w, v)
        w = _mix(G, G.m("MULTIPLY", on, op), w, r)
    clamp = G.node("ShaderNodeClamp")
    G.put(w, clamp.inputs["Value"])
    return clamp.outputs[0]


def _regrid(G, a, b, voxel, value, reach=None):
    """A new distance volume made voxel by voxel from two others: value(a here, b here) gives its distance. The SDF
    nodes take no fields, so this fills a volume over both (inside and a band around them, wider by `reach`), then
    makes a clean distance volume of its surface, which later rows and layers can use."""
    both = G.node("GeometryNodeSDFGridBoolean", operation="UNION")
    G.l.new(b, both.inputs[1])
    G.l.new(a, both.inputs[1])
    shell = G.node("GeometryNodeGridToMesh")
    shell.inputs["Threshold"].default_value = 0.0
    G.l.new(both.outputs[0], shell.inputs["Grid"])
    filled = G.node("GeometryNodeMeshToDensityGrid")
    G.l.new(shell.outputs["Mesh"], filled.inputs["Mesh"])
    G.l.new(voxel, filled.inputs["Voxel Size"])
    wider = G.node("GeometryNodeGridDilateAndErode", data_type="FLOAT")
    G.l.new(filled.outputs[0], wider.inputs["Grid"])
    if reach is None:
        wider.inputs["Steps"].default_value = 3
    else:
        G.l.new(G.m("ADD", G.m("CEIL", G.m("DIVIDE", reach, voxel)), 3.0), wider.inputs["Steps"])
    out = G.node("GeometryNodeFieldToGrid", data_type="FLOAT")
    item = out.grid_items.new("FLOAT", "Distance")
    G.l.new(wider.outputs[0], out.inputs["Topology"])
    pos = G.node("GeometryNodeInputPosition").outputs[0]
    here = []
    for grid in (a, b):
        sg = G.node("GeometryNodeSampleGrid", data_type="FLOAT")
        G.l.new(grid, sg.inputs["Grid"])
        G.l.new(pos, sg.inputs["Position"])
        here.append(sg.outputs["Value"])
    G.l.new(value(*here), out.inputs[item.name] if item.name in out.inputs else out.inputs[1])
    bg = G.node("GeometryNodeSetGridBackground", data_type="FLOAT")    # cells left out lie outside
    G.l.new(out.outputs[0], bg.inputs["Grid"])
    G.l.new(G.m("MULTIPLY", voxel, 3.0), bg.inputs["Background"])
    surf = G.node("GeometryNodeGridToMesh")
    surf.inputs["Threshold"].default_value = 0.0
    G.l.new(bg.outputs[0], surf.inputs["Grid"])
    again = G.node("GeometryNodeMeshToSDFGrid")
    G.l.new(surf.outputs["Mesh"], again.inputs["Mesh"])
    G.l.new(voxel, again.inputs["Voxel Size"])
    if "Band Width" in again.inputs:
        again.inputs["Band Width"].default_value = 3
    return again.outputs[0]


def _soft(G, k, a, b):
    """Smooth minimum of two distances over k: where they are closer than k the corner between them is filled in."""
    k = G.m("MAXIMUM", k, 1e-5)
    h = G.m("DIVIDE", G.m("MAXIMUM", G.m("SUBTRACT", k, G.m("ABSOLUTE", G.m("SUBTRACT", a, b))), 0.0), k)
    return G.m("SUBTRACT", G.m("MINIMUM", a, b), G.m("MULTIPLY", G.m("MULTIPLY", h, h), G.m("MULTIPLY", k, 0.25)))


def _soft_meet(G, builder, i, row, grid, part, voxel):
    """A row meeting the volume above it with a soft blend of Blend (cm) where they meet."""
    k = G.cm(G.driven(builder, f"b4d_vol_items[{i}].blend", row.blend))
    neg = lambda v: G.m("MULTIPLY", v, -1.0)
    if row.mode == "SUBTRACT":                        # max(a, -b) = -min(-a, b)
        fn = lambda a, b: neg(_soft(G, k, neg(a), b))
    elif row.mode == "INTERSECT":                     # max(a, b) = -min(-a, -b)
        fn = lambda a, b: neg(_soft(G, k, neg(a), neg(b)))
    else:
        fn = lambda a, b: _soft(G, k, a, b)
    return _regrid(G, grid, part, voxel, fn, reach=k)


def build_builder(builder):
    name = f"Blenda Volume Builder [{builder.name}]"
    tree = _new_tree(name, "volume_builder", builder)
    G = _G(tree)
    gin, gout = G.node("NodeGroupInput"), G.node("NodeGroupOutput")
    voxel = G.cm(G.m("MAXIMUM", gin.outputs["Voxel Size"], 0.1))
    grid = None
    for i, row in enumerate(builder.b4d_vol_items):
        if row.layer:
            if grid is not None and row.use and row.layer in LAYERS:
                grid = _layer(G, builder, i, row, grid, voxel)
            continue
        if row not in rows(builder):
            continue
        part = _row_grid(G, builder, i, row, voxel)
        if grid is None:                              # the first row starts the volume, whatever its mode
            grid = part
            continue
        if row.blend > 0.0:                           # a soft blend where it meets the rows above
            grid = _soft_meet(G, builder, i, row, grid, part, voxel)
            continue
        op = G.node("GeometryNodeSDFGridBoolean", operation=BOOLEAN[row.mode])
        many = op.inputs[1]                           # several grids go into one socket (Grid 2)
        if row.mode == "SUBTRACT":
            G.l.new(grid, op.inputs[0])
            G.l.new(part, many)
        else:
            G.l.new(part, many)
            G.l.new(grid, many)
        grid = op.outputs["Grid"]
    if grid is None:
        G.l.new(G.node("GeometryNodeJoinGeometry").outputs[0], gout.inputs[0])     # nothing to build: empty
        return tree
    off = G.node("GeometryNodeSDFGridOffset")
    G.l.new(grid, off.inputs["Grid"])
    G.l.new(G.cm(gin.outputs["Grow / Shrink"]), off.inputs["Distance"])
    smooth = G.node("GeometryNodeSDFGridMean")
    G.l.new(off.outputs[0], smooth.inputs["Grid"])
    smooth.inputs["Width"].default_value = 1
    G.l.new(gin.outputs["Smoothing"], smooth.inputs["Iterations"])
    fillet = G.node("GeometryNodeSDFGridFillet")
    G.l.new(smooth.outputs[0], fillet.inputs["Grid"])
    G.l.new(gin.outputs["Rounding"], fillet.inputs["Iterations"])
    store = G.node("GeometryNodeStoreNamedGrid", data_type="FLOAT")
    store.inputs["Name"].default_value = GRID
    G.l.new(G.node("GeometryNodeJoinGeometry").outputs[0], store.inputs["Volume"])
    G.l.new(fillet.outputs[0], store.inputs["Grid"])
    # what the viewport draws: a fog that is thick inside the surface and fades out across it ("density" is the grid
    # Blender shows first); the distance grid stays for the Volume Mesher and other Volume Builders
    fog = G.node("GeometryNodeFieldToGrid", data_type="FLOAT")
    item = fog.grid_items.new("FLOAT", "Density")
    G.l.new(fillet.outputs[0], fog.inputs["Topology"])
    read = G.node("GeometryNodeSampleGrid", data_type="FLOAT")
    G.l.new(fillet.outputs[0], read.inputs["Grid"])
    G.l.new(G.node("GeometryNodeInputPosition").outputs[0], read.inputs["Position"])
    dens = G.node("ShaderNodeMapRange", clamp=True)
    G.l.new(read.outputs["Value"], dens.inputs["Value"])
    G.l.new(G.m("MULTIPLY", voxel, -1.0), dens.inputs["From Min"])
    G.l.new(voxel, dens.inputs["From Max"])
    dens.inputs["To Min"].default_value, dens.inputs["To Max"].default_value = 1.0, 0.0
    G.l.new(dens.outputs["Result"], fog.inputs[item.name] if item.name in fog.inputs else fog.inputs[1])
    if builder.b4d_vol_fog:
        # Render as Fog: a filled density grid over the volume's bounds (the distance grid only has cells near the
        # surface): thick inside, fading out over Fog Edge across the surface
        outline = G.node("GeometryNodeGridToMesh")
        G.l.new(fillet.outputs[0], outline.inputs["Grid"])
        outline.inputs["Threshold"].default_value = 0.0   # its own default (10 cm) lies outside a thin band
        box = G.node("GeometryNodeBoundBox")
        G.l.new(outline.outputs["Mesh"], box.inputs["Geometry"])
        edge = G.m("MAXIMUM", G.cm(gin.outputs["Fog Edge"]), 0.0001)
        pad = G.node("ShaderNodeVectorMath", operation="SCALE")
        pad.inputs[0].default_value = (1.0, 1.0, 1.0)
        G.l.new(G.m("ADD", edge, voxel), pad.inputs["Scale"])
        lo = G.node("ShaderNodeVectorMath", operation="SUBTRACT")
        G.l.new(box.outputs["Min"], lo.inputs[0])
        G.l.new(pad.outputs[0], lo.inputs[1])
        hi = G.node("ShaderNodeVectorMath", operation="ADD")
        G.l.new(box.outputs["Max"], hi.inputs[0])
        G.l.new(pad.outputs[0], hi.inputs[1])
        size = G.node("ShaderNodeVectorMath", operation="SUBTRACT")
        G.l.new(hi.outputs[0], size.inputs[0])
        G.l.new(lo.outputs[0], size.inputs[1])
        xyz = G.node("ShaderNodeSeparateXYZ")
        G.l.new(size.outputs[0], xyz.inputs[0])
        cube = G.node("GeometryNodeVolumeCube")
        G.l.new(lo.outputs[0], cube.inputs["Min"])
        G.l.new(hi.outputs[0], cube.inputs["Max"])
        for axis, k in (("X", 0), ("Y", 1), ("Z", 2)):
            G.l.new(G.m("MINIMUM", G.m("CEIL", G.m("DIVIDE", xyz.outputs[k], voxel)), 160.0), cube.inputs[f"Resolution {axis}"])
        inside = G.node("GeometryNodeSampleGrid", data_type="FLOAT")
        G.l.new(fillet.outputs[0], inside.inputs["Grid"])
        G.l.new(G.node("GeometryNodeInputPosition").outputs[0], inside.inputs["Position"])
        thick = G.node("ShaderNodeMapRange", clamp=True)
        G.l.new(inside.outputs["Value"], thick.inputs["Value"])
        G.l.new(G.m("MULTIPLY", edge, -1.0), thick.inputs["From Min"])
        thick.inputs["From Max"].default_value = 0.0
        thick.inputs["To Min"].default_value, thick.inputs["To Max"].default_value = 1.0, 0.0
        G.l.new(thick.outputs["Result"], cube.inputs["Density"])
        keep = G.node("GeometryNodeStoreNamedGrid", data_type="FLOAT")     # the distance grid goes along
        keep.inputs["Name"].default_value = GRID
        G.l.new(cube.outputs["Volume"], keep.inputs["Volume"])
        G.l.new(fillet.outputs[0], keep.inputs["Grid"])
        setm = G.node("GeometryNodeSetMaterial")        # a volume made in nodes renders with its own material only
        G.l.new(keep.outputs[0], setm.inputs["Geometry"])
        setm.inputs["Material"].default_value = fog_material()
        G.l.new(setm.outputs[0], gout.inputs[0])
        return tree
    if builder.b4d_vol_view == "FOG":
        shown = G.node("GeometryNodeStoreNamedGrid", data_type="FLOAT")
        shown.inputs["Name"].default_value = "density"
        _first(G, shown, store)
        G.l.new(fog.outputs[0], shown.inputs["Grid"])
        G.l.new(store.outputs[0], gout.inputs[0])
        return tree
    # Surface or Voxels: the viewport draws a mesh of the volume. The volume keeps an empty "density" grid (the one
    # Blender draws), so the distance grid doesn't show as a haze; the mesh is only made in the viewport
    blank = G.node("GeometryNodeFieldToGrid", data_type="FLOAT")
    bitem = blank.grid_items.new("FLOAT", "Density")
    G.l.new(fillet.outputs[0], blank.inputs["Topology"])
    (blank.inputs[bitem.name] if bitem.name in blank.inputs else blank.inputs[1]).default_value = 0.0
    shown = G.node("GeometryNodeStoreNamedGrid", data_type="FLOAT")
    shown.inputs["Name"].default_value = "density"
    _first(G, shown, store)
    G.l.new(blank.outputs[0], shown.inputs["Grid"])
    if builder.b4d_vol_view == "VOXELS":             # a cube on every voxel at the surface, like building blocks
        cells = G.node("GeometryNodeGridToPoints", data_type="FLOAT")
        G.l.new(fillet.outputs[0], cells.inputs["Grid"])
        near = G.node("FunctionNodeCompare", data_type="FLOAT", operation="LESS_EQUAL")
        G.l.new(cells.outputs["Value"], near.inputs[0])
        near.inputs[1].default_value = 0.0
        far = G.node("FunctionNodeCompare", data_type="FLOAT", operation="GREATER_THAN")
        G.l.new(cells.outputs["Value"], far.inputs[0])
        G.l.new(G.m("MULTIPLY", voxel, -1.0), far.inputs[1])
        both = G.node("FunctionNodeBooleanMath", operation="AND")
        G.l.new(near.outputs[0], both.inputs[0])
        G.l.new(far.outputs[0], both.inputs[1])
        keep = G.node("GeometryNodeSeparateGeometry", domain="POINT")
        G.l.new(cells.outputs["Points"], keep.inputs["Geometry"])
        G.l.new(both.outputs[0], keep.inputs["Selection"])
        box = G.node("GeometryNodeMeshCube")
        size = G.node("ShaderNodeCombineXYZ")
        v95 = G.m("MULTIPLY", voxel, 0.95)
        for k in range(3):
            G.l.new(v95, size.inputs[k])
        G.l.new(size.outputs[0], box.inputs["Size"])
        inst = G.node("GeometryNodeInstanceOnPoints")
        G.l.new(keep.outputs["Selection"], inst.inputs["Points"])
        G.l.new(box.outputs["Mesh"], inst.inputs["Instance"])
        look = G.node("GeometryNodeRealizeInstances")
        G.l.new(inst.outputs[0], look.inputs["Geometry"])
        look = look.outputs[0]
    else:
        surf = G.node("GeometryNodeGridToMesh")
        G.l.new(fillet.outputs[0], surf.inputs["Grid"])
        surf.inputs["Threshold"].default_value = 0.0      # the volume's edge; the default (10 cm) is outside a band
                                                          # three voxels wide once voxels are under ~3.4 cm
        look = surf.outputs["Mesh"]
    gate = G.node("GeometryNodeSwitch", input_type="GEOMETRY")     # the mesh is only a preview: none in renders
    G.l.new(G.node("GeometryNodeIsViewport").outputs[0], gate.inputs["Switch"])
    G.l.new(look, gate.inputs["True"])
    join = G.node("GeometryNodeJoinGeometry")
    G.l.new(gate.outputs[0], join.inputs[0])
    G.l.new(store.outputs[0], join.inputs[0])
    G.l.new(join.outputs[0], gout.inputs[0])
    return tree


def _first(G, shown, store):
    """Put the "density" grid (shown) into the volume before the distance grid (store): the viewport draws a volume's
    first grid, and the distance grid drawn as fog is only a grey haze."""
    G.l.new(G.node("GeometryNodeJoinGeometry").outputs[0], shown.inputs["Volume"])
    G.l.new(shown.outputs[0], store.inputs["Volume"])


def build_mesher(mesher):
    name = f"Blenda Volume Mesher [{mesher.name}]"
    tree = _new_tree(name, "volume_mesher", mesher)
    own = tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.move(own, 1)                       # the first input: the Mesher's own mesh (the quads, once made)
    G = _G(tree)
    gin, gout = G.node("NodeGroupInput"), G.node("NodeGroupOutput")
    if mesher.b4d_vq_on:                              # Quad Remesh made: show the quads kept in its own mesh
        G.l.new(gin.outputs["Geometry"], gout.inputs[0])
        return tree
    src = builder_of(mesher)
    if src is None:
        G.l.new(G.node("GeometryNodeJoinGeometry").outputs[0], gout.inputs[0])
        return tree
    get = G.node("GeometryNodeGetNamedGrid", data_type="FLOAT")
    G.l.new(G.info(src).outputs["Geometry"], get.inputs["Volume"])
    get.inputs["Name"].default_value = GRID
    surf = G.node("GeometryNodeGridToMesh")
    G.l.new(get.outputs["Grid"], surf.inputs["Grid"])
    G.l.new(G.cm(gin.outputs["Threshold"]), surf.inputs["Threshold"])
    G.l.new(gin.outputs["Adaptivity"], surf.inputs["Adaptivity"])
    blur = G.node("GeometryNodeBlurAttribute", data_type="FLOAT_VECTOR")
    G.l.new(G.node("GeometryNodeInputPosition").outputs[0], blur.inputs["Value"])
    G.l.new(gin.outputs["Smoothing"], blur.inputs["Iterations"])
    setp = G.node("GeometryNodeSetPosition")
    G.l.new(surf.outputs["Mesh"], setp.inputs["Geometry"])
    G.l.new(blur.outputs[0], setp.inputs["Position"])
    shade = G.node("GeometryNodeSetShadeSmooth")
    G.l.new(setp.outputs[0], shade.inputs["Mesh"])
    G.l.new(gin.outputs["Smooth Shading"], shade.inputs["Shade Smooth"])
    out = shade.outputs[0]
    mat = _material(mesher)
    if mat is not None:                               # a new surface has no material of its own: give it the Mesher's
        setm = G.node("GeometryNodeSetMaterial")
        G.l.new(out, setm.inputs["Geometry"])
        setm.inputs["Material"].default_value = mat
        out = setm.outputs[0]
    G.l.new(out, gout.inputs[0])
    return tree


def _material(ob):
    return next((sl.material for sl in ob.material_slots if sl.material is not None), None)


def _signature(ob):
    if kind(ob) == "volume_builder":
        live = rows(ob)
        return ([f"L:{r.layer}:{r.use}:" + ",".join(f"{f.obj.name}/{f.mix}" for _j, f in _fields(r)) if r.layer else
                 f"{r.obj.name}:{r.mode}:{_input_shape(r.obj, r)}:{r.filter}:{r.blend > 0}" for r in ob.b4d_vol_items if r.layer or r in live] +
                [str(len(ob.b4d_vol_items)), f"fog:{ob.b4d_vol_fog}", f"view:{ob.b4d_vol_view}"])
    src = builder_of(ob)
    return [src.name if src else "", getattr(_material(ob), "name", ""), f"quads:{ob.b4d_vq_on}"]


def rebuild(ob):
    k = kind(ob)
    mod = mod_of(ob)
    if mod is None:
        mod = ob.modifiers.new(MOD, "NODES")
    old = {}
    if mod.node_group is not None:
        for it in mod.node_group.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT":
                try:
                    old[it.name] = getattr(*input_slot(mod, it.identifier))
                except Exception:
                    pass
    tree = build_builder(ob) if k == "volume_builder" else build_mesher(ob)
    mod.node_group = tree
    for name, v in old.items():
        if name in tree.interface.items_tree:
            try:
                set_input(mod, tree.interface.items_tree[name].identifier, v)
            except Exception:
                pass
    ob["b4d_vol_sig"] = _signature(ob)
    ob.update_tag()


def _needs_rebuild(ob):
    mod = mod_of(ob)
    if mod is None or mod.node_group is None or mod.node_group.get("b4d_owner") != ob.name:
        return True
    return list(ob.get("b4d_vol_sig", [])) != _signature(ob)


# --- keeping things in step ------------------------------------------------------------------------------------

def _fill_list(builder):
    """New children get a row (at the end); rows whose object left (or was deleted) go."""
    kids = [c for c in g.kids_of(builder) if usable(c)]
    lst = builder.b4d_vol_items
    for i in reversed(range(len(lst))):
        if lst[i].layer:                              # filter layers are not objects: they stay
            continue
        if lst[i].obj is None or lst[i].obj not in kids:
            lst.remove(i)
    have = {r.obj for r in lst if not r.layer}
    for c in kids:
        if c not in have:
            r = lst.add()
            r.obj = c
            r.radius = max(1.0, value(builder, "Voxel Size") or 5.0) * 2.0
    if builder.b4d_vol_index >= len(lst):
        builder.b4d_vol_index = max(0, len(lst) - 1)


_busy = [False]


def sync(scene):
    if _busy[0] or scene is None:
        return
    _busy[0] = True
    try:
        keep = set()
        obs = [o for o in scene.objects if kind(o)]
        for ob in sorted(obs, key=lambda o: kind(o) != "volume_builder"):     # builders first: meshers read them
            if kind(ob) == "volume_builder":
                _fill_list(ob)
                if ob.b4d_vol_fog and any(k not in ob for k in FOG_PROPS):
                    _sync_fog(ob)
            if _needs_rebuild(ob):
                rebuild(ob)
            if enabled(ob):
                used = [r.obj for r in rows(ob)] if kind(ob) == "volume_builder" else [builder_of(ob)]
                for o in used:
                    if o is not None:
                        keep.add(o.name)
                        _hide(o)
        for o in scene.objects:
            if HIDDEN in o and o.name not in keep:
                _show(o)
            elif HIDDEN in o and kind(o) == "volume_builder" and o.hide_render == _renders_fog(o):
                o.hide_render = not _renders_fog(o)
    finally:
        _busy[0] = False


HIDDEN = "b4d_vol_hidden"      # how an object looked before a volume object took it (its own key: the generators
                               # bring back what they hid, and would bring these back too)


def _hide(ob):
    if HIDDEN in ob:
        return
    ob[HIDDEN] = {"display": ob.display_type, "render": int(ob.hide_render)}
    ob.display_type = "BOUNDS" if kind(ob) == "volume_builder" else "WIRE"   # a volume drawn as a wire still shows its fog
    ob.hide_render = not _renders_fog(ob)


def _renders_fog(ob):
    """A Volume Builder set to Render as Fog keeps rendering under a Volume Mesher: the fog and the surface together."""
    return kind(ob) == "volume_builder" and ob.b4d_vol_fog


def _show(ob):
    was = ob.get(HIDDEN)
    try:
        display, render = str(was.get("display", "TEXTURED")), bool(was.get("render", 0))
    except (TypeError, AttributeError):
        display, render = "TEXTURED", False
    del ob[HIDDEN]
    try:
        ob.display_type = display
    except TypeError:
        ob.display_type = "TEXTURED"
    ob.hide_render = render


def sync_all():
    sync(bpy.context.scene)


@bpy.app.handlers.persistent
def _on_update(scene, depsgraph=None):
    sync(scene)
    if depsgraph is not None and not _busy[0]:
        changed = {u.id.name for u in depsgraph.updates if isinstance(u.id, bpy.types.Object) and FEED not in u.id}
        if changed:
            _busy[0] = True
            try:
                feed_all(scene, depsgraph, only=changed)
            finally:
                _busy[0] = False


# --- Render as Fog ---------------------------------------------------------------------------------------------

def fog_material():
    """One shared volume material: density from the builder's fog grid times the object's Fog Density, coloured by
    its Fog Color (both read from the object, so builders sharing it can differ)."""
    mat = bpy.data.materials.get(FOG_MATERIAL)
    if mat is not None and mat.get("b4d_fog_v", 1) >= FOG_VERSION:
        return mat
    if mat is None:
        mat = bpy.data.materials.new(FOG_MATERIAL)
    mat["b4d_fog_v"] = FOG_VERSION
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    grid = nt.nodes.new("ShaderNodeAttribute")
    grid.attribute_type, grid.attribute_name = "GEOMETRY", "density"
    amount = nt.nodes.new("ShaderNodeAttribute")
    amount.attribute_type, amount.attribute_name = "OBJECT", "b4d_fog_density"
    tint = nt.nodes.new("ShaderNodeAttribute")
    tint.attribute_type, tint.attribute_name = "OBJECT", "b4d_fog_color"
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(grid.outputs["Fac"], mul.inputs[0])
    nt.links.new(amount.outputs["Fac"], mul.inputs[1])
    # noise: clouds the size of Noise Scale (cm, in the object's space), as much as Noise says
    coord = nt.nodes.new("ShaderNodeTexCoord")
    nscale = nt.nodes.new("ShaderNodeAttribute")
    nscale.attribute_type, nscale.attribute_name = "OBJECT", "b4d_fog_noise_scale"
    per = nt.nodes.new("ShaderNodeMath")
    per.operation = "DIVIDE"
    per.inputs[0].default_value = 100.0
    safe = nt.nodes.new("ShaderNodeMath")
    safe.operation = "MAXIMUM"
    safe.inputs[1].default_value = 0.1
    nt.links.new(nscale.outputs["Fac"], safe.inputs[0])
    nt.links.new(safe.outputs[0], per.inputs[1])
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Detail"].default_value = 6.0
    nt.links.new(coord.outputs["Object"], tex.inputs["Vector"])
    nt.links.new(per.outputs[0], tex.inputs["Scale"])
    shape = nt.nodes.new("ShaderNodeMapRange")
    shape.clamp = True
    shape.inputs["From Min"].default_value, shape.inputs["From Max"].default_value = 0.42, 0.62
    nt.links.new(tex.outputs["Fac"], shape.inputs["Value"])
    namount = nt.nodes.new("ShaderNodeAttribute")
    namount.attribute_type, namount.attribute_name = "OBJECT", "b4d_fog_noise"
    broken = nt.nodes.new("ShaderNodeMix")
    broken.data_type = "FLOAT"
    broken.clamp_factor = True
    nt.links.new(namount.outputs["Fac"], broken.inputs[0])
    broken.inputs[2].default_value = 1.0
    nt.links.new(shape.outputs["Result"], broken.inputs[3])
    dens = nt.nodes.new("ShaderNodeMath")
    dens.operation = "MULTIPLY"
    nt.links.new(mul.outputs[0], dens.inputs[0])
    nt.links.new(broken.outputs[0], dens.inputs[1])
    nt.links.new(dens.outputs[0], vol.inputs["Density"])
    nt.links.new(tint.outputs["Color"], vol.inputs["Color"])
    nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
    vol.inputs["Density Attribute"].default_value = ""
    return mat


FOG_PROPS = ("b4d_fog_density", "b4d_fog_color", "b4d_fog_noise", "b4d_fog_noise_scale")
FOG_VERSION = 2                                       # the material is remade when it is older than this


def _sync_fog(ob):
    """Render as Fog on: the builder gets its own Fog Density and Fog Color (the fog material, set on the volume in
    its nodes, reads them from the object). Also takes away a fog material an earlier version put in its slots."""
    mats = ob.data.materials
    for i in reversed(range(len(mats))):
        if mats[i] is not None and mats[i].name == FOG_MATERIAL:
            mats.pop(index=i)
    if ob.b4d_vol_fog:
        if "b4d_fog_density" not in ob:
            ob["b4d_fog_density"] = 5.0
            ob.id_properties_ui("b4d_fog_density").update(min=0.0, soft_max=100.0, description="How thick the fog is")
        if "b4d_fog_color" not in ob:
            ob["b4d_fog_color"] = (0.8, 0.8, 0.8)
            ob.id_properties_ui("b4d_fog_color").update(subtype="COLOR", min=0.0, max=1.0, description="The fog's colour")
        if "b4d_fog_noise" not in ob:
            ob["b4d_fog_noise"] = 0.0
            ob.id_properties_ui("b4d_fog_noise").update(min=0.0, max=1.0, soft_max=1.0,
                                                        description="Break the fog up into wisps and clouds (0 to 1)")
        if "b4d_fog_noise_scale" not in ob:
            ob["b4d_fog_noise_scale"] = 50.0
            ob.id_properties_ui("b4d_fog_noise_scale").update(min=0.1, soft_max=1000.0,
                                                              description="How big the clouds of the noise are (cm)")


def _fog_changed(self, context):
    _sync_fog(self)
    sync_all()


# --- making them -----------------------------------------------------------------------------------------------

def create(context, k):
    sel = g._selection(context)
    ob = bpy.data.objects.new(LABELS[k], bpy.data.meshes.new(LABELS[k]))
    context.collection.objects.link(ob)
    ob["b4d_type"] = k
    tidy_name(ob)
    if k == "volume_mesher":
        sel = [o for o in sel if kind(o) == "volume_builder"][:1]     # a Mesher takes one Volume Builder
    else:
        sel = [o for o in sel if usable(o) or o.type == "EMPTY"]
    if sel:
        g.wrap(ob, sel)
    else:
        ob.location = context.scene.cursor.location
    rebuild(ob)
    sync_all()
    return ob


# --- the Objects list ------------------------------------------------------------------------------------------

def _row_changed(self, context):
    sync_all()


def _density_changed(self, context):
    ob = self.id_data
    if isinstance(ob, bpy.types.Object):
        if self.obj is not None:
            try:
                _feed(self.obj, self, context.evaluated_depsgraph_get())
            except Exception:
                pass
        ob.update_tag()


def _blend_changed(self, context):
    if isinstance(self.id_data, bpy.types.Object):
        self.id_data.update_tag()
    sync_all()                                        # 0 and above 0 build different nodes


def _live(self, context):
    if isinstance(self.id_data, bpy.types.Object):
        self.id_data.update_tag()


def _is_field(self, ob):
    from . import moclone_fx as fx
    return fx.is_field(ob)


class BLENDA4D_PG_volume_field(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object, name="Field", poll=_is_field, update=_row_changed)
    on: bpy.props.BoolProperty(name="On", default=True, description="Use this field", update=_live)
    mix: bpy.props.EnumProperty(name="Mix", items=FIELD_MIX, default="MAX", update=_row_changed,
                                description="How this field goes together with the ones above it in the list")
    opacity: bpy.props.FloatProperty(name="Opacity", default=100.0, min=0.0, max=100.0, subtype="PERCENTAGE",
                                     description="How much this field counts", update=_live)


class BLENDA4D_PG_volume_item(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object, name="Object")
    layer: bpy.props.StringProperty(name="Filter Layer", description="Not empty for a filter layer: which effect")
    fields: bpy.props.CollectionProperty(type=BLENDA4D_PG_volume_field)
    use: bpy.props.BoolProperty(name="Use", default=True, update=_row_changed,
                                description="Leave this object out for a while without taking it out from under the Volume Builder")
    mode: bpy.props.EnumProperty(name="Mode", items=MODES, default="ADD", update=_row_changed,
                                 description="How this object meets the volume made by the rows above it")
    source: bpy.props.EnumProperty(name="Volume From", items=SOURCES, default="AUTO", update=_row_changed,
                                   description="What part of the object becomes volume")
    radius: bpy.props.FloatProperty(name="Radius", default=10.0, min=0.0, soft_max=1000.0, precision=1,
                                    description="How thick the tubes, balls or shell are (cm)")
    density: bpy.props.FloatProperty(name="Density", default=0.1, min=0.0, soft_max=1.0, precision=3, update=_density_changed,
                                     description="Smoke or volume thicker than this becomes volume")
    grid: bpy.props.StringProperty(name="Grid", default="density", update=_row_changed,
                                   description="Which grid of the volume (VDB) to read")
    blend: bpy.props.FloatProperty(name="Blend", default=0.0, min=0.0, soft_max=100.0, precision=1, update=_blend_changed,
                                   description="Melt this object into the rows above it over this distance (cm): 0 is a sharp edge")
    grow: bpy.props.FloatProperty(name="Grow / Shrink", default=0.0, soft_min=-100.0, soft_max=100.0, precision=1,
                                  description="Make this object's part thicker (positive) or thinner (cm)")
    smooth: bpy.props.IntProperty(name="Smoothing", default=0, min=0, max=50,
                                  description="Filter this object's part before it meets the rows above: how many passes")
    filter: bpy.props.EnumProperty(name="Filter", items=[(k, label, tip) for k, label, tip, _n, _w in FILTERS], default="MEAN",
                                   update=_row_changed, description="How this object's part is smoothed")


class BLENDA4D_UL_volume_items(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "use", text="")
        sub = row.row()
        sub.active = item.use
        if item.layer:
            label, _tip, _n, _w, icon_ = LAYERS.get(item.layer, ("?", "", "", False, "QUESTION"))
            n = len(_fields(item))
            sub.label(text=f"{label} (filter)" + (f" · {n} field{'s' if n > 1 else ''}" if n else ""), icon=icon_)
            return
        ob = item.obj
        sub.label(text=ob.name if ob else "(gone)", icon=kinds.KINDS.get(kind(ob), {}).get("icon", "OBJECT_DATA")
                  if kind(ob) else {"MESH": "MESH_DATA", "CURVE": "CURVE_DATA", "POINTCLOUD": "POINTCLOUD_DATA", "FONT": "FONT_DATA",
                   "META": "META_DATA", "SURFACE": "SURFACE_DATA", "GREASEPENCIL": "OUTLINER_DATA_GREASEPENCIL",
                   "VOLUME": "VOLUME_DATA", "EMPTY": "OUTLINER_OB_GROUP_INSTANCE"}.get(
                      getattr(ob, "type", ""), "OBJECT_DATA"))
        sub.prop(item, "mode", text="", icon_only=True, emboss=False)


class BLENDA4D_OT_volume_move(bpy.types.Operator):
    """Move the chosen object up or down the list: the order decides what adds to and cuts from what"""
    bl_idname = "blenda4d.volume_move"
    bl_label = "Move in List"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})
    step: bpy.props.IntProperty(options={"HIDDEN"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None:
            return {"CANCELLED"}
        i, j = ob.b4d_vol_index, ob.b4d_vol_index + self.step
        if not (0 <= i < len(ob.b4d_vol_items) and 0 <= j < len(ob.b4d_vol_items)):
            return {"CANCELLED"}
        ob.b4d_vol_items.move(i, j)
        ob.b4d_vol_index = j
        rebuild(ob)                                   # the drivers point at rows by number
        sync_all()
        return {"FINISHED"}


class BLENDA4D_OT_volume_add_layer(bpy.types.Operator):
    """Add a filter layer under the chosen row: it changes everything made by the rows above it"""
    bl_idname = "blenda4d.volume_add_layer"
    bl_label = "Add Filter Layer"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})
    effect: bpy.props.EnumProperty(items=[(k, v[0], v[1]) for k, v in LAYERS.items()])

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None:
            return {"CANCELLED"}
        lst = ob.b4d_vol_items
        it = lst.add()
        it.layer = self.effect
        it.smooth = 2
        it.grow = max(1.0, value(ob, "Voxel Size") or 5.0) * 2.0
        at = min(ob.b4d_vol_index + 1, len(lst) - 1) if len(lst) > 1 else 0
        lst.move(len(lst) - 1, at)
        ob.b4d_vol_index = at
        rebuild(ob)
        sync_all()
        return {"FINISHED"}


class BLENDA4D_MT_volume_layer_add(bpy.types.Menu):
    bl_label = "Add Filter Layer"
    bl_idname = "BLENDA4D_MT_volume_layer_add"

    def draw(self, context):
        ob = context.view_layer.objects.active
        for k, (label, _tip, _n, _w, icon) in LAYERS.items():
            op = self.layout.operator("blenda4d.volume_add_layer", text=label, icon=icon)
            op.owner, op.effect = getattr(ob, "name", ""), k


class BLENDA4D_OT_volume_remove_layer(bpy.types.Operator):
    """Take this filter layer out of the list"""
    bl_idname = "blenda4d.volume_remove_layer"
    bl_label = "Remove Filter Layer"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})
    index: bpy.props.IntProperty(options={"HIDDEN"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None or not (0 <= self.index < len(ob.b4d_vol_items)) or not ob.b4d_vol_items[self.index].layer:
            return {"CANCELLED"}
        ob.b4d_vol_items.remove(self.index)
        ob.b4d_vol_index = max(0, min(ob.b4d_vol_index, len(ob.b4d_vol_items) - 1))
        rebuild(ob)
        sync_all()
        return {"FINISHED"}


class BLENDA4D_OT_volume_add_field(bpy.types.Operator):
    """Make a new field and limit the chosen filter layer to where it reaches"""
    bl_idname = "blenda4d.volume_add_field"
    bl_label = "Add Field"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})
    index: bpy.props.IntProperty(options={"HIDDEN"})
    field: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None or not (0 <= self.index < len(ob.b4d_vol_items)):
            return {"CANCELLED"}
        for o in context.selected_objects:            # the new field is made on its own, not with the builder selected
            o.select_set(False)
        bpy.ops.blenda4d.add_kind(kind=self.field)
        f = context.view_layer.objects.active
        if f is None or f == ob:
            return {"CANCELLED"}
        f.location = ob.matrix_world.translation
        it = ob.b4d_vol_items[self.index].fields.add()
        it.obj = f
        rebuild(ob)
        sync_all()
        return {"FINISHED"}


class BLENDA4D_MT_volume_field_add(bpy.types.Menu):
    bl_label = "Add Field"
    bl_idname = "BLENDA4D_MT_volume_field_add"

    def draw(self, context):
        from . import moclone_fx as fx
        ob = getattr(context, "b4d_vol_owner", None) or context.view_layer.objects.active
        for k, (label, _tip) in fx.FIELDS.items():
            op = self.layout.operator("blenda4d.volume_add_field", text=label, icon=fx.ICONS.get(k, "SPHERE"))
            op.owner, op.index, op.field = ob.name, ob.b4d_vol_index, k


class BLENDA4D_OT_volume_remove_field(bpy.types.Operator):
    """Take this field out of the layer's list (the field stays in the scene)"""
    bl_idname = "blenda4d.volume_remove_field"
    bl_label = "Remove Field"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})
    index: bpy.props.IntProperty(options={"HIDDEN"})
    field: bpy.props.IntProperty(options={"HIDDEN"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None or not (0 <= self.index < len(ob.b4d_vol_items)):
            return {"CANCELLED"}
        fs = ob.b4d_vol_items[self.index].fields
        if 0 <= self.field < len(fs):
            fs.remove(self.field)
        rebuild(ob)
        sync_all()
        return {"FINISHED"}


# --- Attribute Manager pages -----------------------------------------------------------------------------------

def _settings(col, ob):
    for sname, _t, _d, _lo, _hi, _tip in INPUTS[kind(ob)]:
        s = slot(ob, sname)
        if s is not None:
            col.prop(*s, text=sname + (" (cm)" if sname in ("Voxel Size", "Grow / Shrink", "Threshold") else ""))


def page_builder(col, ob):
    col.use_property_split = True
    for sname in ("Voxel Size", "Grow / Shrink", "Smoothing", "Rounding"):
        s = slot(ob, sname)
        if s is not None:
            col.prop(*s, text=sname + (" (cm)" if sname in ("Voxel Size", "Grow / Shrink") else ""))
    if not ob.b4d_vol_fog:
        col.prop(ob, "b4d_vol_view")
    col.prop(ob, "b4d_vol_fog")
    if ob.b4d_vol_fog:
        sub = col.column()
        if "b4d_fog_density" in ob:
            sub.prop(ob, '["b4d_fog_density"]', text="Fog Density")
            sub.prop(ob, '["b4d_fog_color"]', text="Fog Color")
        if "b4d_fog_noise" in ob:
            sub.prop(ob, '["b4d_fog_noise"]', text="Noise")
            sub.prop(ob, '["b4d_fog_noise_scale"]', text="Noise Scale (cm)")
        s = slot(ob, "Fog Edge")
        if s is not None:
            sub.prop(*s, text="Fog Edge (cm)")
        if HIDDEN in ob:
            sub.label(text="Renders as fog around the Volume Mesher's surface", icon="INFO")
    col.separator()
    col.use_property_split = False
    col.label(text="Objects, in the order they meet")
    r = col.row()
    r.template_list("BLENDA4D_UL_volume_items", "", ob, "b4d_vol_items", ob, "b4d_vol_index", rows=4)
    side = r.column(align=True)
    for icon, step in (("TRIA_UP", -1), ("TRIA_DOWN", 1)):
        op = side.operator("blenda4d.volume_move", text="", icon=icon)
        op.owner, op.step = ob.name, step
    col.menu("BLENDA4D_MT_volume_layer_add", text="Add Filter Layer", icon="ADD")
    lst = ob.b4d_vol_items
    i = ob.b4d_vol_index
    if 0 <= i < len(lst) and lst[i].layer:
        _page_layer(col, ob, i, lst[i])
        return
    if not len(lst):
        col.label(text="Drag meshes, splines, text, points or Volume Builders here or under it", icon="INFO")
        return
    i = ob.b4d_vol_index
    if 0 <= i < len(lst) and lst[i].obj is not None:
        row = lst[i]
        box = col.column()
        box.use_property_split = True
        box.label(text=f"Row: {row.obj.name}")
        box.prop(row, "mode")
        if i == 0:
            box.label(text="The first row starts the volume", icon="INFO")
        if kind(row.obj) != "volume_builder":
            box.prop(row, "source")
        shape = _input_shape(row.obj, row)
        if shape in ("tube", "points", "text", "particles"):
            box.prop(row, "radius", text="Radius (cm)")
        if shape in ("smoke", "fog"):
            box.prop(row, "density", text="Density")
        if shape == "fog":
            box.prop(row, "grid")
        if shape == "smoke":
            ds = _smoke_domain(row.obj)
            if ds is not None and ds.use_adaptive_domain:
                box.label(text="Adaptive Domain moves the smoke: turn it off for the volume to follow", icon="ERROR")
            box.label(text="Reads the smoke cache: bake it, or play the simulation", icon="INFO")
        if shape == "particles":
            box.label(text="Follows the live particles as the frames play", icon="INFO")
        if i > 0:
            box.prop(row, "blend", text="Blend (cm)")
        box.prop(row, "grow", text="Grow / Shrink (cm)")
        box.prop(row, "filter")
        box.prop(row, "smooth", text="Passes")
        if shape == "solid" and row.obj.type == "MESH" and len(row.obj.data.polygons) and not _closed(row.obj):
            box.label(text="This mesh has holes: its inside may come out wrong", icon="ERROR")


def _page_layer(col, ob, i, row):
    from . import icons
    from . import moclone_fx as fx
    label, tip, _n, _w, _icon = LAYERS.get(row.layer, ("?", "", "", False, ""))
    box = col.column()
    box.use_property_split = True
    head = box.row()
    head.label(text=f"Filter layer: {label}")
    rm = head.operator("blenda4d.volume_remove_layer", text="", icon="X", emboss=False)
    rm.owner, rm.index = ob.name, i
    box.label(text="Works on everything made by the rows above it", icon="INFO")
    if row.layer == "GROW":
        box.prop(row, "grow", text="Distance (cm)")
    else:
        box.prop(row, "smooth", text="Passes")
    box.separator()
    box.use_property_split = False
    box.label(text="Fields: where it works (none: everywhere)")
    fl = box.column(align=True)
    for j, it in enumerate(row.fields):
        line = fl.row(align=True)
        split = line.split(factor=0.45, align=True)
        left, right = split.row(align=True), split.row(align=True)
        left.alignment = "LEFT"
        if it.obj is None:
            left.label(text="(gone)", icon="ERROR")
        else:
            left.prop(it, "on", text="")
            op = left.operator("blenda4d.fx_select", text=it.obj.name, emboss=False,
                               **icons.kw(fx.ICONS.get(it.obj.get("b4d_type"), "DOT"), "fields"))
            op.name = it.obj.name
            right.prop(it, "mix", text="")
            right.prop(it, "opacity", text="")
        r = right.operator("blenda4d.volume_remove_field", text="", icon="X", emboss=False)
        r.owner, r.index, r.field = ob.name, i, j
    if not len(row.fields):
        fl.label(text="Drag fields here from the Object Manager", icon="INFO")
    box.menu("BLENDA4D_MT_volume_field_add", text="Add Field", icon="ADD")


def _closed(ob):
    """True when every edge of the mesh is shared by two faces (it has an inside)."""
    me = ob.data
    if not hasattr(me, "edges") or not len(me.polygons):
        return False
    count = {}
    for p in me.polygons:
        for k in p.edge_keys:
            count[k] = count.get(k, 0) + 1
    return all(n == 2 for n in count.values())


def page_mesher(col, ob):
    col.use_property_split = True
    _settings(col, ob)
    if builder_of(ob) is None:
        col.label(text="Put a Volume Builder under it", icon="INFO")
        return
    col.separator()
    col.label(text="Quad Remesh")
    col.prop(ob, "b4d_vq_faces")
    col.prop(ob, "b4d_vq_sharp")
    row = col.row(heading="Symmetry", align=True)
    for axis in "xyz":
        row.prop(ob, f"b4d_vq_sym_{axis}", text=axis.upper(), toggle=True)
    if ob.b4d_vq_sym_x or ob.b4d_vq_sym_y or ob.b4d_vq_sym_z:
        col.label(text="Mirrors across the Mesher's centre, keeping the fuller side", icon="MOD_MIRROR")
    r = col.row(align=True)
    op = r.operator("blenda4d.volume_quad_remesh", text="Update Quads" if ob.b4d_vq_on else "Remesh to Quads", icon="MOD_REMESH")
    op.owner = ob.name
    if ob.b4d_vq_on:
        op = r.operator("blenda4d.volume_quad_live", text="Back to Live", icon="LOOP_BACK")
        op.owner = ob.name
    msg = str(ob.get("b4d_vq_msg", ""))
    if msg.startswith("!"):
        col.label(text=msg[1:], icon="ERROR")
    elif msg and ob.b4d_vq_on:
        col.label(text=msg, icon="CHECKMARK")
    if ob.b4d_vq_on:
        col.label(text="Showing quads: changes to the volume show after Update Quads", icon="INFO")


# --- Quad Remesh -----------------------------------------------------------------------------------------------

SHOWN_AXIS = {"x": 0, "y": 2, "z": 1}                 # the shown axes (Y up) in Blender's space


def _live_surface(mesher, context):
    """The Mesher's surface as it is now made from its Volume Builder, as a new mesh."""
    was = mesher.b4d_vq_on
    if was:
        mesher.b4d_vq_on = False                  # look at the live surface (without the update callback)
        rebuild(mesher)
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(mesher.evaluated_get(dg))
    if was:
        mesher.b4d_vq_on = True
        rebuild(mesher)
    return me


QF_INPUT = 20                                         # QuadriFlow needs only the shape: about this many faces per quad wanted


def _quadriflow(context, me, mesher, sym):
    """Run QuadriFlow on a copy holding `me`; returns the new mesh or None."""
    tmp = bpy.data.objects.new("Blenda Quad Remesh", me)
    context.scene.collection.objects.link(tmp)
    try:
        with context.temp_override(active_object=tmp, object=tmp, selected_objects=[tmp], selected_editable_objects=[tmp]):
            res = bpy.ops.object.quadriflow_remesh(mode="FACES", target_faces=mesher.b4d_vq_faces, use_mesh_symmetry=sym,
                                                   use_preserve_sharp=mesher.b4d_vq_sharp, use_preserve_boundary=True, seed=0)
        out = tmp.data
        if "FINISHED" not in res or not len(out.polygons) or any(len(p.vertices) != 4 for p in out.polygons[:50]):
            return None
        tmp.data = bpy.data.meshes.new("_")                # keep the result when the helper goes
        return out
    finally:
        d = tmp.data
        bpy.data.objects.remove(tmp)
        if d is not None and d.users == 0:
            bpy.data.meshes.remove(d)


def _repaired(context, me, voxel):
    """A copy of `me` remade watertight by Blender's voxel remesh at `voxel` (m): it also cuts a very fine surface
    down quickly, and mends tiny holes, pinches and stray bits."""
    tmp = bpy.data.objects.new("Blenda Quad Remesh", me.copy())
    context.scene.collection.objects.link(tmp)
    try:
        tmp.data.remesh_voxel_size = voxel
        with context.temp_override(active_object=tmp, object=tmp, selected_objects=[tmp], selected_editable_objects=[tmp]):
            bpy.ops.object.voxel_remesh()
        out = tmp.data
        tmp.data = bpy.data.meshes.new("_")
        return out
    finally:
        d = tmp.data
        bpy.data.objects.remove(tmp)
        if d is not None and d.users == 0:
            bpy.data.meshes.remove(d)


def quad_remesh(mesher, context):
    """Remesh the Mesher's surface into quads that follow its shape (Blender's QuadriFlow), kept in the Mesher's own
    mesh; with symmetry the fuller side is mirrored across the Mesher's centre first, so the quads match too. A very
    fine surface is cut down first (QuadriFlow only needs the shape); if QuadriFlow refuses the surface it is tried
    once more on a watertight copy. The outcome is kept in b4d_vq_msg for the page. Returns an error message, or None."""
    import bmesh
    import time
    t0 = time.time()
    wm = context.window_manager
    wm.progress_begin(0, 4)
    made = []
    try:
        me = _live_surface(mesher, context)
        made.append(me)
        if not len(me.polygons):
            return _said(mesher, "There is no surface to remesh")
        wm.progress_update(1)
        want = mesher.b4d_vq_faces * QF_INPUT
        if len(me.polygons) > want * 1.5:              # very fine: QuadriFlow needs only the shape, so cut it down first
            import numpy as np
            areas = np.empty(len(me.polygons), dtype=np.float32)
            me.polygons.foreach_get("area", areas)
            me = _repaired(context, me, max(1e-4, float(np.sqrt(areas.sum() / want))))
            made.append(me)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        axes = [a for a in "xyz" if getattr(mesher, f"b4d_vq_sym_{a}")]
        for a in axes:
            k = SHOWN_AXIS[a]
            plus = sum(max(v.co[k], 0.0) for v in bm.verts)
            minus = sum(max(-v.co[k], 0.0) for v in bm.verts)
            bmesh.ops.symmetrize(bm, input=bm.verts[:] + bm.edges[:] + bm.faces[:],
                                 direction=("" if plus >= minus else "-") + "XYZ"[k], dist=1e-4)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        for k in range(3):
            setattr(me, f"use_mirror_{'xyz'[k]}", any(SHOWN_AXIS[a] == k for a in axes))
        wm.progress_update(2)
        quads = _quadriflow(context, me, mesher, bool(axes))
        if quads is None:                              # pinches, tiny holes or stray bits: make it watertight, try again
            src = builder_of(mesher)
            voxel = max(0.001, (value(src, "Voxel Size") or 5.0) * SCALE) if src else 0.05
            fixed = _repaired(context, me, voxel)
            made.append(fixed)
            for k in range(3):
                setattr(fixed, f"use_mirror_{'xyz'[k]}", getattr(me, f"use_mirror_{'xyz'[k]}"))
            wm.progress_update(3)
            quads = _quadriflow(context, fixed, mesher, bool(axes))
        if quads is None:
            return _said(mesher, "Quad Remesh failed on this surface: try fewer Target Faces or a larger Voxel Size")
        mats = [m for m in mesher.data.materials]
        old = mesher.data
        quads.name = old.name
        mesher.data = quads
        for m in mats:
            quads.materials.append(m)
        smooth = bool(value(mesher, "Smooth Shading"))
        for p in quads.polygons:
            p.use_smooth = smooth
        if old.users == 0:
            bpy.data.meshes.remove(old)
        mesher.b4d_vq_on = True
        rebuild(mesher)
        _said(mesher, f"{len(quads.polygons)} quads in {time.time() - t0:.1f} s", ok=True)
        return None
    finally:
        wm.progress_end()
        for m in made:
            if m.name in bpy.data.meshes and m.users == 0:
                bpy.data.meshes.remove(m)


def _said(mesher, text, ok=False):
    mesher["b4d_vq_msg"] = ("" if ok else "!") + text
    return None if ok else text


class BLENDA4D_OT_volume_quad_remesh(bpy.types.Operator):
    """Remesh the surface into quads that follow its shape. The quads stay until Update Quads or Back to Live"""
    bl_idname = "blenda4d.volume_quad_remesh"
    bl_label = "Remesh to Quads"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None or kind(ob) != "volume_mesher":
            return {"CANCELLED"}
        err = quad_remesh(ob, context)
        if err:
            self.report({"WARNING"}, err)
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(ob.data.polygons)} quads")
        return {"FINISHED"}


class BLENDA4D_OT_volume_quad_live(bpy.types.Operator):
    """Leave the quads and show the surface made live from the Volume Builder again"""
    bl_idname = "blenda4d.volume_quad_live"
    bl_label = "Back to Live"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None or kind(ob) != "volume_mesher":
            return {"CANCELLED"}
        ob.b4d_vq_on = False
        ob.data.clear_geometry()
        rebuild(ob)
        sync_all()
        return {"FINISHED"}


# --- drag and drop from the Object Manager ---------------------------------------------------------------------

def drop(context, objs, event):
    """Objects let go over a Volume Builder's page go under it (keeping their place in the world) and so join its list;
    a Volume Builder let go over a Volume Mesher's page goes under that."""
    from . import roles
    over = next((a for a in context.window.screen.areas if roles.role(a) == "ATTRIBUTES"
                 and a.x <= event.mouse_x < a.x + a.width and a.y <= event.mouse_y < a.y + a.height), None)
    ob = context.view_layer.objects.active
    if over is None or kind(ob) is None:
        return False
    from . import moclone_fx as fx
    lst = getattr(ob, "b4d_vol_items", None)
    if kind(ob) == "volume_builder" and lst is not None and 0 <= ob.b4d_vol_index < len(lst) and lst[ob.b4d_vol_index].layer:
        row = lst[ob.b4d_vol_index]                   # fields let go over a filter layer's page join its Fields list
        took = False
        for o in objs:
            if fx.is_field(o) and all(f.obj != o for f in row.fields):
                row.fields.add().obj = o
                took = True
        if took:
            rebuild(ob)
            sync_all()
            over.tag_redraw()
            return True
    if kind(ob) == "volume_mesher":
        objs = [o for o in objs if kind(o) == "volume_builder"][:1] if builder_of(ob) is None else []
    else:
        objs = [o for o in objs if usable(o) and o != ob and ob not in _ancestors_and_self(o)]
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = ob
        o.matrix_parent_inverse.identity()
        o.matrix_world = mw
    if objs:
        sync_all()
        over.tag_redraw()
    return bool(objs)


def _ancestors_and_self(o):
    out = []
    while o is not None:
        out.append(o)
        o = o.parent
    return out


# --- registration ----------------------------------------------------------------------------------------------

classes = (BLENDA4D_PG_volume_field, BLENDA4D_PG_volume_item, BLENDA4D_UL_volume_items, BLENDA4D_OT_volume_move,
           BLENDA4D_OT_volume_add_layer, BLENDA4D_MT_volume_layer_add, BLENDA4D_OT_volume_remove_layer,
           BLENDA4D_OT_volume_add_field, BLENDA4D_MT_volume_field_add, BLENDA4D_OT_volume_remove_field,
           BLENDA4D_OT_volume_quad_remesh, BLENDA4D_OT_volume_quad_live)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.b4d_vol_items = bpy.props.CollectionProperty(type=BLENDA4D_PG_volume_item)
    bpy.types.Object.b4d_vol_index = bpy.props.IntProperty(default=0)
    bpy.types.Object.b4d_vol_fog = bpy.props.BoolProperty(
        name="Render as Fog", default=False, update=_fog_changed,
        description="Render the volume as fog or smoke (a volume material reads it), not only feed a Volume Mesher")
    bpy.types.Object.b4d_vol_view = bpy.props.EnumProperty(
        name="Viewport", default="SURFACE", update=_row_changed,
        items=[("SURFACE", "Surface", "Show the volume's surface as a solid shape"),
               ("VOXELS", "Voxels", "Show the volume as a cube on every voxel at its surface"),
               ("FOG", "Fog", "Show the volume as a soft fog")],
        description="How the Volume Builder looks in the viewport (renders are not affected)")
    O = bpy.types.Object
    O.b4d_vq_on = bpy.props.BoolProperty(name="Showing Quads", default=False, options={"HIDDEN"})
    O.b4d_vq_faces = bpy.props.IntProperty(name="Target Faces", default=4000, min=50, soft_max=100000,
                                           description="About how many quads to make")
    O.b4d_vq_sharp = bpy.props.BoolProperty(name="Keep Sharp Edges", default=True,
                                            description="Let the quads follow sharp edges and corners")
    for axis in "XYZ":
        setattr(O, f"b4d_vq_sym_{axis.lower()}", bpy.props.BoolProperty(
            name=f"Symmetry {axis}", default=False,
            description=f"Make the quads (and the shape) the same on both sides of the Mesher's centre along {axis}"))
    from . import managers
    if drop not in managers.OM_DROP:
        managers.OM_DROP.append(drop)
    pages = {"volume_builder": page_builder, "volume_mesher": page_mesher}
    for k in ("volume_builder", "volume_mesher"):
        kinds.add(k, LABELS[k], ICONS[k], create=(lambda k: lambda context: create(context, k))(k),
                  tabs=[("OBJECT", "Object")], pages={"OBJECT": pages[k]}, titles={"OBJECT": LABELS[k]},
                  describe=TIPS[k] + " (selected objects go under it)")
        kinds.create_button("volume", LABELS[k], k)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)
    if _on_frame not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_on_frame)


def unregister():
    if _on_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_update)
    if _on_frame in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_on_frame)
    from . import managers
    if drop in managers.OM_DROP:
        managers.OM_DROP.remove(drop)
    for n in ("b4d_vol_items", "b4d_vol_index", "b4d_vol_fog", "b4d_vol_view", "b4d_vq_on", "b4d_vq_faces", "b4d_vq_sharp",
              "b4d_vq_sym_x", "b4d_vq_sym_y", "b4d_vq_sym_z"):
        if hasattr(bpy.types.Object, n):
            delattr(bpy.types.Object, n)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
