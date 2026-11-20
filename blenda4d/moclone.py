# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone: objects that make, break up and trace copies, the effectors that change them and the Fields that say
where an effector acts.

Objects (each a mesh object with one Geometry Nodes modifier, built in moclone_nodes.py):
- Cloner: lays out copies of the objects under it. Modes: Linear (a row, each copy one step further), Grid (a block,
  a ball or a cylinder of rows), Radial (a ring or an arc), Honeycomb (rows with every other row shifted half a
  step) and Object (along a spline, on the points of a mesh or a Matrix, or scattered over a surface). With several
  children, the copies use them in turn or pick at random.
- Matrix: the same layouts with a small cube on every place and no children. It does not render; a Cloner in Object
  mode set to Points uses its places, after its effectors.
- Fracture: every object under it becomes a piece effectors can move; with Explode Segments, every loose part does.
- Voronoi Fracture: breaks the objects under it into pieces around random points inside them.
- Tracer: lines through the places an object, or every copy of a Cloner kept as instances, passes over time.
The children of a Cloner, Fracture or Voronoi Fracture show as a wire while they are used, so they stay selectable.

Effectors (Random, Plain, Delay, Step, Target, Time) are Nulls with their own settings. An object lists the effectors
that act on it on its Effectors page, in order; each row has its own check box to leave that effector out for a
while. Making an effector with such objects selected adds it to their lists, and dragging an effector from the
Object Manager onto the Effectors page (or onto the object's row) adds it too.

Fields (Linear, Spherical, Box, Random) are Nulls too. An effector lists its Fields on its Fields page; with none it
acts everywhere, with some it acts only as far as the strongest of them reaches. Making a Field with effectors
selected, or dragging one onto an effector's Fields page or row, adds it.

The groups are built again when children, lists or the Voronoi settings change (settings kept). Effector and Field
settings are custom properties (b4d_eff_*, b4d_fld_*) read by drivers, so files keep working with Blenda mode off.
sync() runs after every scene update and keeps all of this in step."""
import bpy
from mathutils import Matrix, Vector

from . import kinds
from . import moclone_nodes as mn

MOD = "Blenda MoClone"
CONSUMED = "b4d_cloned"                  # on a child the object uses: how it looked before, to give it back
SIG = "b4d_clone_sig"                    # what the group was built from

# object kind -> (label, Object Manager icon, tooltip)
OBJECTS = {
    "cloner": ("Cloner", "MOD_ARRAY", "Lay out copies of the objects under it (selected objects go under it)"),
    "matrix": ("Matrix", "LIGHTPROBE_VOLUME", "Show the places a Cloner layout makes, as small cubes that do not render"),
    "fracture": ("Fracture", "MOD_EXPLODE", "Let effectors move the objects under it as pieces (selected objects go under it)"),
    "voronoi_fracture": ("Voronoi Fracture", "MOD_EXPLODE",
                         "Break the objects under it into pieces effectors can move (selected objects go under it)"),
    "tracer": ("Tracer", "CURVE_PATH", "Draw lines through the places an object or a Cloner's copies pass over time"),
}
OBJECT_ORDER = ("cloner", "matrix", "fracture", "voronoi_fracture", "tracer")
WITH_EFFECTORS = ("cloner", "matrix", "fracture", "voronoi_fracture")
USES_CHILDREN = ("cloner", "fracture", "voronoi_fracture")

# effector kind -> (label, icon, tooltip, starting values)
EFFECTORS = {
    "random_effector": ("Random Effector", "FORCE_TURBULENCE", "Move, turn, size and tint each piece by a different random amount",
                        {"b4d_eff_position": (50.0, 50.0, 50.0)}),
    "plain_effector": ("Plain Effector", "EMPTY_AXIS", "Move, turn, size and tint every piece by the same amount (use a Field to limit it)",
                       {"b4d_eff_position": (0.0, 100.0, 0.0)}),
    "delay_effector": ("Delay Effector", "TIME", "Make the pieces trail behind their moves, catching up over the next frames",
                       {"b4d_eff_strength": 80.0}),
    "step_effector": ("Step Effector", "IPO_CONSTANT", "Change the pieces more and more from the first to the last",
                      {"b4d_eff_scale": (100.0, 100.0, 100.0)}),
    "target_effector": ("Target Effector", "TRACKER", "Turn the pieces so they face this effector", {}),
    "time_effector": ("Time Effector", "TIME", "Change the pieces more and more as the animation plays (amounts per second)",
                      {"b4d_eff_rotation": (0.0, 1.5707963, 0.0)}),
    "shader_effector": ("Shader Effector", "TEXTURE", "Move, turn, size and tint the pieces by a pattern (noise, cells, waves, checker)",
                        {"b4d_eff_position": (0.0, 100.0, 0.0), "b4d_eff_contrast": 100.0}),
    "wave_effector": ("Wave Effector", "MOD_WAVE", "Move, turn and size the pieces back and forth in a wave over time and along the copies",
                      {"b4d_eff_position": (0.0, 50.0, 0.0)}),
}
EFFECTOR_ORDER = ("random_effector", "plain_effector", "shader_effector", "delay_effector", "wave_effector",
                  "step_effector", "target_effector", "time_effector")

# field kind -> (label, icon, tooltip, starting values)
FIELDS = {
    "linear_field": ("Linear Field", "FORCE_FORCE", "Let an effector grow from nothing at this Field to full strength one Length along its Z", {}),
    "spherical_field": ("Spherical Field", "FORCE_FORCE", "Let an effector act inside a ball, fading out at its edge", {}),
    "box_field": ("Box Field", "FORCE_FORCE", "Let an effector act inside a box, fading out at its sides", {}),
    "random_field": ("Random Field", "FORCE_TURBULENCE", "Let an effector act in a smooth random pattern that can move", {}),
    "cylinder_field": ("Cylinder Field", "MESH_CYLINDER", "Let an effector act inside an upright cylinder, fading out at its sides and ends", {}),
    "capsule_field": ("Capsule Field", "MESH_CAPSULE", "Let an effector act inside a capsule (a cylinder with round ends)", {}),
    "cone_field": ("Cone Field", "MESH_CONE", "Let an effector act inside a cone that opens upward from this Field", {}),
    "torus_field": ("Torus Field", "MESH_TORUS", "Let an effector act inside a ring around this Field", {}),
    "radial_field": ("Radial Field", "FORCE_VORTEX", "Let an effector grow from nothing to full strength going round this Field", {}),
    "shader_field": ("Shader Field", "TEXTURE", "Let an effector act by a pattern: noise, cells, waves or a checker",
                     {"b4d_fld_contrast": 100.0}),
    "wave_field": ("Wave Field", "MOD_WAVE", "Let an effector act in rings going out from this Field", {}),
}
FIELD_ORDER = ("linear_field", "spherical_field", "box_field", "cylinder_field", "capsule_field", "cone_field",
               "torus_field", "radial_field", "random_field", "shader_field", "wave_field")

# setting -> (default, how the field shows)
SETTINGS = {
    "b4d_eff_strength": (100.0, dict(subtype="PERCENTAGE", soft_min=0.0, soft_max=100.0, precision=1,
                                     description="How much of the effect the pieces get")),
    "b4d_eff_position": ((0.0, 0.0, 0.0), dict(soft_min=-10000.0, soft_max=10000.0, precision=1, step=100,
                                               description="How far the pieces move, in centimetres, along their own axes")),
    "b4d_eff_rotation": ((0.0, 0.0, 0.0), dict(subtype="EULER", description="How far the pieces turn about their own axes")),
    "b4d_eff_scale": ((0.0, 0.0, 0.0), dict(soft_min=-100.0, soft_max=1000.0, precision=1,
                                            description="How much the pieces grow (or shrink, below 0), in percent")),
    "b4d_eff_use_color": (False, dict(description="Tint the pieces; a material shows it through an Attribute node "
                                                  f"reading \"{mn.COLOR_ATTR}\"")),
    "b4d_eff_color": ((1.0, 0.25, 0.05), dict(subtype="COLOR", min=0.0, max=1.0, description="The tint")),
    "b4d_eff_seed": (0, dict(min=0, max=1000000, description="Pick a different random pattern")),
    "b4d_fld_strength": (100.0, dict(subtype="PERCENTAGE", min=0.0, soft_max=100.0, precision=1,
                                     description="How much of its effectors' strength this Field lets through")),
    "b4d_fld_invert": (False, dict(description="Swap inside and outside: act where the Field was not")),
    "b4d_fld_falloff": (20.0, dict(subtype="PERCENTAGE", min=0.0, max=100.0, precision=1,
                                   description="How much of the way in from the edge the effect fades")),
    "b4d_fld_radius": (200.0, dict(min=0.0, soft_max=10000.0, precision=1, step=100, description="Size of the ball, in centimetres")),
    "b4d_fld_size": ((400.0, 400.0, 400.0), dict(min=0.0, soft_max=10000.0, precision=1, step=100,
                                                 description="Size of the box, in centimetres")),
    "b4d_fld_length": (400.0, dict(min=0.01, soft_max=10000.0, precision=1, step=100,
                                   description="How far along the Field's Z the effect takes to reach full strength (cm)")),
    "b4d_fld_noise_size": (200.0, dict(min=0.1, soft_max=10000.0, precision=1, step=100, description="Size of the patches (cm)")),
    "b4d_fld_seed": (0, dict(min=0, max=100000, description="Pick a different pattern")),
    "b4d_fld_speed": (0.0, dict(soft_min=0.0, soft_max=10.0, precision=2, description="How fast the pattern changes as the animation plays")),
    "b4d_fld_contrast": (50.0, dict(min=0.0, soft_max=100.0, precision=1, subtype="PERCENTAGE",
                                    description="How sharp the edges between the patches are")),
    "b4d_eff_random_mode": (0, None),
    "b4d_eff_speed": (1.0, dict(soft_min=0.0, soft_max=10.0, precision=2, description="How fast it changes as the animation plays")),
    "b4d_eff_pattern": (0, None),
    "b4d_eff_noise_size": (200.0, dict(min=0.1, soft_max=10000.0, precision=1, step=100, description="Size of the pattern (cm)")),
    "b4d_eff_contrast": (50.0, dict(min=0.0, soft_max=100.0, precision=1, subtype="PERCENTAGE",
                                    description="How sharp the edges of the pattern are")),
    "b4d_eff_wave_shape": (0, None),
    "b4d_eff_frequency": (0.5, dict(soft_min=0.0, soft_max=10.0, precision=2, description="Waves per second")),
    "b4d_eff_spread": (1.0, dict(soft_min=0.0, soft_max=10.0, precision=2,
                                 description="How many waves fit along the copies, from the first to the last")),
    "b4d_eff_upright": (False, dict(description="Keep the pieces' Y pointing up while they face the effector")),
    "b4d_fld_height": (400.0, dict(min=0.0, soft_max=10000.0, precision=1, step=100, description="Height along the Field's Y (cm)")),
    "b4d_fld_tube": (50.0, dict(min=0.0, soft_max=10000.0, precision=1, step=100, description="Thickness of the ring (cm)")),
    "b4d_fld_sweep": (6.2831853, dict(subtype="ANGLE", min=0.0001, soft_max=6.2831853,
                                      description="How far round the effect takes to reach full strength")),
    "b4d_fld_wavelength": (200.0, dict(min=0.1, soft_max=10000.0, precision=1, step=100,
                                       description="Distance from one ring to the next (cm)")),
    "b4d_fld_pattern": (0, None),
    "b4d_vor_count": (20, dict(min=1, max=500, description="How many pieces")),
    "b4d_vor_seed": (0, dict(min=0, max=100000, description="Place the cuts differently")),
}
_MOVE = ("b4d_eff_strength", "b4d_eff_position", "b4d_eff_rotation", "b4d_eff_scale")
_TINT = ("b4d_eff_use_color", "b4d_eff_color")
_PATTERN = ("b4d_eff_pattern", "b4d_eff_noise_size", "b4d_eff_contrast", "b4d_eff_speed", "b4d_eff_seed")
_F = ("b4d_fld_strength", "b4d_fld_invert")
KIND_SETTINGS = {
    "random_effector": _MOVE + _TINT + ("b4d_eff_seed", "b4d_eff_random_mode", "b4d_eff_speed"),
    "shader_effector": _MOVE + _TINT + _PATTERN,
    "wave_effector": _MOVE + _TINT + ("b4d_eff_wave_shape", "b4d_eff_frequency", "b4d_eff_spread"),
    "plain_effector": _MOVE + _TINT,
    "delay_effector": ("b4d_eff_strength",),
    "step_effector": _MOVE + _TINT,
    "target_effector": ("b4d_eff_strength", "b4d_eff_upright"),
    "time_effector": _MOVE,
    "linear_field": ("b4d_fld_strength", "b4d_fld_invert", "b4d_fld_length", "b4d_fld_falloff"),
    "spherical_field": ("b4d_fld_strength", "b4d_fld_invert", "b4d_fld_radius", "b4d_fld_falloff"),
    "box_field": ("b4d_fld_strength", "b4d_fld_invert", "b4d_fld_size", "b4d_fld_falloff"),
    "random_field": _F + ("b4d_fld_noise_size", "b4d_fld_seed", "b4d_fld_speed", "b4d_fld_contrast", "b4d_fld_falloff"),
    "cylinder_field": _F + ("b4d_fld_radius", "b4d_fld_height", "b4d_fld_falloff"),
    "capsule_field": _F + ("b4d_fld_radius", "b4d_fld_height", "b4d_fld_falloff"),
    "cone_field": _F + ("b4d_fld_radius", "b4d_fld_height", "b4d_fld_falloff"),
    "torus_field": _F + ("b4d_fld_radius", "b4d_fld_tube", "b4d_fld_falloff"),
    "radial_field": _F + ("b4d_fld_sweep", "b4d_fld_falloff"),
    "shader_field": _F + ("b4d_fld_pattern", "b4d_fld_noise_size", "b4d_fld_seed", "b4d_fld_speed", "b4d_fld_contrast", "b4d_fld_falloff"),
    "wave_field": _F + ("b4d_fld_wavelength", "b4d_fld_speed", "b4d_fld_falloff"),
    "voronoi_fracture": ("b4d_vor_count", "b4d_vor_seed"),
}


def kind_of(ob):
    k = ob.get("b4d_type") if ob is not None else None
    return k if k in OBJECTS or k in EFFECTORS or k in FIELDS else None


def object_kind(ob):
    k = kind_of(ob)
    return k if k in OBJECTS else None


def effector_kind(ob):
    k = kind_of(ob)
    return k if k in EFFECTORS else None


def field_kind(ob):
    k = kind_of(ob)
    return k if k in FIELDS else None


def is_cloner(ob):
    return object_kind(ob) == "cloner"


def enabled(ob):
    return bool(ob.get("_b4d_enabled", True))


def kids_of(ob):
    """The objects it uses: its children with geometry, in Object Manager order (by name)."""
    k = object_kind(ob)
    if k not in USES_CHILDREN:
        return []
    types = ("MESH",) if k == "voronoi_fracture" else ("MESH", "CURVE", "FONT")
    return [c for c in sorted(ob.children, key=lambda c: c.name) if c.type in types and kind_of(c) is None]


def _listed(ob, prop, kind_fn):
    out = []
    for link in getattr(ob, prop, ()):
        o = link.object
        k = kind_fn(o)
        if k is not None and link.use and o.name in bpy.data.objects and all(o != x[0] for x in out):
            out.append((o, k, getattr(link, "blend", "MAX")))
    return out


def fields_of(effector):
    """[(field, kind, how it combines)] in list order: rows switched off, empty rows and objects that are not Fields
    are skipped."""
    return _listed(effector, "b4d_fields", field_kind)


def effectors_of(ob):
    """[(effector, kind)] in list order, the same way."""
    return [(o, k) for o, k, _b in _listed(ob, "b4d_effectors", effector_kind)]


def stamp(ob, kind, start=None):
    """Give the object every setting its kind reads (a missing one would break the drivers)."""
    if "_b4d_enabled" not in ob:
        ob["_b4d_enabled"] = True
    for key in KIND_SETTINGS.get(kind, ()):
        if key in ob:
            continue
        default, ui = SETTINGS[key]
        v = (start or {}).get(key, default)
        ob[key] = list(v) if isinstance(v, tuple) else v
        if ui:                                        # a menu setting is shown through its own Object property
            ob.id_properties_ui(key).update(default=list(default) if isinstance(default, tuple) else default, **ui)


# --- the modifier ------------------------------------------------------------------------------------------------
def mod_of(ob):
    return ob.modifiers.get(MOD) if ob is not None else None


def slot(ob, name):
    """(owner, attribute) of one of the object's group settings, or None."""
    from .primitives import input_slot
    mod = mod_of(ob)
    if mod is None or mod.node_group is None:
        return None
    it = next((i for i in mod.node_group.interface.items_tree
               if i.item_type == "SOCKET" and i.in_out == "INPUT" and i.name == name and i.socket_type != "NodeSocketGeometry"), None)
    if it is None:
        return None
    try:
        return input_slot(mod, it.identifier)
    except (KeyError, AttributeError):
        return None


def get(ob, name):
    s = slot(ob, name)
    return getattr(*s) if s else None


def put(ob, name, v):
    s = slot(ob, name)
    if s is not None:
        setattr(*s, v)
        ob.update_tag()


def _effector_list(ob):
    return [(e, k, fields_of(e)) for e, k in effectors_of(ob)]


def _signature(ob):
    k = object_kind(ob)
    parts = [ob.name, k, ",".join(c.name for c in kids_of(ob)),
             ";".join(f"{e.name}:{ek}:" + ",".join(f"{f.name}/{b}" for f, _fk, b in fl) for e, ek, fl in _effector_list(ob))]
    if k == "voronoi_fracture":
        parts.append(f"{ob.get('b4d_vor_count')}:{ob.get('b4d_vor_seed')}")
        for c in kids_of(ob):
            m = c.matrix_world
            parts.append(f"{c.data.name}:{len(c.data.vertices)}:" + ",".join(f"{x:.4f}" for row in m for x in row))
        parts.append(",".join(f"{x:.4f}" for row in ob.matrix_world for x in row))
    return "|".join(parts)


def rebuild(ob):
    k = object_kind(ob)
    mod = mod_of(ob)
    if mod is None:
        mod = ob.modifiers.new(MOD, "NODES")
    old = {}
    if mod.node_group is not None:
        for it in mod.node_group.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.socket_type != "NodeSocketGeometry":
                v = get(ob, it.name)
                old[it.name] = tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v   # copied: the swap frees it
    if k == "voronoi_fracture":
        cut(ob)
    tree = mn.make_group(f"Blenda {OBJECTS[k][0]} [{ob.name}]", k, kids_of(ob), _effector_list(ob), ob.name)
    mod.node_group = tree
    for name, v in old.items():
        try:
            put(ob, name, v)
        except (TypeError, AttributeError, ValueError):
            pass
    ob[SIG] = _signature(ob)
    ob.update_tag()


def _needs_rebuild(ob):
    mod = mod_of(ob)
    if mod is None or mod.node_group is None or mod.node_group.get("b4d_owner") != ob.name:
        return True
    return ob.get(SIG) != _signature(ob)


# --- Voronoi Fracture: cutting the children into pieces -----------------------------------------------------------
def _inside(bvh, p):
    """A point is inside a closed mesh when a ray from it crosses the surface an odd number of times."""
    hits, o, d = 0, p.copy(), Vector((0.5773, 0.5774, 0.5773))
    for _ in range(64):
        loc, _n, _i, _d = bvh.ray_cast(o, d)
        if loc is None:
            break
        hits += 1
        o = loc + d * 1e-5
    return hits % 2 == 1


def cut(ob):
    """Write the pieces into the Voronoi Fracture's own mesh: every child (as it shows, in the object's space) is cut
    into cells around random points inside it; each cell is closed and kept as one loose part."""
    import random

    import bmesh
    from mathutils.bvhtree import BVHTree
    deps = bpy.context.evaluated_depsgraph_get()
    src = bmesh.new()
    to_local = ob.matrix_world.inverted()
    mats = []
    for c in kids_of(ob):
        ev = c.evaluated_get(deps)
        me = ev.to_mesh()
        me.transform(to_local @ c.matrix_world)
        base = len(mats)
        mats += [m.original if m is not None else None for m in me.materials]   # never the evaluated copies: they get freed
        for p in me.polygons:
            p.material_index += base
        src.from_mesh(me)
        ev.to_mesh_clear()
    out = ob.data
    out.clear_geometry()
    out.materials.clear()                         # written again below, once per child's material slot
    if not src.verts:
        src.free()
        return
    bmesh.ops.triangulate(src, faces=[f for f in src.faces if len(f.verts) > 4])
    bvh = BVHTree.FromBMesh(src)
    lo = Vector([min(v.co[i] for v in src.verts) for i in range(3)])
    hi = Vector([max(v.co[i] for v in src.verts) for i in range(3)])
    rng = random.Random(int(ob.get("b4d_vor_seed", 0)))
    want = int(ob.get("b4d_vor_count", 20))
    seeds = []
    for _ in range(want * 60):
        if len(seeds) >= want:
            break
        p = Vector([rng.uniform(lo[i], hi[i]) for i in range(3)])
        if _inside(bvh, p):
            seeds.append(p)
    if not seeds:
        seeds = [(lo + hi) / 2]
    verts, faces, mat_ids = [], [], []
    for i, p in enumerate(seeds):
        cell = src.copy()
        for j, q in enumerate(seeds):
            if i == j or not cell.faces:
                continue
            n = (q - p).normalized()
            geom = cell.verts[:] + cell.edges[:] + cell.faces[:]
            res = bmesh.ops.bisect_plane(cell, geom=geom, plane_co=(p + q) / 2, plane_no=n, clear_outer=True)
            edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge) and e.is_boundary]
            if edges:
                bmesh.ops.holes_fill(cell, edges=edges, sides=0)
        if cell.faces:
            start = len(verts)
            verts += [tuple(v.co) for v in cell.verts]
            index = {v: k for k, v in enumerate(cell.verts)}
            for f in cell.faces:
                faces.append([start + index[v] for v in f.verts])
                mat_ids.append(f.material_index)
        cell.free()
    src.free()
    out.from_pydata(verts, [], faces)
    for m in mats:
        out.materials.append(m)
    if mat_ids:
        out.polygons.foreach_set("material_index", mat_ids)
    out.update()


# --- showing the children as a wire -----------------------------------------------------------------------------------
def _consume(ob):
    if CONSUMED in ob:
        return
    ob[CONSUMED] = {"display": ob.display_type, "render": int(ob.hide_render)}
    ob.display_type = "WIRE"
    ob.hide_render = True


def _release(ob):
    was = ob.get(CONSUMED)
    if was is None:
        return
    try:                                         # copy the values out before the property (and `was`) is deleted
        display, render = str(was.get("display", "TEXTURED")), bool(was.get("render", 0))
    except (TypeError, AttributeError):
        display, render = "TEXTURED", False
    del ob[CONSUMED]
    try:
        ob.display_type = display
    except TypeError:
        ob.display_type = "TEXTURED"
    ob.hide_render = render


def _field_display(ob, kind):
    """The Null draws the Field's reach."""
    r = ob.get("b4d_fld_radius", 200.0) * mn.SCALE
    want = {"spherical_field": ("SPHERE", r), "capsule_field": ("SPHERE", r), "cylinder_field": ("CIRCLE", r),
            "torus_field": ("CIRCLE", r), "cone_field": ("CONE", ob.get("b4d_fld_height", 400.0) * mn.SCALE),
            "box_field": ("CUBE", max(ob.get("b4d_fld_size", (400.0,) * 3)) * 0.5 * mn.SCALE),
            "linear_field": ("SINGLE_ARROW", ob.get("b4d_fld_length", 400.0) * mn.SCALE),
            "radial_field": ("CIRCLE", 1.0), "wave_field": ("CIRCLE", ob.get("b4d_fld_wavelength", 200.0) * mn.SCALE),
            "random_field": ("SPHERE", ob.get("b4d_fld_noise_size", 200.0) * 0.5 * mn.SCALE),
            "shader_field": ("CUBE", ob.get("b4d_fld_noise_size", 200.0) * 0.5 * mn.SCALE)}[kind]
    if ob.empty_display_type != want[0]:
        ob.empty_display_type = want[0]
    if abs(ob.empty_display_size - want[1]) > 1e-6:
        ob.empty_display_size = max(want[1], 1e-4)


def _restart_trailing(ob):
    """A Delay Effector remembers past frames; when its settings change, that memory is dropped so the trailing is
    worked out again with the new values (Blender would otherwise keep showing the old frames)."""
    key = ";".join(f"{e.name}:{e.get('b4d_eff_strength')}:{enabled(e)}:" + ",".join(f.name for f, _k, _b in fl)
                   for e, k, fl in _effector_list(ob) if k == "delay_effector")
    if ob.get("b4d_delay_key", "") == key:
        return
    ob["b4d_delay_key"] = key
    try:
        with bpy.context.temp_override(selected_objects=[ob], selected_editable_objects=[ob], active_object=ob, object=ob):
            bpy.ops.object.simulation_nodes_cache_delete(selected=True)
    except (RuntimeError, TypeError, AttributeError):
        pass


_busy = [False]


def sync(scene):
    if _busy[0] or scene is None:
        return
    _busy[0] = True
    try:
        keep = set()
        for ob in scene.objects:
            k = kind_of(ob)
            if k is None:
                continue
            stamp(ob, k)
            if k in FIELDS and ob.type == "EMPTY":
                _field_display(ob, k)
            if k not in OBJECTS:
                continue
            if _needs_rebuild(ob):
                rebuild(ob)
            if k in WITH_EFFECTORS:
                _restart_trailing(ob)
            if enabled(ob):
                for c in kids_of(ob):
                    keep.add(c.name)
                    _consume(c)
        for ob in scene.objects:
            if CONSUMED in ob and ob.name not in keep:
                _release(ob)
    finally:
        _busy[0] = False


def sync_all():
    sync(bpy.context.scene)


@bpy.app.handlers.persistent       # opening a file drops handlers that are not persistent
def _on_update(scene, depsgraph=None):
    try:
        sync(scene)
    except Exception:
        import traceback
        traceback.print_exc()


# --- making them ---------------------------------------------------------------------------------------------------
def create_object(context, kind):
    from .generators import _selection, wrap
    from .primitives import tidy_name
    sel = [o for o in _selection(context) if kind_of(o) is None] if kind in USES_CHILDREN else []
    tracked = next((o for o in context.selected_objects), None) if kind == "tracer" else None
    label = OBJECTS[kind][0]
    ob = bpy.data.objects.new(label, bpy.data.meshes.new(label))
    context.collection.objects.link(ob)
    ob["b4d_type"] = kind
    tidy_name(ob)
    stamp(ob, kind)
    if sel:
        wrap(ob, sel)
    else:
        ob.location = context.scene.cursor.location
    if kind == "matrix":
        ob.hide_render = True                       # it shows the places; it is not meant to render
    rebuild(ob)
    if kind == "matrix":
        put(ob, "Mode", "Grid")
    if kind == "tracer" and tracked is not None:
        ob.matrix_world = Matrix.Identity(4)
        put(ob, "Object", tracked)
    sync_all()
    return ob


def add_to(ob, other, prop="b4d_effectors"):
    lst = getattr(ob, prop)
    if any(link.object == other for link in lst):
        return False
    row = lst.add()
    row.object = other
    setattr(ob, "b4d_effector_index" if prop == "b4d_effectors" else "b4d_field_index", len(lst) - 1)
    return True


def _make_null(context, kind, label, start):
    from .primitives import tidy_name
    ob = bpy.data.objects.new(label, None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.25
    context.collection.objects.link(ob)
    ob["b4d_type"] = kind
    tidy_name(ob)
    stamp(ob, kind, start)
    return ob


def create_effector(context, kind):
    label, _icon, _tip, start = EFFECTORS[kind]
    owners = [o for o in context.selected_objects if object_kind(o) in WITH_EFFECTORS]
    ob = _make_null(context, kind, label, start)
    if kind == "target_effector":
        ob.empty_display_type = "SPHERE"
    if owners:
        ob.matrix_world = Matrix.Translation(owners[0].matrix_world.translation)
        if kind == "target_effector":
            ob.location.z += 3.0                   # above the copies, so turning to face it shows
        for c in owners:
            add_to(c, ob)
    else:
        ob.location = context.scene.cursor.location
    sync_all()
    return ob


def create_field(context, kind):
    label, _icon, _tip, start = FIELDS[kind]
    owners = [o for o in context.selected_objects if effector_kind(o) is not None]
    ob = _make_null(context, kind, label, start)
    ob.location = owners[0].matrix_world.translation if owners else context.scene.cursor.location
    for e in owners:
        add_to(e, ob, "b4d_fields")
    sync_all()
    return ob


# --- the lists: Effectors on an object, Fields on an effector ------------------------------------------------------
def _is_effector(self, ob):
    return effector_kind(ob) is not None


def _is_field(self, ob):
    return field_kind(ob) is not None


def _list_changed(self, context):
    sync_all()


class BLENDA4D_PG_effector_link(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object, name="Effector", poll=_is_effector, update=_list_changed,
                                      description="An effector that changes this object's pieces")
    use: bpy.props.BoolProperty(name="Use", default=True, update=_list_changed,
                                description="Let this effector act here; untick to leave it out for a while")


class BLENDA4D_PG_field_link(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object, name="Field", poll=_is_field, update=_list_changed,
                                      description="A Field that limits where this effector acts")
    use: bpy.props.BoolProperty(name="Use", default=True, update=_list_changed,
                                description="Let this Field limit the effector; untick to leave it out for a while")
    blend: bpy.props.EnumProperty(name="Combine", default="MAX", update=_list_changed, items=(
        ("MAX", "Max", "Where it reaches further than the Fields above, it wins"),
        ("ADD", "Add", "Adds its reach to the Fields above"),
        ("SUBTRACT", "Subtract", "Takes its reach away from the Fields above"),
        ("MULTIPLY", "Multiply", "Keeps only what it and the Fields above share"),
        ("MIN", "Min", "Where it reaches less than the Fields above, it wins")),
        description="How this Field combines with the rows above it (the first row starts the reach)")


class BLENDA4D_UL_links(bpy.types.UIList):
    """A row per effector or Field: its check box (this list only), its icon and name."""
    bl_idname = "BLENDA4D_UL_links"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        ob = item.object
        row.prop(item, "use", text="")
        if ob is None:                                   # an empty row: pick the object in it
            row.prop(item, "object", text="", icon="QUESTION")
            return
        k = kind_of(ob)
        sub = row.row(align=True)
        sub.active = item.use and enabled(ob)
        sub.label(text=ob.name, icon=(EFFECTORS.get(k) or FIELDS.get(k) or ("", "ERROR"))[1])
        if not enabled(ob):
            sub.label(text="", icon="X")                 # switched off everywhere (its Object Manager check mark)
        if hasattr(item, "blend") and index > 0:         # the first row starts the reach; the others say how they join
            r = row.row(align=True)
            r.ui_units_x = 4.5
            r.active = item.use
            r.prop(item, "blend", text="")


class BLENDA4D_OT_link_slot(bpy.types.Operator):
    bl_idname = "blenda4d.link_slot"
    bl_label = "List"
    bl_description = "Add an empty row to the list, take the selected row out, or move it"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    prop: bpy.props.StringProperty(default="b4d_effectors")
    action: bpy.props.EnumProperty(items=(("ADD", "Add", "Add an empty row; pick the object in it"),
                                          ("REMOVE", "Remove", "Take the selected row out of the list"),
                                          ("UP", "Up", "Act earlier"), ("DOWN", "Down", "Act later")))

    @classmethod
    def description(cls, context, props):
        return {"ADD": "Add an empty row; pick the object in it", "REMOVE": "Take the selected row out of the list",
                "UP": "Move the selected row up: it acts earlier", "DOWN": "Move the selected row down: it acts later"}[props.action]

    @classmethod
    def poll(cls, context):
        return kind_of(context.view_layer.objects.active) is not None

    def execute(self, context):
        ob = context.view_layer.objects.active
        idx = "b4d_effector_index" if self.prop == "b4d_effectors" else "b4d_field_index"
        lst, i = getattr(ob, self.prop), getattr(ob, idx)
        if self.action == "ADD":
            lst.add()
            setattr(ob, idx, len(lst) - 1)
        elif 0 <= i < len(lst):
            if self.action == "REMOVE":
                lst.remove(i)
                setattr(ob, idx, max(0, i - 1))
            else:
                j = i - 1 if self.action == "UP" else i + 1
                if 0 <= j < len(lst):
                    lst.move(i, j)
                    setattr(ob, idx, j)
        sync_all()
        return {"FINISHED"}


def drop(context, event, objs, row_name):
    """Object Manager drop: effectors dragged onto the Attribute Manager (showing an object with Effectors) or onto
    that object's row go into its Effectors list; Fields dragged onto an effector the same way go into its Fields
    list. Returns True when the drop was taken here (nothing is put under anything then)."""
    from . import roles
    target = None
    mx, my = event.mouse_x, event.mouse_y
    screen = getattr(context.window, "screen", None)
    for area in (screen.areas if screen else ()):
        if roles.role(area) == "ATTRIBUTES" and area.x <= mx < area.x + area.width and area.y <= my < area.y + area.height:
            target = context.view_layer.objects.active
            break
    if target is None and row_name:
        target = bpy.data.objects.get(row_name)
    if target is None:
        return False
    if object_kind(target) in WITH_EFFECTORS:
        want, prop = [o for o in objs if effector_kind(o)], "b4d_effectors"
    elif effector_kind(target):
        want, prop = [o for o in objs if field_kind(o)], "b4d_fields"
    else:
        return False
    if not want or len(want) != len(objs):
        return False
    added = sum(add_to(target, o, prop) for o in want)
    if added:
        try:                                     # show the list it went into
            context.window_manager.b4d_am_tab = "EFFECTORS" if prop == "b4d_effectors" else "FIELDS"
        except (AttributeError, TypeError):
            pass
        sync_all()
    return True


# --- Attribute Manager pages ---------------------------------------------------------------------------------------
def _rows(col, ob, rows):
    """rows: (setting, label) or (setting, label, shown-when(value)); None leaves a gap."""
    def value(name):
        return get(ob, name)
    for r in rows:
        if r is None:
            col.separator()
            continue
        if len(r) > 2 and r[2] is not None and not r[2](value):
            continue
        s = slot(ob, r[0])
        if s is None:
            continue
        owner, attr = s
        v = getattr(owner, attr)
        if hasattr(v, "__len__") and not isinstance(v, str):
            axes = r[3](value) if len(r) > 3 else "XYZ"      # only the axes the mode uses
            sub = col.column(align=True)
            for i, axis in enumerate("XYZ"):
                if axis in axes:
                    sub.prop(owner, attr, index=i, text=f"{r[1]} . {axis}")
        else:
            col.prop(owner, attr, text=r[1])


def _missing(col, ob):
    if mod_of(ob) is None or mod_of(ob).node_group is None:
        col.label(text="This object's nodes are missing", icon="ERROR")
        return True
    return False


def _is(*modes):
    return lambda v: v("Mode") in modes


def _layout_rows(order=True):
    rows = [("Mode", "Mode")]
    if order:
        rows += [("Clone Order", "Clones")]
    rows += [
        ("Seed", "Seed", lambda v: v("Clone Order") == "Random" or (v("Mode") == "Object" and v("Distribution") == "Surface")),
        None,
        ("Object", "Object", _is("Object")),
        ("Distribution", "Distribution", _is("Object")),
        ("Count", "Count", lambda v: v("Mode") in ("Linear", "Radial") or
         (v("Mode") == "Object" and v("Distribution") != "Points")),
        ("Offset Mode", "Mode", _is("Linear")),
        ("Offset", "Offset", _is("Linear")),
        ("Step Rotation", "Step Rotation", _is("Linear")),
        ("Step Size", "Step Size %", _is("Linear")),
        ("Count X", "Count . X", _is("Grid", "Honeycomb")), ("Count Y", "Count . Y", _is("Grid")),
        ("Count Z", "Count . Z", _is("Grid", "Honeycomb")),
        ("Spacing Mode", "Mode", _is("Grid", "Honeycomb")),
        ("Spacing", "Size", _is("Grid", "Honeycomb"), lambda v: "XZ" if v("Mode") == "Honeycomb" else "XYZ"),
        ("Form", "Form", _is("Grid")),
        ("Radius", "Radius", _is("Radial")), ("Plane", "Plane", _is("Radial")),
        ("Start Angle", "Start Angle", _is("Radial")), ("End Angle", "End Angle", _is("Radial")),
        ("Align", "Align", _is("Radial", "Object")),
    ]
    return rows


def _object_hints(col, ob):
    if get(ob, "Mode") != "Object":
        return
    target = get(ob, "Object")
    if target is None:
        col.label(text="Pick a spline, a polygon object or a Matrix", icon="INFO")
    elif target.type != "MESH" and get(ob, "Distribution") != "Along Spline":
        col.label(text="Points and Surface need a polygon object or a Matrix", icon="INFO")


def page_cloner(col, ob):
    if _missing(col, ob):
        return
    if not kids_of(ob):
        col.label(text="Put objects under the Cloner to copy them", icon="INFO")
    _rows(col, ob, _layout_rows() + [None, ("Keep Instances", "Keep as Instances")])
    _object_hints(col, ob)


def page_matrix(col, ob):
    if _missing(col, ob):
        return
    _rows(col, ob, _layout_rows(order=False) + [None, ("Cube Size", "Cube Size")])
    _object_hints(col, ob)
    col.label(text="Pick it in a Cloner's Object mode (Points) to use its places", icon="INFO")


def page_fracture(col, ob):
    if _missing(col, ob):
        return
    if not kids_of(ob):
        col.label(text="Put objects under the Fracture", icon="INFO")
    _rows(col, ob, [("Explode Segments", "Explode Segments"), ("Keep Instances", "Keep as Instances")])


def page_voronoi(col, ob):
    if _missing(col, ob):
        return
    if not kids_of(ob):
        col.label(text="Put polygon objects under the Voronoi Fracture", icon="INFO")
    col.prop(ob, '["b4d_vor_count"]', text="Pieces")
    col.prop(ob, '["b4d_vor_seed"]', text="Seed")
    _rows(col, ob, [("Piece Size", "Piece Size %"), ("Keep Instances", "Keep as Instances")])
    if kids_of(ob):
        col.label(text=f"{len(ob.data.vertices)} points in {len(ob.data.polygons)} faces", icon="MOD_EXPLODE")


def page_tracer(col, ob):
    if _missing(col, ob):
        return
    _rows(col, ob, [("Object", "Trace"), ("Limit", "Limit (frames)"), ("Thickness", "Thickness")])
    if get(ob, "Object") is None:
        col.label(text="Pick the object to trace, or a Cloner kept as instances", icon="INFO")
    col.label(text="Play the animation from its first frame to draw the lines", icon="INFO")


def _list(col, ob, prop, empty_hint):
    idx = "b4d_effector_index" if prop == "b4d_effectors" else "b4d_field_index"
    row = col.row()
    row.template_list("BLENDA4D_UL_links", prop, ob, prop, ob, idx, rows=4)
    side = row.column(align=True)
    for action, icon in (("ADD", "ADD"), ("REMOVE", "REMOVE"), (None, None), ("UP", "TRIA_UP"), ("DOWN", "TRIA_DOWN")):
        if action is None:
            side.separator()
            continue
        op = side.operator("blenda4d.link_slot", text="", icon=icon)
        op.prop, op.action = prop, action
    if not len(getattr(ob, prop)):
        col.label(text=empty_hint, icon="INFO")


def page_effectors(col, ob):
    col.use_property_split = False
    col.label(text="Effectors act on the pieces in this order")
    _list(col, ob, "b4d_effectors", "Drag an effector here from the Object Manager, or select this and make one")


def page_fields(col, ob):
    col.use_property_split = False
    col.label(text="With Fields, the effector acts only where they reach")
    _list(col, ob, "b4d_fields", "Drag a Field here from the Object Manager, or select this and make one")


def _vec(col, ob, key, label):
    sub = col.column(align=True)
    for i, a in enumerate("XYZ"):
        sub.prop(ob, f'["{key}"]', index=i, text=f"{label} . {a}")


def _users(col, ob, prop, what):
    users = [o.name for o in bpy.data.objects if any(link.object == ob and link.use for link in getattr(o, prop, ()))]
    col.separator()
    col.label(text=("Acts on: " + ", ".join(users)) if users else f"Not in any {what} list",
              icon="LINKED" if users else "INFO")


def _row(col, ob, key, text):
    if key in ob:
        col.prop(ob, f'["{key}"]', text=text)


def _pattern_rows(col, ob, prefix):
    col.prop(ob, prefix + "_pattern_ui", text="Pattern")
    _row(col, ob, prefix + "_noise_size", "Pattern Size")
    _row(col, ob, prefix + "_contrast", "Contrast")
    _row(col, ob, prefix + "_speed", "Speed")
    _row(col, ob, prefix + "_seed", "Seed")


def page_effector(col, ob):
    kind = effector_kind(ob)
    keys = KIND_SETTINGS[kind]
    col.prop(ob, '["b4d_eff_strength"]', text="Strength")
    if kind == "target_effector":
        _row(col, ob, "b4d_eff_upright", "Keep Upright")
        col.label(text="Pieces turn their Z axis toward this effector", icon="INFO")
    elif kind == "delay_effector":
        col.label(text="Pieces trail behind; play from the first frame", icon="INFO")
    else:
        if kind == "random_effector":
            col.prop(ob, "b4d_eff_random_mode_ui", text="Mode")
            if ob.get("b4d_eff_random_mode") == 2:
                _row(col, ob, "b4d_eff_speed", "Speed")
        elif kind == "shader_effector":
            _pattern_rows(col, ob, "b4d_eff")
        elif kind == "wave_effector":
            col.prop(ob, "b4d_eff_wave_shape_ui", text="Shape")
            _row(col, ob, "b4d_eff_frequency", "Frequency")
            _row(col, ob, "b4d_eff_spread", "Waves Along Copies")
        col.separator()
        per = " / s" if kind == "time_effector" else ""
        _vec(col, ob, "b4d_eff_position", "Position" + per)
        _vec(col, ob, "b4d_eff_rotation", "Rotation" + per)
        _vec(col, ob, "b4d_eff_scale", "Size %" + per)
        if "b4d_eff_use_color" in keys:
            col.separator()
            col.prop(ob, '["b4d_eff_use_color"]', text="Color")
            r = col.row()
            r.active = bool(ob.get("b4d_eff_use_color"))
            r.prop(ob, '["b4d_eff_color"]', text="Tint")
        if kind == "random_effector":
            _row(col, ob, "b4d_eff_seed", "Seed")
    _users(col, ob, "b4d_effectors", "Effectors")


def page_field(col, ob):
    kind = field_kind(ob)
    col.prop(ob, '["b4d_fld_strength"]', text="Strength")
    col.prop(ob, '["b4d_fld_invert"]', text="Invert")
    col.separator()
    if kind == "box_field":
        _vec(col, ob, "b4d_fld_size", "Size")
    elif kind == "linear_field":
        _row(col, ob, "b4d_fld_length", "Length")
    elif kind == "radial_field":
        _row(col, ob, "b4d_fld_sweep", "Sweep")
    elif kind == "wave_field":
        _row(col, ob, "b4d_fld_wavelength", "Wavelength")
        _row(col, ob, "b4d_fld_speed", "Speed")
    elif kind == "random_field":
        _row(col, ob, "b4d_fld_noise_size", "Pattern Size")
        _row(col, ob, "b4d_fld_contrast", "Contrast")
        _row(col, ob, "b4d_fld_speed", "Speed")
        _row(col, ob, "b4d_fld_seed", "Seed")
    elif kind == "shader_field":
        _pattern_rows(col, ob, "b4d_fld")
    else:
        _row(col, ob, "b4d_fld_radius", "Radius")
        _row(col, ob, "b4d_fld_height", "Height")
        _row(col, ob, "b4d_fld_tube", "Thickness")
    if kind in ("spherical_field", "box_field", "cylinder_field", "capsule_field", "cone_field", "torus_field"):
        col.prop(ob, '["b4d_fld_falloff"]', text="Soft Edge")
    _users(col, ob, "b4d_fields", "effector's Fields")


# --- menu settings (stored as whole numbers in the custom properties, shown through Object properties) ------------
def _menu(key, name, items):
    items = tuple((ident, label, tip, i) for i, (ident, label, tip) in enumerate(items))

    def get(self):
        return int(self.get(key, 0))

    def put(self, v):
        self[key] = int(v)
        self.update_tag()
    return bpy.props.EnumProperty(name=name, items=items, get=get, set=put)


_PATTERN_ITEMS = (("NOISE", "Noise", "Soft, cloudy patches"), ("CELLS", "Cells", "Round cells, each fading from its middle"),
                  ("WAVES", "Waves", "Straight bands"), ("CHECKER", "Checker", "Squares, on and off"))


def _menus():
    return {
        "b4d_eff_random_mode_ui": _menu("b4d_eff_random_mode", "Mode", (
            ("UNIFORM", "Uniform", "Any amount in the range, all as likely"),
            ("GAUSSIAN", "Gaussian", "Mostly small amounts, now and then a large one"),
            ("NOISE", "Noise", "Smooth amounts that drift as the animation plays"))),
        "b4d_eff_wave_shape_ui": _menu("b4d_eff_wave_shape", "Shape", (
            ("SINE", "Sine", "A smooth wave"), ("TRIANGLE", "Triangle", "Straight up and down"),
            ("SQUARE", "Square", "Jumps between the two ends"), ("SAW", "Saw", "Rises, then drops at once"))),
        "b4d_eff_pattern_ui": _menu("b4d_eff_pattern", "Pattern", _PATTERN_ITEMS),
        "b4d_fld_pattern_ui": _menu("b4d_fld_pattern", "Pattern", _PATTERN_ITEMS),
    }


PAGES = {"cloner": page_cloner, "matrix": page_matrix, "fracture": page_fracture, "voronoi_fracture": page_voronoi,
         "tracer": page_tracer}


# --- registration ----------------------------------------------------------------------------------------------------
classes = (BLENDA4D_PG_effector_link, BLENDA4D_PG_field_link, BLENDA4D_UL_links, BLENDA4D_OT_link_slot)
PROPS = ("b4d_effectors", "b4d_effector_index", "b4d_fields", "b4d_field_index", "b4d_eff_random_mode_ui",
         "b4d_eff_wave_shape_ui", "b4d_eff_pattern_ui", "b4d_fld_pattern_ui")
GROUP_OF = {**{k: "moclone" for k in OBJECTS}, **{k: "effectors" for k in EFFECTORS}, **{k: "fields" for k in FIELDS}}
_saved = {}


def _take_over_menus():
    """Remember the create column groups and the MoClone menu as they were; they come back on unregister. The menu's
    greyed entries that the live ones take over go (the live entries are added through kinds.menu_item)."""
    from . import bars, menus
    for g in ("moclone", "effectors", "fields"):
        if bars.GROUPS.get(g) is not None:
            _saved.setdefault(g, list(bars.GROUPS[g]))
    items = menus.MAIN.get("MoClone")
    if items is not None:
        _saved.setdefault("menu", list(items))
        live = {v[0] for v in list(OBJECTS.values()) + list(EFFECTORS.values()) + list(FIELDS.values())} | {"Effectors", "Fields"}
        items[:] = [it for it in items if not (isinstance(it, tuple) and it[0] in live and it[1] is None)]
        while items and items[-1] == menus.SEP:
            items.pop()


def _give_back_menus():
    from . import bars, menus
    for g in ("moclone", "effectors", "fields"):
        if g in _saved and bars.GROUPS.get(g) is not None:
            bars.GROUPS[g][:] = _saved.pop(g)
    if "menu" in _saved and menus.MAIN.get("MoClone") is not None:
        menus.MAIN["MoClone"][:] = _saved.pop("menu")
    kinds._MENU["MoClone"] = [e for e in kinds._MENU.get("MoClone", []) if e[1] not in GROUP_OF]


def register():
    _take_over_menus()
    for c in classes:
        bpy.utils.register_class(c)
    O = bpy.types.Object
    O.b4d_effectors = bpy.props.CollectionProperty(type=BLENDA4D_PG_effector_link)
    O.b4d_effector_index = bpy.props.IntProperty(name="Effector", min=0)
    O.b4d_fields = bpy.props.CollectionProperty(type=BLENDA4D_PG_field_link)
    O.b4d_field_index = bpy.props.IntProperty(name="Field", min=0)
    for name, prop in _menus().items():
        setattr(O, name, prop)
    for k in OBJECT_ORDER:
        label, icon, tip = OBJECTS[k]
        tabs, pages = [("OBJECT", "Object")], {"OBJECT": PAGES[k]}
        if k in WITH_EFFECTORS:
            tabs.append(("EFFECTORS", "Effectors"))
            pages["EFFECTORS"] = page_effectors
        kinds.add(k, label + " Object", icon, create=(lambda k: lambda context: create_object(context, k))(k),
                  tabs=tabs, pages=pages, titles={"OBJECT": "Object Properties", "EFFECTORS": "Effectors"}, describe=tip)
    for k in EFFECTOR_ORDER:
        label, icon, tip, _start = EFFECTORS[k]
        kinds.add(k, label, icon, create=(lambda k: lambda context: create_effector(context, k))(k),
                  tabs=[("OBJECT", "Effector"), ("FIELDS", "Fields")], pages={"OBJECT": page_effector, "FIELDS": page_fields},
                  titles={"OBJECT": label, "FIELDS": "Fields"},
                  describe=tip + " (with a Cloner, Matrix or Fracture selected, it is added to its list)")
    for k in FIELD_ORDER:
        label, icon, tip, _start = FIELDS[k]
        kinds.add(k, label, icon, create=(lambda k: lambda context: create_field(context, k))(k),
                  tabs=[("OBJECT", "Field")], pages={"OBJECT": page_field}, titles={"OBJECT": label},
                  describe=tip + " (with an effector selected, it is added to its Fields)")
    for k in OBJECT_ORDER + EFFECTOR_ORDER + FIELD_ORDER:
        label = (OBJECTS.get(k) or EFFECTORS.get(k) or FIELDS.get(k))[0]
        kinds.create_button(GROUP_OF[k], label, k)
        kinds.menu_item("MoClone", label, k)
    from . import managers
    if drop not in managers.OM_DROP:
        managers.OM_DROP.append(drop)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)


def unregister():
    if _on_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_update)
    from . import managers
    if drop in managers.OM_DROP:
        managers.OM_DROP.remove(drop)
    for k in GROUP_OF:
        kinds.KINDS.pop(k, None)
    _give_back_menus()
    for n in PROPS:
        if hasattr(bpy.types.Object, n):
            delattr(bpy.types.Object, n)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
