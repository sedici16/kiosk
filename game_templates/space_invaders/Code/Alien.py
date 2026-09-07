import pygame
import os
import platform as _pf


# File Importing (Changes Directory to Where the File is Saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

SPD = 3 if _pf.machine().lower().startswith(("arm", "aarch")) else 1


class Alien(pygame.sprite.Sprite):
    def __init__(self, color, x, y):
        super().__init__()
        file_path = "../Graphics/" + color + ".png"
        self.image = pygame.image.load(file_path).convert_alpha()
        self.rect = self.image.get_rect(topleft = (x, y))

        if color == "Red": self.value = 100
        elif color == "Green": self.value = 200
        else: self.value = 300

    def update(self, direction):
        self.rect.x += direction


class Extra(pygame.sprite.Sprite):
    def __init__(self, side, screen_width):
        super().__init__()
        self.image = pygame.image.load("../Graphics/Extra.png").convert_alpha()
        
        if side == "right":
            x = screen_width + 50
            self.speed = -3 * SPD
        else:
            x = -50
            self.speed = 3 * SPD

        self.rect = self.image.get_rect(topleft = (x, 80))

    def update(self):
        self.rect.x += self.speed