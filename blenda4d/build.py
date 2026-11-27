# SPDX-License-Identifier: GPL-3.0-or-later
"""Build Blenda's layouts (layouts.py) on the live screen at exact pixel sizes.

Areas are made with area_split / area_close (which work without window focus), one step per redraw, because an
area's size only updates on the next event loop:
  document tabs (full width, top) | managers column (right, full height: Objects over Attributes)
  command palette (top, left of the managers) | tools column (drawn at the viewport's left edge, toolcol.py)
  create column (drawn in the viewport's toolbar strip, strip.py)
  timeline (bottom, under the viewport) | optional Material Manager column (between viewport and create column)
  | optional Asset Browser column (left of the viewport).
With the Timeline (timeline_edit.py) or the Node Editor (nodetabs.py) open under the viewport the layout has the tools and create columns as two areas down its sides, so they stay
full height; what is drawn in them keeps its size, and they get their width back after the window is resized."""
import bpy

from . import roles

DOC_TABS_PX = 30
PALETTE_PX = 62
TIMELINE_PX = 97              # three rows (timeline.py)
TOOL_ZOOM = {"PALETTE": 7}   # zoom steps (as Ctrl+scroll): larger icons, boxes stay square
CREATE_PX = 57                # as wide as the viewport's own strip: the column stays put when it becomes an area
VIEW_TABS_PX = 30             # four views: their one row of tabs
EDITORS = 0.44                # the share of the viewport's height the Timeline under it takes
STRIP_ZOOM = 0               # the create column is drawn at its own size (strip.py): the strip needs no zoom
MANAGERS_PX = 330
MATERIALS_PX = 230
MM_BAR_PX = 30
UV_BAR_PX = 40                # the UV Editor's row of tools
OM_HEAD_PX = 88               # the Object Manager's title, menus and tool row (unzoomed; the Size slider zooms only the rows)
ASSETS_PX = 420
ATTRIBUTES = 0.56             # the Attribute Manager's share of the managers column
EDGE = 3

_active = [0]


def busy():
    return _active[0] > 0


# --- the curtain: while a whole layout is being built, every region is painted plain, so a slow machine shows the
# finished layout and never the areas being split and moved on the way. It lifts when the build is done, and on its own
# after CURTAIN_MAX seconds whatever happens.
CURTAIN_MAX = 20.0
_curtain = [0.0]
_curtain_handles = []
_CURTAIN_SPACES = ("SpaceView3D", "SpaceProperties", "SpaceOutliner", "SpaceImageEditor", "SpaceNodeEditor",
                   "SpaceDopeSheetEditor", "SpaceGraphEditor", "SpaceNLA", "SpaceSequenceEditor", "SpaceTextEditor",
                   "SpaceSpreadsheet", "SpaceFileBrowser", "SpaceInfo", "SpaceConsole", "SpaceClipEditor")
_CURTAIN_REGIONS = ("WINDOW", "HEADER", "TOOL_HEADER", "TOOLS", "UI", "CHANNELS", "FOOTER", "ASSET_SHELF",
                    "ASSET_SHELF_HEADER", "NAVIGATION_BAR", "EXECUTE")


def curtain(on):
    import time
    if on and _curtain_handles:                          # drawn last, over every column Blenda paints itself
        curtain_off()
        curtain_on()
    _curtain[0] = time.monotonic() + CURTAIN_MAX if on else 0.0
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()


def _draw_curtain():
    import time
    if _curtain[0] == 0.0:
        return
    if time.monotonic() > _curtain[0]:
        _curtain[0] = 0.0
        return
    region = bpy.context.region
    if region is None:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    col = tuple(bpy.context.preferences.themes[0].view_3d.space.back) if hasattr(
        bpy.context.preferences.themes[0].view_3d.space, "back") else (0.19, 0.19, 0.19)
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    w, h = region.width, region.height
    batch = batch_for_shader(sh, "TRIS", {"pos": ((0, 0), (w, 0), (w, h), (0, h))}, indices=((0, 1, 2), (0, 2, 3)))
    gpu.state.blend_set("NONE")
    sh.uniform_float("color", (*col[:3], 1.0))
    batch.draw(sh)


def curtain_on():
    for sp in _CURTAIN_SPACES:
        cls = getattr(bpy.types, sp, None)
        if cls is None:
            continue
        for rt in _CURTAIN_REGIONS:
            try:
                _curtain_handles.append((cls, cls.draw_handler_add(_draw_curtain, (), rt, "POST_PIXEL"), rt))
            except (TypeError, ValueError):
                pass


def curtain_off():
    for cls, h, rt in _curtain_handles:
        try:
            cls.draw_handler_remove(h, rt)
        except (ValueError, ReferenceError):
            pass
    _curtain_handles.clear()
    _curtain[0] = 0.0


def run_steps(gen, done=None):
    """Run a generator one step per redraw; a step that fails while the window is not ready is retried."""
    from . import magnify
    magnify.leave_all()                                    # areas are split and joined: plain views only
    state = {"retries": 20}
    _active[0] += 1

    def tick():
        try:
            next(gen)
            return 0.0                                   # the next step as soon as Blender has laid out the last
        except StopIteration:
            _active[0] -= 1
            if done:
                done()
            return None
        except RuntimeError as ex:
            state["retries"] -= 1
            if state["retries"] > 0:
                return 0.25
            _active[0] -= 1
            print("Blenda 4D: layout step gave up:", ex)
            return None
        except Exception:
            _active[0] -= 1
            raise
    bpy.app.timers.register(tick)


def _scale():
    return bpy.context.preferences.system.ui_scale


def px(v):
    return int(round(v * _scale()))


def _region(area, kind):
    if not roles.alive(area):                              # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == kind), None)


def _ov(window, area, region="WINDOW"):
    kw = {} if window.screen.is_temporary else {"screen": window.screen}      # Blender refuses one of a small window
    return bpy.context.temp_override(window=window, area=area, region=_region(area, region), **kw)


def biggest_view(screen):
    views = [a for a in screen.areas if a.type == "VIEW_3D"]
    if not views:
        big = max(screen.areas, key=lambda a: a.width * a.height)
        big.type = "VIEW_3D"
        views = [big]
    return max(views, key=lambda a: a.width * a.height)


def lay_out(window, *areas):
    """Blender gives an area its size, and its regions theirs, when one of its regions is switched: after this a new
    area can be measured, split and dressed without waiting for a redraw."""
    for area in areas:
        space = area.spaces.active
        with _ov(window, area):
            space.show_region_header = not space.show_region_header
            space.show_region_header = not space.show_region_header


def split(window, area, direction, size_px, side):
    size = area.height if direction == "HORIZONTAL" else area.width
    frac = size_px / max(size, 1)
    factor = {"TOP": 1 - frac, "BOTTOM": frac, "LEFT": frac, "RIGHT": 1 - frac}[side]
    before = {a.as_pointer() for a in window.screen.areas}
    with _ov(window, area):
        bpy.ops.screen.area_split(direction=direction, factor=factor)
    new = next(a for a in window.screen.areas if a.as_pointer() not in before)
    lay_out(window, new, area)
    yield from ()
    pair = (new, area)
    if direction == "HORIZONTAL":
        top, bottom = sorted(pair, key=lambda a: -a.y)
        return top if side == "TOP" else bottom
    left, right = sorted(pair, key=lambda a: a.x)
    return left if side == "LEFT" else right


def make_role(window, area, name):
    area.type = "PROPERTIES"
    lay_out(window, area)
    for _ in range(20):
        if roles.set_role(area, name):
            break
        area.tag_redraw()
        yield
    lay_out(window, area)
    roles.hide_nav(area, window)
    if name in TOOL_ZOOM:
        yield
        _zoom(window, area, TOOL_ZOOM[name])
        yield


def _zoom(window, area, n):
    """Blender's own area zoom (as Ctrl+scroll does): buttons and icons grow together."""
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if region is None:
        return
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
            for _ in range(n):
                bpy.ops.view2d.zoom_in()
    except RuntimeError as ex:
        print("Blenda 4D: could not zoom", area.type, ex)


def split_now(window, area, direction, size_px, side, size=None):
    """Split off a strip and return it at once: Blender makes the smaller part the new area, which is the strip.
    `size` stands in for the area's size when Blender has not laid the area out yet."""
    size = size or (area.height if direction == "HORIZONTAL" else area.width)
    frac = size_px / max(size, 1)
    factor = {"TOP": 1 - frac, "BOTTOM": frac, "LEFT": frac, "RIGHT": 1 - frac}[side]
    before = {a.as_pointer() for a in window.screen.areas}
    with _ov(window, area):
        bpy.ops.screen.area_split(direction=direction, factor=factor)
    return next(a for a in window.screen.areas if a.as_pointer() not in before)


def role_now(area, name, window=None):
    """The area becomes its role's editor in the same step it appears (no frame shows a stray editor)."""
    area.type = "PROPERTIES"
    roles.set_role(area, name)
    try:
        roles.hide_nav(area, window or _window_of(area))
    except RuntimeError:
        pass


def _window_of(area):
    """The window showing this area's screen: Blender needs it to lay a region out (without it, it crashed on Windows)."""
    for w in bpy.context.window_manager.windows:
        if w.screen == area.id_data:
            return w
    return None


def settle(window, *pairs):
    """After the frame: make sure each area has its role and no tab column (set at once where Blender allowed)."""
    for area, name in pairs:
        for _ in range(20):
            if roles.set_role(area, name):
                break
            yield
        roles.hide_nav(area, window)


def _add_column(window, width_px, side, main, bar):
    """A column beside the viewport with its bottom strip, each one its final editor from the frame it appears in."""
    view = biggest_view(window.screen)
    # Blender makes the smaller part the new area: the column stays the smaller one, or it would land on the other side
    col = split_now(window, view, "VERTICAL", min(px(width_px) + EDGE, round(view.width * 0.45)), side)
    role_now(col, main, window)
    lay_out(window, col)                                   # the column has its size before it is split
    strip = split_now(window, col, "HORIZONTAL", px(MM_BAR_PX) + EDGE, "BOTTOM")
    role_now(strip, bar, window)
    yield from settle(window, (col, main), (strip, bar))


def _width(window, key, usual):
    from . import layouts
    return max(60, layouts.spec_of(window.screen)["sizes"].get(key, usual))


def add_assets(window):
    """The Asset Browser column, left of the viewport, with its bottom strip."""
    from . import toolcol
    tools = 0 if roles.areas(window.screen, "MODES") else toolcol.WIDTH       # it hosts the tools column
    yield from _add_column(window, _width(window, "assets", ASSETS_PX + toolcol.WIDTH) - toolcol.WIDTH + tools, "LEFT", "ASSETS", "AB_BAR")


def add_materials(window, own_create=True):
    """The Material Manager column between the viewport and the create column, with its bottom strip. Where the create
    column is still the viewport's own strip, it first becomes a column of its own at the right edge."""

    if own_create and not roles.areas(window.screen, "CREATE"):   # four views lay out their own create column
        create = yield from split(window, biggest_view(window.screen), "VERTICAL", px(CREATE_PX) + EDGE, "RIGHT")
        yield from make_role(window, create, "CREATE")
        for a in window.screen.areas:
            if a.type == "VIEW_3D":
                dress_view(a)                              # its own strip hides: the column shows the buttons now
    yield from _add_column(window, _width(window, "materials", MATERIALS_PX), "RIGHT", "MATERIALS", "MM_BAR")


COLUMNS = {"MATERIALS": (add_materials, "MM_BAR"), "ASSETS": (add_assets, "AB_BAR")}
CORE = ("DOC_TABS", "PALETTE", "OBJECTS", "ATTRIBUTES", "OM_BAR", "OM_HEAD")


def old_timelines(screen):
    """Blender's own timeline, the strip under the viewport before Blenda drew its own."""
    return [a for a in screen.areas if a.type == "DOPESHEET_EDITOR" and a.ui_type == "TIMELINE"]


def side_px():
    """The tools column's width as an area of its own."""
    from . import toolcol
    return px(toolcol.WIDTH) + EDGE


def view_top(window, area):
    """Pixels from this column's top down to the viewport's picture: it starts level with it, as inside the viewport."""
    view = max((a for a in window.screen.areas if a.type == "VIEW_3D"), key=lambda a: (a.y + a.height, a.width), default=None)
    if view is None:
        return 0
    rows = sum(r.height for r in view.regions if r.type in {"HEADER", "TOOL_HEADER"} and r.height > 1 and r.alignment == "TOP")
    return max(0, area.y + area.height - (view.y + view.height) + rows)


def intact(screen):
    """The layout is all there (each strip once, a viewport, its timeline and editors): nothing to rebuild."""
    from . import layouts, nodetabs, uvtab
    spec = layouts.spec_of(screen)
    if any(len(roles.areas(screen, r)) != 1 for r in CORE):
        return False
    stacked, keys = bool(spec["editors"]), spec["editors"] == "KEYS"
    four = sum(a.type == "VIEW_3D" for a in screen.areas) > 1
    own = roles.areas(screen, "MODES")                     # the tools column's own area: with the Timeline or four views
    if len(own) > 1 or (len(own) != stacked and not four):
        return False
    if len(roles.areas(screen, "VIEW_TABS")) > four:
        return False
    if not nodetabs.intact(screen, spec["editors"]) or not uvtab.intact(screen, spec["editors"]):
        return False
    if any(len(roles.areas(screen, r)) != keys for r in ("TL_BAR", "TL_EDIT")) or (stacked and len(roles.areas(screen, "CREATE")) != 1):
        return False
    if not any(a.type == "VIEW_3D" for a in screen.areas) or len(roles.areas(screen, "TIMELINE")) != spec["timeline"]:
        return False
    if old_timelines(screen):
        return False
    for main, (_add, bar) in COLUMNS.items():
        if len(roles.areas(screen, main)) != len(roles.areas(screen, bar)) or len(roles.areas(screen, main)) > 1:
            return False
    return True


# --- the parts a layout adds under and beside the viewport ----------------------------------------------------------
def add_timeline(window):
    strip = yield from split(window, biggest_view(window.screen), "HORIZONTAL", px(TIMELINE_PX) + EDGE, "BOTTOM")
    yield from make_role(window, strip, "TIMELINE")


def stacked(screen):
    """Is there an editor under the viewport, between the two columns?"""
    from . import nodetabs, uvtab
    return bool(roles.areas(screen, "TL_EDIT")) or nodetabs.editor(screen) is not None or uvtab.editor(screen) is not None


def add_stack(window, spec, materials=False, assets=False):
    """The tools and create columns down the sides and, between them under the viewport, the Timeline or the Node Editor.
    The Material Manager goes between the viewport and the create column; the Asset Browser is beside the viewport,
    above the editors."""
    from . import nodetabs, uvtab
    kind, sizes = spec["editors"], spec["sizes"]
    screen = window.screen
    tools = yield from split(window, biggest_view(screen), "VERTICAL", side_px(), "LEFT")
    yield from make_role(window, tools, "MODES")
    create = yield from split(window, biggest_view(screen), "VERTICAL", px(CREATE_PX) + EDGE, "RIGHT")
    yield from make_role(window, create, "CREATE")
    if materials:                                          # between the viewport and the create column
        yield from add_materials(window)
    view = biggest_view(screen)
    dress_view(view)
    if kind == uvtab.KIND:                                 # beside the viewport, not under it
        yield from uvtab.add_steps(window, view, sizes)
        if assets:
            yield from add_assets(window)
        return
    nodes = kind in nodetabs.KINDS
    key = "nodes" if nodes else "editors"
    share = min(0.8, max(0.15, sizes.get(key, nodetabs.NODES if nodes else EDITORS)))
    if key not in sizes:                             # a short window: still a few rows of tracks
        share = max(share, min(0.6, px(220) / max(1, view.height)))
    low = yield from split(window, view, "HORIZONTAL", round(view.height * share), "BOTTOM")
    if nodes:
        yield from nodetabs.add_steps(window, low, kind, sizes)
    else:
        yield from make_role(window, low, "TL_EDIT")
        from . import timeline_edit
        bar = yield from split(window, low, "HORIZONTAL", min(px(timeline_edit.BAR_PX) + EDGE, round(low.height * 0.45)), "TOP")
        yield from make_role(window, bar, "TL_BAR")
    if assets:
        yield from add_assets(window)


def _into_view(window, area):
    from . import quadview
    view = biggest_view(window.screen)
    yield from quadview._join(window, area, view)


def remove_stack(window):
    """The editors and the two columns go back into the viewport, each one a join along a whole edge."""
    from . import nodetabs, quadview, uvtab
    screen = window.screen
    if roles.areas(screen, "ASSETS"):
        yield from remove_column(window, "ASSETS")
    yield from uvtab.remove_steps(window)
    yield from nodetabs.remove_steps(window)
    for bar in roles.areas(screen, "TL_BAR"):
        if roles.areas(screen, "TL_EDIT"):
            yield from quadview._join(window, bar, roles.areas(screen, "TL_EDIT")[0])
    for e in roles.areas(screen, "TL_EDIT"):
        yield from _into_view(window, e)
    for a in roles.areas(screen, "CREATE"):
        yield from _into_view(window, a)
    for n in COLUMNS:
        if roles.areas(screen, n):
            yield from remove_column(window, n)
    for a in roles.areas(screen, "MODES"):
        yield from _into_view(window, a)
    for a in screen.areas:
        if a.type == "VIEW_3D":
            dress_view(a)


def remove_column(window, name, fold=False):
    from . import quadview, uvtab
    if uvtab.editor(window.screen) is not None:            # every column is as high as the viewport here: into that one, by name
        for a in roles.areas(window.screen, COLUMNS[name][1]):
            yield from quadview._join(window, a, roles.areas(window.screen, name)[0])
        for a in roles.areas(window.screen, name):
            yield from _into_view(window, a)
        return
    for role in (COLUMNS[name][1], name):                  # the strip into its column, the column into the viewport,
        for a in roles.areas(window.screen, role):         # in one step: no frame shows the column without its strip
            with _ov(window, a):
                bpy.ops.screen.area_close()
    yield
    if fold and name == "MATERIALS" and not stacked(window.screen) and len(quadview.views(window.screen)) <= 1:
        for a in roles.areas(window.screen, "CREATE"):     # the create column goes back to being the viewport's strip
            yield from _into_view(window, a)
        for a in window.screen.areas:
            if a.type == "VIEW_3D":
                dress_view(a)


def renew_steps(window):
    """The stack again at its own sizes (the window was resized); everything else stays where it is."""
    from . import layouts, quadview
    screen = window.screen
    spec = layouts.spec_of(screen)
    on = [n for n in COLUMNS if roles.areas(screen, n)]
    four = len(quadview.views(screen)) > 1
    if four and not spec["editors"]:
        yield from quadview.renew_steps(window)
        return
    if four:
        yield from quadview.expand_steps(window, _persp(screen))
    yield from remove_stack(window)
    yield from add_stack(window, spec, "MATERIALS" in on, "ASSETS" in on)
    if not intact(screen):
        yield from steps(window, materials="MATERIALS" in on, assets="ASSETS" in on)
    if four:
        yield from quadview.split_steps(window)
    for a in screen.areas:
        a.tag_redraw()


def _persp(screen):
    """The Perspective one of the four views."""
    from . import quadview
    vs = quadview.views(screen)
    return next((a for a in vs if quadview.corner_of(a, screen) == "PERSP"), vs[0])


def dock_steps(window, on):
    """Open the Timeline above the strip, or fold it away, in whatever layout is shown."""
    from . import layouts, quadview, render_settings
    screen, ws = window.screen, window.workspace
    spec = layouts.spec_of(screen)
    cols = {n: bool(roles.areas(screen, n)) for n in COLUMNS}
    render_settings.show_view(screen)
    from . import viewer
    yield from viewer.leave_steps(window)
    four = len(quadview.views(screen)) > 1
    if four:
        yield from quadview.expand_steps(window, _persp(screen))
    ws[layouts.DOCK] = bool(on)
    spec = layouts.spec_of(screen)
    if stacked(screen):                                    # the Node Editor makes way for the Timeline, and comes back
        yield from remove_stack(window)
    for n in COLUMNS:
        if spec["editors"] and roles.areas(screen, n):
            yield from remove_column(window, n)
    if spec["timeline"] and not roles.areas(screen, "TIMELINE"):
        yield from add_timeline(window)
    for a in [] if spec["timeline"] else roles.areas(screen, "TIMELINE"):
        yield from _into_view(window, a)
    if spec["editors"]:
        yield from add_stack(window, spec, cols["MATERIALS"], cols["ASSETS"])
    else:
        for n in ("ASSETS", "MATERIALS"):
            if cols[n]:
                yield from COLUMNS[n][0](window)
    if not intact(screen):
        yield from steps(window, materials=cols["MATERIALS"], assets=cols["ASSETS"])
    if four:
        yield from quadview.split_steps(window)
    for a in screen.areas:
        a.tag_redraw()


def drifted(screen, sizes):
    """Are the managers, the command bar or the timeline another size than the layout's own?"""
    def one(role):
        return next(iter(roles.areas(screen, role)), None)
    attr, palette = one("ATTRIBUTES"), one("PALETTE")
    if abs(attr.width - px(sizes.get("managers", MANAGERS_PX))) > 8 or abs(palette.height - EDGE - px(PALETTE_PX)) > 6:
        return True
    whole = sum(one(r).height for r in ("OBJECTS", "OM_HEAD", "OM_BAR", "ATTRIBUTES"))
    if abs(attr.height / max(1, whole) - sizes.get("attributes", ATTRIBUTES)) > 0.02:
        return True
    return any(abs(a.height - px(TIMELINE_PX)) > 8 for a in roles.areas(screen, "TIMELINE"))


def switch_steps(window, name):
    """Bring a layout's saved arrangement up. What both layouts share stays where it is."""
    from . import layouts, quadview, render_settings
    screen, ws = window.screen, window.workspace
    old, new = layouts.spec_of(screen), layouts.spec(name)
    render_settings.show_view(screen)                     # Render Settings in the viewport's place: viewport back first
    from . import viewer
    yield from viewer.leave_steps(window)
    whole = intact(screen) and not drifted(screen, new["sizes"])
    layouts.set_current(ws, name)
    views = quadview.views(screen)
    if whole and len(views) > 1:                           # four views: back to the Perspective one
        yield from quadview.expand_steps(window, _persp(screen))
    if whole:
        moved = (old["timeline"], old["editors"]) != (new["timeline"], new["editors"]) or (bool(new["editors"]) and (
            old["sizes"] != new["sizes"] or any(bool(roles.areas(screen, n)) != new[n.lower()] for n in COLUMNS)))
        if moved:
            yield from remove_stack(window)
        for n in COLUMNS:
            if roles.areas(screen, n) and (not new[n.lower()] or old["sizes"].get(n.lower()) != new["sizes"].get(n.lower())):
                yield from remove_column(window, n)
        if moved:
            if old["timeline"] and not new["timeline"]:
                for a in roles.areas(screen, "TIMELINE"):
                    yield from _into_view(window, a)
            elif new["timeline"] and not old["timeline"]:
                yield from add_timeline(window)
            if new["editors"]:
                yield from add_stack(window, new, new["materials"], new["assets"])
        for n in ("ASSETS", "MATERIALS"):
            if new[n.lower()] and not roles.areas(screen, n):
                yield from COLUMNS[n][0](window)
    if not whole or not intact(screen) or len(quadview.views(screen)) > 1:
        yield from steps(window, materials=new["materials"], assets=new["assets"])
    from . import tabmode
    tabmode.switched(window, old["base"], new["base"])
    for a in screen.areas:
        a.tag_redraw()


def column_steps(window, name, on):
    """Show or hide one optional column, leaving every other area where it is."""
    screen = window.screen
    from . import layouts, quadview
    add = COLUMNS[name][0]
    from . import viewer
    again = viewer.docked(window)
    yield from viewer.leave_steps(window)
    spec = layouts.spec_of(screen)
    four = len(quadview.views(screen)) > 1
    if four:                                               # beside all four views, not inside one of them
        yield from quadview.expand_steps(window, _persp(screen))
    if name == "MATERIALS" and spec["editors"] and roles.areas(screen, "MODES"):  # beside the editors too: they are put in again after it
        want = {n: bool(roles.areas(screen, n)) for n in COLUMNS}
        want[name] = on
        yield from remove_stack(window)
        yield from add_stack(window, spec, want["MATERIALS"], want["ASSETS"])
    elif on:
        yield from (add(window, own_create=not four) if name == "MATERIALS" else add(window))
    else:                                                  # with four views their create column stays as it is
        yield from remove_column(window, name, fold=not four)
    if not intact(screen):                                 # the change did not land as planned: build it all
        yield from steps(window, materials=bool(roles.areas(screen, "MATERIALS")) if name != "MATERIALS" else on,
                         assets=bool(roles.areas(screen, "ASSETS")) if name != "ASSETS" else on)
    if four:
        yield from quadview.split_steps(window)
    if again:                                              # the Render Viewer was in the viewport's place: again beside it
        yield from viewer.dock_steps(window)
    for a in screen.areas:
        a.tag_redraw()


def steps(window, materials=False, assets=False, spec=None):
    screen = window.screen
    from . import layouts, render_settings
    spec = spec or layouts.spec_of(screen)
    sizes = spec["sizes"]
    render_settings.show_view(screen)                     # Render Settings in the viewport's place: viewport back first
    from . import viewer
    yield from viewer.leave_steps(window)
    # 1. everything back into one viewport
    for _ in range(40):
        extra = [a for a in screen.areas if a.type != "VIEW_3D"] + \
                [a for a in screen.areas if a.type == "VIEW_3D" and a != biggest_view(screen)]
        if not extra:
            break
        with _ov(window, extra[0]):
            bpy.ops.screen.area_close()
        yield
    view = biggest_view(screen)
    # 2. strips at exact sizes, full-width ones first
    tabs = yield from split(window, view, "HORIZONTAL", px(DOC_TABS_PX) + EDGE, "TOP")
    yield from make_role(window, tabs, "DOC_TABS")
    managers = yield from split(window, biggest_view(screen), "VERTICAL", px(sizes.get("managers", MANAGERS_PX)) + EDGE, "RIGHT")
    yield from make_role(window, managers, "OBJECTS")
    palette = yield from split(window, biggest_view(screen), "HORIZONTAL", px(PALETTE_PX) + EDGE, "TOP")
    yield from make_role(window, palette, "PALETTE")
    # the create column is drawn in the viewport's own toolbar strip (bars.BLENDA4D_PT_view_tools), moved to the
    # viewport's right edge: the strip keeps its width when the window is resized; a separate area would stretch
    if spec["timeline"]:
        yield from add_timeline(window)
    if spec["editors"]:
        yield from add_stack(window, spec, materials, assets)
        materials = assets = False                         # in already, beside the editors
    if assets:
        yield from add_assets(window)
    if materials:
        yield from add_materials(window)
    attributes = yield from split(window, managers, "HORIZONTAL", round(managers.height * min(0.85, max(0.15, sizes.get("attributes", ATTRIBUTES)))), "BOTTOM")
    yield from make_role(window, attributes, "ATTRIBUTES")
    objs = sorted(roles.areas(screen, "OBJECTS"), key=lambda a: a.y)
    if len(objs) > 1:                                      # the split can hand back the other half
        yield from make_role(window, objs[0], "ATTRIBUTES")
    objs = sorted(roles.areas(screen, "OBJECTS"), key=lambda a: a.y)
    if objs:                                               # the Object Manager's bottom strip: its Size slider
        om_bar = yield from split(window, objs[-1], "HORIZONTAL", px(MM_BAR_PX) + EDGE, "BOTTOM")
        yield from make_role(window, om_bar, "OM_BAR")
        objs = sorted(roles.areas(screen, "OBJECTS") + roles.areas(screen, "OM_BAR"), key=lambda a: a.y)
        if len(roles.areas(screen, "OBJECTS")) == 2:       # the split handed back the other half
            yield from make_role(window, min(roles.areas(screen, "OBJECTS"), key=lambda a: a.y), "OM_BAR")
    objs = roles.areas(screen, "OBJECTS")
    if objs:                                               # and its top strip: title, menus, search, tool row
        head = yield from split(window, objs[0], "HORIZONTAL", px(OM_HEAD_PX) + EDGE, "TOP")
        yield from make_role(window, head, "OM_HEAD")
        if len(roles.areas(screen, "OBJECTS")) == 2:       # the split handed back the other half
            yield from make_role(window, max(roles.areas(screen, "OBJECTS"), key=lambda a: a.y), "OM_HEAD")
    # 3. the viewport and timeline lose Blender's own chrome; the toolbar strip moves to the viewport's right edge
    for a in screen.areas:
        if a.type == "VIEW_3D":
            hidden = not a.spaces.active.show_region_toolbar
            dress_view(a)
            tools = _region(a, "TOOLS")
            if tools is not None and tools.alignment != "RIGHT":
                if hidden:
                    yield                                  # the strip, kept hidden while building, is laid out again first
                try:
                    with _ov(window, a, "TOOLS"):
                        bpy.ops.screen.region_flip()
                except RuntimeError as ex:
                    print("Blenda 4D: could not move the toolbar strip", ex)
                yield
            if tools is not None:                          # start the strip's view fresh after the move, then zoom
                try:                                       # it so its buttons are as big as the tools column's
                    with _ov(window, a, "TOOLS"):
                        bpy.ops.view2d.reset()
                        for _ in range(STRIP_ZOOM):
                            bpy.ops.view2d.zoom_in()
                except RuntimeError:
                    pass
                yield
    for a in screen.areas:
        a.tag_redraw()


def hush(screen):
    """Blender's own viewport chrome off at once, before any build step runs, so a slow machine never shows it: the
    navigation gizmo, the view name and statistics, and the toolbar strip until it has been moved to the right."""
    for a in screen.areas:
        if a.type != "VIEW_3D" or not len(a.spaces):
            continue
        v3d = a.spaces.active
        try:
            v3d.show_gizmo_navigate = False
            v3d.overlay.show_text = False
            v3d.overlay.show_stats = False
            tools = _region(a, "TOOLS")
            if tools is not None and tools.alignment != "RIGHT" and v3d.show_region_toolbar:
                v3d.show_region_toolbar = False
        except (AttributeError, ReferenceError):
            pass


def dress_view(area):
    v3d = area.spaces.active
    # four views, or editors under the viewport: the create column is one separate column beside them, not a strip
    apart = sum(a.type == "VIEW_3D" for a in area.id_data.areas) > 1 or bool(roles.areas(area.id_data, "CREATE"))
    for attr, want in (("show_region_ui", False), ("show_region_toolbar", not apart), ("show_region_header", True),
                       ("show_region_tool_header", not roles.areas(area.id_data, "VIEW_TABS")), ("show_region_hud", False),
                       ("show_region_asset_shelf", False)):
        try:
            if getattr(v3d, attr) != want:
                setattr(v3d, attr, want)
        except AttributeError:                             # the brush shelf cannot be switched where there is none
            pass
    v3d.show_gizmo_navigate = False
    v3d.lock_camera = True          # looking through a camera, orbit / pan / zoom move the camera itself
    v3d.overlay.show_text = False
    v3d.overlay.show_stats = False


def toggle(window, name, on):
    """Show or hide an optional column (Material Manager, Asset Browser): only that column changes."""
    run_steps(column_steps(window, name, on))


def drop_modes(window, materials, assets):
    """A layout saved before 0.1.22 has the tools column as an area: close just that, keep everything else."""
    for a in roles.areas(window.screen, "MODES"):
        with _ov(window, a):
            bpy.ops.screen.area_close()
        yield
    if not intact(window.screen):
        yield from steps(window, materials=materials, assets=assets)
    for a in window.screen.areas:
        a.tag_redraw()


def _renew_timeline(window, done, spec):
    for a in old_timelines(window.screen):
        yield from make_role(window, a, "TIMELINE")
    for a in old_timelines(window.screen):                # could not be changed: build it all
        rebuild(window, done, force=True, spec=spec)
        return
    rebuild(window, done, spec=spec)


def rebuild(window, done=None, force=False, spec=None):
    """Build the window's layout; a layout that is already all there is only tidied (no area moves)."""
    from . import viewer
    hush(window.screen)
    if viewer.docked(window):                              # saved with the Render Viewer in the viewport's place
        run_steps(viewer.leave_steps(window), lambda: rebuild(window, done, force, spec))
        return
    if not force and old_timelines(window.screen):        # a layout from before 0.1.23: the new strip in the old one's place
        run_steps(_renew_timeline(window, done, spec))
        return
    if not force and intact(window.screen):
        curtain(False)                                     # already all there: nothing to hide
        for a in window.screen.areas:
            if a.type == "VIEW_3D":
                dress_view(a)
        four = sum(a.type == "VIEW_3D" for a in window.screen.areas) > 1
        if four and not roles.areas(window.screen, "VIEW_TABS"):
            from . import quadview                         # four views saved by 0.1.22: a tab row in each, the column cut in two
            run_steps(quadview.renew_steps(window), done)
        elif done:
            done()
        return
    opts = dict(materials=bool(roles.areas(window.screen, "MATERIALS")), assets=bool(roles.areas(window.screen, "ASSETS")))
    curtain(True)                                          # a whole build: show only its result
    after = done

    def done():
        curtain(False)
        if after:
            after()
    if spec is not None:                                   # the startup layout, for a new workspace
        run_steps(steps(window, materials=spec["materials"], assets=spec["assets"], spec=spec), done)
    elif not force and roles.areas(window.screen, "MODES") and not roles.areas(window.screen, "TL_EDIT"):
        run_steps(drop_modes(window, **opts), done)
    else:
        run_steps(steps(window, **opts), done)
