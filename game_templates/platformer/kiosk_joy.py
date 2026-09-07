"""Shared arcade-stick / gamepad support for the kiosk games.

Drop-in and additive: the keyboard keeps working exactly as before. This just
lets a plugged-in joystick (e.g. the cabinet's arcade sticks) drive the same
actions. Safe to import and call with no joystick attached - every function is
a no-op then.

Typical use in a game:

    import kiosk_joy
    ...
    pygame.init()
    kiosk_joy.init()
    ...
    # continuous movement, alongside pygame.key.get_pressed():
    if keys[pygame.K_LEFT] or kiosk_joy.left():  ...
    # one-shot presses, alongside KEYDOWN handling:
    elif kiosk_joy.is_action(event):  ...        # jump / shoot / start / restart
    # held fire button, alongside a get_pressed() K_SPACE check:
    if keys[pygame.K_SPACE] or kiosk_joy.action_held():  ...
"""
import pygame

_sticks = []
DEADZONE = 0.5


def init():
    """Call once, after pygame.init(). Harmless when no joystick is present."""
    try:
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            _sticks.append(j)
    except pygame.error:
        pass


def _axis(j, n):
    try:
        return j.get_axis(n)
    except (pygame.error, IndexError):
        return 0.0


def x():
    """-1 = left, 1 = right, 0 = centred. Reads any stick's D-pad hat or X axis."""
    v = 0
    for j in _sticks:
        for h in range(j.get_numhats()):
            hx, _ = j.get_hat(h)
            if hx:
                v = hx
        a = _axis(j, 0)
        if a <= -DEADZONE:
            v = -1
        elif a >= DEADZONE:
            v = 1
    return v


def y():
    """-1 = up, 1 = down, 0 = centred (screen coordinates: up is negative)."""
    v = 0
    for j in _sticks:
        for h in range(j.get_numhats()):
            _, hy = j.get_hat(h)
            if hy:
                v = -hy                       # hat up is +1 -> screen up is -1
        a = _axis(j, 1)
        if a <= -DEADZONE:
            v = -1
        elif a >= DEADZONE:
            v = 1
    return v


def left():
    return x() < 0


def right():
    return x() > 0


def up():
    return y() < 0


def down():
    return y() > 0


def action_held():
    """True while any joystick button is held - use as an extra 'fire' key."""
    for j in _sticks:
        for b in range(j.get_numbuttons()):
            try:
                if j.get_button(b):
                    return True
            except pygame.error:
                pass
    return False


def is_action(event):
    """True for a joystick button press event - the equivalent of the game's
    main one-shot key (jump / shoot / start / restart)."""
    return event.type == pygame.JOYBUTTONDOWN


# ---- exit combo -----------------------------------------------------------
# On the cabinet there is no keyboard, so every game needs a stick way out.
# DragonRise pads (per RetroPie's config): button 1 = Select, 2 = Start,
# 6/7 = shoulders. Accept Select+Start (the RetroPie-standard gesture) or both
# shoulders, held briefly so a stray double-press during play can't quit.
_QUIT_COMBOS = ((1, 2), (6, 7))
QUIT_HOLD_FRAMES = 30           # ~0.5 s at 60 fps
_quit_held = [0]


def _combo_down():
    for j in _sticks:
        n = j.get_numbuttons()
        for combo in _QUIT_COMBOS:
            try:
                if all(b < n and j.get_button(b) for b in combo):
                    return True
            except pygame.error:
                pass
    return False


def wants_quit():
    """Call once per frame. True once the exit combo (Select+Start, or both
    shoulder buttons) has been held ~half a second - treat it like ESC."""
    _quit_held[0] = _quit_held[0] + 1 if _combo_down() else 0
    return _quit_held[0] >= QUIT_HOLD_FRAMES


_hint_font = [None]


def blit_exit_hint(surface):
    """Small bottom-right 'hold Select+Start to exit' note. Safe to call every
    frame; no-op if there is no joystick attached."""
    if not _sticks:
        return
    if _hint_font[0] is None:
        _hint_font[0] = pygame.font.Font(None, 22)
    img = _hint_font[0].render("Select + Start  =  esci", True, (235, 235, 235))
    bg = pygame.Surface((img.get_width() + 10, img.get_height() + 6), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 130))
    w, h = surface.get_size()
    surface.blit(bg, (w - bg.get_width() - 4, h - bg.get_height() - 4))
    surface.blit(img, (w - img.get_width() - 9, h - img.get_height() - 7))
