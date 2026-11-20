# Roadmap

What Blenda 4D does not do yet. Pick an item, read AGENTS.md, open a pull request. Each feature module lives in its
own file under `blenda4d/` and plugs in through `kinds.py`, so most items touch one file.

## Next up
1. **Timeline**: the full animation workflow. A keyframe editor docked above the transport row, a curve editor, framing
   all, selected or current keys, key pages (interpolation, tangents, what happens before and after the keys), and
   jumping to or deleting keys from any setting. Today's timeline is the transport row only.

## Splines (`splines.py`)
- Our own point-editing tools (Blender's curve edit mode and Pen stand in today).
- More ways to space the points along a curve (only even spacing today).
- More shapes, and gears with shaped teeth.

## MoClone (`moclone.py`)
In:
- Objects: the Cloner (Linear, Grid with box, ball and cylinder forms, Radial, Honeycomb, Object; a Null with objects
  under it is copied as one clone), Matrix, Fracture, Voronoi Fracture and Tracer.
- Effectors: Random (Uniform, Gaussian, Noise), Plain, Shader (Noise, Cells, Waves, Checker, Image), Delay (Blend,
  Spring), Wave, Step, Target (with Keep Upright), Time, Inheritance, Push Apart, Spline, Volume, Formula, Sound (one
  band per piece, baked to keyframes) and Group (holds other effectors, with its own Strength and Fields). Every effector
  that tints can use a fixed colour or a gradient.
- Fields: Linear, Spherical, Box, Cylinder, Capsule, Cone, Torus, Radial, Random, Shader, Wave, Image (movies and
  sequences play), Sound, Formula, Time, Object, Spline, Material (the image a material uses) and Group (holds other
  Fields). Rows combine by Max, Add, Subtract, Multiply or Min, each with a Mix; effectors can make their Fields
  remember (Keep, Fade).
- Effector and Field lists take drops from the Object Manager and have a check box per row.

Still to do:
- Effectors: effectors acting on the child's own animation time, the Shader Effector reading a full material (only
  its image today), a ReEffector separate from the Group Effector.
- Fields: Remember with spreading (growth into neighbours), Field layers that change a Field (curve, remap, freeze).
- More Cloner modes and options: spirals, copies inside a volume, Object mode reading the object's own selections,
  more Clone Order options (blend between children, sorted by index).
- Voronoi Fracture: points from another object or a Matrix, an inner material for the cut faces, cuts on open meshes.
- Tracer: trace a spline's points or a mesh's points, not only object origins and Cloner copies kept as instances.
- MoText, MoExtrude, MoInstance and MoSpline; MoGraph selections and weight maps.
- Drag handles in the viewport for Count, spacing, Field sizes.

## Generators (`generators.py`)
- More Sweep options: guide curves, scale and twist along the path, finer UV control.
- More Loft and Extrude options, including bevels on text.
- More cap and bevel shapes for the spline generators.
- More Symmetry, Boolean, Array, Instance and Connect options.
- Quad remeshing (voxel only today) and more polygon-reduction controls.
- A cage overlay for Subdivision Surface.
- Children are read in name order (the Object Manager sorts by name); user-ordered children would be better.

## Deformers (`deformers.py`)
- Drag handles in the viewport for strength and angle.
- Fields and falloff, so a deformer can fade out.
- More deformers.
- Displace from an image, a gentler smoothing mode, a wave that fades with distance, a Shrinkwrap offset.

## Lights and sky (`lights.py`, `sky.py`)
- Volumetric glow per light.
- Sun shadow quality settings.
- A Sky material in the Material Manager; transparent background tied to the Sky.

## Asset Browser (`assets.py`)
- More asset types and saved searches.
- Folder rename and delete that also move the files on disk.
- Using brush and scene assets directly (they are appended today).
- A real drag from the browser (today a press on a tile is turned into a drop by the add-on).

## Render (`render_settings.py`, `topbar.py`)
- A history of renders with side-by-side compare.
- A render queue (its menu items are there, greyed).
- Render settings nested inside each other, so a variation only stores what it changes.
- More frame-range options and multi-line notes on a setting.

## Add-ons (`addons_ui.py`)
- Add-on items in other Blender menus (Edit, Select, edit-mode and node editor menus).
- Add-on settings drawn as Attribute Manager pages; add-on object buttons in the create column.
- An optional small manifest an add-on can include to say where its buttons and pages belong.
- Add-on panels in other editors (Shader Editor, Image Editor).

## Material tags (`material_tag.py`)
- Several material tags on one object, and tags that cover only part of an object.
- More projection types, and soft blending between the faces of the box projection.
- Editing several selected tags at once; dragging tags between objects.

## Managers and pages
- **Variations**: several versions of one scene (cameras, materials, visibility) from the Variations tab.
- **Tags**: more tag types and their pages.
- **Material editing**: a simple page for editing any material, with a shader switch.
- **Object Manager**: bookmarks, layers, search filters, a column divider for tags.
- Four views: remember the hidden views across sessions.
- Keymap: more shortcuts, including keys for the managers.

## Everyday safety
- Safety copies before any file replaces the open one, and a File > Safety Copies menu.
- Orders that survive reopening for every list the user can reorder.

## Platform
- Testing on Windows and Linux (the add-on is plain Python and should already run there).
- Checking the tinted icons on high-resolution (Retina) displays.
- Volume tools, character tools and simulation pages.
