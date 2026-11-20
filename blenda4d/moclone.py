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
    "random_effector": ("Random Effector", "STICKY_UVS_DISABLE", "Move, turn, size and tint each piece by a different random amount",
                        {"b4d_eff_position": (50.0, 50.0, 50.0)}),
    "plain_effector": ("Plain Effector", "OBJECT_ORIGIN", "Move, turn, size and tint every piece by the same amount (use a Field to limit it)",
                       {"b4d_eff_position": (0.0, 100.0, 0.0)}),
    "delay_effector": ("Delay Effector", "IPO_EASE_IN_OUT", "Make the pieces trail behind their moves, catching up over the next frames",
                       {"b4d_eff_strength": 80.0}),
    "step_effector": ("Step Effector", "IPO_CONSTANT", "Change the pieces more and more from the first to the last",
                      {"b4d_eff_scale": (100.0, 100.0, 100.0)}),
    "target_effector": ("Target Effector", "CON_TRACKTO", "Turn the pieces so they face this effector", {}),
    "time_effector": ("Time Effector", "PREVIEW_RANGE", "Change the pieces more and more as the animation plays (amounts per second)",
                      {"b4d_eff_rotation": (0.0, 1.5707963, 0.0)}),
    "shader_effector": ("Shader Effector", "NODE_MATERIAL", "Move, turn, size and tint the pieces by a pattern (noise, cells, waves, checker)",
                        {"b4d_eff_position": (0.0, 100.0, 0.0), "b4d_eff_contrast": 100.0}),
    "wave_effector": ("Wave Effector", "FORCE_HARMONIC", "Move, turn and size the pieces back and forth in a wave over time and along the copies",
                      {"b4d_eff_position": (0.0, 50.0, 0.0)}),
    "inheritance_effector": ("Inheritance Effector", "CON_CHILDOF",
                             "Move the pieces to the places of another Cloner's or Matrix's copies, one for one", {}),
    "push_apart_effector": ("Push Apart Effector", "ARROW_LEFTRIGHT", "Push pieces that are too close apart so they don't overlap",
                            {"b4d_eff_radius": 75.0}),
    "spline_effector": ("Spline Effector", "CON_FOLLOWPATH", "Move the pieces onto a spline, spread along it", {}),
    "volume_effector": ("Volume Effector", "CUBE", "Move, turn, size and tint the pieces that are inside another object",
                        {"b4d_eff_position": (0.0, 100.0, 0.0)}),
    "formula_effector": ("Formula Effector", "CON_TRANSFORM", "Move, turn, size and tint the pieces by a formula you type",
                         {"b4d_eff_position": (0.0, 50.0, 0.0)}),
    "sound_effector": ("Sound Effector", "OUTLINER_DATA_SPEAKER",
                       "Move, turn, size and tint the pieces by a sound: each piece follows one band, low notes first",
                       {"b4d_eff_position": (0.0, 100.0, 0.0)}),
    "group_effector": ("Group Effector", "GROUP", "Hold other effectors, with one Strength and one set of Fields for all of them", {}),
}
EFFECTOR_ORDER = ("random_effector", "plain_effector", "shader_effector", "delay_effector", "wave_effector",
                  "step_effector", "target_effector", "time_effector", "inheritance_effector", "push_apart_effector",
                  "spline_effector", "volume_effector", "formula_effector", "sound_effector", "group_effector")

# field kind -> (label, icon, tooltip, starting values)
FIELDS = {
    "linear_field": ("Linear Field", "IPO_LINEAR", "Let an effector grow from nothing at this Field to full strength one Length along its Z", {}),
    "spherical_field": ("Spherical Field", "MESH_UVSPHERE", "Let an effector act inside a ball, fading out at its edge", {}),
    "box_field": ("Box Field", "MESH_CUBE", "Let an effector act inside a box, fading out at its sides", {}),
    "random_field": ("Random Field", "STICKY_UVS_DISABLE", "Let an effector act in a smooth random pattern that can move", {}),
    "cylinder_field": ("Cylinder Field", "MESH_CYLINDER", "Let an effector act inside an upright cylinder, fading out at its sides and ends", {}),
    "capsule_field": ("Capsule Field", "MESH_CAPSULE", "Let an effector act inside a capsule (a cylinder with round ends)", {}),
    "cone_field": ("Cone Field", "MESH_CONE", "Let an effector act inside a cone that opens upward from this Field", {}),
    "torus_field": ("Torus Field", "MESH_TORUS", "Let an effector act inside a ring around this Field", {}),
    "radial_field": ("Radial Field", "FORCE_VORTEX", "Let an effector grow from nothing to full strength going round this Field", {}),
    "shader_field": ("Shader Field", "NODE_MATERIAL", "Let an effector act by a pattern: noise, cells, waves or a checker",
                     {"b4d_fld_contrast": 100.0}),
    "wave_field": ("Wave Field", "MOD_WAVE", "Let an effector act in rings going out from this Field", {}),
    "image_field": ("Image Field", "IMAGE_DATA", "Let an effector act by the brightness of an image laid flat under this Field", {}),
    "sound_field": ("Sound Field", "OUTLINER_DATA_SPEAKER", "Let an effector act as strongly as a sound is loud at each frame", {}),
    "formula_field": ("Formula Field", "CON_TRANSFORM", "Let an effector act by a formula you type, from the place, time and piece", {}),
    "time_field": ("Time Field", "PREVIEW_RANGE", "Let an effector grow from nothing to full strength as the animation plays", {}),
    "object_field": ("Object Field", "MESH_ICOSPHERE", "Let an effector act inside another object, fading out around it", {}),
    "spline_field": ("Spline Field", "CON_FOLLOWPATH", "Let an effector act near a spline, fading out over Radius", {}),
    "material_field": ("Material Field", "MATERIAL", "Let an effector act by the image a material uses, laid flat under this Field", {}),
    "group_field": ("Group Field", "GROUP", "Hold other Fields, combined, with one Strength for all of them", {}),
}
FIELD_ORDER = ("linear_field", "spherical_field", "box_field", "cylinder_field", "capsule_field", "cone_field",
               "torus_field", "radial_field", "random_field", "shader_field", "wave_field", "image_field", "sound_field",
               "formula_field", "time_field", "object_field", "spline_field", "material_field", "group_field")

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
    "b4d_eff_color_mode": (0, None),
    "b4d_eff_color2": ((0.05, 0.35, 1.0), dict(subtype="COLOR", min=0.0, max=1.0,
                                             description="The other end of the gradient")),
    "b4d_eff_source": (None, None),
    "b4d_eff_spline": (None, None),
    "b4d_eff_volume": (None, None),
    "b4d_eff_radius": (50.0, dict(min=0.0, soft_max=10000.0, precision=1, step=100,
                                  description="How much room each piece keeps around it (cm)")),
    "b4d_eff_iterations": (5, dict(min=1, max=100, description="How many passes it makes; more passes untangle crowds better")),
    "b4d_eff_start": (0.0, dict(subtype="PERCENTAGE", soft_min=0.0, soft_max=100.0, precision=1,
                                description="Where along the spline the first piece goes")),
    "b4d_eff_end": (100.0, dict(subtype="PERCENTAGE", soft_min=0.0, soft_max=100.0, precision=1,
                                description="Where along the spline the last piece goes")),
    "b4d_eff_offset": (0.0, dict(subtype="PERCENTAGE", soft_min=-100.0, soft_max=100.0, precision=1,
                                 description="Slide all pieces along the spline (they wrap round past the end)")),
    "b4d_eff_align": (True, dict(description="Turn the pieces so their X axis follows the spline")),
    "b4d_eff_formula": ("sin(t * 2 + id * 0.5)", dict(description="The amount for each piece: x y z (cm), t (seconds), f (frame), "
                                                             "id, count, rnd; + - * / ** and sin cos abs min max fract clamp ...")),
    "b4d_eff_sound": ("", dict(subtype="FILE_PATH", description="The sound file the pieces follow")),
    "b4d_eff_low": (40.0, dict(min=1.0, max=20000.0, precision=0, description="The lowest band starts here (Hz); bake again after changing it")),
    "b4d_eff_high": (12000.0, dict(min=1.0, max=20000.0, precision=0, description="The highest band ends here (Hz); bake again after changing it")),
    "b4d_eff_gain": (100.0, dict(subtype="PERCENTAGE", min=0.0, soft_max=400.0, precision=1, description="Turn the sound up or down")),
    "b4d_eff_bands": (tuple([0.0] * mn.SOUND_BANDS), dict(min=0.0, max=1.0, description="How loud each band is at this frame (baked)")),
    "b4d_eff_delay_mode": (0, None),
    "b4d_eff_stiffness": (60.0, dict(min=0.1, soft_max=500.0, precision=1, description="How hard the spring pulls the pieces back")),
    "b4d_eff_damping": (30.0, dict(subtype="PERCENTAGE", min=0.0, max=100.0, precision=1, description="How fast the bouncing dies down")),
    "b4d_eff_image": (None, None),
    "b4d_fld_formula": ("0.5 + 0.5 * sin(x / 50 + t * 2)", dict(description="The reach at each place, 0 to 1: x y z (cm, in the Field's "
                                                                       "space), t (seconds), f (frame), id, rnd")),
    "b4d_fld_duration": (2.0, dict(min=0.0, soft_max=60.0, precision=2, subtype="TIME_ABSOLUTE",
                                   description="How long it takes to reach full strength (seconds)")),
    "b4d_fld_delay": (0.0, dict(min=0.0, soft_max=60.0, precision=2, subtype="TIME_ABSOLUTE",
                                description="How long it waits after the first frame before it starts (seconds)")),
    "b4d_fld_object": (None, None),
    "b4d_fld_distance": (100.0, dict(min=0.0, soft_max=10000.0, precision=1, step=100,
                                     description="How far outside the object the effect fades out (cm)")),
    "b4d_fld_spline": (None, None),
    "b4d_fld_material": (None, None),
    "b4d_fld_frame_offset": (0, dict(soft_min=-1000, soft_max=1000, description="Start a movie or image sequence this many frames later")),
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
    "b4d_fld_image": (None, None),
    "b4d_fld_image_size": (400.0, dict(min=0.1, soft_max=10000.0, precision=1, step=100,
                                       description="How wide the image lies (cm), centred on the Field")),
    "b4d_fld_sound": ("", dict(subtype="FILE_PATH", description="The sound file whose loudness drives the Field")),
    "b4d_fld_low": (20.0, dict(min=1.0, max=20000.0, soft_max=20000.0, precision=0,
                               description="Leave out sounds lower than this (Hz); bake again after changing it")),
    "b4d_fld_high": (20000.0, dict(min=1.0, max=20000.0, precision=0,
                                   description="Leave out sounds higher than this (Hz); bake again after changing it")),
    "b4d_fld_level": (0.0, dict(min=0.0, max=1.0, description="How loud the sound is at this frame (baked from the file)")),
    "b4d_fld_gain": (100.0, dict(subtype="PERCENTAGE", min=0.0, soft_max=400.0, precision=1,
                                 description="Turn the loudness up or down")),
    "b4d_eff_memory": (0, None),
    "b4d_eff_fade": (1.0, dict(min=0.0, soft_max=10.0, precision=2, subtype="TIME_ABSOLUTE",
                               description="How long a piece takes to let go after the Fields leave it (seconds)")),
    "b4d_vor_count": (20, dict(min=1, max=500, description="How many pieces")),
    "b4d_vor_seed": (0, dict(min=0, max=100000, description="Place the cuts differently")),
}
_MOVE = ("b4d_eff_strength", "b4d_eff_position", "b4d_eff_rotation", "b4d_eff_scale")
_TINT = ("b4d_eff_use_color", "b4d_eff_color", "b4d_eff_color_mode", "b4d_eff_color2")
_PATTERN = ("b4d_eff_pattern", "b4d_eff_noise_size", "b4d_eff_contrast", "b4d_eff_speed", "b4d_eff_seed", "b4d_eff_image")
_F = ("b4d_fld_strength", "b4d_fld_invert")
_MEMORY = ("b4d_eff_memory", "b4d_eff_fade")
KIND_SETTINGS = {
    "random_effector": _MOVE + _TINT + ("b4d_eff_seed", "b4d_eff_random_mode", "b4d_eff_speed"),
    "shader_effector": _MOVE + _TINT + _PATTERN,
    "wave_effector": _MOVE + _TINT + ("b4d_eff_wave_shape", "b4d_eff_frequency", "b4d_eff_spread"),
    "plain_effector": _MOVE + _TINT,
    "delay_effector": ("b4d_eff_strength", "b4d_eff_delay_mode", "b4d_eff_stiffness", "b4d_eff_damping"),
    "step_effector": _MOVE + _TINT,
    "target_effector": ("b4d_eff_strength", "b4d_eff_upright"),
    "time_effector": _MOVE,
    "inheritance_effector": ("b4d_eff_strength", "b4d_eff_source"),
    "push_apart_effector": ("b4d_eff_strength", "b4d_eff_radius", "b4d_eff_iterations"),
    "spline_effector": ("b4d_eff_strength", "b4d_eff_spline", "b4d_eff_start", "b4d_eff_end", "b4d_eff_offset", "b4d_eff_align"),
    "volume_effector": _MOVE + _TINT + ("b4d_eff_volume",),
    "formula_effector": _MOVE + _TINT + ("b4d_eff_formula",),
    "sound_effector": _MOVE + _TINT + ("b4d_eff_sound", "b4d_eff_low", "b4d_eff_high", "b4d_eff_gain", "b4d_eff_bands"),
    "group_effector": ("b4d_eff_strength",),
    "linear_field": ("b4d_fld_strength", "b4d_fld_invert", "b4d_fld_length", "b4d_fld_falloff"),
    "spherical_field": ("b4d_fld_strength", "b4d_fld_invert", "b4d_fld_radius", "b4d_fld_falloff"),
    "box_field": ("b4d_fld_strength", "b4d_fld_invert", "b4d_fld_size", "b4d_fld_falloff"),
    "random_field": _F + ("b4d_fld_noise_size", "b4d_fld_seed", "b4d_fld_speed", "b4d_fld_contrast", "b4d_fld_falloff"),
    "cylinder_field": _F + ("b4d_fld_radius", "b4d_fld_height", "b4d_fld_falloff"),
    "capsule_field": _F + ("b4d_fld_radius", "b4d_fld_height", "b4d_fld_falloff"),
    "cone_field": _F + ("b4d_fld_radius", "b4d_fld_height", "b4d_fld_falloff"),
    "torus_field": _F + ("b4d_fld_radius", "b4d_fld_tube", "b4d_fld_falloff"),
    "radial_field": _F + ("b4d_fld_sweep", "b4d_fld_falloff"),
    "shader_field": _F + ("b4d_fld_pattern", "b4d_fld_noise_size", "b4d_fld_seed", "b4d_fld_speed", "b4d_fld_contrast",
                          "b4d_fld_image", "b4d_fld_falloff"),
    "wave_field": _F + ("b4d_fld_wavelength", "b4d_fld_speed", "b4d_fld_falloff"),
    "image_field": _F + ("b4d_fld_image", "b4d_fld_image_size", "b4d_fld_frame_offset", "b4d_fld_falloff"),
    "material_field": _F + ("b4d_fld_material", "b4d_fld_image_size", "b4d_fld_frame_offset", "b4d_fld_falloff"),
    "formula_field": _F + ("b4d_fld_formula", "b4d_fld_falloff"),
    "time_field": _F + ("b4d_fld_duration", "b4d_fld_delay", "b4d_fld_falloff"),
    "object_field": _F + ("b4d_fld_object", "b4d_fld_distance", "b4d_fld_falloff"),
    "spline_field": _F + ("b4d_fld_spline", "b4d_fld_radius", "b4d_fld_falloff"),
    "group_field": _F + ("b4d_fld_falloff",),
    "sound_field": _F + ("b4d_fld_sound", "b4d_fld_low", "b4d_fld_high", "b4d_fld_level", "b4d_fld_gain", "b4d_fld_falloff"),
    "voronoi_fracture": ("b4d_vor_count", "b4d_vor_seed"),
}
for _k in EFFECTORS:
    KIND_SETTINGS[_k] = KIND_SETTINGS[_k] + _MEMORY


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
    types = ("MESH",) if k == "voronoi_fracture" else mn.GEOMETRY_TYPES
    return [c for c in sorted(ob.children, key=lambda c: c.name) if kind_of(c) is None and (
        c.type in types or (k == "cloner" and c.type == "EMPTY" and _null_parts(c)))]


def _null_parts(null):
    """The objects with geometry anywhere under a Null (a Cloner copies them together as one clone)."""
    return [d for d in null.children_recursive if d.type in mn.GEOMETRY_TYPES and kind_of(d) is None]


def copied_objects(ob):
    """Everything a MoClone object uses: its children, and what is under its Nulls."""
    out = []
    for c in kids_of(ob):
        out.append(c)
        if c.type == "EMPTY":
            out += _null_parts(c)
    return out


def _listed(ob, prop, kind_fn):
    out = []
    for link in getattr(ob, prop, ()):
        o = link.object
        k = kind_fn(o)
        if k is not None and link.use and o.name in bpy.data.objects and all(o != x[0] for x in out):
            out.append((o, k, getattr(link, "blend", "MAX"), round(getattr(link, "mix", 100.0), 3)))
    return out


def _members_eff(ob):
    return [(e, k, fields_of(e)) for e, k in effectors_of(ob) if e != ob]


def _members_fld(ob):
    return [x for x in fields_of(ob) if x[0] != ob]


mn.effector_members = _members_eff
mn.field_members = _members_fld


def fields_of(effector):
    """[(field, kind, how it combines)] in list order: rows switched off, empty rows and objects that are not Fields
    are skipped."""
    return _listed(effector, "b4d_fields", field_kind)


def effectors_of(ob):
    """[(effector, kind)] in list order, the same way."""
    return [(o, k) for o, k, _b, _m in _listed(ob, "b4d_effectors", effector_kind)]


POINTERS = {
    "b4d_fld_image": ("IMAGE", "The image whose brightness says where to act"),
    "b4d_eff_source": ("OBJECT", "The Matrix, Cloner (with Keep Instances) or object whose copies or points the pieces take"),
    "b4d_eff_spline": ("OBJECT", "The spline the pieces move onto"),
    "b4d_eff_volume": ("OBJECT", "The object whose inside the effector acts in"),
    "b4d_eff_image": ("IMAGE", "The image whose brightness moves the pieces (pattern Image)"),
    "b4d_fld_object": ("OBJECT", "The object whose inside the Field reaches"),
    "b4d_fld_spline": ("OBJECT", "The spline the Field follows"),
    "b4d_fld_material": ("MATERIAL", "The material whose image the Field reads"),
}


def _picked(ob):
    return ",".join(getattr(ob.get(k), "name", "") for k in POINTERS if k in ob)


def stamp(ob, kind, start=None):
    """Give the object every setting its kind reads (a missing one would break the drivers)."""
    if "_b4d_enabled" not in ob:
        ob["_b4d_enabled"] = True
    for key in KIND_SETTINGS.get(kind, ()):
        if key in ob:
            continue
        default, ui = SETTINGS[key]
        if key in POINTERS:                           # a data-block picked from the file
            ob[key] = None
            try:
                ob.id_properties_ui(key).update(id_type=POINTERS[key][0], description=POINTERS[key][1])
            except (TypeError, KeyError):
                pass
            continue
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


def _describe_fields(fl, depth=0):
    out = []
    for f, fk, b, m in fl:
        part = f"{f.name}/{b}/{m}/{_picked(f)}/{f.get('b4d_fld_formula', '') if fk == 'formula_field' else ''}"
        if fk == "group_field" and depth < 4:
            part += "(" + _describe_fields(_members_fld(f), depth + 1) + ")"
        out.append(part)
    return ",".join(out)


def _describe_effectors(lst, depth=0):
    out = []
    for e, ek, fl in lst:
        part = (f"{e.name}:{ek}:{e.get('b4d_eff_memory', 0)}:{e.get('b4d_eff_color_mode', 0)}:{e.get('b4d_eff_delay_mode', 0)}:"
                f"{_picked(e)}:{e.get('b4d_eff_formula', '') if ek == 'formula_effector' else ''}:" + _describe_fields(fl))
        if ek == "group_effector" and depth < 4:
            part += "{" + _describe_effectors(_members_eff(e), depth + 1) + "}"
        out.append(part)
    return ";".join(out)


def _signature(ob):
    k = object_kind(ob)
    parts = [ob.name, k, ",".join(c.name for c in copied_objects(ob)),
             _describe_effectors(_effector_list(ob))]
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
            "shader_field": ("CUBE", ob.get("b4d_fld_noise_size", 200.0) * 0.5 * mn.SCALE),
            "image_field": ("CUBE", ob.get("b4d_fld_image_size", 400.0) * 0.5 * mn.SCALE),
            "sound_field": ("SPHERE", 0.3),
            "material_field": ("CUBE", ob.get("b4d_fld_image_size", 400.0) * 0.5 * mn.SCALE),
            "formula_field": ("PLAIN_AXES", 0.5), "time_field": ("SPHERE", 0.3), "group_field": ("PLAIN_AXES", 0.5),
            "object_field": ("PLAIN_AXES", 0.5),
            "spline_field": ("SPHERE", ob.get("b4d_fld_radius", 200.0) * mn.SCALE)}[kind]
    if ob.empty_display_type != want[0]:
        ob.empty_display_type = want[0]
    if abs(ob.empty_display_size - want[1]) > 1e-6:
        ob.empty_display_size = max(want[1], 1e-4)


def _restart_trailing(ob):
    """A Delay Effector remembers past frames; when its settings change, that memory is dropped so the trailing is
    worked out again with the new values (Blender would otherwise keep showing the old frames)."""
    key = ";".join(f"{e.name}:{e.get('b4d_eff_strength')}:{e.get('b4d_eff_fade')}:{enabled(e)}:{e.get('b4d_eff_delay_mode')}:"
                   f"{e.get('b4d_eff_stiffness')}:{e.get('b4d_eff_damping')}:" +
                   ",".join(f"{f.name}/{b}/{m}" for f, _k, b, m in fl)
                   for e, k, fl in _effector_list(ob) if k == "delay_effector" or (fl and e.get("b4d_eff_memory")))
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
                for c in copied_objects(ob):
                    keep.add(c.name)
                    if c.type != "EMPTY":
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
    owners = [o for o in context.selected_objects if object_kind(o) in WITH_EFFECTORS or effector_kind(o) == "group_effector"]
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
    owners = [o for o in context.selected_objects if effector_kind(o) is not None or field_kind(o) == "group_field"]
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
    mix: bpy.props.FloatProperty(name="Mix", default=100.0, min=0.0, max=100.0, subtype="PERCENTAGE", precision=1,
                                 update=_list_changed, description="How much of this Field goes into the reach")
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


# --- Image and Sound Fields: loading files -------------------------------------------------------------------------
def _field_of(context, kind):
    ob = context.view_layer.objects.active
    return ob if field_kind(ob) == kind else None


class BLENDA4D_OT_field_image(bpy.types.Operator):
    bl_idname = "blenda4d.field_image"
    bl_label = "Open Image"
    bl_description = "Open an image (or a movie or image sequence) from disk for this object"
    bl_options = {"REGISTER", "UNDO"}
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    key: bpy.props.StringProperty(default="b4d_fld_image", options={"HIDDEN", "SKIP_SAVE"})
    filter_movie: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_image: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return kind_of(context.view_layer.objects.active) is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        ob = context.view_layer.objects.active
        if self.key not in ob:
            return {"CANCELLED"}
        try:
            img = bpy.data.images.load(self.filepath, check_existing=True)
        except RuntimeError as ex:
            self.report({"ERROR"}, f"Could not open the image: {ex}")
            return {"CANCELLED"}
        ob[self.key] = img
        sync_all()
        return {"FINISHED"}


def _levels(snd, rate, fps, low, high):
    """Loudness per frame of `snd`, filtered to low..high (Hz): the frame's average level, a full-scale tone is 1."""
    if low > 20.0:
        snd = snd.highpass(low)
    if high < min(20000.0, rate / 2):
        snd = snd.lowpass(high)
    data = snd.data()
    mono = data.mean(axis=1) if data.ndim > 1 else data
    per = rate / fps
    frames = max(1, int(len(mono) / per))
    out = []
    for i in range(frames):
        part = mono[int(i * per):int((i + 1) * per)]
        rms = float((part.astype("float64") ** 2).mean() ** 0.5) if len(part) else 0.0
        out.append(min(1.0, rms / 0.7071))
    return out


def _bake_keys(ob, key, index, start, values):
    """One constant keyframe per frame on ob[key] (index for an array setting)."""
    from bpy_extras import anim_utils
    if index is None:
        ob[key] = values[0]
        ob.keyframe_insert(f'["{key}"]', frame=start)
    else:
        ob[key][index] = values[0]
        ob.keyframe_insert(f'["{key}"]', index=index, frame=start)
    ad = ob.animation_data
    bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
    fc = next(f for f in bag.fcurves if f.data_path == f'["{key}"]' and (index is None or f.array_index == index))
    fc.keyframe_points.clear()
    fc.keyframe_points.add(len(values))
    co = []
    for i, v in enumerate(values):
        co += [start + i, v]
    fc.keyframe_points.foreach_set("co", co)
    fc.keyframe_points.foreach_set("interpolation", [0] * len(values))      # constant: one value per frame
    fc.update()


def bake_bands(ob, scene):
    """Sound Effector: split the sound into bands from Low to High (evenly on a musical scale) and bake each band's
    loudness per frame into the effector's Bands, as keyframes."""
    import aud
    path = bpy.path.abspath(ob.get("b4d_eff_sound", ""))
    snd = aud.Sound(path)
    rate = float(snd.specs[0])
    fps = scene.render.fps / scene.render.fps_base
    low, high = float(ob.get("b4d_eff_low", 40.0)), float(ob.get("b4d_eff_high", 12000.0))
    high = max(high, low * 1.01)
    n = mn.SOUND_BANDS
    edges = [low * (high / low) ** (i / n) for i in range(n + 1)]
    frames = 0
    for i in range(n):
        values = [min(1.0, v * 2.0) for v in _levels(snd, rate, fps, edges[i], edges[i + 1])]  # bands are quieter
        _bake_keys(ob, "b4d_eff_bands", i, scene.frame_start, values)
        frames = len(values)
    ob.update_tag()
    return frames


def bake_sound(ob, scene):
    """Write the sound's loudness at every frame into the Field's Level, as keyframes (so it plays in plain Blender
    too). Loudness is the frame's average level, filtered to Low..High; a full-scale tone is 1."""
    import aud
    path = bpy.path.abspath(ob.get("b4d_fld_sound", ""))
    snd = aud.Sound(path)
    levels = _levels(snd, float(snd.specs[0]), scene.render.fps / scene.render.fps_base,
                     float(ob.get("b4d_fld_low", 20.0)), float(ob.get("b4d_fld_high", 20000.0)))
    _bake_keys(ob, "b4d_fld_level", None, scene.frame_start, levels)
    ob.update_tag()
    return len(levels)


class BLENDA4D_OT_field_sound(bpy.types.Operator):
    bl_idname = "blenda4d.field_sound"
    bl_label = "Load Sound"
    bl_description = "Pick a sound file and bake its loudness into this Sound Field, one value per frame"
    bl_options = {"REGISTER", "UNDO"}
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    again: bpy.props.BoolProperty(options={"SKIP_SAVE", "HIDDEN"})
    filter_sound: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_movie: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    @classmethod
    def description(cls, context, props):
        return ("Bake the loudness again (after changing Low or High)" if props.again else
                "Pick a sound file and bake its loudness into this Sound Field, one value per frame")

    @classmethod
    def poll(cls, context):
        return kind_of(context.view_layer.objects.active) in ("sound_field", "sound_effector")

    def invoke(self, context, event):
        if self.again:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        ob = context.view_layer.objects.active
        effector = kind_of(ob) == "sound_effector"
        if not self.again:
            ob["b4d_eff_sound" if effector else "b4d_fld_sound"] = self.filepath
        try:
            n = bake_bands(ob, context.scene) if effector else bake_sound(ob, context.scene)
        except Exception as ex:
            self.report({"ERROR"}, f"Could not read the sound: {ex}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Baked {n} frames of loudness")
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
    if object_kind(target) in WITH_EFFECTORS or (effector_kind(target) == "group_effector" and
                                                  all(effector_kind(o) for o in objs)):
        want, prop = [o for o in objs if effector_kind(o) and o != target], "b4d_effectors"
    elif effector_kind(target) or field_kind(target) == "group_field":
        want, prop = [o for o in objs if field_kind(o) and o != target], "b4d_fields"
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
    col.label(text="The effectors it holds, acting in this order" if effector_kind(ob) else
              "Effectors act on the pieces in this order")
    _list(col, ob, "b4d_effectors", "Drag an effector here from the Object Manager, or select this and make one")


def page_fields(col, ob):
    col.use_property_split = False
    col.label(text="The Fields it holds, combined in order" if field_kind(ob) else
              "With Fields, the effector acts only where they reach")
    _list(col, ob, "b4d_fields", "Drag a Field here from the Object Manager, or select this and make one")
    lst, i = ob.b4d_fields, ob.b4d_field_index
    if 0 <= i < len(lst) and lst[i].object is not None:
        row = lst[i]
        box = col.column()
        box.use_property_split = True
        box.label(text=f"Row: {row.object.name}")
        box.prop(row, "mix", text="Mix")
        if i > 0:
            box.prop(row, "blend", text="Combine")
    if len(lst) and effector_kind(ob):
        col.separator()
        sub = col.column()
        sub.use_property_split = True
        sub.prop(ob, "b4d_eff_memory_ui", text="Remember")
        if ob.get("b4d_eff_memory") == 2:
            _row(sub, ob, "b4d_eff_fade", "Fade Time")
        if ob.get("b4d_eff_memory"):
            sub.label(text="Play from the first frame", icon="INFO")


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


def _image_row(col, ob, key, text="Image"):
    r = col.row(align=True)
    r.prop(ob, f'["{key}"]', text=text)
    r.operator("blenda4d.field_image", text="", icon="FILEBROWSER").key = key


def _formula_row(col, ob, key):
    from . import moclone_formula
    col.prop(ob, f'["{key}"]', text="Formula")
    err = moclone_formula.check(str(ob.get(key, "")), mn.FORMULA_NAMES)
    if err:
        col.label(text=err, icon="ERROR")


def _pattern_rows(col, ob, prefix):
    col.prop(ob, prefix + "_pattern_ui", text="Pattern")
    if ob.get(prefix + "_pattern") == 4:
        _image_row(col, ob, prefix + "_image")
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
        col.prop(ob, "b4d_eff_delay_mode_ui", text="Mode")
        if ob.get("b4d_eff_delay_mode") == 1:
            _row(col, ob, "b4d_eff_stiffness", "Stiffness")
            _row(col, ob, "b4d_eff_damping", "Damping")
        col.label(text="Pieces trail behind; play from the first frame", icon="INFO")
    elif kind == "group_effector":
        col.label(text="Its Effectors page lists the effectors it holds", icon="INFO")
    elif kind == "inheritance_effector":
        col.prop(ob, '["b4d_eff_source"]', text="Source")
        src = ob.get("b4d_eff_source")
        if src is None:
            col.label(text="Pick a Matrix, a Cloner or any object with points", icon="INFO")
        elif object_kind(src) == "cloner" and not get(src, "Keep Instances"):
            col.label(text="Turn on the Cloner's Keep Instances to take its copies", icon="INFO")
    elif kind == "push_apart_effector":
        _row(col, ob, "b4d_eff_radius", "Radius")
        _row(col, ob, "b4d_eff_iterations", "Iterations")
    elif kind == "spline_effector":
        col.prop(ob, '["b4d_eff_spline"]', text="Spline")
        if not isinstance(ob.get("b4d_eff_spline"), bpy.types.Object) or ob["b4d_eff_spline"].type != "CURVE":
            col.label(text="Pick a spline", icon="INFO")
        _row(col, ob, "b4d_eff_start", "Start")
        _row(col, ob, "b4d_eff_end", "End")
        _row(col, ob, "b4d_eff_offset", "Offset")
        _row(col, ob, "b4d_eff_align", "Align to Spline")
    else:
        if kind == "volume_effector":
            col.prop(ob, '["b4d_eff_volume"]', text="Volume")
            if not isinstance(ob.get("b4d_eff_volume"), bpy.types.Object):
                col.label(text="Pick a closed mesh: pieces inside it are changed", icon="INFO")
        if kind == "formula_effector":
            _formula_row(col, ob, "b4d_eff_formula")
        elif kind == "sound_effector":
            r = col.row(align=True)
            path = ob.get("b4d_eff_sound", "")
            r.label(text="Sound: " + (bpy.path.basename(path) if path else "none"))
            r.operator("blenda4d.field_sound", text="Load Sound", icon="FILEBROWSER")
            _row(col, ob, "b4d_eff_low", "Low (Hz)")
            _row(col, ob, "b4d_eff_high", "High (Hz)")
            r = col.row()
            r.enabled = bool(path)
            r.operator("blenda4d.field_sound", text="Bake Again", icon="FILE_REFRESH").again = True
            _row(col, ob, "b4d_eff_gain", "Gain")
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
            sub = col.column()
            sub.active = bool(ob.get("b4d_eff_use_color"))
            sub.prop(ob, "b4d_eff_color_mode_ui", text="Color Mode")
            gradient = ob.get("b4d_eff_color_mode") == 1
            sub.prop(ob, '["b4d_eff_color"]', text="From" if gradient else "Tint")
            if gradient:
                sub.prop(ob, '["b4d_eff_color2"]', text="To")
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
    elif kind == "image_field":
        _image_row(col, ob, "b4d_fld_image")
        _row(col, ob, "b4d_fld_image_size", "Size")
        img = ob.get("b4d_fld_image")
        if not isinstance(img, bpy.types.Image):
            col.label(text="Pick or open an image: bright parts act, dark parts don't", icon="INFO")
        elif img.source in ("MOVIE", "SEQUENCE"):
            _row(col, ob, "b4d_fld_frame_offset", "Frame Offset")
    elif kind == "material_field":
        col.prop(ob, '["b4d_fld_material"]', text="Material")
        _row(col, ob, "b4d_fld_image_size", "Size")
        img = mn.material_image(ob.get("b4d_fld_material"))
        col.label(text=f"Reads: {img.name}" if img else "Pick a material that uses an image texture",
                  icon="IMAGE_DATA" if img else "INFO")
        if img is not None and img.source in ("MOVIE", "SEQUENCE"):
            _row(col, ob, "b4d_fld_frame_offset", "Frame Offset")
    elif kind == "formula_field":
        _formula_row(col, ob, "b4d_fld_formula")
    elif kind == "time_field":
        _row(col, ob, "b4d_fld_delay", "Delay")
        _row(col, ob, "b4d_fld_duration", "Duration")
    elif kind == "object_field":
        col.prop(ob, '["b4d_fld_object"]', text="Object")
        _row(col, ob, "b4d_fld_distance", "Distance")
        if not isinstance(ob.get("b4d_fld_object"), bpy.types.Object):
            col.label(text="Pick a closed mesh", icon="INFO")
    elif kind == "spline_field":
        col.prop(ob, '["b4d_fld_spline"]', text="Spline")
        _row(col, ob, "b4d_fld_radius", "Radius")
        if not isinstance(ob.get("b4d_fld_spline"), bpy.types.Object):
            col.label(text="Pick a spline", icon="INFO")
    elif kind == "group_field":
        col.label(text="Its Fields page lists the Fields it holds", icon="INFO")
    elif kind == "sound_field":
        r = col.row(align=True)                       # the file is picked (and baked) by the button only
        path = ob.get("b4d_fld_sound", "")
        r.label(text="Sound: " + (bpy.path.basename(path) if path else "none"))
        r.operator("blenda4d.field_sound", text="Load Sound", icon="FILEBROWSER")
        _row(col, ob, "b4d_fld_low", "Low (Hz)")
        _row(col, ob, "b4d_fld_high", "High (Hz)")
        r = col.row()
        r.enabled = bool(ob.get("b4d_fld_sound"))
        r.operator("blenda4d.field_sound", text="Bake Again", icon="FILE_REFRESH").again = True
        _row(col, ob, "b4d_fld_gain", "Gain")
        col.label(text=f"Loudness at this frame: {100.0 * float(ob.get('b4d_fld_level', 0.0)):.0f} %", icon="SOUND")
    else:
        _row(col, ob, "b4d_fld_radius", "Radius")
        _row(col, ob, "b4d_fld_height", "Height")
        _row(col, ob, "b4d_fld_tube", "Thickness")
    if kind in ("spherical_field", "box_field", "cylinder_field", "capsule_field", "cone_field", "torus_field",
                "spline_field"):
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
                  ("WAVES", "Waves", "Straight bands"), ("CHECKER", "Checker", "Squares, on and off"),
                  ("IMAGE", "Image", "An image's brightness, laid flat; Pattern Size is its width (a movie plays)"))


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
        "b4d_eff_delay_mode_ui": _menu("b4d_eff_delay_mode", "Mode", (
            ("BLEND", "Blend", "Pieces ease toward where they go"),
            ("SPRING", "Spring", "Pieces overshoot and bounce to rest"))),
        "b4d_eff_color_mode_ui": _menu("b4d_eff_color_mode", "Color Mode", (
            ("FIXED", "Fixed", "One tint for all the pieces"),
            ("GRADIENT", "Gradient", "From one colour to the other: by how much each piece is changed, or along the copies"))),
        "b4d_eff_memory_ui": _menu("b4d_eff_memory", "Remember", (
            ("OFF", "Off", "Each frame the Fields' reach is as it is now"),
            ("KEEP", "Keep", "Once a Field has reached a piece, it stays reached"),
            ("FADE", "Fade", "A reached piece lets go over Fade Time after the Field moves on"))),
    }


PAGES = {"cloner": page_cloner, "matrix": page_matrix, "fracture": page_fracture, "voronoi_fracture": page_voronoi,
         "tracer": page_tracer}


# --- registration ----------------------------------------------------------------------------------------------------
classes = (BLENDA4D_PG_effector_link, BLENDA4D_PG_field_link, BLENDA4D_UL_links, BLENDA4D_OT_link_slot,
           BLENDA4D_OT_field_image, BLENDA4D_OT_field_sound)
PROPS = ("b4d_effectors", "b4d_effector_index", "b4d_fields", "b4d_field_index", "b4d_eff_random_mode_ui",
         "b4d_eff_wave_shape_ui", "b4d_eff_pattern_ui", "b4d_fld_pattern_ui", "b4d_eff_memory_ui", "b4d_eff_color_mode_ui",
         "b4d_eff_delay_mode_ui")
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
        tabs, pages = [("OBJECT", "Effector")], {"OBJECT": page_effector, "FIELDS": page_fields}
        if k == "group_effector":
            tabs.append(("EFFECTORS", "Effectors"))
            pages["EFFECTORS"] = page_effectors
        tabs.append(("FIELDS", "Fields"))
        kinds.add(k, label, icon, create=(lambda k: lambda context: create_effector(context, k))(k),
                  tabs=tabs, pages=pages, titles={"OBJECT": label, "FIELDS": "Fields", "EFFECTORS": "Effectors"},
                  describe=tip + " (with a Cloner, Matrix or Fracture selected, it is added to its list)")
    for k in FIELD_ORDER:
        label, icon, tip, _start = FIELDS[k]
        tabs, pages = [("OBJECT", "Field")], {"OBJECT": page_field}
        if k == "group_field":
            tabs.append(("FIELDS", "Fields"))
            pages["FIELDS"] = page_fields
        kinds.add(k, label, icon, create=(lambda k: lambda context: create_field(context, k))(k),
                  tabs=tabs, pages=pages, titles={"OBJECT": label, "FIELDS": "Fields"},
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
