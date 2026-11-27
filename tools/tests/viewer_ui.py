# UI run of the Render Viewer during and after an animation render: Play while the render runs, the Image Editor and
# History when it has ended.
#   BLENDER_USER_CONFIG=<scratch> B4D_OUT=<scratch> Blender --factory-startup --window-geometry 100 60 1700 1000 \
#       --python tools/tests/viewer_ui.py
# Prints "B4D VIEWER ..." lines and "B4D VIEWER FAIL ..." for every check that does not hold. B4D_FRAMES: how many
# frames are rendered (60); the render has to last a few seconds for the checks made while it runs.
import os
import runpy

import bpy

os.environ["B4D_STEPS"] = "wait"
HERE = os.path.dirname(os.path.abspath(__file__))
ns = runpy.run_path(os.path.join(HERE, "..", "try_ui.py"))
PLAN, shot, OUT = ns["PLAN"], ns["shot"], ns["OUT"]
from blenda4d import viewer  # noqa: E402

S = viewer.S
seen = []


def win():
    return bpy.context.window_manager.windows[0]


def check(cond, what):
    print("B4D VIEWER", "ok" if cond else "FAIL", what, flush=True)


def watch():
    if S.rendering and S.play and S.seq:
        seen.append(S.index)
    return 0.0 if S.rendering else None


def render():
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.camera = next(o for o in sc.objects if o.type == "CAMERA")
    sc.render.resolution_x, sc.render.resolution_y, sc.eevee.taa_render_samples = 1920, 1080, 64
    sc.frame_start, sc.frame_end = 1, int(os.environ.get("B4D_FRAMES", "60"))
    sc.b4d_render.frame_range = "ALL"
    sc.render.filepath = os.path.join(OUT, "frames", "f_")
    sc.render.image_settings.file_format = "PNG"
    with bpy.context.temp_override(window=win()):
        print("B4D VIEWER render", bpy.ops.blenda4d.render("INVOKE_DEFAULT", animation=True), flush=True)


def during():
    print("B4D VIEWER during: frames", len(S.seq.frames), "done", viewer._last_done(), "range", S.lo, S.hi, flush=True)
    check(S.rendering and viewer._last_done() >= 2, "the render runs and has finished frames")
    check((S.lo, S.hi) == (1, bpy.context.scene.frame_end), "the range is the whole render from the start")
    bpy.app.timers.register(watch, first_interval=0.0)
    viewer.play(1)


def playing():
    print("B4D VIEWER playing: play", S.play, "live", S.live, "shown", seen[:6], "...", seen[-6:], flush=True)
    check(S.play == 1 and S.rendering, "Play pressed while the picture follows the render keeps playing")
    check(len(set(seen)) > 3, "different frames were shown")
    check(any(b < a for a, b in zip(seen, seen[1:])), "it went round to the start again (Cycle)")
    shot("viewer_playing")
    if S.play:
        viewer.play(1)


def wait_end():
    if S.rendering or bpy.app.is_job_running("RENDER"):
        PLAN.insert(ns["_i"][0] + 1, wait_end)


def after():
    sp = viewer._space()
    check(viewer.editor().type == "IMAGE_EDITOR" and sp is not None and sp.image is not None, "after the render the Image Editor shows the last frame")
    check(len(S.seq.frames) == bpy.context.scene.frame_end, "every frame is in History")
    viewer.play(1)


def after_play():
    check(S.play == 1, "Play after the render plays")
    viewer.play(1)
    shot("viewer_after")


W = [lambda: None] * 3
done = PLAN.pop()
PLAN += [render] + [lambda: None] * 10 + [during] + [lambda: None] * 8 + [playing, wait_end] + W + [after] + W + [after_play, done]
