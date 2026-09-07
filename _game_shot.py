"""Headless screenshot helper: runs a pygame game for N rendered frames with a
dummy video driver, saves the final frame to PNG, then exits hard. Used by
generate_thumbs.py and by dashboard_app.py to snapshot saved games.

    python _game_shot.py <script.py> <out.png> <frame_target>
"""
import os
import sys
import runpy
import threading
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame  # noqa: E402

script, out_png, frame_target = sys.argv[1], sys.argv[2], int(sys.argv[3])

_flip = pygame.display.flip
_update = pygame.display.update
_count = [0]


def _grab():
    _count[0] += 1
    if _count[0] >= frame_target:
        surf = pygame.display.get_surface()
        if surf is not None:
            try:
                pygame.image.save(surf, out_png)
            except Exception:
                pass
        os._exit(0)


def _flip2(*a, **k):
    _grab()
    return _flip(*a, **k)


def _update2(*a, **k):
    _grab()
    return _update(*a, **k)


pygame.display.flip = _flip2
pygame.display.update = _update2


def _deadline():
    time.sleep(30)
    os._exit(1)


threading.Thread(target=_deadline, daemon=True).start()

sys.argv = [script]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))  # so sibling imports work
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit:
    pass
os._exit(0)
