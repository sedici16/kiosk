import os
import json
import random
import bisect
import platform as _platform
import pygame

import kiosk_joy
import kiosk_screen

# The kiosk cabinet is a Raspberry Pi 3 (1.2 GHz ARM) - run leaner there.
ON_PI = _platform.machine().lower().startswith(("arm", "aarch"))

# DOWNWELL_DATA_DIR lets a dashboard/session-manager point this same engine at a
# per-user working copy of assets/levels/overrides without duplicating the code.
DATA_DIR = os.environ.get("DOWNWELL_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(DATA_DIR, "downwell_assets")
TERRAIN_DIR = os.path.join(ASSET_DIR, "terrain")
SPRITE_DIR = os.path.join(ASSET_DIR, "sprites")
SOUND_DIR = os.path.join(ASSET_DIR, "sounds")
SOUND_ACTIONS = ["jump", "shoot", "hit", "gem", "kill", "gameover", "win"]
BASE_DIR = DATA_DIR
LEVEL_FILE = os.path.join(BASE_DIR, "downwell_level.json")
CHUNK_FILE_TEMPLATE = os.path.join(BASE_DIR, "downwell_chunk_{}.json")
CHUNKS_CONFIG_FILE = os.path.join(BASE_DIR, "downwell_chunks_config.json")
OVERRIDES_FILE = os.path.join(BASE_DIR, "overrides.json")
NUM_CHUNK_SLOTS = 4
DEFAULT_REPEAT_COUNT = 10

SCALE = 1.25 if ON_PI else 1.5  # window/tile/sprite/physics scale
LEVEL_Y_START = int(80 * SCALE)

# Physics tick rate. A little slower on the Pi - eases the pace and the load.
SIM_HZ = 50 if ON_PI else 60

WIDTH, HEIGHT = int(400 * SCALE), int(600 * SCALE)
TILE = int(32 * SCALE)
GRAVITY = 0.5 * SCALE
MAX_FALL_SPEED = int(12 * SCALE)
MOVE_SPEED = int(4 * SCALE)
MAX_AMMO = 10
SHOT_SLOWDOWN = int(5 * SCALE)
MAX_HP = 3
SHAFT_HEIGHT = int(4000 * SCALE)

ENEMY_SPAWN_CHANCE = 0.35
GEM_SPAWN_CHANCE = 0.4
SPIKE_SPAWN_CHANCE = 0.25
POWERUP_SPAWN_CHANCE = 0.5

PARTICLE_COLOR = (150, 150, 155)  # gray, matching the inert/terrain palette
MAX_PARTICLES = 40 if ON_PI else 150

# Only entities within this vertical band of the player are checked/collided each
# frame - the shaft holds thousands of platforms and iterating all of them was
# the main cost on the Pi. Two screens of slack keeps fast falls safe.
CULL_DIST = HEIGHT * 2

RAPID_FIRE_INTERVAL = 6  # frames between auto-shots while the button is held
POWERUP_DURATION = 60 * 8  # 8 seconds at 60fps

# Whitelisted knobs an AI assistant (or any other tool) may tune per-session via
# overrides.json, written as {"key": value}. Nothing outside this list, and
# nothing outside its range, can ever change - this is the safety boundary for
# letting a model adjust gameplay without ever touching source code.
OVERRIDABLE_TYPES = {
    "GRAVITY": float, "MAX_FALL_SPEED": int, "MOVE_SPEED": int, "MAX_AMMO": int,
    "SHOT_SLOWDOWN": int, "MAX_HP": int, "ENEMY_SPAWN_CHANCE": float,
    "GEM_SPAWN_CHANCE": float, "SPIKE_SPAWN_CHANCE": float, "POWERUP_SPAWN_CHANCE": float,
    "RAPID_FIRE_INTERVAL": int, "POWERUP_DURATION": int,
}
OVERRIDABLE_RANGES = {
    "GRAVITY": (0.2, 2.0), "MAX_FALL_SPEED": (6, 40), "MOVE_SPEED": (2, 14),
    "MAX_AMMO": (3, 30), "SHOT_SLOWDOWN": (0, 15), "MAX_HP": (1, 9),
    "ENEMY_SPAWN_CHANCE": (0.0, 0.9), "GEM_SPAWN_CHANCE": (0.0, 0.9),
    "SPIKE_SPAWN_CHANCE": (0.0, 0.9), "POWERUP_SPAWN_CHANCE": (0.0, 0.9),
    "RAPID_FIRE_INTERVAL": (1, 30), "POWERUP_DURATION": (60, 60 * 30),
}


def _apply_overrides():
    if not os.path.exists(OVERRIDES_FILE):
        return
    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    for key, value in data.items():
        if key not in OVERRIDABLE_TYPES:
            continue
        try:
            value = OVERRIDABLE_TYPES[key](value)
        except (TypeError, ValueError):
            continue
        lo, hi = OVERRIDABLE_RANGES[key]
        value = max(lo, min(hi, value))
        globals()[key] = value


_apply_overrides()

BULLET_SPEED = MAX_FALL_SPEED + int(4 * SCALE)  # bullets must always outrun the player's own fall - recomputed after overrides


def load_sprite(name, size, base_dir=SPRITE_DIR):
    image = pygame.image.load(os.path.join(base_dir, name)).convert_alpha()
    return pygame.transform.smoothscale(image, size)


def load_terrain_tiles(size):
    files = sorted(f for f in os.listdir(TERRAIN_DIR) if f.endswith(".png"))
    return [load_sprite(f, size, base_dir=TERRAIN_DIR) for f in files]


class Bullet:
    def __init__(self, x, y, vx=0.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.speed = BULLET_SPEED

    def update(self):
        self.x += self.vx
        self.y += self.speed


class Enemy:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def rect(self):
        half = int(14 * SCALE)
        size = int(28 * SCALE)
        return pygame.Rect(self.x - half, self.y - half, size, size)


class Gem:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def rect(self):
        half = int(9 * SCALE)
        size = int(18 * SCALE)
        return pygame.Rect(self.x - half, self.y - half, size, size)


class Platform:
    def __init__(self, x, y, width, terrain_index=0):
        self.x = x
        self.y = y
        self.width = width
        self.terrain_index = terrain_index

    def rect(self):
        return pygame.Rect(self.x, self.y, self.width, TILE)


class Particle:
    def __init__(self, x, y, vx, vy, life):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.15 * SCALE
        self.life -= 1

    def alive(self):
        return self.life > 0


class PowerUp:
    def __init__(self, x, y, kind):
        self.x = x
        self.y = y
        self.kind = kind  # "rapid" or "spread"

    def rect(self):
        half = int(11 * SCALE)
        size = int(22 * SCALE)
        return pygame.Rect(self.x - half, self.y - half, size, size)


class Spike:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.hp = 2

    def rect(self):
        pad = int(4 * SCALE)
        return pygame.Rect(self.x + pad, self.y + pad, TILE - pad * 2, TILE - pad * 2)


def load_level(path, terrain_count):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    platforms = []
    enemies = []
    gems = []
    spikes = []
    for row, col, terrain_index in data.get("ground", []):
        ti = terrain_index % max(1, terrain_count)
        platforms.append(Platform(col * TILE, LEVEL_Y_START + row * TILE, TILE, ti))
    for row, col in data.get("spikes", []):
        spikes.append(Spike(col * TILE, LEVEL_Y_START + row * TILE))
    for row, col in data.get("enemies", []):
        enemies.append(Enemy(col * TILE + TILE // 2, LEVEL_Y_START + row * TILE + TILE // 2))
    for row, col in data.get("gems", []):
        gems.append(Gem(col * TILE + TILE // 2, LEVEL_Y_START + row * TILE + TILE // 2))
    rows = data.get("rows", 40)
    shaft_bottom = LEVEL_Y_START + rows * TILE
    platforms.append(Platform(0, shaft_bottom, WIDTH, 0))
    player_start = data.get("player_start")
    if player_start:
        prow, pcol = player_start
        start_x = pcol * TILE + TILE // 2
        start_y = float(LEVEL_Y_START + prow * TILE)
    else:
        start_x = WIDTH // 2
        start_y = float(int(40 * SCALE))
    return platforms, enemies, gems, spikes, start_x, start_y, shaft_bottom


def load_chunks():
    chunks = []
    for i in range(1, NUM_CHUNK_SLOTS + 1):
        path = CHUNK_FILE_TEMPLATE.format(i)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                chunks.append(json.load(f))
    return chunks


def load_repeat_count():
    if os.path.exists(CHUNKS_CONFIG_FILE):
        try:
            with open(CHUNKS_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("repeat_count", DEFAULT_REPEAT_COUNT)
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_REPEAT_COUNT


def build_from_chunks(chunks, terrain_count):
    repeat_count = load_repeat_count()
    platforms, enemies, gems, spikes = [], [], [], []
    row_offset = 0
    start_x, start_y = None, None
    for _ in range(repeat_count):
        chunk = random.choice(chunks)
        for row, col, terrain_index in chunk.get("ground", []):
            ti = terrain_index % max(1, terrain_count)
            platforms.append(Platform(col * TILE, LEVEL_Y_START + (row + row_offset) * TILE, TILE, ti))
        for row, col in chunk.get("spikes", []):
            spikes.append(Spike(col * TILE, LEVEL_Y_START + (row + row_offset) * TILE))
        for row, col in chunk.get("enemies", []):
            enemies.append(Enemy(col * TILE + TILE // 2, LEVEL_Y_START + (row + row_offset) * TILE + TILE // 2))
        for row, col in chunk.get("gems", []):
            gems.append(Gem(col * TILE + TILE // 2, LEVEL_Y_START + (row + row_offset) * TILE + TILE // 2))
        if start_x is None and chunk.get("player_start"):
            prow, pcol = chunk["player_start"]
            start_x = pcol * TILE + TILE // 2
            start_y = float(LEVEL_Y_START + (prow + row_offset) * TILE)
        row_offset += chunk.get("rows", 25)
    shaft_bottom = LEVEL_Y_START + row_offset * TILE
    platforms.append(Platform(0, shaft_bottom, WIDTH, 0))
    if start_x is None:
        start_x, start_y = WIDTH // 2, float(int(40 * SCALE))
    return platforms, enemies, gems, spikes, start_x, start_y, shaft_bottom


class DownwellClone:
    def __init__(self):
        pygame.init()
        kiosk_joy.init()
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1)
        except pygame.error:
            pass
        self.screen = kiosk_screen.setup(WIDTH, HEIGHT, "Downwell Clone")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, int(28 * SCALE))

        self.sounds = {}
        for key in SOUND_ACTIONS:
            path = os.path.join(SOUND_DIR, key + ".wav")
            if os.path.exists(path):
                try:
                    self.sounds[key] = pygame.mixer.Sound(path)
                except pygame.error:
                    pass

        self.terrain_tiles = load_terrain_tiles((TILE, TILE))
        self.player_sprite = load_sprite("player.png", (int(26 * SCALE), int(26 * SCALE)))
        self.enemy_tile = load_sprite("enemy.png", (int(30 * SCALE), int(30 * SCALE)))
        self.gem_tile = load_sprite("gem.png", (int(18 * SCALE), int(18 * SCALE)))
        self.bullet_sprite = load_sprite("bullet.png", (int(10 * SCALE), int(10 * SCALE)))
        self.spike_tile = load_sprite("spike.png", (TILE, TILE))
        self.heart_full = load_sprite("heart_full.png", (int(22 * SCALE), int(22 * SCALE)))
        self.heart_empty = load_sprite("heart_empty.png", (int(22 * SCALE), int(22 * SCALE)))
        self.powerup_tiles = {
            "rapid": load_sprite("powerup_rapid.png", (int(22 * SCALE), int(22 * SCALE))),
            "spread": load_sprite("powerup_spread.png", (int(22 * SCALE), int(22 * SCALE))),
        }

        self._text_cache = {}   # slot -> (string, rendered surface); re-render only on change
        self.reset()

    def _text(self, slot, s, color):
        entry = self._text_cache.get(slot)
        if entry is None or entry[0] != s:
            entry = (s, self.font.render(s, True, color))
            self._text_cache[slot] = entry
        return entry[1]

    def reset(self):
        self.ammo = MAX_AMMO
        self.hp = MAX_HP
        self.score = 0
        self.depth = 0
        self.bullets = []
        self.game_over = False
        self.win = False
        self.invuln_timer = 0
        self.on_ground = False
        self.vel_y = 0.0
        self.particles = []
        self.rapid_fire_timer = 0
        self.spread_timer = 0
        self.fire_cooldown = 0

        chunks = load_chunks()
        if chunks:
            (self.platforms, self.enemies, self.gems, self.spikes,
             start_x, start_y, self.shaft_height) = build_from_chunks(chunks, len(self.terrain_tiles))
            self.player_x = float(start_x)
            self.player_y = float(start_y)
        elif os.path.exists(LEVEL_FILE):
            (self.platforms, self.enemies, self.gems, self.spikes,
             start_x, start_y, self.shaft_height) = load_level(LEVEL_FILE, len(self.terrain_tiles))
            self.player_x = float(start_x)
            self.player_y = float(start_y)
        else:
            self.player_x = float(WIDTH // 2)
            self.player_y = float(int(40 * SCALE))
            self.platforms, self.enemies, self.gems, self.spikes = self._generate_shaft()
            self.shaft_height = SHAFT_HEIGHT

        self.powerups = self._generate_powerups(self.shaft_height)

        # platforms are static - keep them y-sorted so each frame can bisect out
        # just the handful near the player instead of scanning the whole shaft.
        self.platforms.sort(key=lambda p: p.y)
        self._plat_ys = [p.y for p in self.platforms]

    def _platforms_near(self, y, dist=CULL_DIST):
        lo = bisect.bisect_left(self._plat_ys, y - dist)
        hi = bisect.bisect_right(self._plat_ys, y + dist)
        return self.platforms[lo:hi]

    def _generate_shaft(self):
        platforms = []
        enemies = []
        gems = []
        spikes = []
        y = int(120 * SCALE)
        margin = int(10 * SCALE)
        min_w, max_w = int(90 * SCALE), int(220 * SCALE)
        min_step, max_step = int(90 * SCALE), int(150 * SCALE)
        spike_start_y = int(400 * SCALE)
        enemy_margin = int(30 * SCALE)
        while y < SHAFT_HEIGHT:
            width = random.randint(min_w, max_w)
            x = random.randint(margin, WIDTH - width - margin)
            terrain_index = random.randint(0, len(self.terrain_tiles) - 1)
            platforms.append(Platform(x, y, width, terrain_index))
            if y > spike_start_y and random.random() < SPIKE_SPAWN_CHANCE:
                spikes.append(Spike(x + width // 2 - TILE // 2, y - TILE))
            if random.random() < ENEMY_SPAWN_CHANCE:
                enemies.append(Enemy(
                    random.randint(enemy_margin, WIDTH - enemy_margin),
                    y - random.randint(int(60 * SCALE), int(160 * SCALE)),
                ))
            if random.random() < GEM_SPAWN_CHANCE:
                gems.append(Gem(
                    random.randint(enemy_margin, WIDTH - enemy_margin),
                    y - random.randint(int(30 * SCALE), int(120 * SCALE)),
                ))
            y += random.randint(min_step, max_step)
        platforms.append(Platform(0, SHAFT_HEIGHT, WIDTH, 0))
        return platforms, enemies, gems, spikes

    def _generate_powerups(self, shaft_height):
        powerups = []
        margin = int(30 * SCALE)
        y = int(300 * SCALE)
        step_min, step_max = int(500 * SCALE), int(900 * SCALE)
        while y < shaft_height - int(200 * SCALE):
            if random.random() < POWERUP_SPAWN_CHANCE:
                kind = random.choice(("rapid", "spread"))
                x = random.randint(margin, WIDTH - margin)
                powerups.append(PowerUp(x, y, kind))
            y += random.randint(step_min, step_max)
        return powerups

    def handle_input(self, keys):
        if self.game_over or self.win:
            return
        if keys[pygame.K_LEFT] or kiosk_joy.left():
            self.player_x -= MOVE_SPEED
        if keys[pygame.K_RIGHT] or kiosk_joy.right():
            self.player_x += MOVE_SPEED
        margin = int(12 * SCALE)
        self.player_x = max(margin, min(WIDTH - margin, self.player_x))

        if self.fire_cooldown > 0:
            self.fire_cooldown -= 1
        # Rapid fire power-up: holding the button auto-fires instead of needing repeated presses.
        if (self.rapid_fire_timer > 0 and not self.on_ground and not self.game_over and not self.win
                and (keys[pygame.K_SPACE] or kiosk_joy.action_held()) and self.fire_cooldown <= 0):
            self._fire_shot()
            self.fire_cooldown = RAPID_FIRE_INTERVAL

    def _play(self, key):
        sound = self.sounds.get(key)
        if sound:
            sound.play()

    def _fire_shot(self):
        if self.ammo <= 0:
            return
        self.ammo -= 1
        by = self.player_y + int(14 * SCALE)
        spread_offset = int(3 * SCALE)
        self.bullets.append(Bullet(self.player_x, by))
        if self.spread_timer > 0:
            self.bullets.append(Bullet(self.player_x, by, -spread_offset))
            self.bullets.append(Bullet(self.player_x, by, spread_offset))
        # Firing the gunboots slows the fall (real Downwell mechanic) - gravity
        # re-accelerates it each frame, so rapid firing lets you hover/descend gently.
        self.vel_y = max(self.vel_y - SHOT_SLOWDOWN, -3 * SCALE)
        self._play("shoot")

    def press_action(self):
        # Same button as real Downwell: jump when grounded, shoot when airborne.
        if self.game_over or self.win:
            return
        if self.on_ground:
            self.vel_y = -9 * SCALE
            self.on_ground = False
            self._play("jump")
        else:
            self._fire_shot()

    def _take_damage(self):
        if self.invuln_timer > 0:
            return
        self.hp -= 1
        self.vel_y = -6 * SCALE
        self.invuln_timer = 45
        self._play("hit")
        if self.hp <= 0:
            self.game_over = True
            self._play("gameover")

    def update(self):
        if self.game_over or self.win:
            return

        half = int(12 * SCALE)
        size = int(24 * SCALE)
        prev_bottom = self.player_y + half
        self.vel_y = min(self.vel_y + GRAVITY, MAX_FALL_SPEED)
        self.player_y += self.vel_y
        self.depth = max(self.depth, int(self.player_y))
        self.on_ground = False

        player_rect = pygame.Rect(int(self.player_x) - half, int(self.player_y) - half, size, size)

        fall_ratio = max(0.0, self.vel_y) / MAX_FALL_SPEED
        if fall_ratio > 0.15 and len(self.particles) < MAX_PARTICLES:
            for _ in range(1 + int(fall_ratio * 2)):
                ox = random.uniform(-1, 1) * int(10 * SCALE)
                self.particles.append(Particle(
                    self.player_x + ox,
                    self.player_y - half + int(4 * SCALE),
                    random.uniform(-0.6, 0.6) * SCALE,
                    random.uniform(-0.4, 0.2) * SCALE,
                    random.randint(int(10 * SCALE), int(18 * SCALE)),
                ))

        for p in self.particles[:]:
            p.update()
            if not p.alive():
                self.particles.remove(p)

        py = self.player_y
        for plat in self._platforms_near(py):
            prect = plat.rect()
            if self.vel_y >= 0 and player_rect.colliderect(prect) and prev_bottom <= prect.top + 1:
                self.player_y = prect.top - half
                self.vel_y = 0
                self.ammo = MAX_AMMO
                self.on_ground = True
                player_rect.centery = int(self.player_y)

        for spike in self.spikes:
            if abs(spike.y - py) > CULL_DIST:
                continue
            if player_rect.colliderect(spike.rect()):
                self._take_damage()

        if self.invuln_timer > 0:
            self.invuln_timer -= 1
        if self.rapid_fire_timer > 0:
            self.rapid_fire_timer -= 1
        if self.spread_timer > 0:
            self.spread_timer -= 1

        for bullet in self.bullets[:]:
            bullet.update()
            if bullet.y > self.player_y + HEIGHT:
                self.bullets.remove(bullet)
                continue
            for enemy in self.enemies[:]:
                if enemy.rect().collidepoint(bullet.x, bullet.y):
                    self.enemies.remove(enemy)
                    self.score += 25
                    self.vel_y = -8 * SCALE
                    self._play("kill")
                    if bullet in self.bullets:
                        self.bullets.remove(bullet)
                    break

            if bullet in self.bullets:
                for spike in self.spikes[:]:
                    if spike.rect().collidepoint(bullet.x, bullet.y):
                        spike.hp -= 1
                        if spike.hp <= 0:
                            self.spikes.remove(spike)
                            self.score += 15
                            self._play("kill")
                        else:
                            self._play("hit")
                        self.bullets.remove(bullet)
                        break

        for enemy in self.enemies[:]:
            if abs(enemy.y - py) > CULL_DIST:
                continue
            if player_rect.colliderect(enemy.rect()):
                if self.vel_y > 2 and prev_bottom <= enemy.rect().top + int(6 * SCALE):
                    self.enemies.remove(enemy)
                    self.score += 25
                    self.vel_y = -8 * SCALE
                    self._play("kill")
                else:
                    self._take_damage()

        for gem in self.gems[:]:
            if abs(gem.y - py) > CULL_DIST:
                continue
            if player_rect.colliderect(gem.rect()):
                self.gems.remove(gem)
                self.score += 10
                self._play("gem")

        for powerup in self.powerups[:]:
            if player_rect.colliderect(powerup.rect()):
                self.powerups.remove(powerup)
                if powerup.kind == "rapid":
                    self.rapid_fire_timer = POWERUP_DURATION
                else:
                    self.spread_timer = POWERUP_DURATION
                self.score += 20
                self._play("gem")

        if self.player_y > self.shaft_height - int(20 * SCALE):
            self.win = True
            self._play("win")

    def draw(self):
        self.screen.fill((14, 12, 22))
        cam_y = self.player_y - HEIGHT // 3
        top, bot = cam_y - TILE, cam_y + HEIGHT

        for plat in self._platforms_near(cam_y + HEIGHT // 2, HEIGHT):
            if plat.y < top or plat.y > bot:      # off-camera - skip before any work
                continue
            sy = plat.y - cam_y
            tile_img = self.terrain_tiles[plat.terrain_index]
            for tx in range(plat.x, plat.x + plat.width, TILE):
                self.screen.blit(tile_img, (tx, sy))

        for spike in self.spikes:
            sy = spike.y - cam_y
            if -TILE <= sy <= HEIGHT:
                self.screen.blit(self.spike_tile, (spike.x, sy))

        margin_enemy = int(30 * SCALE)
        for enemy in self.enemies:
            sy = enemy.y - cam_y
            if -margin_enemy <= sy <= HEIGHT:
                self.screen.blit(self.enemy_tile, self.enemy_tile.get_rect(center=(enemy.x, sy)))

        margin_gem = int(20 * SCALE)
        for gem in self.gems:
            sy = gem.y - cam_y
            if -margin_gem <= sy <= HEIGHT:
                self.screen.blit(self.gem_tile, self.gem_tile.get_rect(center=(gem.x, sy)))

        margin_powerup = int(22 * SCALE)
        for powerup in self.powerups:
            sy = powerup.y - cam_y
            if -margin_powerup <= sy <= HEIGHT:
                tile = self.powerup_tiles[powerup.kind]
                self.screen.blit(tile, tile.get_rect(center=(powerup.x, sy)))

        for bullet in self.bullets:
            sy = bullet.y - cam_y
            self.screen.blit(self.bullet_sprite, self.bullet_sprite.get_rect(center=(int(bullet.x), int(sy))))

        for p in self.particles:
            sy = p.y - cam_y
            if -10 <= sy <= HEIGHT + 10:
                frac = p.life / p.max_life
                r = max(1, int(4 * SCALE * frac))
                pygame.draw.circle(self.screen, PARTICLE_COLOR, (int(p.x), int(sy)), r)

        if self.invuln_timer == 0 or self.invuln_timer % 6 < 3:
            py = HEIGHT // 3
            self.screen.blit(self.player_sprite, self.player_sprite.get_rect(center=(int(self.player_x), py)))

        pad = int(10 * SCALE)
        heart_step = int(26 * SCALE)
        for i in range(MAX_HP):
            img = self.heart_full if i < self.hp else self.heart_empty
            self.screen.blit(img, (pad + i * heart_step, pad))

        line2 = pad + int(28 * SCALE)
        self.screen.blit(self._text("ammo", "Ammo: {}/{}".format(self.ammo, MAX_AMMO), (255, 255, 255)), (pad, line2))
        hud_right = int(130 * SCALE)
        self.screen.blit(self._text("score", "Score: {}".format(self.score), (255, 255, 255)), (WIDTH - hud_right, pad))
        self.screen.blit(self._text("depth", "Depth: {}".format(self.depth), (200, 200, 200)), (WIDTH - hud_right, line2))

        line3 = line2 + int(28 * SCALE)
        if self.rapid_fire_timer > 0:
            secs = self.rapid_fire_timer // 60 + 1
            self.screen.blit(self._text("rapid", "Rapid Fire: {}s".format(secs), (255, 210, 120)), (pad, line3))
            line3 += int(28 * SCALE)
        if self.spread_timer > 0:
            secs = self.spread_timer // 60 + 1
            self.screen.blit(self._text("spread", "3-Way Shot: {}s".format(secs), (255, 210, 120)), (pad, line3))

        if self.game_over:
            msg = self._text("end", "GAME OVER - press R to restart", (255, 90, 90))
            self.screen.blit(msg, msg.get_rect(center=(WIDTH // 2, HEIGHT // 2)))
        elif self.win:
            msg = self._text("end", "BOTTOM REACHED! press R to restart", (120, 255, 150))
            self.screen.blit(msg, msg.get_rect(center=(WIDTH // 2, HEIGHT // 2)))

        kiosk_joy.blit_exit_hint(self.screen)
        kiosk_screen.flip()


STEP_MS = 1000.0 / SIM_HZ   # fixed physics timestep
MAX_STEPS = 5               # cap catch-up steps so a hitch can't spiral


def main():
    game = DownwellClone()
    running = True
    acc = 0.0
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    game.press_action()
                elif event.key == pygame.K_r:
                    game.reset()
                elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
            elif kiosk_joy.is_action(event):
                if game.game_over or game.win:
                    game.reset()
                else:
                    game.press_action()
        if kiosk_joy.wants_quit():
            running = False
        # Fixed 60 Hz physics, decoupled from render rate: on a slow machine the
        # game keeps its real speed by stepping update() more than once per frame
        # instead of running in slow motion.
        keys = pygame.key.get_pressed()
        acc += game.clock.tick(60)      # cap render at 60; sim below catches up if slower
        steps = 0
        while acc >= STEP_MS and steps < MAX_STEPS:
            game.handle_input(keys)
            game.update()
            acc -= STEP_MS
            steps += 1
        game.draw()
    pygame.quit()


if __name__ == "__main__":
    main()
