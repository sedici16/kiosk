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
