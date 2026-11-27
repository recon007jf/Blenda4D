# SPDX-License-Identifier: GPL-3.0-or-later
"""Blenda 4D's motion-design keys, offered as a key map in Preferences > Keymap.

The key map itself is a key configuration preset (keymap_preset/presets/keyconfig/Blenda_4D.py), the same kind of
file as Blender's own "Blender" and "Industry Compatible" presets. While Blenda mode is on, its folder is a preset
folder, so "Blenda 4D" is listed in Preferences > Keymap next to Blender's presets.

Turning Blenda mode on also switches to the Blenda 4D key map (as the layout's keys belong to the layout); the
Blender switch puts back the key map that was chosen before. Choosing another key map in Preferences while Blenda
mode is on is respected: the Blender switch then leaves that choice alone. With "Use the Blenda 4D Key Map" off in
the add-on's preferences, the key map is never switched."""
import json
import os

import bpy

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keymap_preset")
NAME = "Blenda_4D"                          # file name = key configuration name; listed as "Blenda 4D"
PRESET = os.path.join(ROOT, "presets", "keyconfig", NAME + ".py")
DEFAULT = "Blender"
_state = {"path": False}


def _memory_file():
    folder = bpy.utils.user_resource("CONFIG", path="blenda4d", create=True)
    return os.path.join(folder, "keymap.json")


def _read_previous():
    try:
        with open(_memory_file()) as f:
            return json.load(f).get("previous") or DEFAULT
    except (OSError, ValueError):
        return DEFAULT


def _write_previous(name):
    try:
        with open(_memory_file(), "w") as f:
            json.dump({"previous": name}, f)
    except OSError:
        pass


def _keyconfigs():
    wm = bpy.context.window_manager
    return wm.keyconfigs if wm is not None else None


def active_name():
    kcs = _keyconfigs()
    return kcs.active.name if kcs is not None and kcs.active is not None else ""


def activate(name):
    """Make the named key configuration the active one, loading its preset file if it is not loaded yet."""
    kcs = _keyconfigs()
    if kcs is None:
        return False
    path = bpy.utils.preset_find(name, "keyconfig")
    if path and bpy.utils.keyconfig_set(path):
        return True
    kc = kcs.get(name)
    if kc is not None:
        kcs.active = kc
        return True
    return False


def _wanted():
    from . import settings
    try:
        return settings.get().keys
    except (KeyError, AttributeError):
        return True


def _use_blenda_keys():
    current = active_name()
    if current == NAME or not _wanted():
        return
    # A key map other than ours is in use: remember it for the way back. (If Preferences still name ours from the
    # last session, Blender could not load it at start-up; the remembered one from then still holds.)
    if bpy.context.preferences.keymap.active_keyconfig != NAME and current:
        _write_previous(current)
    activate(NAME)


def choose_at_start():
    """With the add-on on, Blenda 4D is the key map from the start: add-ons register after Blender has loaded the saved
    key map and before it builds the splash, so switching here makes the splash's Keymap show Blenda 4D. The key map
    in use until now is remembered for the Blender switch."""
    if _keyconfigs() is not None:
        _use_blenda_keys()


def _restore_keys():
    if active_name() != NAME:
        return                               # the person picked another key map themselves: leave it
    prev = _read_previous()
    if prev == NAME or not activate(prev):
        activate(DEFAULT)


def add_preset_path():
    """Preferences > Keymap lists Blenda 4D for as long as the add-on is installed, in either mode."""
    if not _state["path"]:
        bpy.utils.register_preset_path(ROOT)
        _state["path"] = True


def remove_preset_path():
    if _state["path"]:
        bpy.utils.unregister_preset_path(ROOT)
        _state["path"] = False


def register():
    add_preset_path()
    if _keyconfigs() is not None:
        _use_blenda_keys()


def unregister():
    kcs = _keyconfigs()
    # On quit Blender frees its key configurations before add-ons are switched off: touch nothing then.
    quitting = kcs is None or not bpy.context.window_manager.windows and not bpy.app.background
    if not quitting:
        _restore_keys()
        kc = kcs.get(NAME)
        if kc is not None and kcs.active != kc:
            kcs.remove(kc)
