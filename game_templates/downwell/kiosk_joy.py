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
    return button_held()


def button_held(*which):
    """True while one of the given button ids is held (any button if none given).
    Use specific ids when 'any button' is too broad - e.g. a platformer where
    only A/B should jump, not Select/Start."""
    for j in _sticks:
        n = j.get_numbuttons()
        for b in (which or range(n)):
            try:
                if b < n and j.get_button(b):
                    return True
            except pygame.error:
                pass
    return False


def is_action(event):
    """True for a joystick button press event - the equivalent of the game's
    main one-shot key (jump / shoot / start / restart)."""
    return event.type == pygame.JOYBUTTONDOWN


# ---- exit gesture --------------------------------------------------------
# No keyboard on the cabinet, so every game needs a stick way out. The games
# only ever use ONE button at a time, so "hold any two buttons together" is a
# safe, encoder-independent exit - works whatever the pad's button numbering.
QUIT_HOLD_FRAMES = 36           # ~0.6 s at 60 fps - deliberate, not a mash
_quit_held = [0]


def _combo_down():
    for j in _sticks:
        try:
            if sum(1 for b in range(j.get_numbuttons()) if j.get_button(b)) >= 2:
                return True
        except pygame.error:
            pass
    return False


def quit_progress():
    """0.0 while the exit gesture isn't held, ramping to 1.0 as it completes -
    for on-screen feedback."""
    return min(1.0, _quit_held[0] / float(QUIT_HOLD_FRAMES))


def wants_quit():
    """Call once per frame. True once any two joystick buttons have been held
    together ~0.4 s - treat it like pressing ESC."""
    _quit_held[0] = _quit_held[0] + 1 if _combo_down() else 0
    return _quit_held[0] >= QUIT_HOLD_FRAMES


_hint_font = [None]


def blit_exit_hint(surface, area=None):
    """Bottom-right 'hold 2 buttons to exit' note, with a fill bar that grows
    while the gesture is held. Safe every frame; no-op with no joystick.
    `area` = (x, y, w, h) to place the note inside that box instead of the whole
    surface - use it when only part of the surface is shown/updated."""
    if not _sticks:
        return
    if _hint_font[0] is None:
        _hint_font[0] = pygame.font.Font(None, 22)
    img = _hint_font[0].render("2 tasti insieme  =  esci", True, (235, 235, 235))
    pad = 6
    bw, bh = img.get_width() + pad * 2, img.get_height() + pad * 2
    if area:
        ax, ay, aw, ah = area
    else:
        ax, ay = 0, 0
        aw, ah = surface.get_size()
    x, y = ax + aw - bw - 4, ay + ah - bh - 4
    bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 140))
    prog = quit_progress()
    if prog > 0:
        pygame.draw.rect(bg, (90, 200, 120, 200), (0, bh - 4, int(bw * prog), 4))
    surface.blit(bg, (x, y))
    surface.blit(img, (x + pad, y + pad))
