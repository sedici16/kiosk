import os
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageTk

SIZE = 16
CELL_PX = 26
SAVE_SCALE = 2  # matches how generate_terrain_tiles.py / generate_downwell_sprites.py saved these (16*2=32px)

RED = (206, 45, 45)
GRAY = (150, 150, 155)
TERRAIN_BG = (35, 35, 42)

COLOR_HEX = {"red": "#ce2d2d", "gray": "#96969b", "empty": "#23252c"}

BASE_DIR = os.environ.get("DOWNWELL_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
TERRAIN_DIR = os.path.join(BASE_DIR, "downwell_assets", "terrain")
SPRITE_DIR = os.path.join(BASE_DIR, "downwell_assets", "sprites")


def build_asset_list():
    assets = []
    terrain_files = sorted(f for f in os.listdir(TERRAIN_DIR) if f.endswith(".png"))
    for f in terrain_files:
        label = f.replace(".png", "").split("_", 1)[-1].replace("_", " ").title()
        assets.append({"label": f"Terreno: {label}", "path": os.path.join(TERRAIN_DIR, f), "is_terrain": True})
    assets.append({"label": "Personaggio", "path": os.path.join(SPRITE_DIR, "player.png"), "is_terrain": False})
    assets.append({"label": "Mostro", "path": os.path.join(SPRITE_DIR, "enemy.png"), "is_terrain": False})
    return assets


def classify_pixel(rgba, is_terrain):
    r, g, b, a = rgba
    if not is_terrain and a < 50:
        return "empty"
    if is_terrain and (r, g, b) == TERRAIN_BG:
        return "empty"
    dist_red = (r - RED[0]) ** 2 + (g - RED[1]) ** 2 + (b - RED[2]) ** 2
    dist_gray = (r - GRAY[0]) ** 2 + (g - GRAY[1]) ** 2 + (b - GRAY[2]) ** 2
    return "red" if dist_red < dist_gray else "gray"


def load_grid_from_file(path, is_terrain):
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    step_x = max(1, w // SIZE)
    step_y = max(1, h // SIZE)
    grid = [["empty" for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(SIZE):
        for x in range(SIZE):
            px = img.getpixel((min(x * step_x, w - 1), min(y * step_y, h - 1)))
            grid[y][x] = classify_pixel(px, is_terrain)
    return grid


class AssetEditor:
    def __init__(self, root):
        self.root = root
        root.title("Editor Sprite e Terreno - Downwell")
        root.geometry("900x640")
        root.configure(bg="#12141a")

        self.assets = build_asset_list()
        self.current_index = 0
        self.grid = [["empty" for _ in range(SIZE)] for _ in range(SIZE)]
        self.cell_ids = [[None] * SIZE for _ in range(SIZE)]
        self.preview_photo = None
        self.asset_buttons = []

        title_font = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        subtitle_font = tkfont.Font(family="Segoe UI", size=11)
        button_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        tk.Label(root, text="Editor Sprite e Terreno", font=title_font, fg="#7fd8c8", bg="#12141a").pack(pady=(14, 4))
        tk.Label(
            root, text="Scegli un elemento a sinistra, disegna a destra, poi salva.",
            font=subtitle_font, fg="#c8ccd6", bg="#12141a",
        ).pack(pady=(0, 10))

        main = tk.Frame(root, bg="#12141a")
        main.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # --- Asset list (left) ---
        list_frame = tk.Frame(main, bg="#181b22", width=220)
        list_frame.pack(side="left", fill="y")
        list_frame.pack_propagate(False)
        tk.Label(list_frame, text="Elementi:", font=subtitle_font, fg="#8a8f9c", bg="#181b22").pack(anchor="w", padx=10, pady=(10, 4))

        list_canvas = tk.Canvas(list_frame, bg="#181b22", highlightthickness=0)
        list_scroll = tk.Scrollbar(list_frame, orient="vertical", command=list_canvas.yview)
        list_inner = tk.Frame(list_canvas, bg="#181b22")
        list_inner.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.create_window((0, 0), window=list_inner, anchor="nw", width=190)
        list_canvas.configure(yscrollcommand=list_scroll.set)
        list_canvas.pack(side="left", fill="both", expand=True, padx=(6, 0))
        list_scroll.pack(side="right", fill="y")

        for i, asset in enumerate(self.assets):
            thumb = Image.open(asset["path"]).convert("RGBA").resize((24, 24), Image.NEAREST)
            photo = ImageTk.PhotoImage(thumb)
            btn = tk.Button(
                list_inner, text=" " + asset["label"], image=photo, compound="left", anchor="w",
                font=subtitle_font, fg="white", bg="#1d2028", activebackground="#3ea88f",
                activeforeground="white", relief="flat", padx=8, pady=6,
                command=lambda idx=i: self.select_asset(idx),
            )
            btn.image = photo
            btn.pack(fill="x", pady=2, padx=4)
            self.asset_buttons.append(btn)

        # --- Grid + tools (center/right) ---
        center = tk.Frame(main, bg="#12141a")
        center.pack(side="left", fill="both", expand=True, padx=(16, 0))

        canvas_size = SIZE * CELL_PX
        self.canvas = tk.Canvas(
            center, width=canvas_size, height=canvas_size, bg=COLOR_HEX["empty"],
            highlightthickness=2, highlightbackground="#3a3f4a",
        )
        self.canvas.grid(row=0, column=0, padx=(0, 20), pady=4)
        for y in range(SIZE):
            for x in range(SIZE):
                cid = self.canvas.create_rectangle(
                    x * CELL_PX, y * CELL_PX, (x + 1) * CELL_PX, (y + 1) * CELL_PX,
                    fill=COLOR_HEX["empty"], outline="#1a1c22",
                )
                self.cell_ids[y][x] = cid
        self.canvas.bind("<Button-1>", self.paint)
        self.canvas.bind("<B1-Motion>", self.paint)

        side = tk.Frame(center, bg="#12141a")
        side.grid(row=0, column=1, sticky="n")

        tk.Label(side, text="Colore:", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w")
        color_frame = tk.Frame(side, bg="#12141a")
        color_frame.pack(pady=(4, 18), anchor="w")
        self.color_var = tk.StringVar(value="red")
        for label, val in [("Rosso", "red"), ("Grigio", "gray"), ("Vuoto", "empty")]:
            tk.Radiobutton(
                color_frame, text=label, variable=self.color_var, value=val,
                font=subtitle_font, fg="white", bg="#12141a", selectcolor=COLOR_HEX[val],
                activebackground="#12141a", activeforeground="white", indicatoron=True,
            ).pack(anchor="w", pady=2)

        tk.Label(side, text="Anteprima (dimensione di gioco):", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w", pady=(8, 4))
        self.preview_label = tk.Label(side, bg=COLOR_HEX["empty"], width=96, height=96)
        self.preview_label.pack(pady=(0, 18))

        tk.Button(
            side, text="Ricarica Originale", font=button_font, bg="#3a3f4a", fg="white",
            activebackground="#484f5c", activeforeground="white", relief="flat", padx=12, pady=8,
            command=self.reload_current,
        ).pack(fill="x", pady=4)
        tk.Button(
            side, text="Salva", font=button_font, bg="#3ea88f", fg="white",
            activebackground="#4fc2a8", activeforeground="white", relief="flat", padx=12, pady=8,
            command=self.save_current,
        ).pack(fill="x", pady=4)

        self.status_label = tk.Label(root, text="", font=subtitle_font, fg="#f0c674", bg="#12141a")
        self.status_label.pack(pady=(0, 14))

        self.select_asset(0)

    def select_asset(self, index):
        self.current_index = index
        for i, btn in enumerate(self.asset_buttons):
            btn.config(bg="#3ea88f" if i == index else "#1d2028")
        self.reload_current()

    def reload_current(self):
        asset = self.assets[self.current_index]
        self.grid = load_grid_from_file(asset["path"], asset["is_terrain"])
        for y in range(SIZE):
            for x in range(SIZE):
                self.canvas.itemconfig(self.cell_ids[y][x], fill=COLOR_HEX[self.grid[y][x]])
        self.update_preview()
        self.status_label.config(text=f"Modifica: {asset['label']}")

    def paint(self, event):
        x = event.x // CELL_PX
        y = event.y // CELL_PX
        if 0 <= x < SIZE and 0 <= y < SIZE:
            color = self.color_var.get()
            if self.grid[y][x] != color:
                self.grid[y][x] = color
                self.canvas.itemconfig(self.cell_ids[y][x], fill=COLOR_HEX[color])
                self.update_preview()

    def _build_image(self, is_terrain):
        if is_terrain:
            img = Image.new("RGB", (SIZE, SIZE), TERRAIN_BG)
            px = img.load()
            colormap = {"red": RED, "gray": GRAY, "empty": TERRAIN_BG}
            for y in range(SIZE):
                for x in range(SIZE):
                    px[x, y] = colormap[self.grid[y][x]]
            return img.convert("RGBA")
        img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        px = img.load()
        colormap = {"red": (*RED, 255), "gray": (*GRAY, 255)}
        for y in range(SIZE):
            for x in range(SIZE):
                val = self.grid[y][x]
                if val in colormap:
                    px[x, y] = colormap[val]
        return img

    def update_preview(self):
        asset = self.assets[self.current_index]
        img = self._build_image(asset["is_terrain"]).resize((96, 96), Image.NEAREST)
        bg = Image.new("RGBA", (96, 96), (11, 13, 17, 255))
        bg.alpha_composite(img)
        self.preview_photo = ImageTk.PhotoImage(bg)
        self.preview_label.config(image=self.preview_photo)

    def save_current(self):
        asset = self.assets[self.current_index]
        img = self._build_image(asset["is_terrain"])
        out = img.resize((SIZE * SAVE_SCALE, SIZE * SAVE_SCALE), Image.NEAREST)
        if asset["is_terrain"]:
            out = out.convert("RGB")
        out.save(asset["path"])
        self.status_label.config(text=f"Salvato: {asset['label']} - riavvia downwell_clone.py per vedere le modifiche.")


def main():
    root = tk.Tk()
    AssetEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
