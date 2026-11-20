# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the colour-tinted icons Blenda 4D shows in its own columns (a developer tool, not part of the add-on).

    python3 tools/tint_icons.py [--size 64] [--blender /path/to/Blender]

What it does:
  1. Asks a headless Blender (factory settings, scratch config) which icons the create column and the Object Manager
     use, group by group (it reads bars.GROUPS after every feature module has registered), so buttons added by any
     module are picked up. Without a Blender it uses the table FALLBACK below.
  2. Downloads each of those icons' SVG from Blender's own source (release/datafiles/icons_svg, the release branch in
     BRANCH), replaces the white fill with the group's colour (opacity attributes are kept) and rasterises it with
     rsvg-convert to blenda4d/icons/<icon name>__<group>.png.
  3. Copies the tool column's large tool icons (Blender's datafiles/icons/*.dat triangle files from the installed
     Blender) with their accent colour changed to the column's colour, to blenda4d/icons/<tool icon>__<group>.dat.
  4. Draws the three axis letters for the command palette (X, Y, Z with a coloured bar under each).
Re-runnable: files are rewritten in place; files no longer used are removed. Downloads are cached in the system temp folder.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "blenda4d", "icons")
CACHE = os.path.join(tempfile.gettempdir(), "blenda4d_icon_cache")
BRANCH = "blender-v5.2-release"
SVG_URL = "https://projects.blender.org/blender/blender/raw/branch/{branch}/release/datafiles/icons_svg/{name}.svg"
MIRROR_URL = "https://raw.githubusercontent.com/blender/blender/{branch}/release/datafiles/icons_svg/{name}.svg"   # same files
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
RSVG = shutil.which("rsvg-convert") or "/opt/homebrew/bin/rsvg-convert"

# The colour hierarchy (sampled from the private layout's columns). Groups not listed keep Blender's plain icons.
COLOURS = {
    "shapes": "#6fd3d9", "splines": "#6fd3d9", "text": "#6fd3d9",           # things you build from: cyan
    "generators": "#8fd36a", "volume": "#8fd36a",                         # objects that make geometry: green
    "deformers": "#a690e6", "effectors": "#a690e6",                       # objects that change others: violet
    "moclone": "#ee9cc8",                                                 # cloning: pink
    "fields": "#e8d25a",                                                  # fields: yellow
    "null": "#c8cfe8", "environment": "#c8cfe8", "camera": "#c8cfe8", "lights": "#c8cfe8",   # scene: pale lavender
    "spline_tools": "#f5b355",                                            # tool column accents: orange
    "mesh_tools": "#b3b3b3",                                              # tool column accents: grey
}
AXIS = {"x": "#e0605f", "y": "#7fcb6f", "z": "#5f88d8"}
LETTER = "#d1d1d1"

# Object Manager: plain Blender object types that get a group colour (primitives and module kinds come from GROUPS).
OM_TYPES = {"CURVE": "splines", "FONT": "text", "EMPTY": "null", "LIGHT": "lights", "CAMERA": "camera",
            "META": "generators", "VOLUME": "volume"}

# The tool column (bars.MODES_TOOLS): which tool icons get which accent colour. Others stay Blender's own.
TOOLS = {"ops.curve.pen": "spline_tools", "ops.curve.draw": "spline_tools", "ops.mesh.knife_tool": "spline_tools",
         "ops.gpencil.draw": "spline_tools", "ops.view3d.ruler": "spline_tools",
         "ops.mesh.extrude_region_move": "mesh_tools", "ops.mesh.inset": "mesh_tools", "ops.mesh.bevel": "mesh_tools"}
TOOL_ACCENT = (117, 255, 175)      # the accent colour Blender's tool icons use

FALLBACK = {   # used only when no Blender is found
    "null": ["EMPTY_AXIS", "OUTLINER_OB_EMPTY"], "splines": ["CURVE_BEZCURVE", "CURVE_BEZCIRCLE"],
    "shapes": ["MESH_CUBE", "MESH_UVSPHERE"], "text": ["OUTLINER_OB_FONT"], "generators": ["MOD_SUBSURF"],
    "deformers": ["MOD_SIMPLEDEFORM"], "moclone": ["MOD_ARRAY"], "camera": ["OUTLINER_OB_CAMERA"], "lights": ["LIGHT_POINT"],
}

_ASK = r'''
import sys, json
sys.path.insert(0, ROOT)
import blenda4d
from blenda4d import bars, kinds, managers
bars.register()
kinds.register()
uses = {}
for group, members in bars.GROUPS.items():
    for m in members:
        uses.setdefault(group, set()).add(m[1])
for k, icon in managers.PRIM_ICON.items():
    uses.setdefault("shapes", set()).add(icon)
for t, group in OM_TYPES.items():
    uses.setdefault(group, set()).add(managers.TYPE_ICON[t])
for icon in ("LIGHT_POINT", "LIGHT_SUN", "LIGHT_SPOT", "LIGHT_AREA", "LIGHT"):
    uses.setdefault("lights", set()).add(icon)
json.dump({g: sorted(i for i in s if i and i != "NONE") for g, s in uses.items()}, open(OUTFILE, "w"))
'''


def ask_blender(blender):
    with tempfile.TemporaryDirectory() as tmp:
        outfile = os.path.join(tmp, "uses.json")
        script = os.path.join(tmp, "ask.py")
        with open(script, "w") as f:
            f.write(f"ROOT = {ROOT!r}\nOUTFILE = {outfile!r}\nOM_TYPES = {OM_TYPES!r}\n" + _ASK)
        env = dict(os.environ, BLENDER_USER_CONFIG=os.path.join(tmp, "cfg"), BLENDER_USER_SCRIPTS=os.path.join(tmp, "scripts"))
        subprocess.run([blender, "-b", "--factory-startup", "--python", script], env=env, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        if not os.path.exists(outfile):
            return None
        with open(outfile) as f:
            return json.load(f)


def svg_source(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + ".svg")
    if not os.path.exists(path):
        url = SVG_URL.format(branch=BRANCH, name=name)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
        except Exception:
            data = None
            for u in (url.replace("branch/" + BRANCH, "branch/main"), MIRROR_URL.format(branch=BRANCH, name=name)):
                try:
                    with urllib.request.urlopen(u, timeout=30) as r:
                        data = r.read()
                    break
                except Exception:
                    pass
            if data is None:
                return None
        if not data.lstrip().startswith(b"<svg"):
            return None
        with open(path, "wb") as f:
            f.write(data)
    with open(path, encoding="utf-8") as f:
        return f.read()


_WHITE = re.compile(r'(fill\s*[:=]\s*"?)(#fff(?:fff)?|white)\b', re.I)


def tint_svg(svg, colour):
    return _WHITE.sub(lambda m: m.group(1) + colour, svg)


def rasterise(svg_text, out_png, size):
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg_text)
        tmp = f.name
    try:
        subprocess.run([RSVG, "-w", str(size), "-h", str(size), "--keep-aspect-ratio", "-o", out_png, tmp], check=True)
    finally:
        os.unlink(tmp)


def recolour_dat(path, out, accent):
    """Write a copy of one of Blender's tool icon files with its accent colour replaced (loaded at run time with
    bpy.app.icons.new_triangles_from_file, so it is drawn as crisp triangles at the tool column's size)."""
    with open(path, "rb") as f:
        d = bytearray(f.read())
    if d[:3] != b"VCO":
        return False
    n = (len(d) - 8) // 18
    rgb = bytes(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    for c in range(8 + n * 6, 8 + n * 18, 4):
        if tuple(d[c:c + 3]) == TOOL_ACCENT:
            d[c:c + 3] = rgb
    with open(out, "wb") as f:
        f.write(d)
    return True


def dat_to_svg(path, accent):
    """One of Blender's tool icon files (triangles with a colour per corner) as an SVG, accent colour replaced."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:3] != b"VCO":
        return None
    n = (len(d) - 8) // 18
    coords = d[8:8 + n * 6]
    cols = d[8 + n * 6:8 + n * 18]
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" shape-rendering="geometricPrecision">']
    for t in range(n):
        pts = [(coords[t * 6 + 2 * k], 255 - coords[t * 6 + 2 * k + 1]) for k in range(3)]
        r, g, b, a = cols[t * 12:t * 12 + 4]
        if (r, g, b) == TOOL_ACCENT and accent:
            r, g, b = (int(accent[i:i + 2], 16) for i in (1, 3, 5))
        p = " ".join(f"{x},{y}" for x, y in pts)
        # a hairline stroke in the same colour closes the seams between neighbouring triangles
        parts.append(f'<polygon points="{p}" fill="rgb({r},{g},{b})" stroke="rgb({r},{g},{b})" stroke-width="0.6" '
                     f'stroke-linejoin="round" fill-opacity="{a / 255:.3f}" stroke-opacity="{a / 255:.3f}"/>')
    parts.append("</svg>")
    return "\n".join(parts)


LETTERS = {   # simple stroked capitals on a 16 x 16 grid, a coloured bar under each
    "x": "M4 1.5 L12 11.5 M12 1.5 L4 11.5", "y": "M4 1.5 L8 7 L12 1.5 M8 7 L8 11.5", "z": "M4 1.5 L12 1.5 L4 11.5 L12 11.5"}


def letter_svg(axis):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="{LETTERS[axis]}" fill="none" '
            f'stroke="{LETTER}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<rect x="3.5" y="13.6" width="9" height="1.4" rx="0.4" fill="{AXIS[axis]}"/></svg>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--blender", default=BLENDER)
    args = ap.parse_args()
    uses = ask_blender(args.blender) if os.path.exists(args.blender) else None
    if uses is None:
        print("no Blender answer; using the fallback table")
        uses = FALLBACK
    os.makedirs(OUT, exist_ok=True)
    made, missing = set(), []
    for group, icons in sorted(uses.items()):
        colour = COLOURS.get(group)
        if not colour:
            continue
        for icon in icons:
            svg = svg_source(icon.lower())
            if svg is None:
                missing.append(icon)
                continue
            name = f"{icon.lower()}__{group}.png"
            rasterise(tint_svg(svg, colour), os.path.join(OUT, name), args.size)
            made.add(name)
    dat_dir = os.path.join(os.path.dirname(os.path.dirname(args.blender)), "Resources")
    dat_dir = next((os.path.join(dat_dir, v, "datafiles", "icons") for v in sorted(os.listdir(dat_dir))
                    if os.path.isdir(os.path.join(dat_dir, v, "datafiles", "icons"))), None) if os.path.isdir(dat_dir) else None
    for tool, group in TOOLS.items():
        src = os.path.join(dat_dir, tool + ".dat") if dat_dir else ""
        if not os.path.exists(src):
            missing.append(tool)
            continue
        name = f"{tool}__{group}.dat"
        if recolour_dat(src, os.path.join(OUT, name), COLOURS[group]):
            made.add(name)
    for axis in AXIS:
        name = f"axis_{axis}__axis.png"
        rasterise(letter_svg(axis), os.path.join(OUT, name), args.size)
        made.add(name)
    for f in os.listdir(OUT):
        if f.endswith((".png", ".dat")) and f not in made:
            os.unlink(os.path.join(OUT, f))
    print(f"{len(made)} icons in {OUT}")
    if missing:
        print("not found (plain Blender icon is used):", ", ".join(sorted(set(missing))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
