#import pygame and os
import pygame
import os
import random
import kiosk_joy
# Load assets relative to this file, regardless of the launcher's working dir.
os.chdir(os.path.dirname(os.path.abspath(__file__)))
pygame.init()
kiosk_joy.init()


# Define some colors
BLACK    = (   0,   0,   0)
WHITE    = ( 255, 255, 255)
LIGHTBLUE    = (   133, 214,   255)

# retro 1-bit dungeon palette: everything is drawn in just these two colours
DARK = ( 13,  13,  18)
LITE = (200, 192, 170)

#define dimensions
WIN_WIDTH = 800
WIN_HEIGHT = 550
HALF_WIDTH = int(WIN_WIDTH / 2)
HALF_HEIGHT = int(WIN_HEIGHT / 2)

#set window size
size = (WIN_WIDTH, WIN_HEIGHT)

# which level file to play
LEVEL_FILE = "designlevel.txt"

# lives + energy: touching fire drains energy instead of killing instantly;
# at 0 energy you lose a life and respawn; at 0 lives it's game over.
START_LIVES = 3
MAX_ENERGY = 100
ENERGY_DRAIN = 1.5          # energy lost per frame while touching a hazard
RESPAWN_INVULN = 90         # frames of invulnerability after a respawn (~1.5s)

# wandering monster (a grumpy cup) that drifts across the screen right -> left
MONSTER_SPEED = 4
MONSTER_MIN_GAP = 180       # min frames between monsters (~3s)
MONSTER_MAX_GAP = 480       # max frames between monsters (~8s)

#create camera class
class Camera(object):
    def __init__(self, camera_func, width, height):
        self.camera_func = camera_func
        self.state = pygame.Rect(0, 0, width, height)

    def apply(self, target):
        return target.rect.move(self.state.topleft)

    def update(self, target):
        self.state = self.camera_func(self.state, target.rect)

def complex_camera(camera, target_rect):
    l, t, _, _ = target_rect
    _, _, w, h = camera
    l, t, _, _ = -l+HALF_WIDTH, -t+HALF_HEIGHT, w, h

    l = min(0, l)
    l = max(-(camera.width-WIN_WIDTH), l)
    t = max(-(camera.height-WIN_HEIGHT), t)
    t = min(0, t)
    return pygame.Rect(l, t, w, h)

#build a small 1-bit "omino" silhouette facing right / left / up / down
def make_player_sprites():
    W, H = 26, 30

    def build(face):
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        # solid light silhouette
        pygame.draw.rect(s, LITE, (8, 2, 11, 12))    # head
        pygame.draw.rect(s, LITE, (7, 14, 13, 9))    # torso
        pygame.draw.rect(s, LITE, (8, 23, 4, 5))     # left leg
        pygame.draw.rect(s, LITE, (15, 23, 4, 5))    # right leg
        # dark cut-outs + light arm, per direction
        if face == "right":
            pygame.draw.rect(s, DARK, (15, 8, 2, 3))   # eye
            pygame.draw.rect(s, DARK, (8, 5, 2, 4))    # nape notch
            pygame.draw.rect(s, LITE, (20, 15, 5, 3))  # arm forward
        elif face == "left":
            pygame.draw.rect(s, DARK, (9, 8, 2, 3))
            pygame.draw.rect(s, DARK, (16, 5, 2, 4))
            pygame.draw.rect(s, LITE, (1, 15, 5, 3))
        elif face == "up":
            pygame.draw.rect(s, DARK, (11, 3, 4, 2))   # single top notch, no eyes
            pygame.draw.rect(s, LITE, (3, 15, 4, 3))
            pygame.draw.rect(s, LITE, (19, 15, 4, 3))
        else:  # down / idle
            pygame.draw.rect(s, DARK, (10, 8, 2, 3))
            pygame.draw.rect(s, DARK, (15, 8, 2, 3))
            pygame.draw.rect(s, DARK, (12, 12, 3, 2))  # mouth
        return s

    return {f: build(f) for f in ("right", "left", "up", "down", "idle")}


#pre-render the two dungeon-brick tile looks (buried block + walkable-top block)
_PLATFORM_TILES = None

def _build_platform_tiles():
    n = 25
    block = pygame.Surface((n, n))
    block.fill(DARK)
    pygame.draw.rect(block, LITE, (0, 0, n, n), 1)          # tile outline
    pygame.draw.line(block, LITE, (0, 12), (n - 1, 12))     # course divider
    pygame.draw.line(block, LITE, (12, 0), (12, 12))        # upper course seam
    pygame.draw.line(block, LITE, (6, 13), (6, n - 1))      # lower course seams (offset)
    pygame.draw.line(block, LITE, (18, 13), (18, n - 1))
    for (px, py) in ((4, 5), (17, 7), (9, 18), (20, 19)):   # chipped-stone speckle
        block.set_at((px, py), LITE)

    top_block = block.copy()
    pygame.draw.rect(top_block, LITE, (0, 0, n, 3))         # bright lip = you can stand here
    for bx in range(2, n, 6):
        top_block.set_at((bx, 5), LITE)
    return block, top_block

def platform_tiles():
    global _PLATFORM_TILES
    if _PLATFORM_TILES is None:
        _PLATFORM_TILES = _build_platform_tiles()
    return _PLATFORM_TILES


#the monster: a simple grumpy cup, drawn 1-bit like everything else
_MONSTER_SPRITE = None

def monster_sprite():
    global _MONSTER_SPRITE
    if _MONSTER_SPRITE is None:
        w, h = 24, 22
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, LITE, (3, 4, 13, 14))        # cup body
        pygame.draw.rect(s, LITE, (16, 7, 5, 9), 2)      # handle
        pygame.draw.rect(s, DARK, (5, 6, 9, 3))          # hollow rim
        pygame.draw.rect(s, DARK, (6, 11, 2, 2))         # angry eyes
        pygame.draw.rect(s, DARK, (11, 11, 2, 2))
        pygame.draw.line(s, DARK, (6, 15), (13, 15))     # frown
        pygame.draw.rect(s, LITE, (4, 18, 3, 3))         # little feet
        pygame.draw.rect(s, LITE, (12, 18, 3, 3))
        _MONSTER_SPRITE = s
    return _MONSTER_SPRITE


#pre-render a dark dungeon back-wall (dithered light bricks on near-black)
def make_background():
    bgs = pygame.Surface((WIN_WIDTH, WIN_HEIGHT))
    bgs.fill(DARK)
    bw, bh = 72, 36
    for row, yy in enumerate(range(0, WIN_HEIGHT + bh, bh)):
        off = 0 if row % 2 == 0 else bw // 2
        for x0 in range(-bw, WIN_WIDTH + bw, bw):
            x = x0 + off
            for dx in range(0, bw, 4):                      # dotted -> reads as dim grey
                if 0 <= x + dx < WIN_WIDTH and yy < WIN_HEIGHT:
                    bgs.set_at((x + dx, yy), LITE)
            for dy in range(0, bh, 4):
                if 0 <= x < WIN_WIDTH and yy + dy < WIN_HEIGHT:
                    bgs.set_at((x, yy + dy), LITE)
    return bgs


#create thing class
class Thing(pygame.sprite.Sprite):
    def __init__(self):
        pygame.sprite.Sprite.__init__(self)

#create character class
class Character(Thing):
    def __init__(self, x, y):

        Thing.__init__(self)

        self.xspeed = 0
        self.yspeed = 0

        self.onGround = False
        self.sprites = make_player_sprites()
        self.facing = "down"
        self.image = self.sprites[self.facing]
        self.rect = pygame.Rect(x, y, 25, 25)

    def update(self, up, left, right, platforms):
        if up:

            if self.onGround: self.yspeed -= 9


        if left:
            self.xspeed = -8

        if right:
            self.xspeed = 8

        if not self.onGround:

            self.yspeed += 0.3

            if self.yspeed > 100: self.yspeed = 100

        if not(left or right):
            self.xspeed = 0


        self.rect.left += self.xspeed


        self.collide(self.xspeed, 0, platforms)


        self.rect.top += self.yspeed


        self.onGround = False;


        self.collide(0, self.yspeed, platforms)

        # face the way we're moving
        if up and self.yspeed < 0:
            self.facing = "up"
        elif left:
            self.facing = "left"
        elif right:
            self.facing = "right"
        elif self.yspeed > 2:
            self.facing = "down"
        self.image = self.sprites[self.facing]


    def collide(self, xspeed, yspeed, platforms):
        for p in platforms:
            if pygame.sprite.collide_rect(self, p):
                if xspeed > 0:
                    self.rect.right = p.rect.left
                if xspeed < 0:
                    self.rect.left = p.rect.right
                if yspeed > 0:
                    self.rect.bottom = p.rect.top
                    self.onGround = True
                    self.yspeed = 0
                if yspeed < 0:
                    self.rect.top = p.rect.bottom


class Platform(Thing):
    def __init__(self, x, y):

        Thing.__init__(self)

        self._dirt, self._grass = platform_tiles()
        self.image = self._dirt
        self.rect = pygame.Rect(x, y, 25, 25)

    def set_top(self, is_top):
        self.image = self._grass if is_top else self._dirt

    def update(self):
        pass


class coinSprite(Platform):
    def __init__(self, x, y):
        Platform.__init__(self, x, y)
        img = pygame.Surface((16, 16), pygame.SRCALPHA)
        pygame.draw.circle(img, LITE, (8, 8), 7, 2)
        pygame.draw.circle(img, LITE, (8, 8), 2)
        self.image = img
        self.rect = img.get_rect()
        self.rect.centerx = x
        self.rect.centery = y


class fireSprite(Platform):
    def __init__(self, x, y):
        Platform.__init__(self, x, y)
        img = pygame.Surface((25, 25), pygame.SRCALPHA)
        for bx in (1, 8, 15):
            pygame.draw.polygon(img, LITE, [(bx, 24), (bx + 4, 5), (bx + 8, 24)])
        self.image = img
        self.rect = img.get_rect()
        self.rect.centerx = x
        self.rect.centery = y

#wandering monster: crosses the screen right -> left, hurts on contact
class Monster(Thing):
    def __init__(self, x, y):
        Thing.__init__(self)
        self.image = monster_sprite()
        self.rect = self.image.get_rect(center=(x, y))

    def update(self):
        self.rect.x -= MONSTER_SPEED


#create win class
class winSprite(Platform):
    def __init__(self, x, y):
        Platform.__init__(self, x, y)
        img = pygame.Surface((26, 22), pygame.SRCALPHA)
        pygame.draw.polygon(img, LITE, [(2, 20), (2, 8), (8, 13), (13, 3), (18, 13), (24, 8), (24, 20)])
        self.image = img
        self.rect = img.get_rect()
        self.rect.centerx = x
        self.rect.centery = y


#def gameworld function, 'level' parameter being which gameworld file is opened.
#returns "win", "lose" or "restart".
def gameWorld(level):

    timer = pygame.time.Clock()

    up = left = right = False

    background = make_background()

    allSprites = pygame.sprite.Group()
    character = Character(25, 25)

    platforms = []
    coins = []
    fires = []
    wins = []

    x = y = 0
    designlevel = []

    file = open(level,"r")
    world = file.readlines()
    for line in world:
        designlevel.append(line[:-1])

    # build the level
    for row in designlevel:
        for i in row:
            if i == "P":
                p = Platform(x, y)
                platforms.append(p)
                allSprites.add(p)
            if i == "C":
                c = coinSprite(x, y)
                coins.append(c)
                allSprites.add(c)
            if i == "F":
                f = fireSprite(x, y)
                fires.append(f)
                allSprites.add(f)
            x += 25
        y += 25
        x = 0

    # give a grassy top to any platform tile with open air above it
    plat_at = {(p.rect.x, p.rect.y) for p in platforms}
    for p in platforms:
        p.set_top((p.rect.x, p.rect.y - 25) not in plat_at)

    total_level_width  = len(designlevel[0])*25
    total_level_height = len(designlevel)*25

    camera = Camera(complex_camera, total_level_width, total_level_height)
    allSprites.add(character)

    global score
    score = 0
    totalcoins = 0

    lives = START_LIVES
    energy = MAX_ENERGY
    invuln = 0
    hud_font = pygame.font.Font(None, 30)
    start_pos = (25, 25)

    monsters = []
    monster_timer = random.randint(MONSTER_MIN_GAP, MONSTER_MAX_GAP)

    pygame.mixer.init()
    coin = pygame.mixer.Sound("coinsound.wav")
    jump = pygame.mixer.Sound("jumpsound.wav")
    pygame.mixer.music.load("amazinbgmusic.mp3")
    pygame.mixer.music.play(-1,0)

    result = None
    done = False
    while not done:

        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                pygame.quit()
                quit()

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE or event.key == pygame.K_UP:
                    up = True
                    pygame.mixer.Sound.play(jump)
                if event.key == pygame.K_LEFT:
                    left = True
                if event.key == pygame.K_RIGHT:
                    right = True
                if event.key == pygame.K_r:
                    result = "restart"
                    done = True

            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_SPACE or event.key == pygame.K_UP:
                    up = False
                if event.key == pygame.K_RIGHT:
                    right = False
                if event.key == pygame.K_LEFT:
                    left = False

        # draw background
        screen.blit(background, (0, 0))

        #when character hits coin, collect points
        for c in coins:
            if pygame.sprite.collide_rect(character, c):
                pygame.mixer.Sound.play(coin)
                c.rect.centerx = -100
                c.rect.centery = -100
                score += 4
                totalcoins += 1
                if totalcoins == 25:
                    w = winSprite(2450, 250)
                    wins.append(w)
                    allSprites.add(w)

        #spawn + move the wandering monsters (right -> left across the view)
        monster_timer -= 1
        if monster_timer <= 0:
            mx = character.rect.centerx + HALF_WIDTH + 30
            my = character.rect.centery + random.randint(-150, 40)
            m = Monster(mx, my)
            monsters.append(m)
            allSprites.add(m)
            monster_timer = random.randint(MONSTER_MIN_GAP, MONSTER_MAX_GAP)
        for m in monsters[:]:
            m.update()
            if m.rect.right < character.rect.centerx - HALF_WIDTH - 40:
                monsters.remove(m)
                allSprites.remove(m)

        #touching a hazard (fire/spikes or a monster) drains the energy meter
        lost_life = False
        touching_hazard = False
        for f in fires:
            if pygame.sprite.collide_rect(character, f):
                touching_hazard = True
        for m in monsters:
            if pygame.sprite.collide_rect(character, m):
                touching_hazard = True

        if invuln > 0:
            invuln -= 1
        elif touching_hazard:
            energy -= ENERGY_DRAIN
            if energy <= 0:
                lost_life = True

        #character fell off the bottom of the level -> costs a life
        if character.rect.top > total_level_height + 200:
            lost_life = True

        if lost_life:
            lives -= 1
            energy = MAX_ENERGY
            invuln = RESPAWN_INVULN
            character.rect.topleft = start_pos
            character.xspeed = 0
            character.yspeed = 0
            if lives <= 0:
                result = "lose"
                done = True

        #when character hits crown, user wins
        for w in wins:
            if pygame.sprite.collide_rect(character, w):
                result = "win"
                done = True

        # fold in the arcade stick: held direction + any button = jump
        j_up = kiosk_joy.up() or kiosk_joy.action_held()
        eff_up, eff_left, eff_right = up or j_up, left or kiosk_joy.left(), right or kiosk_joy.right()

        camera.update(character)
        character.update(eff_up, eff_left, eff_right, platforms)

        for e in allSprites:
            #flicker the character while invulnerable after a respawn
            if e is character and invuln > 0 and (invuln // 4) % 2 == 0:
                continue
            pos = camera.apply(e)
            if e is character:
                pos = pos.move(-1, -5)  # sprite is taller than the 25px hitbox
            screen.blit(e.image, pos)

        #HUD: lives + energy bar, fixed on screen (2-colour)
        screen.blit(hud_font.render("VITE " + str(max(lives, 0)), True, LITE), (12, 10))
        pygame.draw.rect(screen, DARK, (12, 38, 204, 16))
        pygame.draw.rect(screen, LITE, (12, 38, 204, 16), 1)
        ebar = max(0, int(energy / MAX_ENERGY * 200))
        pygame.draw.rect(screen, LITE, (14, 40, ebar, 12))

        pygame.display.update()
        timer.tick(60)

    pygame.mixer.music.stop()
    return result


#simple end screen: R restarts, ESC / window-close quits
def end_screen(result):
    big = pygame.font.Font(None, 80)
    small = pygame.font.Font(None, 34)
    msg = "HAI VINTO" if result == "win" else "HAI PERSO"

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                quit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    return
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    quit()
            if kiosk_joy.is_action(event):
                return

        screen.fill(DARK)
        t = big.render(msg, True, LITE)
        screen.blit(t, t.get_rect(center=(HALF_WIDTH, HALF_HEIGHT - 30)))
        h = small.render("R  RICOMINCIA    -    ESC  ESCI", True, LITE)
        screen.blit(h, h.get_rect(center=(HALF_WIDTH, HALF_HEIGHT + 35)))
        s = small.render("PUNTEGGIO " + str(score), True, LITE)
        screen.blit(s, s.get_rect(center=(HALF_WIDTH, HALF_HEIGHT + 75)))
        pygame.display.flip()


#Set screen name and creates window
screen = pygame.display.set_mode(size)
pygame.display.set_caption("Game of Crowns")

score = 0

#straight into the game; R restarts, end screen -> R restarts
if __name__ == "__main__":
    while True:
        outcome = gameWorld(LEVEL_FILE)
        if outcome == "restart":
            continue
        end_screen(outcome)
