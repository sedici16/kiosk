"""Screen helper for the cabinet Pi.

The Pi's dispmanx driver ignores the size passed to set_mode and always hands
back a full-screen (e.g. 1366x768) surface. That makes a plain game render into
the top-left corner, and a full-surface flip() is slow on a GPU-less Pi.

`setup()` gives the game a surface of exactly the size it asked for; `flip()`
blits it centred on the real display and only pushes that region to the screen.
On a normal desktop both are pass-throughs.
"""
import pygame

_S = {"disp": None, "canvas": None, "rect": None, "off": (0, 0)}


def setup(w, h, caption=""):
    disp = pygame.display.set_mode((w, h))
    if caption:
        pygame.display.set_caption(caption)
    dw, dh = disp.get_size()
    if (dw, dh) == (w, h):
        _S.update(disp=disp, canvas=disp, rect=None, off=(0, 0))
        return disp
    canvas = pygame.Surface((w, h))
    off = ((dw - w) // 2, (dh - h) // 2)
    _S.update(disp=disp, canvas=canvas, rect=pygame.Rect(off, (w, h)), off=off)
    disp.fill((0, 0, 0))          # clear the borders once
    pygame.display.flip()
    return canvas


def canvas():
    return _S["canvas"]


def flip():
    """Use in place of pygame.display.flip()/update()."""
    if _S["rect"] is None:
        pygame.display.flip()
    else:
        _S["disp"].blit(_S["canvas"], _S["off"])
        pygame.display.update(_S["rect"])
