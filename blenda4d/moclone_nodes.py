# SPDX-License-Identifier: GPL-3.0-or-later
"""Node builders for the Cloner and its effectors (moclone.py has the objects, pages and sync).

A Cloner is a mesh object with one Geometry Nodes modifier. Its group is built for that object: the group inputs are
the Cloner's settings (Blenda units: cm, degrees, percent, shown Y up), every child is read with an Object Info node
and turned into one instance, and the copies are placed by the chosen mode. Each effector in the Cloner's list then
adds a stage that changes the copies. An effector's settings are custom properties on the effector object, read by
drivers in the Cloner's group, so one effector can drive several Cloners and a file keeps working with the add-on off.

Every copy carries a colour in the instance attribute "Clone Color" (white unless an effector tints it); a material
reads it with an Attribute node.

Shown axes are Y up (coords.py): shown (x, y, z) = Blender (x, z, y). Lengths: 1 cm = 0.01 m."""
import math

import bpy

SCALE = 0.01
COLOR_ATTR = "Clone Color"
_ROT, _SCL = ".b4d_clone_rot", ".b4d_clone_scale"     # per-point values carried from the layout to the copies

MODES = [("Linear", 0), ("Grid", 1), ("Radial", 2), ("Object", 3)]
PLANES = [("XZ", 0), ("XY", 1), ("ZY", 2)]
DISTRIBUTIONS = [("Along Spline", 0), ("Points", 1), ("Surface", 2)]
ORDERS = [("Iterate", 0), ("Random", 1)]

# the Cloner's settings: (socket, type, default)
INPUTS = [
    ("Mode", "MENU", "Linear"),
    ("Count", "INT", 3),
    ("Offset", "VECTOR", (100.0, 0.0, 0.0)),
    ("Step Rotation", "VECTOR", (0.0, 0.0, 0.0)),
    ("Step Size", "FLOAT", 0.0),
    ("Count X", "INT", 3), ("Count Y", "INT", 1), ("Count Z", "INT", 3),
    ("Spacing", "VECTOR", (100.0, 100.0, 100.0)),
    ("Radius", "FLOAT", 200.0),
    ("Start Angle", "FLOAT", 0.0),
    ("End Angle", "FLOAT", 360.0),
    ("Plane", "MENU", "XZ"),
    ("Object", "OBJECT", None),
    ("Distribution", "MENU", "Along Spline"),
    ("Align", "BOOL", True),
    ("Clone Order", "MENU", "Iterate"),
    ("Seed", "INT", 0),
    ("Keep Instances", "BOOL", False),
]
MENUS = {"Mode": MODES, "Plane": PLANES, "Distribution": DISTRIBUTIONS, "Clone Order": ORDERS}
LIMITS = {"Count": (0, 100000), "Count X": (1, 10000), "Count Y": (1, 10000), "Count Z": (1, 10000),
          "Seed": (0, 1000000), "Radius": (0.0, 1e6), "Step Size": (-100.0, 1e4)}
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

    def m(self, op, a, b=None):
        n = self.node("ShaderNodeMath", operation=op)
        self.put(a, n.inputs[0])
        if b is not None:
            self.put(b, n.inputs[1])
        return n.outputs[0]

    def v(self, op, a, b=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.put(a, n.inputs[0])
        if b is not None:
            self.put(b, n.inputs[1])
        return n.outputs["Value" if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else "Vector"]

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


# --- the layouts: each returns points carrying a rotation (Euler) and a size ---------------------------------------
def _points(g, count, position, rot=None, size=None):
    p = g.node("GeometryNodePoints")
    g.put(count, p.inputs["Count"])
    g.put(position, p.inputs["Position"])
    p.inputs["Radius"].default_value = 0.01
    out = g.store(p.outputs[0], _ROT, rot if rot is not None else (0.0, 0.0, 0.0), "FLOAT_VECTOR")
    return g.store(out, _SCL, size if size is not None else 1.0, "FLOAT")


def layout_linear(g, o):
    i = g.index()
    pos_node = g.node("ShaderNodeVectorMath", operation="SCALE")
    g.l.new(g.shown(o["Offset"]), pos_node.inputs[0])
    g.l.new(i, pos_node.inputs["Scale"])
    rot_node = g.node("ShaderNodeVectorMath", operation="SCALE")
    g.l.new(g.shown(o["Step Rotation"], math.pi / 180.0), rot_node.inputs[0])
    g.l.new(i, rot_node.inputs["Scale"])
    size = g.m("MAXIMUM", g.m("ADD", 1.0, g.m("MULTIPLY", i, g.m("DIVIDE", o["Step Size"], 100.0))), 0.0)
    return _points(g, o["Count"], pos_node.outputs["Vector"], rot_node.outputs["Vector"], size)


def layout_grid(g, o):
    cx, cy, cz = o["Count X"], o["Count Y"], o["Count Z"]           # shown axes: Y is up
    i = g.index()
    ix = g.m("FLOORED_MODULO", i, cx)
    iy = g.m("FLOORED_MODULO", g.m("FLOOR", g.m("DIVIDE", i, cx)), cy)
    iz = g.m("FLOOR", g.m("DIVIDE", i, g.m("MULTIPLY", cx, cy)))
    sp = g.sep(o["Spacing"])

    def centred(k, n, s):
        return g.m("MULTIPLY", g.m("SUBTRACT", k, g.m("DIVIDE", g.m("SUBTRACT", n, 1.0), 2.0)), g.m("MULTIPLY", s, SCALE))
    shown = (centred(ix, cx, sp[0]), centred(iy, cy, sp[1]), centred(iz, cz, sp[2]))
    pos = g.xyz(shown[0], shown[2], shown[1])
    total = g.m("MULTIPLY", g.m("MULTIPLY", cx, cy), cz)
    return _points(g, total, pos)


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


def layout_object(g, o):
    info = g.node("GeometryNodeObjectInfo", transform_space="RELATIVE")       # where the object is, seen from the Cloner
    g.l.new(o["Object"], info.inputs["Object"])
    parts = g.node("GeometryNodeSeparateComponents")
    g.l.new(info.outputs["Geometry"], parts.inputs[0])
    mesh, curve = parts.outputs["Mesh"], parts.outputs["Curve"]

    def keep(geo, rot):
        """Store the copies' turn: following the spline or surface with Align, upright without."""
        return g.store(g.store(geo, _ROT, _aligned(g, o, rot), "FLOAT_VECTOR"), _SCL, 1.0, "FLOAT")

    # Along Spline: the object's splines (or a mesh's edges) at even spacing
    m2c = g.node("GeometryNodeMeshToCurve")
    g.l.new(mesh, m2c.inputs["Mesh"])
    path = g.join([curve, m2c.outputs[0]])
    c2p = g.node("GeometryNodeCurveToPoints", mode="COUNT")
    g.l.new(path, c2p.inputs["Curve"])
    g.put(g.m("MAXIMUM", o["Count"], 1.0), c2p.inputs["Count"])
    along = keep(c2p.outputs["Points"], c2p.outputs["Rotation"])
    # Points: one copy on every point of a mesh, facing along its normal
    nrm = g.node("GeometryNodeInputNormal").outputs[0]
    with_n = g.store(mesh, ".b4d_clone_n", nrm, "FLOAT_VECTOR")
    m2p = g.node("GeometryNodeMeshToPoints", mode="VERTICES")
    g.l.new(with_n, m2p.inputs["Mesh"])
    up = g.node("FunctionNodeAlignRotationToVector", axis="Z")
    g.l.new(g.named(".b4d_clone_n", "FLOAT_VECTOR"), up.inputs["Vector"])
    on_points = keep(m2p.outputs[0], up.outputs[0])
    # Surface: Count copies scattered over the faces
    area = g.node("GeometryNodeInputMeshFaceArea").outputs[0]
    stat = g.node("GeometryNodeAttributeStatistic", data_type="FLOAT", domain="FACE")
    g.l.new(mesh, stat.inputs["Geometry"])
    g.l.new(area, stat.inputs["Attribute"])
    dist = g.node("GeometryNodeDistributePointsOnFaces", distribute_method="RANDOM")
    g.l.new(mesh, dist.inputs["Mesh"])
    g.l.new(g.m("DIVIDE", o["Count"], g.m("MAXIMUM", stat.outputs["Sum"], 1e-9)), dist.inputs["Density"])
    g.l.new(o["Seed"], dist.inputs["Seed"])
    scatter = keep(dist.outputs["Points"], dist.outputs["Rotation"])
    return g.switch("GEOMETRY", o["Distribution"], [along, on_points, scatter])


def _aligned(g, o, rot):
    """The turn as an Euler vector when Align is on, none when it is off."""
    e = g.to_euler(rot)
    n = g.node("ShaderNodeVectorMath", operation="SCALE")
    g.l.new(e, n.inputs[0])
    g.l.new(o["Align"], n.inputs["Scale"])
    return n.outputs["Vector"]


LAYOUTS = (layout_linear, layout_grid, layout_radial, layout_object)


# --- effectors -------------------------------------------------------------------------------------------------------
def _driven(g, ob, key, index=None, scale=1.0, name=None):
    """A value node following a custom property of ob (a driver, so keyframes on the effector animate it)."""
    n = g.node("ShaderNodeValue")
    n.label = name or key
    fc = n.outputs[0].driver_add("default_value")
    d = fc.driver
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


def _strength(g, ob):
    """Strength in 0..1, and 0 while the effector's check mark is off."""
    n = g.node("ShaderNodeValue")
    n.label = "Strength"
    d = n.outputs[0].driver_add("default_value").driver
    d.type = "SCRIPTED"
    for name, path in (("s", '["b4d_eff_strength"]'), ("e", '["_b4d_enabled"]')):
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
    x, y, z = (_driven(g, ob, key, i, scale) for i in range(3))
    return g.xyz(x, z, y)


def _weights(g, ob, kind):
    """(position, rotation, size, colour) weights per copy: vectors for the first three, a number for colour."""
    if kind == "random_effector":
        seed = _driven(g, ob, "b4d_eff_seed")
        r = [g.random("FLOAT_VECTOR", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), g.m("ADD", seed, k * 7919)) for k in range(3)]
        return r[0], r[1], r[2], g.random("FLOAT", 0.0, 1.0, g.m("ADD", seed, 3 * 7919))
    if kind == "step_effector":
        count = g.node("GeometryNodeAttributeDomainSize", component="INSTANCES").outputs["Instance Count"]
        f = g.m("DIVIDE", g.index(), g.m("MAXIMUM", g.m("SUBTRACT", count, 1.0), 1.0))
        return f, f, f, f
    # time: the values are per second
    t = g.node("GeometryNodeInputSceneTime").outputs["Seconds"]
    return t, t, t, None


def _vec_mul(g, a, b):
    n = g.node("ShaderNodeVectorMath", operation="MULTIPLY")
    g.put(a, n.inputs[0])
    g.put(b, n.inputs[1])
    return n.outputs[0]


def _scaled(g, vec, factor):
    n = g.node("ShaderNodeVectorMath", operation="SCALE")
    g.put(vec, n.inputs[0])
    g.put(factor, n.inputs["Scale"])
    return n.outputs["Vector"]


def effector_stage(g, geo, ob, kind):
    """Change the copies in geo by one effector."""
    s = _strength(g, ob)
    if kind == "target_effector":
        # each copy turns its shown Z (Blender Y) toward the effector, by Strength
        info = g.node("GeometryNodeObjectInfo", transform_space="RELATIVE")
        info.inputs["Object"].default_value = ob
        xf = g.node("FunctionNodeSeparateTransform")
        g.l.new(g.node("GeometryNodeInstanceTransform").outputs[0], xf.inputs[0])
        aim = g.node("FunctionNodeAlignRotationToVector", axis="Y")
        g.l.new(xf.outputs["Rotation"], aim.inputs["Rotation"])
        g.l.new(s, aim.inputs["Factor"])
        g.l.new(g.v("SUBTRACT", info.outputs["Location"], xf.outputs["Translation"]), aim.inputs["Vector"])
        comb = g.node("FunctionNodeCombineTransform")
        g.l.new(xf.outputs["Translation"], comb.inputs["Translation"])
        g.l.new(aim.outputs[0], comb.inputs["Rotation"])
        g.l.new(xf.outputs["Scale"], comb.inputs["Scale"])
        st = g.node("GeometryNodeSetInstanceTransform")
        g.l.new(geo, st.inputs["Instances"])
        g.l.new(comb.outputs[0], st.inputs["Transform"])
        return st.outputs[0]
    wp, wr, ws, wc = _weights(g, ob, kind)
    pos = _scaled(g, _vec_mul(g, _shown_vec(g, ob, "b4d_eff_position", SCALE), wp), s)
    rot = _scaled(g, _vec_mul(g, _shown_vec(g, ob, "b4d_eff_rotation", 1.0), wr), s)
    size = _scaled(g, _vec_mul(g, _shown_vec(g, ob, "b4d_eff_scale", 0.01), ws), s)
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
    amount = g.m("MULTIPLY", g.m("MULTIPLY", wc, s), _driven(g, ob, "b4d_eff_use_color"))
    tint = g.node("FunctionNodeCombineColor")
    for i in range(3):
        g.l.new(_driven(g, ob, "b4d_eff_color", i), tint.inputs[i])
    mix = g.node("ShaderNodeMix", data_type="RGBA", clamp_factor=True)
    g.l.new(amount, mix.inputs[0])
    g.l.new(g.named(COLOR_ATTR, "FLOAT_COLOR"), mix.inputs[6])            # the colour A and B sockets
    g.l.new(tint.outputs[0], mix.inputs[7])
    return g.store(out, COLOR_ATTR, mix.outputs[2], "FLOAT_COLOR", "INSTANCE")


# --- the group ---------------------------------------------------------------------------------------------------------
def make_group(name, kids, effectors, owner):
    """A fresh node group for one Cloner: kids are the objects copied, effectors [(object, kind)] in list order."""
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old)
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.is_modifier = True
    tree["b4d_owner"] = owner
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for sname, stype, default in INPUTS:
        s = tree.interface.new_socket(sname, in_out="INPUT", socket_type=SOCKET[stype])
        if stype in ("INT", "FLOAT"):
            lo, hi = LIMITS.get(sname, (-1e6, 1e6))
            s.min_value, s.max_value = lo, hi
        if stype not in ("MENU", "OBJECT") and default is not None:
            s.default_value = default
    g = G(tree)
    gin, gout = g.node("NodeGroupInput"), g.node("NodeGroupOutput")
    o = {sock.name: sock for sock in gin.outputs if sock.name}
    for sname, items in MENUS.items():
        ms = g.node("GeometryNodeMenuSwitch", data_type="INT")
        ms.enum_items.clear()
        for lab, _num in items:
            ms.enum_items.new(lab)
        g.l.new(gin.outputs[sname], ms.inputs["Menu"])
        for lab, num in items:
            ms.inputs[lab].default_value = num
        o[sname] = ms.outputs[0]
        tree.interface.items_tree[sname].default_value = dict((n, d) for n, t, d in INPUTS)[sname]
    if not kids:
        g.l.new(g.node("GeometryNodeJoinGeometry").outputs[0], gout.inputs["Geometry"])
        return tree
    # every child becomes one instance; the copies pick from them in turn or at random
    gti = g.node("GeometryNodeGeometryToInstance")
    for child in reversed(kids):
        # the child as it is turned and sized under the Cloner, but at the Cloner's origin: the layout places it
        info = g.node("GeometryNodeObjectInfo", transform_space="RELATIVE")
        info.inputs["Object"].default_value = child
        home = g.node("GeometryNodeTransform")
        g.l.new(info.outputs["Geometry"], home.inputs["Geometry"])
        g.l.new(_scaled(g, info.outputs["Location"], -1.0),
                home.inputs["Translation"])
        g.l.new(home.outputs[0], gti.inputs[0])
    pts = g.switch("GEOMETRY", o["Mode"], [fn(g, o) for fn in LAYOUTS])
    order = g.switch("INT", o["Clone Order"], [g.index(), g.random("INT", 0, 1000000, o["Seed"])])
    iop = g.node("GeometryNodeInstanceOnPoints")
    g.l.new(pts, iop.inputs["Points"])
    g.l.new(gti.outputs[0], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    g.l.new(order, iop.inputs["Instance Index"])
    g.l.new(g.euler(g.named(_ROT, "FLOAT_VECTOR")), iop.inputs["Rotation"])
    g.l.new(g.named(_SCL, "FLOAT"), iop.inputs["Scale"])
    out = iop.outputs[0]
    for attr in (_ROT, _SCL, ".b4d_clone_n"):
        rm = g.node("GeometryNodeRemoveAttribute")
        g.l.new(out, rm.inputs["Geometry"])
        rm.inputs["Name"].default_value = attr
        out = rm.outputs[0]
    out = g.store(out, COLOR_ATTR, (1.0, 1.0, 1.0, 1.0), "FLOAT_COLOR", "INSTANCE")
    for ob, kind in effectors:
        out = effector_stage(g, out, ob, kind)
    real = g.node("GeometryNodeRealizeInstances")
    g.l.new(out, real.inputs["Geometry"])
    g.l.new(g.geo_switch(o["Keep Instances"], real.outputs[0], out), gout.inputs["Geometry"])
    return tree
