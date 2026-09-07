import os
import json
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageTk

COLS = 12
CELL_PX = 24
SINGLE_ROWS = 150       # 150 * 32 = 4800px - a full hand-designed well
CHUNK_ROWS = 25         # shorter chunks meant to be combined randomly
NUM_CHUNKS = 4

BASE_DIR = os.environ.get("DOWNWELL_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
TERRAIN_DIR = os.path.join(BASE_DIR, "downwell_assets", "terrain")
SPRITE_DIR = os.path.join(BASE_DIR, "downwell_assets", "sprites")
LEVEL_FILE = os.path.join(BASE_DIR, "downwell_level.json")
CHUNK_FILE_TEMPLATE = os.path.join(BASE_DIR, "downwell_chunk_{}.json")
CHUNKS_CONFIG_FILE = os.path.join(BASE_DIR, "downwell_chunks_config.json")
DEFAULT_REPEAT_COUNT = 10

EMPTY_HEX = "#0b0d11"
GRID_LINE = "#1e2128"
START_HEX = "#1c3a5e"
PLACED_BG = "#1a1c22"


def load_thumb(path, size):
    img = Image.open(path).convert("RGBA")
    return img.resize((size, size), Image.NEAREST)


def json_to_cells(data, rows):
    cells = [[None for _ in range(COLS)] for _ in range(rows)]
    for row, col, ti in data.get("ground", []):
        if 0 <= row < rows and 0 <= col < COLS:
            cells[row][col] = ("ground", ti)
    for row, col in data.get("spikes", []):
        if 0 <= row < rows and 0 <= col < COLS:
            cells[row][col] = ("spike",)
    for row, col in data.get("enemies", []):
        if 0 <= row < rows and 0 <= col < COLS:
            cells[row][col] = ("enemy",)
    for row, col in data.get("gems", []):
        if 0 <= row < rows and 0 <= col < COLS:
            cells[row][col] = ("gem",)
    start_pos = None
    ps = data.get("player_start")
    if ps:
        start_pos = (ps[0], ps[1])
        if 0 <= ps[0] < rows and 0 <= ps[1] < COLS:
            cells[ps[0]][ps[1]] = ("start",)
    return cells, start_pos


def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


class GridEditor:
    """One paintable well-grid (used for both the single-level tab and each chunk)."""

    def __init__(self, parent, rows, terrain_paths, sprite_paths, status_setter, canvas_height=520):
        self.rows = rows
        self.terrain_paths = terrain_paths
        self.sprite_paths = sprite_paths
        self.status_setter = status_setter
        self.tool = ("ground", 0)
        self.photo_refs = []
        self.cell_photo_cache = {}
        self.start_pos = None

        self.cells = [[None for _ in range(COLS)] for _ in range(rows)]
        self.cell_rect_ids = [[None for _ in range(COLS)] for _ in range(rows)]
        self.cell_image_ids = [[None for _ in range(COLS)] for _ in range(rows)]

        self.frame = tk.Frame(parent, bg="#12141a")

        main = tk.Frame(self.frame, bg="#12141a")
        main.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        canvas_frame = tk.Frame(main, bg="#12141a")
        canvas_frame.pack(side="left", fill="both", expand=True)

        canvas_w = COLS * CELL_PX
        canvas_h = rows * CELL_PX
        self.canvas = tk.Canvas(
            canvas_frame, width=canvas_w + 4, height=canvas_height, bg=EMPTY_HEX,
            highlightthickness=2, highlightbackground="#3a3f4a",
            scrollregion=(0, 0, canvas_w, canvas_h),
        )
        vbar = tk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        for r in range(rows):
            for c in range(COLS):
                cid = self.canvas.create_rectangle(
                    c * CELL_PX, r * CELL_PX, (c + 1) * CELL_PX, (r + 1) * CELL_PX,
                    fill=EMPTY_HEX, outline=GRID_LINE,
                )
                self.cell_rect_ids[r][c] = cid

        self.canvas.bind("<Button-1>", self.paint)
        self.canvas.bind("<B1-Motion>", self.paint)
        self.canvas.bind("<Button-3>", self.erase)
        self.canvas.bind("<B3-Motion>", self.erase)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        subtitle_font = tkfont.Font(family="Segoe UI", size=11)
        button_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        side = tk.Frame(main, bg="#12141a", width=200)
        side.pack(side="left", fill="y", padx=(16, 0))
        side.pack_propagate(False)

        tk.Label(side, text="Terreno:", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w")
        terrain_frame = tk.Frame(side, bg="#12141a")
        terrain_frame.pack(pady=(4, 14))
        for i, path in enumerate(self.terrain_paths):
            thumb = load_thumb(path, 28)
            photo = ImageTk.PhotoImage(thumb)
            self.photo_refs.append(photo)
            tk.Button(
                terrain_frame, image=photo, relief="flat", bd=2,
                bg="#1d2028", activebackground="#3ea88f",
                command=lambda idx=i: self.select_tool(("ground", idx)),
            ).grid(row=i // 5, column=i % 5, padx=2, pady=2)

        tk.Label(side, text="Strumenti:", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w", pady=(4, 4))
        tool_frame = tk.Frame(side, bg="#12141a")
        tool_frame.pack(pady=(0, 14), fill="x")
        icon_specs = [("spike", "Spuntoni"), ("enemy", "Nemico"), ("gem", "Gemma"), ("start", "Partenza")]
        for tag, label in icon_specs:
            thumb = load_thumb(self.sprite_paths[tag], 26)
            photo = ImageTk.PhotoImage(thumb)
            self.photo_refs.append(photo)
            row = tk.Frame(tool_frame, bg="#12141a")
            row.pack(fill="x", pady=2)
            tk.Button(
                row, image=photo, relief="flat", bd=2, bg="#1d2028", activebackground="#3ea88f",
                command=lambda t=tag: self.select_tool((t,)),
            ).pack(side="left")
            tk.Label(row, text=label, font=subtitle_font, fg="white", bg="#12141a").pack(side="left", padx=8)

        tk.Label(
            side, text="Click sinistro: disegna\nClick destro: cancella\nRotella: scorri su/giu",
            font=subtitle_font, fg="#5a5f6c", bg="#12141a", justify="left",
        ).pack(anchor="w", pady=(4, 14))

        tk.Button(
            side, text="Svuota", font=button_font, bg="#3a3f4a", fg="white",
            activebackground="#484f5c", activeforeground="white", relief="flat", padx=12, pady=8,
            command=self.clear_all,
        ).pack(fill="x", pady=4)

        self.side_frame = side  # allow caller to pack extra buttons (e.g. Save) below

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)) * 3, "units")

    def select_tool(self, tool):
        self.tool = tool
        if tool[0] == "ground":
            self.status_setter(f"Strumento: Terreno #{tool[1] + 1}")
        else:
            names = {"spike": "Spuntoni", "enemy": "Nemico", "gem": "Gemma", "start": "Partenza"}
            self.status_setter(f"Strumento: {names[tool[0]]}")

    def _get_cell_photo(self, key, path):
        if key not in self.cell_photo_cache:
            thumb = load_thumb(path, CELL_PX - 2)
            self.cell_photo_cache[key] = ImageTk.PhotoImage(thumb)
        return self.cell_photo_cache[key]

    def _clear_cell_image(self, r, c):
        img_id = self.cell_image_ids[r][c]
        if img_id is not None:
            self.canvas.delete(img_id)
            self.cell_image_ids[r][c] = None

    def _render_cell(self, r, c):
        self._clear_cell_image(r, c)
        val = self.cells[r][c]
        cx = c * CELL_PX + CELL_PX // 2
        cy = r * CELL_PX + CELL_PX // 2
        if val is None:
            self.canvas.itemconfig(self.cell_rect_ids[r][c], fill=EMPTY_HEX)
            return
        if val[0] == "ground":
            self.canvas.itemconfig(self.cell_rect_ids[r][c], fill=PLACED_BG)
            photo = self._get_cell_photo(f"ground_{val[1]}", self.terrain_paths[val[1]])
            self.cell_image_ids[r][c] = self.canvas.create_image(cx, cy, image=photo)
            return
        self.canvas.itemconfig(self.cell_rect_ids[r][c], fill=START_HEX if val[0] == "start" else PLACED_BG)
        photo = self._get_cell_photo(val[0], self.sprite_paths[val[0]])
        self.cell_image_ids[r][c] = self.canvas.create_image(cx, cy, image=photo)

    def paint(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        c, r = int(cx // CELL_PX), int(cy // CELL_PX)
        if not (0 <= r < self.rows and 0 <= c < COLS):
            return
        if self.tool[0] == "start":
            if self.start_pos:
                pr, pc = self.start_pos
                self.cells[pr][pc] = None
                self._render_cell(pr, pc)
            self.start_pos = (r, c)
        self.cells[r][c] = self.tool
        self._render_cell(r, c)

    def erase(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        c, r = int(cx // CELL_PX), int(cy // CELL_PX)
        if not (0 <= r < self.rows and 0 <= c < COLS):
            return
        if self.cells[r][c] and self.cells[r][c][0] == "start":
            self.start_pos = None
        self.cells[r][c] = None
        self._render_cell(r, c)

    def clear_all(self):
        for r in range(self.rows):
            for c in range(COLS):
                if self.cells[r][c] is not None:
                    self.cells[r][c] = None
                    self._render_cell(r, c)
        self.start_pos = None
        self.status_setter("Griglia svuotata.")

    def load_cells(self, cells, start_pos):
        for r in range(self.rows):
            for c in range(COLS):
                self.cells[r][c] = cells[r][c]
        self.start_pos = start_pos
        for r in range(self.rows):
            for c in range(COLS):
                self._render_cell(r, c)

    def to_json_data(self):
        ground, spikes, enemies, gems = [], [], [], []
        for r in range(self.rows):
            for c in range(COLS):
                val = self.cells[r][c]
                if not val:
                    continue
                if val[0] == "ground":
                    ground.append([r, c, val[1]])
                elif val[0] == "spike":
                    spikes.append([r, c])
                elif val[0] == "enemy":
                    enemies.append([r, c])
                elif val[0] == "gem":
                    gems.append([r, c])
        return {
            "cols": COLS,
            "rows": self.rows,
            "ground": ground,
            "spikes": spikes,
            "enemies": enemies,
            "gems": gems,
            "player_start": list(self.start_pos) if self.start_pos else None,
        }


class LevelEditorApp:
    def __init__(self, root):
        self.root = root
        root.title("Editor Livelli - Downwell")
        root.geometry("800x700")
        root.configure(bg="#12141a")

        title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        subtitle_font = tkfont.Font(family="Segoe UI", size=11)
        button_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        tk.Label(root, text="Editor Livelli del Pozzo", font=title_font, fg="#7fd8c8", bg="#12141a").pack(pady=(12, 8))

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background="#12141a", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1d2028", foreground="white", padding=[16, 8], font=("Segoe UI", 11, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#3ea88f")], foreground=[("selected", "white")])

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        single_tab = tk.Frame(notebook, bg="#12141a")
        chunk_tab = tk.Frame(notebook, bg="#12141a")
        notebook.add(single_tab, text="Livello Singolo")
        notebook.add(chunk_tab, text="Blocchi Casuali")

        terrain_files = sorted(f for f in os.listdir(TERRAIN_DIR) if f.endswith(".png"))
        self.terrain_paths = [os.path.join(TERRAIN_DIR, f) for f in terrain_files]
        self.sprite_paths = {
            "spike": os.path.join(SPRITE_DIR, "spike.png"),
            "enemy": os.path.join(SPRITE_DIR, "enemy.png"),
            "gem": os.path.join(SPRITE_DIR, "gem.png"),
            "start": os.path.join(SPRITE_DIR, "player.png"),
        }

        # --- Single level tab ---
        self.status_label = tk.Label(root, text="", font=subtitle_font, fg="#f0c674", bg="#12141a")

        tk.Label(
            single_tab, text="Disegna il pozzo intero, dall'alto verso il basso (scorri con la rotella).",
            font=subtitle_font, fg="#c8ccd6", bg="#12141a",
        ).pack(pady=(6, 6))
        self.single_editor = GridEditor(
            single_tab, SINGLE_ROWS, self.terrain_paths, self.sprite_paths, self.set_status,
        )
        self.single_editor.frame.pack(fill="both", expand=True)
        tk.Button(
            self.single_editor.side_frame, text="Salva Livello", font=button_font, bg="#3ea88f", fg="white",
            activebackground="#4fc2a8", activeforeground="white", relief="flat", padx=12, pady=8,
            command=self.save_single_level,
        ).pack(fill="x", pady=4)

        # --- Chunk tab ---
        tk.Label(
            chunk_tab,
            text=f"Disegna {NUM_CHUNKS} blocchi piu' corti: il gioco li combinera' a caso per creare un pozzo lungo e vario.",
            font=subtitle_font, fg="#c8ccd6", bg="#12141a", wraplength=700, justify="left",
        ).pack(pady=(6, 6))

        repeat_frame = tk.Frame(chunk_tab, bg="#12141a")
        repeat_frame.pack(pady=(0, 8))
        tk.Label(
            repeat_frame, text="Quante volte ripetere prima di atterrare (fine del pozzo):",
            font=subtitle_font, fg="#8a8f9c", bg="#12141a",
        ).pack(side="left", padx=(0, 8))
        self.repeat_var = tk.IntVar(value=self._load_repeat_count())
        tk.Spinbox(
            repeat_frame, from_=1, to=50, textvariable=self.repeat_var, width=5,
            font=subtitle_font, bg="#1d2028", fg="white", buttonbackground="#252a35",
            relief="flat", justify="center",
        ).pack(side="left")

        chooser = tk.Frame(chunk_tab, bg="#12141a")
        chooser.pack(pady=(0, 8))
        self.chunk_buttons = []
        for i in range(1, NUM_CHUNKS + 1):
            btn = tk.Button(
                chooser, text=f"Blocco {i}", font=button_font, bg="#252a35", fg="white",
                activebackground="#3ea88f", activeforeground="white", relief="flat", padx=14, pady=6,
                command=lambda n=i: self.switch_chunk(n),
            )
            btn.pack(side="left", padx=4)
            self.chunk_buttons.append(btn)

        self.chunk_editor = GridEditor(
            chunk_tab, CHUNK_ROWS, self.terrain_paths, self.sprite_paths, self.set_status, canvas_height=480,
        )
        self.chunk_editor.frame.pack(fill="both", expand=True)
        tk.Button(
            self.chunk_editor.side_frame, text="Salva Questo Blocco", font=button_font, bg="#3ea88f", fg="white",
            activebackground="#4fc2a8", activeforeground="white", relief="flat", padx=12, pady=8,
            command=self.save_current_chunk,
        ).pack(fill="x", pady=4)

        self.status_label.pack(pady=(6, 10))

        # Reload the single level from disk, if one was already saved.
        single_data = load_json_file(LEVEL_FILE) if os.path.exists(LEVEL_FILE) else None
        if single_data:
            cells, start_pos = json_to_cells(single_data, SINGLE_ROWS)
            self.single_editor.load_cells(cells, start_pos)

        # Reload all 4 chunks from disk (if saved) so switching doesn't lose previous work.
        self.chunk_data = {}
        for i in range(1, NUM_CHUNKS + 1):
            path = CHUNK_FILE_TEMPLATE.format(i)
            data = load_json_file(path) if os.path.exists(path) else None
            if data:
                cells, start_pos = json_to_cells(data, CHUNK_ROWS)
            else:
                cells = [[None] * COLS for _ in range(CHUNK_ROWS)]
                start_pos = None
            self.chunk_data[i] = {"cells": cells, "start": start_pos}

        self.current_chunk = 1
        self.chunk_editor.load_cells(self.chunk_data[1]["cells"], self.chunk_data[1]["start"])
        self._highlight_chunk_button()

    def _load_repeat_count(self):
        if os.path.exists(CHUNKS_CONFIG_FILE):
            try:
                with open(CHUNKS_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get("repeat_count", DEFAULT_REPEAT_COUNT)
            except (json.JSONDecodeError, OSError):
                pass
        return DEFAULT_REPEAT_COUNT

    def _save_repeat_count(self):
        with open(CHUNKS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"repeat_count": int(self.repeat_var.get())}, f, ensure_ascii=False, indent=2)

    def set_status(self, text):
        self.status_label.config(text=text)

    def save_single_level(self):
        data = self.single_editor.to_json_data()
        with open(LEVEL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.set_status(f"Livello salvato in {os.path.basename(LEVEL_FILE)} - avvia downwell_clone.py per giocarlo!")

    def _highlight_chunk_button(self):
        for i, btn in enumerate(self.chunk_buttons, start=1):
            btn.config(bg="#3ea88f" if i == self.current_chunk else "#252a35")

    def switch_chunk(self, n):
        # stash current chunk's edits before switching
        self.chunk_data[self.current_chunk] = {
            "cells": [row[:] for row in self.chunk_editor.cells],
            "start": self.chunk_editor.start_pos,
        }
        self.current_chunk = n
        self._highlight_chunk_button()
        stored = self.chunk_data[n]
        self.chunk_editor.load_cells(stored["cells"], stored["start"])
        self.set_status(f"Stai modificando il Blocco {n}.")

    def save_current_chunk(self):
        self.chunk_data[self.current_chunk] = {
            "cells": [row[:] for row in self.chunk_editor.cells],
            "start": self.chunk_editor.start_pos,
        }
        data = self.chunk_editor.to_json_data()
        path = CHUNK_FILE_TEMPLATE.format(self.current_chunk)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._save_repeat_count()
        self.set_status(f"Blocco {self.current_chunk} salvato in {os.path.basename(path)} (ripetizioni: {self.repeat_var.get()}).")


def main():
    root = tk.Tk()
    LevelEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
