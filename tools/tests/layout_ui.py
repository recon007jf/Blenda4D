# UI run of the layout builder: every layout tab in turn, then back and forth between some of them. For each state it
# prints how many redraws the build waited for and where every area ended up, so two checkouts can be compared line by
# line; a layout has to come up the same whichever tab it is reached from.
#   BLENDER_USER_CONFIG=<scratch> B4D_OUT=<scratch> Blender --factory-startup --window-geometry 100 60 1700 1000 \
#       --python tools/tests/layout_ui.py
# Prints "B4D LAYOUT ..." lines and "B4D LAYOUT FAIL ..." for every check that does not hold.
import os
import runpy

import bpy

os.environ["B4D_STEPS"] = "wait"
HERE = os.path.dirname(os.path.abspath(__file__))
ns = runpy.run_path(os.path.join(HERE, "..", "try_ui.py"))
PLAN = ns["PLAN"]
from blenda4d import build, layouts, roles  # noqa: E402

waits = [0]
first = {}
_run = build.run_steps


def run_steps(gen, done=None):
    def counted():
        for _ in gen:
            waits[0] += 1
            yield
    return _run(counted(), done)


build.run_steps = run_steps


def win():
    return bpy.context.window_manager.windows[0]


def check(cond, what):
    print("B4D LAYOUT", "ok" if cond else "FAIL", what, flush=True)


def report(name, again=True):
    def go():
        areas = sorted((roles.role(a) or a.type, a.x, a.y, a.width, a.height) for a in win().screen.areas)
        print(f"B4D LAYOUT {name}: {waits[0]} redraws waited for, areas {areas}", flush=True)
        check(not build.busy() and build.intact(win().screen), f"{name}: built and whole")
        if again:                                          # the layout built at start is not compared: its Timeline strip
            check(first.setdefault(name, areas) == areas, f"{name}: the same areas as the first time")   # is a few pixels higher
    return go


def use(name):
    def go():
        waits[0] = 0
        with bpy.context.temp_override(window=win(), screen=win().screen):
            bpy.ops.blenda4d.layout_use(name=name)
    return go


W = [lambda: None] * 5
names = layouts.names()
done = PLAN.pop()
PLAN += [report(names[0], again=False)]
for name in names[1:] + [names[0], "Shading", "Animation", "UV Editing", "Geometry Nodes", names[0]]:
    PLAN += [use(name)] + W + [report(name)]
PLAN += [done]
