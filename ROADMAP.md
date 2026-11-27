# Roadmap

What Blenda 4D does not do yet. Pick an item, read AGENTS.md, open a pull request. Each feature module lives in its
own file under `blenda4d/` and plugs in through `kinds.py`, so most items touch one file.

## Next up
1. **Timeline**: the full animation workflow. A keyframe editor docked above the transport row, a curve editor, framing
   all, selected or current keys, key pages (interpolation, tangents, what happens before and after the keys), and
   jumping to or deleting keys from any setting. Today's timeline is the transport row only.
2. **Cloning tools (MoClone)**, the rest (`moclone*.py`): the Cloner, Matrix, Fracture, Voronoi Fracture, MoText,
   MoExtrude, PolyFX, MoSpline, Tracer and MoInstance are in, with the first seven effectors plus Formula, Inheritance,
   Push Apart, ReEffector, Sound, Spline, Volume and Group, nine fields, clone physics and the field tags.
   Still to come: Blend and Sort clone modes (with Modify Clone); the field-layer stack (Time, Step, Delay, Decay,
   Freeze, Remap, Curve...); Weight Paint and the Selection tool for clones; a MoClone Cache; a Multi Shader; more than
   one of each field tag per object.

## Splines (`splines.py`)
- Our own point-editing tools (Blender's curve edit mode and Pen stand in today).
- More ways to space the points along a curve (only even spacing today).
- More shapes, and gears with shaped teeth.

## Generators (`generators.py`)
- More Sweep options: guide curves, scale and twist along the path, finer UV control.
- More Loft and Extrude options, including bevels on text.
- More cap and bevel shapes for the spline generators.
- More Symmetry, Boolean, Array, Instance and Connect options.
- Quad remeshing (voxel only today) and more polygon-reduction controls.
- A cage overlay for Subdivision Surface.

## Deformers (`deformers.py`)
- Drag handles in the viewport for strength and angle.
- Fields and falloff, so a deformer can fade out.
- More deformers.
- Displace from an image, a gentler smoothing mode, a wave that fades with distance, a Shrinkwrap offset.

## Volumes (`volume.py`)
In: the **Volume Builder** (meshes, splines, text, points, particles, smoke, VDB volumes, metaballs, NURBS surfaces,
Grease Pencil, collection instances and other Volume Builders under it become one distance volume; an Objects list, which also takes drops from the Object Manager, adds, subtracts or intersects each one in
order, with Volume From (Auto, Filled, Surface, Points, Edges, Particles, Smoke / Density), Radius, Grow / Shrink and a Filter (Smooth, Clean,
Relax, Round) per row; filter layers in the list (Smooth, Clean, Relax, Round, Fillet, Grow / Shrink) that change
everything above them, each limited to where its fields reach (mixed Max, Normal, Min, Add, Subtract or Multiply);
a soft Blend where each row meets the ones above; and Voxel Size, Grow / Shrink,
Smoothing and Rounding for the whole; the viewport shows it as a surface, voxels or fog; Render as Fog renders it as fog or smoke with its own density, colour and noise, also under a Volume Mesher) and
the **Volume Mesher** (turns the Volume Builder under it into a surface: Threshold, Adaptivity, Smoothing, Smooth
Shading; the surface takes the Mesher's material; Quad Remesh with Target Faces, Keep Sharp Edges and Symmetry X, Y, Z).
Still to do:
- Quads whose size follows the detail (Blender's QuadriFlow makes evenly sized quads), and Quad Remesh that updates
  by itself when the volume changes.
- Smoke from an Adaptive Domain (the smoke moves with the domain's moving box; today it needs Adaptive Domain off),
  and liquids (FLIP) as inputs.
- Fog noise that moves over time.

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
- Character tools and simulation pages.
