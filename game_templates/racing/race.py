"""Corsa Retro - a 1-bit top-down racing game for the fair kiosk.

Same look as "Game of Crowns" (game_templates/platformer): everything is drawn
with just two colours and pygame primitives - no image or sound files, one
self-contained script. Dodge the oncoming cars, grab coins, skim past traffic
for near-miss bonuses; the longer you drive the more you score and the faster
the road rushes at you.

Controls
    Left / Right ......... arrow keys or A / D
    Speed up ............. W or Up arrow (hold)
    Pause ............... Space
    Restart (after crash)  Space or R
    Quit ............... Esc or Q
"""
import math
import os
import random
from sys import exit as sys_exit

import pygame

pygame.init()

# ------------------------------------------------------------------ look & feel
# retro 1-bit dungeon palette - identical to Game of Crowns
DARK = (13, 13, 18)
LITE = (200, 192, 170)

WIN_W, WIN_H = 800, 660
FPS = 60

# ------------------------------------------------------------- gameplay knobs
# (all easy to tweak by prompt: "rendi l'auto piu veloce", "aggiungi piu
#  traffico", "allarga la strada", "piu monete", "bonus sorpasso piu alto"...)
ROAD_W = 460                # width of the drivable road, centred on screen
PLAYER_STEER_SPEED = 6      # how fast you slide left / right
START_SPEED = 4.0           # how fast the world rushes toward you at the start
SPEED_PER_LEVEL = 0.35      # extra world speed gained each level
BOOST_EXTRA = 5.0           # extra speed while holding W / Up
LEVEL_EVERY = 1200          # points between levels
ENEMY_COUNT = 3             # oncoming cars on the road at once

COIN_COUNT = 3             # coins on the road at once
COIN_BONUS = 25            # points per coin
PUDDLE_COUNT = 2          # oil / water patches at once
SLIP_FRAMES = 55         # how long you lose grip after hitting a patch
NEARMISS_GAP = 20        # extra px clearance that still counts as a near miss
NEARMISS_BONUS = 50     # points for skimming past an enemy without crashing
CRASH_FRAMES = 34      # length of the crash animation before GAME OVER

CAR_W, CAR_H = 40, 64
COIN_R = 8
PUD_W, PUD_H = 72, 28

HS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "high_scores.txt")


def make_player_car():
    """Your car: a solid light body, dark glass near the top (it faces up)."""
    s = pygame.Surface((CAR_W, CAR_H), pygame.SRCALPHA)
    pygame.draw.rect(s, LITE, (3, 2, CAR_W - 6, CAR_H - 4))          # body
    pygame.draw.rect(s, DARK, (8, 7, CAR_W - 16, 12))              # windshield
    pygame.draw.rect(s, DARK, (10, 41, CAR_W - 20, 9))            # rear window
    for wy in (13, CAR_H - 25):                                    # dark wheels
        pygame.draw.rect(s, DARK, (0, wy, 4, 13))
        pygame.draw.rect(s, DARK, (CAR_W - 4, wy, 4, 13))
    return s


def make_enemy_car():
    """Oncoming car: also a light body, but glass near the BOTTOM and a bold
    dark chevron pointing down so you read it as coming straight at you."""
    s = pygame.Surface((CAR_W, CAR_H), pygame.SRCALPHA)
    pygame.draw.rect(s, LITE, (3, 2, CAR_W - 6, CAR_H - 4))          # body
    pygame.draw.rect(s, DARK, (8, CAR_H - 19, CAR_W - 16, 12))     # windshield
    pygame.draw.polygon(s, DARK, [                                 # downward chevron
        (6, 12), (CAR_W // 2, 26), (CAR_W - 6, 12),
        (CAR_W - 6, 20), (CAR_W // 2, 34), (6, 20),
    ])
    for wy in (13, CAR_H - 25):
        pygame.draw.rect(s, DARK, (0, wy, 4, 13))
        pygame.draw.rect(s, DARK, (CAR_W - 4, wy, 4, 13))
    return s


def make_coin():
    s = pygame.Surface((COIN_R * 2 + 2, COIN_R * 2 + 2), pygame.SRCALPHA)
    c = COIN_R + 1
    pygame.draw.circle(s, LITE, (c, c), COIN_R, 2)
    pygame.draw.circle(s, LITE, (c, c), 2)
    return s


def make_puddle():
    """A dark oil slick - invisible fill on the dark road, read from its dotted
    light rim and a couple of inner shimmer specks."""
    s = pygame.Surface((PUD_W, PUD_H), pygame.SRCALPHA)
    pygame.draw.ellipse(s, DARK, (0, 0, PUD_W, PUD_H))
    for a in range(0, 360, 14):
        r = math.radians(a)
        x = PUD_W / 2 + (PUD_W / 2 - 2) * math.cos(r)
        y = PUD_H / 2 + (PUD_H / 2 - 2) * math.sin(r)
        if 0 <= x < PUD_W and 0 <= y < PUD_H:
            s.set_at((int(x), int(y)), LITE)
    for sx, sy in ((PUD_W * 0.35, PUD_H * 0.45), (PUD_W * 0.6, PUD_H * 0.6)):
        s.set_at((int(sx), int(sy)), LITE)
    return s


def make_background():
    """Dithered dungeon-brick wall, tiled so it wraps seamlessly when scrolled
    vertically. Same trick as Game of Crowns."""
    bg = pygame.Surface((WIN_W, WIN_H))
    bg.fill(DARK)
    bw, bh = 60, 30                       # WIN_H is an exact multiple of bh -> no seam
    for row, yy in enumerate(range(0, WIN_H, bh)):
        off = 0 if row % 2 == 0 else bw // 2
        for x0 in range(-bw, WIN_W + bw, bw):
            x = x0 + off
            for dx in range(0, bw, 4):
                if 0 <= x + dx < WIN_W:
                    bg.set_at((x + dx, yy), LITE)
            for dy in range(0, bh, 4):
                if 0 <= x < WIN_W and yy + dy < WIN_H:
                    bg.set_at((x, yy + dy), LITE)
    return bg


def _star_points(cx, cy, r):
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.42
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return pts


class Race:
    def __init__(self):
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Corsa Retro")
        self.canvas = pygame.Surface((WIN_W, WIN_H))
        self.clock = pygame.time.Clock()

        self.bg = make_background()
        self.player_img = make_player_car()
        self.enemy_img = make_enemy_car()
        self.coin_img = make_coin()
        self.puddle_img = make_puddle()
        self.hud_font = pygame.font.Font(None, 32)
        self.big_font = pygame.font.Font(None, 90)
        self.mid_font = pygame.font.Font(None, 34)
        self.pop_font = pygame.font.Font(None, 30)

        self.road_left = (WIN_W - ROAD_W) // 2
        self.road_right = self.road_left + ROAD_W

        self.max_score = self._load_hs()
        self.reset()

    # ------------------------------------------------------------- high score
    def _load_hs(self):
        try:
            with open(HS_PATH) as f:
                vals = [int(float(x)) for x in f.read().split()]
            return max(vals) if vals else 0
        except (OSError, ValueError):
            return 0

    def _save_hs(self):
        try:
            with open(HS_PATH, "w") as f:
                f.write(str(self.max_score))
        except OSError:
            pass

    # ------------------------------------------------------------- round setup
    def _lane_bounds(self, w=CAR_W):
        return self.road_left + 6, self.road_right - 6 - w

    def reset(self):
        self.score = 0
        self.coins_got = 0
        self.level = 0
        self.speed = START_SPEED
        self.scroll = 0.0
        self.slip = 0
        self.shake = 0.0
        self.crash_timer = 0
        self.crash_pos = (0, 0)
        self.state = "PLAY"                       # PLAY / PAUSE / CRASH / OVER
        self.px = (self.road_left + self.road_right) / 2 - CAR_W / 2
        self.py = WIN_H - CAR_H - 24

        lo, hi = self._lane_bounds()
        self.enemies = [
            {"x": random.uniform(lo, hi), "y": -200.0 - i * 260, "scored": False}
            for i in range(ENEMY_COUNT)
        ]
        clo, chi = self._lane_bounds(COIN_R * 2)
        self.coins = [{"x": random.uniform(clo, chi), "y": -140.0 - i * 230}
                      for i in range(COIN_COUNT)]
        plo, phi = self._lane_bounds(PUD_W)
        self.puddles = [{"x": random.uniform(plo, phi), "y": -500.0 - i * 360}
                        for i in range(PUDDLE_COUNT)]

        self.popups = []            # {x, y, txt, life}
        self.confetti = []          # {x, y, vx, vy}
        self.record_timer = 0
        self.start_max = self.max_score
        self.beaten_record = False

    def _respawn_enemy(self, e):
        lo, hi = self._lane_bounds()
        e["y"] = random.uniform(-320, -80)
        e["scored"] = False
        x = random.uniform(lo, hi)
        for _ in range(12):
            if all(o is e or o["y"] > 60 or abs(x - o["x"]) > CAR_W + 12
                   for o in self.enemies):
                break
            x = random.uniform(lo, hi)
        e["x"] = x

    def _recycle(self, obj, w, y_lo, y_hi):
        lo, hi = self._lane_bounds(w)
        obj["x"] = random.uniform(lo, hi)
        obj["y"] = random.uniform(y_lo, y_hi)

    # ------------------------------------------------------------- main loop
    def run(self):
        while True:
            self.handle_events()
            if self.state == "PLAY":
                self.update()
            elif self.state == "CRASH":
                self.crash_step()
            if self.state != "PAUSE":
                self.tick_particles()
            self.draw()
            self.present()
            self.clock.tick(FPS)

    def present(self):
        ox = oy = 0
        if self.shake > 0.6:
            m = int(self.shake)
            ox, oy = random.randint(-m, m), random.randint(-m, m)
            self.shake *= 0.88
        else:
            self.shake = 0.0
        self.screen.fill(DARK)
        self.screen.blit(self.canvas, (ox, oy))
        pygame.display.update()

    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.quit()
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.quit()
                elif ev.key == pygame.K_SPACE:
                    if self.state == "PLAY":
                        self.state = "PAUSE"
                    elif self.state == "PAUSE":
                        self.state = "PLAY"
                    elif self.state == "OVER":
                        self.reset()
                elif ev.key == pygame.K_r and self.state == "OVER":
                    self.reset()

    def update(self):
        keys = pygame.key.get_pressed()
        boost = keys[pygame.K_w] or keys[pygame.K_UP]
        eff = self.speed + (BOOST_EXTRA if boost else 0.0)

        steer = PLAYER_STEER_SPEED * (0.45 if self.slip > 0 else 1.0)
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.px -= steer
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.px += steer
        if self.slip > 0:
            self.slip -= 1
            self.px += math.sin(self.slip * 0.5) * 2.4      # skid sway
        lo, hi = self._lane_bounds()
        self.px = max(lo, min(self.px, hi))

        self.scroll += eff
        pr = pygame.Rect(int(self.px), int(self.py), CAR_W, CAR_H)

        # oncoming cars
        for e in self.enemies:
            e["y"] += eff
            er = pygame.Rect(int(e["x"]), int(e["y"]), CAR_W, CAR_H)
            if pr.colliderect(er):
                self.begin_crash()
                return
            if not e["scored"] and e["y"] > self.py + CAR_H:
                if abs(e["x"] - self.px) < CAR_W + NEARMISS_GAP:
                    self.score += NEARMISS_BONUS
                    self.popups.append({"x": self.px + CAR_W / 2, "y": self.py - 6,
                                        "txt": f"+{NEARMISS_BONUS}", "life": 45})
                e["scored"] = True
            if e["y"] > WIN_H + 20:
                self._respawn_enemy(e)

        # coins
        for c in self.coins:
            c["y"] += eff
            cr = pygame.Rect(int(c["x"]), int(c["y"]), COIN_R * 2, COIN_R * 2)
            if pr.colliderect(cr):
                self.score += COIN_BONUS
                self.coins_got += 1
                self.popups.append({"x": c["x"] + COIN_R, "y": c["y"],
                                    "txt": f"+{COIN_BONUS}", "life": 40})
                self._recycle(c, COIN_R * 2, -260, -80)
            elif c["y"] > WIN_H + 20:
                self._recycle(c, COIN_R * 2, -260, -80)

        # oil / water patches
        for p in self.puddles:
            p["y"] += eff
            prr = pygame.Rect(int(p["x"]), int(p["y"]) + 6, PUD_W, PUD_H - 12)
            if self.slip <= 0 and pr.colliderect(prr):
                self.slip = SLIP_FRAMES
                self.popups.append({"x": self.px + CAR_W / 2, "y": self.py - 6,
                                    "txt": "SBANDA!", "life": 40})
            if p["y"] > WIN_H + 40:
                self._recycle(p, PUD_W, -640, -180)

        # score, level, record
        self.score += 1 + int(0.4 * self.level)
        lvl = self.score // LEVEL_EVERY
        if lvl > self.level:
            self.level = lvl
            self.speed = START_SPEED + SPEED_PER_LEVEL * self.level
        if not self.beaten_record and self.start_max > 0 and self.score > self.start_max:
            self.celebrate_record()
        if self.score > self.max_score:
            self.max_score = self.score

    def begin_crash(self):
        self.state = "CRASH"
        self.crash_timer = CRASH_FRAMES
        self.shake = 12.0
        self.crash_pos = (self.px, self.py)
        if self.score > self.max_score:
            self.max_score = self.score
        self._save_hs()

    def crash_step(self):
        self.crash_timer -= 1
        if self.crash_timer > CRASH_FRAMES - 10:
            self.shake = max(self.shake, self.crash_timer * 0.4)
        if self.crash_timer <= 0:
            self.state = "OVER"

    def celebrate_record(self):
        self.beaten_record = True
        self.record_timer = 150
        for _ in range(44):
            self.confetti.append({
                "x": random.uniform(0, WIN_W), "y": random.uniform(-60, -4),
                "vx": random.uniform(-1.4, 1.4), "vy": random.uniform(1.4, 4.2),
            })

    def tick_particles(self):
        for pop in self.popups:
            pop["y"] -= 1.3
            pop["life"] -= 1
        self.popups = [p for p in self.popups if p["life"] > 0]
        for f in self.confetti:
            f["x"] += f["vx"]
            f["y"] += f["vy"]
            f["vy"] += 0.14
        self.confetti = [f for f in self.confetti if f["y"] < WIN_H + 10]
        if self.record_timer > 0:
            self.record_timer -= 1

    # ------------------------------------------------------------- drawing
    def draw(self):
        s = self.canvas

        byoff = int(self.scroll) % WIN_H
        s.blit(self.bg, (0, byoff - WIN_H))
        s.blit(self.bg, (0, byoff))

        pygame.draw.rect(s, DARK, (self.road_left, 0, ROAD_W, WIN_H))
        pygame.draw.rect(s, LITE, (self.road_left, 0, 4, WIN_H))
        pygame.draw.rect(s, LITE, (self.road_right - 4, 0, 4, WIN_H))

        off = int(self.scroll) % 48
        for y in range(-48 + off, WIN_H, 48):
            pygame.draw.rect(s, LITE, (self.road_left + 10, y, 4, 16))
            pygame.draw.rect(s, LITE, (self.road_right - 14, y, 4, 16))

        coff = int(self.scroll) % 68
        cx = WIN_W // 2 - 3
        for y in range(-68 + coff, WIN_H, 68):
            pygame.draw.rect(s, LITE, (cx, y, 6, 34))

        for p in self.puddles:
            s.blit(self.puddle_img, (int(p["x"]), int(p["y"])))
        for c in self.coins:
            s.blit(self.coin_img, (int(c["x"]), int(c["y"])))
        for e in self.enemies:
            s.blit(self.enemy_img, (int(e["x"]), int(e["y"])))

        if self.state == "CRASH":
            self._draw_wreck(s, *self.crash_pos)
        else:
            s.blit(self.player_img, (int(self.px), int(self.py)))

        for pop in self.popups:
            if pop["life"] % 6 != 1:                       # slight flicker as it fades
                r = self.pop_font.render(pop["txt"], True, LITE)
                s.blit(r, r.get_rect(center=(int(pop["x"]), int(pop["y"]))))
        for f in self.confetti:
            pygame.draw.rect(s, LITE, (int(f["x"]), int(f["y"]), 3, 3))

        s.blit(self.hud_font.render(f"PUNTI {self.score}", True, LITE), (14, 12))
        s.blit(self.hud_font.render(f"RECORD {self.max_score}", True, LITE), (14, 40))
        s.blit(self.hud_font.render(f"LIV {self.level + 1}", True, LITE), (14, 68))
        s.blit(self.hud_font.render(f"MONETE {self.coins_got}", True, LITE), (14, 96))

        if self.record_timer > 0 and (self.record_timer // 6) % 2 == 0:
            r = self.mid_font.render("NUOVO RECORD!", True, LITE)
            s.blit(r, r.get_rect(center=(WIN_W // 2, 40)))

        if self.state == "CRASH":
            flash = max(0, self.crash_timer - (CRASH_FRAMES - 8)) / 8.0
            if flash > 0:
                veil = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
                veil.fill((255, 255, 255, int(210 * flash)))
                s.blit(veil, (0, 0))
        elif self.state == "PAUSE":
            self._overlay("PAUSA", [
                "Sinistra / Destra:  frecce o A / D",
                "Accelera:  W o freccia su",
                "Monete = punti bonus, sorpassi stretti = +50",
                "Pausa:  barra spaziatrice     Esci:  ESC o Q",
                "",
                "Premi SPAZIO per continuare",
            ])
        elif self.state == "OVER":
            lines = [f"Punteggio:  {self.score}", f"Record:  {self.max_score}",
                     f"Monete raccolte:  {self.coins_got}", ""]
            if self.beaten_record:
                lines.append("NUOVO RECORD!")
            lines.append("SPAZIO o R = ricomincia      ESC = esci")
            self._overlay("HAI PERSO", lines)
            if self.beaten_record:
                self._draw_medal(s, WIN_W // 2, 130)

    def _draw_wreck(self, s, x, y):
        pygame.draw.rect(s, LITE, (x + 2, y + 8, CAR_W - 4, CAR_H - 16))
        pygame.draw.line(s, DARK, (x + 4, y + 10), (x + CAR_W - 4, y + CAR_H - 10), 3)
        pygame.draw.line(s, DARK, (x + CAR_W - 4, y + 10), (x + 4, y + CAR_H - 10), 3)
        for dx, dy in ((-9, 6), (CAR_W + 4, 12), (7, CAR_H - 2), (CAR_W - 12, -7)):
            pygame.draw.rect(s, LITE, (x + dx, y + dy, 4, 4))

    def _draw_medal(self, s, cx, cy):
        pygame.draw.circle(s, LITE, (cx, cy), 24)
        pygame.draw.circle(s, DARK, (cx, cy), 24, 3)
        pygame.draw.polygon(s, DARK, _star_points(cx, cy, 13))

    def _overlay(self, title, lines):
        s = self.canvas
        veil = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        veil.fill((13, 13, 18, 222))
        s.blit(veil, (0, 0))
        t = self.big_font.render(title, True, LITE)
        s.blit(t, t.get_rect(center=(WIN_W // 2, 220)))
        y = 310
        for ln in lines:
            if ln:
                r = self.mid_font.render(ln, True, LITE)
                s.blit(r, r.get_rect(center=(WIN_W // 2, y)))
            y += 40

    @staticmethod
    def quit():
        pygame.quit()
        sys_exit()


if __name__ == "__main__":
    Race().run()
