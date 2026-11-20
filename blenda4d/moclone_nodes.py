# SPDX-License-Identifier: GPL-3.0-or-later
"""Node builders for MoClone (moclone.py has the objects, pages and sync).

Every MoClone object is a mesh object with one Geometry Nodes modifier whose group is built for that object:
- Cloner: the objects under it, copied by the chosen layout (Linear, Grid, Radial, Honeycomb, Object).
- Matrix: the same layouts, with a small cube on every place and no children; it shows the places and does not
  render. A Cloner in Object mode can use a Matrix's places.
- Fracture: the objects under it, each one a piece effectors can move (or every loose part of them a piece).
- Voronoi Fracture: the objects under it broken into pieces (moclone.py cuts them; the group turns each into a piece).
- Tracer: lines drawn through the places an object or a Cloner's copies pass over time.

The group inputs are the object's settings (Blenda units: cm, degrees, percent, shown Y up). Each effector in the
object's Effectors list adds a stage that changes the pieces; each Field in an effector's Fields list limits where
that effector acts. Effector and Field settings are custom properties on their own objects, read by drivers in the
group, so one effector or Field can serve several objects and a file keeps working with the add-on off.

Every piece carries a colour in the instance attribute "Clone Color" (white unless an effector tints it); a material
reads it with an Attribute node.

Shown axes are Y up (coords.py): shown (x, y, z) = Blender (x, z, y). Lengths: 1 cm = 0.01 m."""
import math

import bpy

SCALE = 0.01
COLOR_ATTR = "Clone Color"
_ROT, _SCL = ".b4d_clone_rot", ".b4d_clone_scale"     # per-point values carried from the layout to the copies
_CENTRE, _ISLAND, _NORMAL, _FRAME = ".b4d_piece_centre", ".b4d_piece", ".b4d_clone_n", ".b4d_trace_frame"

MODES = [("Linear", 0), ("Grid", 1), ("Radial", 2), ("Honeycomb", 3), ("Object", 4)]
STEP_MODES = [("Per Step", 0), ("End Point", 1)]
FORMS = [("Box", 0), ("Sphere", 1), ("Cylinder", 2)]
PLANES = [("XZ", 0), ("XY", 1), ("ZY", 2)]
DISTRIBUTIONS = [("Along Spline", 0), ("Points", 1), ("Surface", 2)]
ORDERS = [("Iterate", 0), ("Random", 1)]

# the layout settings shared by the Cloner and the Matrix: (socket, type, default)
LAYOUT = [
    ("Mode", "MENU", "Linear"),
    ("Count", "INT", 3),
    ("Offset Mode", "MENU", "Per Step"),
    ("Offset", "VECTOR", (100.0, 0.0, 0.0)),
    ("Step Rotation", "VECTOR", (0.0, 0.0, 0.0)),
    ("Step Size", "FLOAT", 0.0),
    ("Count X", "INT", 5), ("Count Y", "INT", 1), ("Count Z", "INT", 3),
    ("Spacing Mode", "MENU", "Per Step"),
    ("Spacing", "VECTOR", (150.0, 100.0, 150.0)),
    ("Form", "MENU", "Box"),
    ("Radius", "FLOAT", 200.0),
    ("Start Angle", "FLOAT", 0.0),
    ("End Angle", "FLOAT", 360.0),
    ("Plane", "MENU", "XZ"),
    ("Object", "OBJECT", None),
    ("Distribution", "MENU", "Along Spline"),
    ("Align", "BOOL", True),
    ("Seed", "INT", 0),
]
INPUTS = {
    "cloner": LAYOUT + [("Clone Order", "MENU", "Iterate"), ("Keep Instances", "BOOL", False)],
    "matrix": LAYOUT + [("Cube Size", "FLOAT", 10.0)],
    "fracture": [("Explode Segments", "BOOL", False), ("Keep Instances", "BOOL", False)],
    "voronoi_fracture": [("Piece Size", "FLOAT", 100.0), ("Keep Instances", "BOOL", False)],
    "tracer": [("Object", "OBJECT", None), ("Limit", "INT", 0), ("Thickness", "FLOAT", 0.0)],
}
MENUS = {"Mode": MODES, "Plane": PLANES, "Distribution": DISTRIBUTIONS, "Clone Order": ORDERS,
         "Offset Mode": STEP_MODES, "Spacing Mode": STEP_MODES, "Form": FORMS}
LIMITS = {"Count": (0, 100000), "Count X": (1, 10000), "Count Y": (1, 10000), "Count Z": (1, 10000),
          "Seed": (0, 1000000), "Radius": (0.0, 1e6), "Step Size": (-100.0, 1e4), "Cube Size": (0.1, 1e5),
          "Piece Size": (0.0, 1000.0), "Limit": (0, 100000), "Thickness": (0.0, 1e5)}
SOCKET = {"FLOAT": "NodeSocketFloat", "INT": "NodeSocketInt", "VECTOR": "NodeSocketVector", "BOOL": "NodeSocketBool",
          "OBJECT": "NodeSocketObject", "MENU": "NodeSocketMenu"}


class G:
    """A few node helpers that take either a socket or a plain number."""

    def __init__(self, tree):
        self.t, self.n, self.l = tree, tree.nodes, tree.links

    def put(self, v, sock):
        if hasattr(v, "is_output"):
            self.l.new(v, sock)
        else:
            sock.default_value = v

    def node(self, idname, **attrs):
        n = self.n.new(idname)
        for k, v in attrs.items():
            setattr(n, k, v)
        return n

    def m(self, op, a, b=None, c=None):
        n = self.node("ShaderNodeMath", operation=op)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.put(v, n.inputs[i])
        return n.outputs[0]

    def clamp(self, v):
        n = self.node("ShaderNodeClamp")
        self.put(v, n.inputs["Value"])
        return n.outputs[0]

    def v(self, op, a, b=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.put(a, n.inputs[0])
        if b is not None:
            self.put(b, n.inputs[1])
        return n.outputs["Value" if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else "Vector"]

    def scaled(self, vec, factor):
        n = self.node("ShaderNodeVectorMath", operation="SCALE")
        self.put(vec, n.inputs[0])
        self.put(factor, n.inputs["Scale"])
        return n.outputs["Vector"]

    def xyz(self, x=0.0, y=0.0, z=0.0):
        n = self.node("ShaderNodeCombineXYZ")
        for i, c in enumerate((x, y, z)):
            self.put(c, n.inputs[i])
        return n.outputs[0]

    def sep(self, vec):
        n = self.node("ShaderNodeSeparateXYZ")
        self.put(vec, n.inputs[0])
        return n.outputs

    def shown(self, vec, scale=SCALE):
        """A shown (Y up) vector to Blender's axes, times scale."""
        s = self.sep(vec)
        return self.xyz(self.m("MULTIPLY", s[0], scale), self.m("MULTIPLY", s[2], scale), self.m("MULTIPLY", s[1], scale))

    def index(self):
        return self.node("GeometryNodeInputIndex").outputs[0]

    def switch(self, kind, idx, items):
        sw = self.node("GeometryNodeIndexSwitch", data_type=kind)
        while len(sw.index_switch_items) < len(items):
            sw.index_switch_items.new()
        self.put(idx, sw.inputs[0])
        for i, it in enumerate(items):
            self.put(it, sw.inputs[i + 1])
        return sw.outputs[0]

    def geo_switch(self, flag, off, on):
        sw = self.node("GeometryNodeSwitch", input_type="GEOMETRY")
        self.put(flag, sw.inputs["Switch"])
        self.l.new(off, sw.inputs["False"])
        self.l.new(on, sw.inputs["True"])
        return sw.outputs[0]

    def store(self, geo, name, value, data_type, domain="POINT"):
        st = self.node("GeometryNodeStoreNamedAttribute", data_type=data_type, domain=domain)
        self.l.new(geo, st.inputs["Geometry"])
        st.inputs["Name"].default_value = name
        self.put(value, st.inputs["Value"])
        return st.outputs[0]

    def named(self, name, data_type):
        n = self.node("GeometryNodeInputNamedAttribute", data_type=data_type)
        n.inputs["Name"].default_value = name
        return n.outputs[0]

    def drop_attrs(self, geo, *names):
        for name in names:
            rm = self.node("GeometryNodeRemoveAttribute")
            self.l.new(geo, rm.inputs["Geometry"])
            rm.inputs["Name"].default_value = name
            geo = rm.outputs[0]
        return geo

    def join(self, geos):
        j = self.node("GeometryNodeJoinGeometry")
        for g in reversed(geos):           # a multi-input socket lists its newest link first
            self.l.new(g, j.inputs[0])
        return j.outputs[0]

    def random(self, data_type, lo, hi, seed, ident=None):
        n = self.node("FunctionNodeRandomValue", data_type=data_type)
        self.put(lo, n.inputs["Min"])
        self.put(hi, n.inputs["Max"])
        self.put(ident if ident is not None else self.index(), n.inputs["ID"])
        self.put(seed, n.inputs["Seed"])
        return n.outputs[0]

    def euler(self, vec):
        n = self.node("FunctionNodeEulerToRotation")
        self.put(vec, n.inputs[0])
        return n.outputs[0]

    def to_euler(self, rot):
        n = self.node("FunctionNodeRotationToEuler")
        self.put(rot, n.inputs[0])
        return n.outputs[0]

    def info(self, ob=None, space="RELATIVE", as_instance=False):
        n = self.node("GeometryNodeObjectInfo", transform_space=space)
        if hasattr(ob, "is_output"):
            self.l.new(ob, n.inputs["Object"])
        elif ob is not None:
            n.inputs["Object"].default_value = ob
        n.inputs["As Instance"].default_value = as_instance
        return n

    def empty(self):
        return self.node("GeometryNodeJoinGeometry").outputs[0]


# --- the layouts: each returns points carrying a rotation (Euler) and a size ---------------------------------------
def _points(g, count, position, rot=None, size=None):
    p = g.node("GeometryNodePoints")
    g.put(count, p.inputs["Count"])
    g.put(position, p.inputs["Position"])
    p.inputs["Radius"].default_value = 0.01
    out = g.store(p.outputs[0], _ROT, rot if rot is not None else (0.0, 0.0, 0.0), "FLOAT_VECTOR")
    return g.store(out, _SCL, size if size is not None else 1.0, "FLOAT")


def _step(g, total, count, mode):
    """Per Step: the value as it is; End Point: the value spread over count - 1 steps."""
    per = g.m("DIVIDE", total, g.m("MAXIMUM", g.m("SUBTRACT", count, 1.0), 1.0))
    return g.switch("FLOAT", mode, [total, per])


def layout_linear(g, o):
    i, n = g.index(), o["Count"]
    off = g.sep(o["Offset"])
    step = g.xyz(*(_step(g, off[k], n, o["Offset Mode"]) for k in range(3)))
    pos = g.scaled(g.shown(step), i)
    rot = g.scaled(g.shown(o["Step Rotation"], math.pi / 180.0), i)
    size = g.m("MAXIMUM", g.m("ADD", 1.0, g.m("MULTIPLY", i, g.m("DIVIDE", o["Step Size"], 100.0))), 0.0)
    return _points(g, n, pos, rot, size)


def _centred(g, k, n, spacing):
    return g.m("MULTIPLY", g.m("SUBTRACT", k, g.m("DIVIDE", g.m("SUBTRACT", n, 1.0), 2.0)), g.m("MULTIPLY", spacing, SCALE))


def layout_grid(g, o):
    cx, cy, cz = o["Count X"], o["Count Y"], o["Count Z"]           # shown axes: Y is up
    i = g.index()
    ix = g.m("FLOORED_MODULO", i, cx)
    iy = g.m("FLOORED_MODULO", g.m("FLOOR", g.m("DIVIDE", i, cx)), cy)
    iz = g.m("FLOOR", g.m("DIVIDE", i, g.m("MULTIPLY", cx, cy)))
    sp = g.sep(o["Spacing"])
    steps = [_step(g, sp[k], n, o["Spacing Mode"]) for k, n in enumerate((cx, cy, cz))]
    shown = (_centred(g, ix, cx, steps[0]), _centred(g, iy, cy, steps[1]), _centred(g, iz, cz, steps[2]))
    pos = g.xyz(shown[0], shown[2], shown[1])
    total = g.m("MULTIPLY", g.m("MULTIPLY", cx, cy), cz)
    pts = _points(g, total, pos)
    # Form: keep the places inside a sphere or an upright cylinder that fills the block
    half = [g.m("MAXIMUM", g.m("MULTIPLY", g.m("MULTIPLY", g.m("SUBTRACT", n, 1.0), s), 0.5 * SCALE), 1e-6)
            for n, s in zip((cx, cy, cz), steps)]
    p = g.sep(g.node("GeometryNodeInputPosition").outputs[0])
    u = (g.m("DIVIDE", p[0], half[0]), g.m("DIVIDE", p[2], half[1]), g.m("DIVIDE", p[1], half[2]))  # shown x, y, z
    ball = g.m("ADD", g.m("ADD", g.m("MULTIPLY", u[0], u[0]), g.m("MULTIPLY", u[1], u[1])), g.m("MULTIPLY", u[2], u[2]))
    tube = g.m("ADD", g.m("MULTIPLY", u[0], u[0]), g.m("MULTIPLY", u[2], u[2]))
    outside = g.switch("FLOAT", o["Form"], [0.0, g.m("GREATER_THAN", ball, 1.0001), g.m("GREATER_THAN", tube, 1.0001)])
    cut = g.node("GeometryNodeDeleteGeometry", domain="POINT")
    g.l.new(pts, cut.inputs["Geometry"])
    g.l.new(outside, cut.inputs["Selection"])
    return cut.outputs[0]


def layout_radial(g, o):
    n, i = o["Count"], g.index()
    start = g.m("RADIANS", o["Start Angle"])
    span = g.m("SUBTRACT", g.m("RADIANS", o["End Angle"]), start)
    full = g.m("GREATER_THAN", g.m("ABSOLUTE", span), 2 * math.pi - 1e-4)      # a whole turn: the last copy is not on the first
    steps = g.m("ADD", g.m("SUBTRACT", n, 1.0), full)
    a = g.m("ADD", start, g.m("MULTIPLY", span, g.m("DIVIDE", i, steps)))
    r = g.m("MULTIPLY", o["Radius"], SCALE)
    c, s = g.m("MULTIPLY", r, g.m("COSINE", a)), g.m("MULTIPLY", r, g.m("SINE", a))
    # XZ: the ground (Blender XY), turning about shown Y; XY: upright, facing shown Z (Blender XZ); ZY: upright, facing X
    pos = g.switch("VECTOR", o["Plane"], [g.xyz(c, s, 0.0), g.xyz(c, 0.0, s), g.xyz(0.0, c, s)])
    aligned = g.m("MULTIPLY", a, o["Align"])
    rot = g.switch("VECTOR", o["Plane"], [g.xyz(0.0, 0.0, aligned), g.xyz(0.0, g.m("MULTIPLY", aligned, -1.0), 0.0),
                                          g.xyz(aligned, 0.0, 0.0)])
    return _points(g, n, pos, rot)


def layout_honeycomb(g, o):
    """Rows on the ground (shown X by Z), every other row shifted by half a step, like the cells of a comb."""
    cx, cz, i = o["Count X"], o["Count Z"], g.index()
    sp = g.sep(o["Spacing"])
    sx, sz = _step(g, sp[0], cx, o["Spacing Mode"]), _step(g, sp[2], cz, o["Spacing Mode"])
    ix, iz = g.m("FLOORED_MODULO", i, cx), g.m("FLOOR", g.m("DIVIDE", i, cx))
    shift = g.m("MULTIPLY", g.m("FLOORED_MODULO", iz, 2.0), 0.5)
    x = _centred(g, g.m("ADD", ix, shift), g.m("ADD", cx, 0.5), sx)
    z = _centred(g, iz, cz, sz)
    return _points(g, g.m("MULTIPLY", cx, cz), g.xyz(x, z, 0.0))


def layout_object(g, o):
    info = g.info(o["Object"])                      # where the object is, seen from the Cloner
    parts = g.node("GeometryNodeSeparateComponents")
    g.l.new(info.outputs["Geometry"], parts.inputs[0])
    mesh, curve, inst = parts.outputs["Mesh"], parts.outputs["Curve"], parts.outputs["Instances"]

    def keep(geo, rot):
        """Store the copies' turn: following the spline or surface with Align, upright without."""
        return g.store(g.store(geo, _ROT, g.scaled(g.to_euler(rot), o["Align"]), "FLOAT_VECTOR"), _SCL, 1.0, "FLOAT")

    # Along Spline: the object's splines (or a mesh's edges) at even spacing
    m2c = g.node("GeometryNodeMeshToCurve")
    g.l.new(mesh, m2c.inputs["Mesh"])
    c2p = g.node("GeometryNodeCurveToPoints", mode="COUNT")
    g.l.new(g.join([curve, m2c.outputs[0]]), c2p.inputs["Curve"])
    g.put(g.m("MAXIMUM", o["Count"], 1.0), c2p.inputs["Count"])
    along = keep(c2p.outputs["Points"], c2p.outputs["Rotation"])
    # Points: one copy on every point of a mesh, facing along its normal, and on every place of a Matrix
    with_n = g.store(mesh, _NORMAL, g.node("GeometryNodeInputNormal").outputs[0], "FLOAT_VECTOR")
    m2p = g.node("GeometryNodeMeshToPoints", mode="VERTICES")
    g.l.new(with_n, m2p.inputs["Mesh"])
    up = g.node("FunctionNodeAlignRotationToVector", axis="Z")
    g.l.new(g.named(_NORMAL, "FLOAT_VECTOR"), up.inputs["Vector"])
    on_mesh = keep(m2p.outputs[0], up.outputs[0])
    i2p = g.node("GeometryNodeInstancesToPoints")
    g.l.new(inst, i2p.inputs["Instances"])
    places = g.store(g.store(i2p.outputs[0], _ROT, (0.0, 0.0, 0.0), "FLOAT_VECTOR"), _SCL, 1.0, "FLOAT")
    on_points = g.join([on_mesh, places])
    # Surface: Count copies scattered over the faces
    stat = g.node("GeometryNodeAttributeStatistic", data_type="FLOAT", domain="FACE")
    g.l.new(mesh, stat.inputs["Geometry"])
    g.l.new(g.node("GeometryNodeInputMeshFaceArea").outputs[0], stat.inputs["Attribute"])
    dist = g.node("GeometryNodeDistributePointsOnFaces", distribute_method="RANDOM")
    g.l.new(mesh, dist.inputs["Mesh"])
    g.l.new(g.m("DIVIDE", o["Count"], g.m("MAXIMUM", stat.outputs["Sum"], 1e-9)), dist.inputs["Density"])
    g.l.new(o["Seed"], dist.inputs["Seed"])
    scatter = keep(dist.outputs["Points"], dist.outputs["Rotation"])
    return g.switch("GEOMETRY", o["Distribution"], [along, on_points, scatter])


LAYOUTS = (layout_linear, layout_grid, layout_radial, layout_honeycomb, layout_object)


def _layout_copies(g, o, instance, order=None):
    """Instances of `instance` (a list of instances, picked by order) on the chosen layout's places."""
    pts = g.switch("GEOMETRY", o["Mode"], [fn(g, o) for fn in LAYOUTS])
    iop = g.node("GeometryNodeInstanceOnPoints")
    g.l.new(pts, iop.inputs["Points"])
    g.l.new(instance, iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    g.put(order if order is not None else 0, iop.inputs["Instance Index"])
    g.l.new(g.euler(g.named(_ROT, "FLOAT_VECTOR")), iop.inputs["Rotation"])
    g.l.new(g.named(_SCL, "FLOAT"), iop.inputs["Scale"])
    return g.drop_attrs(iop.outputs[0], _ROT, _SCL, _NORMAL)


# --- pieces: every loose part of a mesh becomes an instance placed at its own centre ---------------------------
def pieces(g, mesh):
    island = g.node("GeometryNodeInputMeshIsland").outputs["Island Index"]
    pos = g.node("GeometryNodeInputPosition").outputs[0]
    acc = g.node("GeometryNodeAccumulateField", data_type="FLOAT_VECTOR", domain="POINT")
    g.l.new(pos, acc.inputs[0])
    g.l.new(island, acc.inputs["Group ID"])
    cnt = g.node("GeometryNodeAccumulateField", data_type="FLOAT", domain="POINT")
    cnt.inputs[0].default_value = 1.0
    g.l.new(island, cnt.inputs["Group ID"])
    centre = g.scaled(acc.outputs["Total"], g.m("DIVIDE", 1.0, g.m("MAXIMUM", cnt.outputs["Total"], 1.0)))
    marked = g.store(g.store(mesh, _CENTRE, centre, "FLOAT_VECTOR"), _ISLAND, island, "INT")
    home = g.node("GeometryNodeSetPosition")
    g.l.new(marked, home.inputs["Geometry"])
    g.l.new(g.scaled(g.named(_CENTRE, "FLOAT_VECTOR"), -1.0), home.inputs["Offset"])
    split = g.node("GeometryNodeSplitToInstances", domain="FACE")
    g.l.new(home.outputs[0], split.inputs["Geometry"])
    g.l.new(g.node("GeometryNodeInputMeshIsland").outputs["Island Index"], split.inputs["Group ID"])
    # one point per part (its first point), in part order, at the part's centre
    first = g.m("COMPARE", cnt.outputs["Trailing"], 1.0, 0.0)
    m2p = g.node("GeometryNodeMeshToPoints", mode="VERTICES")
    g.l.new(marked, m2p.inputs["Mesh"])
    g.l.new(first, m2p.inputs["Selection"])
    g.l.new(g.named(_CENTRE, "FLOAT_VECTOR"), m2p.inputs["Position"])
    sort = g.node("GeometryNodeSortElements", domain="POINT")
    g.l.new(m2p.outputs[0], sort.inputs["Geometry"])
    g.l.new(g.named(_ISLAND, "INT"), sort.inputs["Sort Weight"])
    iop = g.node("GeometryNodeInstanceOnPoints")
    g.l.new(sort.outputs[0], iop.inputs["Points"])
    g.l.new(g.drop_attrs(split.outputs[0], _CENTRE, _ISLAND), iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    g.l.new(g.index(), iop.inputs["Instance Index"])
    return g.drop_attrs(iop.outputs[0], _CENTRE, _ISLAND)


# --- drivers -----------------------------------------------------------------------------------------------------------
def driven(g, ob, key, index=None, scale=1.0, name=None):
    """A value node following a custom property of ob (a driver, so keyframes on the object animate it)."""
    n = g.node("ShaderNodeValue")
    n.label = name or key
    d = n.outputs[0].driver_add("default_value").driver
    var = d.variables.new()
    var.name = "v"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = ob
    var.targets[0].data_path = f'["{key}"]' + (f"[{index}]" if index is not None else "")
    if scale == 1.0:
        d.type = "AVERAGE"
    else:
        d.type = "SCRIPTED"
        d.expression = f"v * {scale!r}"
    return n.outputs[0]


def strength(g, ob, key):
    """A percentage in 0..1, and 0 while the object's check mark is off."""
    n = g.node("ShaderNodeValue")
    n.label = "Strength"
    d = n.outputs[0].driver_add("default_value").driver
    d.type = "SCRIPTED"
    for name, path in (("s", f'["{key}"]'), ("e", '["_b4d_enabled"]')):
        var = d.variables.new()
        var.name = name
        var.type = "SINGLE_PROP"
        var.targets[0].id_type = "OBJECT"
        var.targets[0].id = ob
        var.targets[0].data_path = path
    d.expression = "s * e / 100"
    return n.outputs[0]


def _shown_vec(g, ob, key, scale):
    """A shown (Y up) vector property, in Blender's axes."""
    x, y, z = (driven(g, ob, key, i, scale) for i in range(3))
    return g.xyz(x, z, y)


def _instance_xf(g):
    xf = g.node("FunctionNodeSeparateTransform")
    g.l.new(g.node("GeometryNodeInstanceTransform").outputs[0], xf.inputs[0])
    return xf


# --- fields: where an effector acts -----------------------------------------------------------------------------------
def field_weight(g, ob, kind, at):
    """0..1 for one Field at the place `at` (in the group object's space)."""
    info = g.info(ob)
    inv = g.node("FunctionNodeInvertMatrix")
    g.l.new(info.outputs["Transform"], inv.inputs[0])
    tp = g.node("FunctionNodeTransformPoint")
    g.put(at, tp.inputs["Vector"])
    g.l.new(inv.outputs[0], tp.inputs["Transform"])
    p = tp.outputs[0]                                  # in the Field's own space, metres
    soft = g.m("MAXIMUM", driven(g, ob, "b4d_fld_falloff", scale=0.01), 1e-4)

    def edge(d):                                      # 1 inside, fading to 0 over the soft edge, 0 past 1
        return g.clamp(g.m("DIVIDE", g.m("SUBTRACT", 1.0, d), soft))
    if kind == "spherical_field":
        w = edge(g.m("DIVIDE", g.v("LENGTH", p), g.m("MAXIMUM", driven(g, ob, "b4d_fld_radius", scale=SCALE), 1e-6)))
    elif kind == "box_field":
        half = _shown_vec(g, ob, "b4d_fld_size", 0.5 * SCALE)
        q = g.sep(g.v("DIVIDE", g.v("ABSOLUTE", p), g.v("MAXIMUM", half, (1e-6, 1e-6, 1e-6))))
        w = edge(g.m("MAXIMUM", g.m("MAXIMUM", q[0], q[1]), q[2]))
    elif kind == "linear_field":                      # 0 at the Field, 1 one Length along its shown Z (Blender Y)
        w = g.clamp(g.m("DIVIDE", g.sep(p)[1], g.m("MAXIMUM", driven(g, ob, "b4d_fld_length", scale=SCALE), 1e-6)))
    else:                                             # random_field: a smooth noise pattern that can move
        noise = g.node("ShaderNodeTexNoise", noise_dimensions="4D")
        g.l.new(g.scaled(g.v("ADD", p, g.xyz(driven(g, ob, "b4d_fld_seed", scale=7.31), 0.0, 0.0)),
                         g.m("DIVIDE", 1.0, g.m("MAXIMUM", driven(g, ob, "b4d_fld_noise_size", scale=SCALE), 1e-6))),
                noise.inputs["Vector"])
        g.l.new(g.m("MULTIPLY", g.node("GeometryNodeInputSceneTime").outputs["Seconds"],
                    driven(g, ob, "b4d_fld_speed")), noise.inputs["W"])
        noise.inputs["Detail"].default_value = 1.0
        w = g.clamp(g.m("ADD", g.m("MULTIPLY", g.m("SUBTRACT", noise.outputs["Factor"], 0.5),
                                   driven(g, ob, "b4d_fld_contrast", scale=0.04)), 0.5))
    inv_on = driven(g, ob, "b4d_fld_invert")
    w = g.m("ADD", w, g.m("MULTIPLY", inv_on, g.m("SUBTRACT", 1.0, g.m("MULTIPLY", w, 2.0))))
    return g.m("MULTIPLY", w, strength(g, ob, "b4d_fld_strength"))


def fields_weight(g, fields, at):
    """The strongest of the Fields at `at`; 1 everywhere when there are none or all are switched off."""
    if not fields:
        return None
    best, any_on = 0.0, 0.0
    for ob, kind in fields:
        on = driven(g, ob, "_b4d_enabled")
        best = g.m("MAXIMUM", best, g.m("MULTIPLY", field_weight(g, ob, kind, at), on))
        any_on = g.m("MAXIMUM", any_on, on)
    return g.m("ADD", 1.0, g.m("MULTIPLY", any_on, g.m("SUBTRACT", best, 1.0)))


# --- effectors -------------------------------------------------------------------------------------------------------
def _weights(g, geo, ob, kind):
    """(position, rotation, size, colour) weights per piece: vectors for the first three, a number for colour."""
    if kind == "random_effector":
        seed = driven(g, ob, "b4d_eff_seed")
        r = [g.random("FLOAT_VECTOR", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), g.m("ADD", seed, k * 7919)) for k in range(3)]
        return r[0], r[1], r[2], g.random("FLOAT", 0.0, 1.0, g.m("ADD", seed, 3 * 7919))
    if kind == "step_effector":
        size = g.node("GeometryNodeAttributeDomainSize", component="INSTANCES")
        g.l.new(geo, size.inputs["Geometry"])
        f = g.m("DIVIDE", g.index(), g.m("MAXIMUM", g.m("SUBTRACT", size.outputs["Instance Count"], 1.0), 1.0))
        return f, f, f, f
    if kind == "plain_effector":
        return 1.0, 1.0, 1.0, 1.0
    t = g.node("GeometryNodeInputSceneTime").outputs["Seconds"]     # time_effector: the values are per second
    return t, t, t, None


def _vec_mul(g, a, b):
    n = g.node("ShaderNodeVectorMath", operation="MULTIPLY")
    for v, sock in ((a, n.inputs[0]), (b, n.inputs[1])):
        g.put((v, v, v) if isinstance(v, (int, float)) else v, sock)
    return n.outputs[0]


def _target(g, geo, ob, s):
    """Each piece turns its shown Z (Blender Y) toward the effector, by Strength."""
    info = g.info(ob)
    xf = _instance_xf(g)
    aim = g.node("FunctionNodeAlignRotationToVector", axis="Y")
    g.l.new(xf.outputs["Rotation"], aim.inputs["Rotation"])
    g.put(s, aim.inputs["Factor"])
    g.l.new(g.v("SUBTRACT", info.outputs["Location"], xf.outputs["Translation"]), aim.inputs["Vector"])
    comb = g.node("FunctionNodeCombineTransform")
    g.l.new(xf.outputs["Translation"], comb.inputs["Translation"])
    g.l.new(aim.outputs[0], comb.inputs["Rotation"])
    g.l.new(xf.outputs["Scale"], comb.inputs["Scale"])
    st = g.node("GeometryNodeSetInstanceTransform")
    g.l.new(geo, st.inputs["Instances"])
    g.l.new(comb.outputs[0], st.inputs["Transform"])
    return st.outputs[0]


def _delay(g, geo, s):
    """Each piece follows where the earlier stages put it, trailing behind by Strength (it remembers the last frame)."""
    sin, sout = g.node("GeometryNodeSimulationInput"), g.node("GeometryNodeSimulationOutput")
    sin.pair_with_output(sout)
    g.l.new(geo, sin.inputs[0])
    was = g.node("GeometryNodeSampleIndex", data_type="FLOAT4X4", domain="INSTANCE")
    g.l.new(sin.outputs["Geometry"], was.inputs["Geometry"])
    g.l.new(g.node("GeometryNodeInstanceTransform").outputs[0], was.inputs["Value"])
    g.l.new(g.index(), was.inputs["Index"])
    before, now = g.node("FunctionNodeSeparateTransform"), _instance_xf(g)
    g.l.new(was.outputs[0], before.inputs[0])
    follow = g.m("SUBTRACT", 1.0, g.m("MULTIPLY", s, 0.95))           # how far each frame moves toward the new place
    mixes = []
    for k, dt in (("Translation", "VECTOR"), ("Rotation", "ROTATION"), ("Scale", "VECTOR")):
        mx = g.node("ShaderNodeMix", data_type=dt, clamp_factor=True)
        g.put(follow, mx.inputs[0])
        a = {"VECTOR": 4, "ROTATION": 8}[dt]
        g.l.new(before.outputs[k], mx.inputs[a])
        g.l.new(now.outputs[k], mx.inputs[a + 1])
        mixes.append(mx.outputs[{"VECTOR": 1, "ROTATION": 3}[dt]])
    comb = g.node("FunctionNodeCombineTransform")
    for k, out in zip(("Translation", "Rotation", "Scale"), mixes):
        g.l.new(out, comb.inputs[k])
    st = g.node("GeometryNodeSetInstanceTransform")
    g.l.new(geo, st.inputs["Instances"])
    g.l.new(comb.outputs[0], st.inputs["Transform"])
    g.l.new(st.outputs[0], sout.inputs["Geometry"])
    return sout.outputs["Geometry"]


def effector_stage(g, geo, ob, kind, fields):
    """Change the pieces in geo by one effector, limited to where its Fields reach."""
    s = strength(g, ob, "b4d_eff_strength")
    fw = fields_weight(g, fields, _instance_xf(g).outputs["Translation"])
    if fw is not None:
        s = g.m("MULTIPLY", s, fw)
    if kind == "target_effector":
        return _target(g, geo, ob, s)
    if kind == "delay_effector":
        return _delay(g, geo, s)
    wp, wr, ws, wc = _weights(g, geo, ob, kind)
    pos = g.scaled(_vec_mul(g, _shown_vec(g, ob, "b4d_eff_position", SCALE), wp), s)
    rot = g.scaled(_vec_mul(g, _shown_vec(g, ob, "b4d_eff_rotation", 1.0), wr), s)
    size = g.scaled(_vec_mul(g, _shown_vec(g, ob, "b4d_eff_scale", 0.01), ws), s)
    size = g.v("MAXIMUM", g.v("ADD", size, (1.0, 1.0, 1.0)), (0.0, 0.0, 0.0))
    tr = g.node("GeometryNodeTranslateInstances")
    g.l.new(geo, tr.inputs["Instances"])
    g.l.new(pos, tr.inputs["Translation"])
    tr.inputs["Local Space"].default_value = True
    ro = g.node("GeometryNodeRotateInstances")
    g.l.new(tr.outputs[0], ro.inputs["Instances"])
    g.l.new(g.euler(rot), ro.inputs["Rotation"])
    ro.inputs["Local Space"].default_value = True
    sc = g.node("GeometryNodeScaleInstances")
    g.l.new(ro.outputs[0], sc.inputs["Instances"])
    g.l.new(size, sc.inputs["Scale"])
    sc.inputs["Local Space"].default_value = True
    out = sc.outputs[0]
    if wc is None:
        return out
    amount = g.m("MULTIPLY", g.m("MULTIPLY", wc, s), driven(g, ob, "b4d_eff_use_color"))
    tint = g.node("FunctionNodeCombineColor")
    for i in range(3):
        g.l.new(driven(g, ob, "b4d_eff_color", i), tint.inputs[i])
    mix = g.node("ShaderNodeMix", data_type="RGBA", clamp_factor=True)
    g.l.new(amount, mix.inputs[0])
    g.l.new(g.named(COLOR_ATTR, "FLOAT_COLOR"), mix.inputs[6])     # the colour A and B sockets
    g.l.new(tint.outputs[0], mix.inputs[7])
    return g.store(out, COLOR_ATTR, mix.outputs[2], "FLOAT_COLOR", "INSTANCE")


# --- the groups --------------------------------------------------------------------------------------------------------
def _group(name, kind, owner):
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old)
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.is_modifier = True
    tree["b4d_owner"] = owner
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    inputs = INPUTS[kind]
    for sname, stype, default in inputs:
        s = tree.interface.new_socket(sname, in_out="INPUT", socket_type=SOCKET[stype])
        if stype in ("INT", "FLOAT"):
            lo, hi = LIMITS.get(sname, (-1e6, 1e6))
            s.min_value, s.max_value = lo, hi
        if stype not in ("MENU", "OBJECT") and default is not None:
            s.default_value = default
    g = G(tree)
    gin, gout = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    o = {sock.name: sock for sock in gin.outputs if sock.name}
    for sname, stype, default in inputs:
        if stype != "MENU":
            continue
        items = MENUS[sname]
        ms = g.node("GeometryNodeMenuSwitch", data_type="INT")
        ms.enum_items.clear()
        for lab, _num in items:
            ms.enum_items.new(lab)
        g.l.new(gin.outputs[sname], ms.inputs["Menu"])
        for lab, num in items:
            ms.inputs[lab].default_value = num
        o[sname] = ms.outputs[0]
        tree.interface.items_tree[sname].default_value = default
    return tree, g, o, gout


def _finish(g, o, gout, out, effectors, keep=True):
    """White Clone Color, the effector stages in list order, then real geometry unless Keep Instances is on."""
    out = g.store(out, COLOR_ATTR, (1.0, 1.0, 1.0, 1.0), "FLOAT_COLOR", "INSTANCE")
    for ob, kind, fields in effectors:
        out = effector_stage(g, out, ob, kind, fields)
    if not keep:
        g.l.new(out, gout.inputs["Geometry"])
        return
    real = g.node("GeometryNodeRealizeInstances")
    g.l.new(out, real.inputs["Geometry"])
    g.l.new(g.geo_switch(o["Keep Instances"], real.outputs[0], out), gout.inputs["Geometry"])


def make_group(name, kind, kids, effectors, owner):
    """A fresh node group for one MoClone object. kids: the objects it uses (in order); effectors: [(object, kind,
    [(field, field kind)])] in list order."""
    tree, g, o, gout = _group(name, kind, owner)
    if kind == "tracer":
        _tracer(g, o, gout)
        return tree
    if kind == "matrix":
        cube = g.node("GeometryNodeMeshCube")
        size = g.m("MULTIPLY", o["Cube Size"], SCALE)
        g.l.new(g.xyz(size, size, size), cube.inputs["Size"])
        gti = g.node("GeometryNodeGeometryToInstance")
        g.l.new(cube.outputs["Mesh"], gti.inputs[0])
        _finish(g, o, gout, _layout_copies(g, o, gti.outputs[0]), effectors, keep=False)
        return tree
    if not kids:
        g.l.new(g.empty(), gout.inputs["Geometry"])
        return tree
    if kind == "cloner":
        # every child becomes one instance, turned and sized as under the Cloner but at its origin; the copies pick
        # from them in turn or at random
        gti = g.node("GeometryNodeGeometryToInstance")
        for child in reversed(kids):
            info = g.info(child)
            home = g.node("GeometryNodeTransform")
            g.l.new(info.outputs["Geometry"], home.inputs["Geometry"])
            g.l.new(g.scaled(info.outputs["Location"], -1.0), home.inputs["Translation"])
            g.l.new(home.outputs[0], gti.inputs[0])
        order = g.switch("INT", o["Clone Order"], [g.index(), g.random("INT", 0, 1000000, o["Seed"])])
        out = _layout_copies(g, o, gti.outputs[0], order)
    elif kind == "fracture":
        whole = g.join([g.info(child, as_instance=True).outputs["Geometry"] for child in kids])
        parts = pieces(g, g.join([g.info(child).outputs["Geometry"] for child in kids]))
        out = g.geo_switch(o["Explode Segments"], whole, parts)
    else:                                             # voronoi_fracture: moclone.py wrote the cut pieces into this mesh
        out = pieces(g, _own_mesh(g, tree))
        sc = g.node("GeometryNodeScaleInstances")
        g.l.new(out, sc.inputs["Instances"])
        g.l.new(g.m("DIVIDE", o["Piece Size"], 100.0), sc.inputs["Scale"])
        sc.inputs["Local Space"].default_value = True
        out = sc.outputs[0]
    _finish(g, o, gout, out, effectors)
    return tree


def _own_mesh(g, tree):
    """The modifier's own input geometry (the object's mesh): the group gets a Geometry input for it."""
    sock = tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.move(sock, 1)                    # the first input: the modifier passes the object's mesh there
    gin = g.node("NodeGroupInput")
    return next(s for s in gin.outputs if s.name == "Geometry")


def _tracer(g, o, gout):
    """Lines through the places an object (or each of a Cloner's copies, kept as instances) passes over time."""
    info = g.info(o["Object"])
    parts = g.node("GeometryNodeSeparateComponents")
    g.l.new(info.outputs["Geometry"], parts.inputs[0])
    i2p = g.node("GeometryNodeInstancesToPoints")
    g.l.new(parts.outputs["Instances"], i2p.inputs["Instances"])
    one = g.node("GeometryNodePoints")
    one.inputs["Count"].default_value = 1
    g.l.new(info.outputs["Location"], one.inputs["Position"])
    count = g.node("GeometryNodeAttributeDomainSize", component="INSTANCES")
    g.l.new(info.outputs["Geometry"], count.inputs["Geometry"])
    now = g.geo_switch(g.m("GREATER_THAN", count.outputs["Instance Count"], 0.0), one.outputs[0], i2p.outputs[0])
    frame = g.node("GeometryNodeInputSceneTime").outputs["Frame"]
    now = g.store(g.store(now, _FRAME, frame, "FLOAT"), _ISLAND, g.index(), "INT")
    sin, sout = g.node("GeometryNodeSimulationInput"), g.node("GeometryNodeSimulationOutput")
    sin.pair_with_output(sout)
    g.l.new(now, sin.inputs[0])
    grown = g.join([sin.outputs["Geometry"], now])
    old = g.m("MULTIPLY", g.m("GREATER_THAN", o["Limit"], 0.0),
              g.m("GREATER_THAN", g.m("SUBTRACT", frame, g.named(_FRAME, "FLOAT")), o["Limit"]))
    trim = g.node("GeometryNodeDeleteGeometry", domain="POINT")
    g.l.new(grown, trim.inputs["Geometry"])
    g.l.new(old, trim.inputs["Selection"])
    g.l.new(trim.outputs[0], sout.inputs["Geometry"])
    lines = g.node("GeometryNodePointsToCurves")
    g.l.new(sout.outputs["Geometry"], lines.inputs["Points"])
    g.l.new(g.named(_ISLAND, "INT"), lines.inputs["Curve Group ID"])
    g.l.new(g.named(_FRAME, "FLOAT"), lines.inputs["Weight"])
    curves = g.drop_attrs(lines.outputs[0], _FRAME, _ISLAND)
    ring = g.node("GeometryNodeCurvePrimitiveCircle", mode="RADIUS")
    ring.inputs["Resolution"].default_value = 8
    g.l.new(g.m("MULTIPLY", o["Thickness"], 0.5 * SCALE), ring.inputs["Radius"])
    tube = g.node("GeometryNodeCurveToMesh")
    g.l.new(curves, tube.inputs["Curve"])
    g.l.new(ring.outputs["Curve"], tube.inputs["Profile Curve"])
    g.l.new(g.geo_switch(g.m("GREATER_THAN", o["Thickness"], 0.0), curves, tube.outputs["Mesh"]), gout.inputs["Geometry"])
