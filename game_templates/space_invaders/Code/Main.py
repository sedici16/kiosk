# Tutorial: https://youtu.be/o-6pADy5Mdg

import os
import sys
import platform as _platform

# cd to this file's folder BEFORE importing the sibling modules - some of them
# also chdir on import, which would make __file__ resolve wrong if we waited.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# The cabinet Pi has no GPU. Skip the CRT overlay (a 600x600 per-pixel-alpha
# blit, ~130 ms/frame there), use partial screen updates, cap the frame rate
# low, and scale all movement by SPD so the game still plays at its real speed.
ON_PI = _platform.machine().lower().startswith(("arm", "aarch"))
SPD = 3 if ON_PI else 1
FRAME_CAP = 20 if ON_PI else 60

import pygame
from Player import Player
import Obstacle
from Alien import Alien, Extra
from Laser import Laser
from random import choice, randint

import kiosk_joy
import kiosk_screen


class GameOver(Exception):
    """Raised to end the current round. .won is True on victory, False on defeat."""
    def __init__(self, won):
        super().__init__()
        self.won = won


class Game:
    def __init__(self):
        # Game Window UI and Icon
        pygame .display.set_caption("Space Invaders")
        pygame_icon = pygame.image.load("../Graphics/Red.png")
        pygame.display.set_icon(pygame_icon)

        # Player Setup
        player_sprite = Player((screen_width / 2, screen_height), screen_width, 5 * SPD)
        self.player = pygame.sprite.GroupSingle(player_sprite)

        # Health and Score Setup
        self.lives = 3
        self.live_surf = pygame.image.load("../Graphics/Player.png").convert_alpha()
        self.live_x_start_pos = screen_width - (self.live_surf.get_size()[0] * 2 + 20)
        self.score = 0
        self.font = pygame.font.Font("../Font/Pixeled.ttf", 20)

        # Obstacle Setup
        self.shape = Obstacle.shape
        self.block_size = 10 if ON_PI else 6   # fewer, bigger blocks on the Pi
        self.blocks = pygame.sprite.Group()
        self.obstacle_amount = 4
        self.obstacle_x_positions = [num * (screen_width / self.obstacle_amount) for num in range(self.obstacle_amount)]
        self.create_multiple_obstacles(*self.obstacle_x_positions, x_start = screen_width / 15, y_start = 480)

        # Alien Setup
        self.aliens = pygame.sprite.Group()
        self.alien_lasers = pygame.sprite.Group()
        self.alien_setup(rows = 6, cols = 8)
        self.alien_direction = SPD

        # Extra Alien Setup
        self.extra = pygame.sprite.GroupSingle()
        self.extra_spawn_time = randint(400, 800)

        # Audio
        music = pygame.mixer.Sound("../Audio/Music.wav")
        music.set_volume(0.2)
        music.play(loops = -1)
        self.laser_sound = pygame.mixer.Sound('../Audio/Laser.wav')
        self.laser_sound.set_volume(0.2)
        self.explosion_sound = pygame.mixer.Sound('../Audio/Explosion.wav')
        self.explosion_sound.set_volume(0.5)

    def create_obstacle(self, x_start, y_start, offset_x):
        for row_index, row in enumerate(self.shape):
            for col_index, col in enumerate(row):
                if col == "x":
                    x = x_start + col_index * self.block_size + offset_x
                    y = y_start + row_index * self.block_size
                    block = Obstacle.Block(self.block_size, (241, 79, 80), x, y)
                    self.blocks.add(block)

    def create_multiple_obstacles(self, *offset, x_start, y_start):
        for offset_x in offset:
            self.create_obstacle(x_start, y_start, offset_x)

    def alien_setup(self, rows, cols, x_distance = 60, y_distance = 48, x_offset = 70, y_offset = 100):
        for row_index, row in enumerate(range(rows)):
            for col_index, col in enumerate(range(cols)):
                x = col_index * x_distance + x_offset
                y = row_index * y_distance + y_offset
                
                if row_index == 0: alien_sprite = Alien("Yellow", x, y)
                elif 1 <= row_index <= 2: alien_sprite = Alien("Green", x, y)
                else: alien_sprite = Alien("Red", x, y)
                self.aliens.add(alien_sprite)

    def alien_position_checker(self):
        all_aliens = self.aliens.sprites()
        for alien in all_aliens:
            if alien.rect.right >= screen_width:
                self.alien_direction = -SPD
                self.alien_move_down(2 * SPD)
            elif alien.rect.left <= 0:
                self.alien_direction = SPD
                self.alien_move_down(2 * SPD)

    def alien_move_down(self, distance):
        if self.aliens:
            for alien in self.aliens.sprites():
                alien.rect.y += distance

    def alien_shoot(self):
        if self.aliens.sprites():
            random_alien = choice(self.aliens.sprites())
            laser_sprite = Laser(random_alien.rect.center, 6 * SPD, screen_height)
            self.alien_lasers.add(laser_sprite)
            self.laser_sound.play()

    def extra_alien_timer(self):
        self.extra_spawn_time -= 1
        if self.extra_spawn_time <= 0:
            self.extra.add(Extra(choice(["right", "left"]), screen_width, ))
            self.extra_spawn_time = randint(400, 800)

    def collision_checks(self):

        # Player Lasers
        if self.player.sprite.lasers:
            for laser in self.player.sprite.lasers:
                # Obstacle Collisions
                if pygame.sprite.spritecollide(laser, self.blocks, True):
                    laser.kill()

                # Alien Collisions
                aliens_hit = pygame.sprite.spritecollide(laser, self.aliens, True)
                if aliens_hit:
                    for alien in aliens_hit:
                        self.score += alien.value
                    screen.fill((255, 255, 255))
                    laser.kill()
                    self.explosion_sound.play()

                # Extra Collisions
                if pygame.sprite.spritecollide(laser, self.extra, True):
                    screen.fill((255, 255, 255))
                    self.score += 500
                    laser.kill()
                    self.explosion_sound.play()
        
        # Alien Lasers
        if self.alien_lasers:
            for laser in self.alien_lasers:
                # Obstacle Collisions
                if pygame.sprite.spritecollide(laser, self.blocks, True):
                    laser.kill()

                # Player Collisions
                if pygame.sprite.spritecollide(laser, self.player, False):
                    laser.kill()
                    screen.fill((122, 0, 0))
                    self.lives -= 1
                    
        # Aliens
        if self.aliens:
            for alien in self.aliens:
                # Obstacle Collisions
                pygame.sprite.spritecollide(alien, self.blocks, True)

                # Player Collisions
                if pygame.sprite.spritecollide(alien, self.player, True):
                    raise GameOver(False)

    def display_lives(self):
        for live in range(self.lives - 1):
            x = self.live_x_start_pos + (live * (self.live_surf.get_size()[0] + 10))
            screen.blit(self.live_surf, (x, 8))

        if self.lives <= 0:
            raise GameOver(False)

    def display_score(self):
        score_surf = self.font.render("Score: {}".format(self.score), False, "White")
        score_rect = score_surf.get_rect(topleft = (10, -10))
        screen.blit(score_surf, score_rect)

    def victory_message(self):
        if not self.aliens.sprites():
            raise GameOver(True)

    def update(self):
        # one 60 Hz logic step (may raise GameOver)
        self.player.update()
        self.alien_lasers.update()
        self.extra.update()
        self.aliens.update(self.alien_direction)
        self.alien_position_checker()
        self.extra_alien_timer()
        self.collision_checks()
        self.victory_message()

    def draw(self):
        self.player.sprite.lasers.draw(screen)
        self.player.draw(screen)
        self.blocks.draw(screen)
        self.aliens.draw(screen)
        self.alien_lasers.draw(screen)
        self.extra.draw(screen)
        self.display_lives()
        self.display_score()

    def run(self):
        self.update()
        self.draw()


class CRT:
    def __init__(self):
        self.tv = pygame.image.load("../Graphics/TV.png").convert_alpha()
        self.tv = pygame.transform.scale(self.tv, (screen_width, screen_height))
        self.create_crt_lines()   # bake the scanlines once, not every frame

    def create_crt_lines(self):
        line_height = 3
        line_amount = int(screen_height / line_height)
        for line in range(line_amount):
            y_pos = line * line_height
            pygame.draw.line(self.tv, "Black", (0, y_pos), (screen_width, y_pos), 1)

    def draw(self):
        self.tv.set_alpha(randint(75, 90))
        screen.blit(self.tv, (0, 0))


if __name__ == "__main__":
    # buffer grande: sul Pi il jack analogico (driver bcm2835, poco affidabile)
    # va in underrun e ammutolisce l'audio dopo pochi secondi se il buffer di
    # default e' troppo piccolo per reggere i rallentamenti della CPU durante
    # il rendering del gioco
    pygame.mixer.pre_init(buffer=4096)
    pygame.init()
    kiosk_joy.init()
    screen_width = 720 if ON_PI else 600
    screen_height = 720 if ON_PI else 600
    screen = kiosk_screen.setup(screen_width, screen_height, "Space Invaders")
    clock = pygame.time.Clock()
    game = Game()
    crt = CRT()

    # Alien fire every 800 ms off the frame clock. (pygame.time.set_timer spawns
    # a thread that crashes the Pi's old pygame with take_gil: NULL tstate.)
    alien_shoot_ms = 0.0

    over_font = pygame.font.Font("../Font/Pixeled.ttf", 28)
    hint_font = pygame.font.Font("../Font/Pixeled.ttf", 14)
    game_over = False
    game_won = False

    def draw_end_screen():
        title = "HAI VINTO!" if game_won else "GAME OVER"
        color = (120, 230, 140) if game_won else (230, 110, 110)
        title_surf = over_font.render(title, False, color)
        screen.blit(title_surf, title_surf.get_rect(center=(screen_width / 2, screen_height / 2 - 30)))
        hint_surf = hint_font.render("R = ricomincia    ESC = esci", False, "White")
        screen.blit(hint_surf, hint_surf.get_rect(center=(screen_width / 2, screen_height / 2 + 20)))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    pygame.quit()
                    sys.exit()
                if game_over and event.key == pygame.K_r:
                    game = Game()
                    game_over = False
                    game_won = False
            if kiosk_joy.is_action(event) and game_over:
                game = Game()
                game_over = False
                game_won = False

        if kiosk_joy.wants_quit():
            pygame.quit()
            sys.exit()

        clock.tick(FRAME_CAP)
        if not game_over:
            alien_shoot_ms += clock.get_time()
            if alien_shoot_ms >= 800:
                alien_shoot_ms = 0.0
                game.alien_shoot()
            try:
                game.update()
            except GameOver as result:
                game_over = True
                game_won = result.won

        screen.fill((30, 30, 30))
        if game_over:
            draw_end_screen()
        else:
            game.draw()
        if not ON_PI:
            crt.draw()
        kiosk_joy.blit_exit_hint(screen)
        kiosk_screen.flip()
