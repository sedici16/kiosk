import os
import sys
import re
import json
import time
import shutil
import subprocess
import threading
import queue
import compileall
import io
import contextlib
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import font as tkfont, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

import retropie_push

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "game_templates")
SESSIONS_DIR = os.path.join(BASE_DIR, "downwell_sessions")
SAVED_DIR = os.path.join(BASE_DIR, "downwell_saved_games")
UNDO_DIR = os.path.join(SESSIONS_DIR, "_undo")
GAME_SHOT = os.path.join(BASE_DIR, "_game_shot.py")
USAGE_TOTALS_PATH = os.path.join(BASE_DIR, "usage_totals.json")
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(SAVED_DIR, exist_ok=True)
os.makedirs(UNDO_DIR, exist_ok=True)

ZERO_USAGE = {"edits": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def load_usage_totals():
    """Running totals across the whole fair, persisted so an app restart
    doesn't lose the day's spend. Delete usage_totals.json to reset them."""
    try:
        with open(USAGE_TOTALS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {**ZERO_USAGE, **data}
    except (OSError, ValueError):
        return dict(ZERO_USAGE)


def save_usage_totals(totals):
    with open(USAGE_TOTALS_PATH, "w", encoding="utf-8") as fh:
        json.dump(totals, fh, ensure_ascii=False, indent=2)

CLAUDE_EXE = shutil.which("claude") or os.path.join(
    os.path.expanduser("~"), ".local", "bin", "claude.exe"
)
CLAUDE_MODEL = "sonnet"  # default if the visitor doesn't change it on the login screen

# Gemini is experimental: a single HTTP call (no Read/Edit tools like Claude
# Code), reads/rewrites only the game's main "run" file. Needs GEMINI_API_KEY
# set in the environment - the button/model choice is otherwise hidden.
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_PRICE_IN_PER_M = 0.25   # $/1M input tokens
GEMINI_PRICE_OUT_PER_M = 1.50  # $/1M output tokens

# (cli alias, button label, short hint) - offered on the login screen
MODEL_CHOICES = [
    ("haiku", "Haiku", "veloce, economico"),
    ("sonnet", "Sonnet", "bilanciato"),
    ("opus", "Opus", "qualità massima"),
]
if os.environ.get("GEMINI_API_KEY"):
    MODEL_CHOICES.append(("gemini", "Gemini", "sperimentale, molto economico"))

SESSION_MINUTES = 30

# RetroPie push target - read from retropie.json (git-ignored). None => the
# "Invia al RetroPie" button is hidden and nothing on the Pi is ever touched.
RETROPIE_CFG = retropie_push.load_config()

# how many frames to render before grabbing a thumbnail, per game
THUMB_FRAMES = {"downwell": 160, "space_invaders": 130, "platformer": 220, "racing": 150}

# Each game the visitor can pick. "run" is (script path, working dir) relative to
# the session directory; "editors" are extra Downwell-only authoring tools;
# "pi_slot" is the fixed name of its Ports entry on the RetroPie (one per game,
# each push overwrites it); "pi_data_dir" flags games needing DOWNWELL_DATA_DIR.
GAMES = {
    "downwell": {
        "label": "Il Pozzo",
        "blurb": "Scendi nel pozzo infinito sparando ai nemici e raccogliendo gemme.",
        "template": os.path.join(TEMPLATES_DIR, "downwell"),
        "run": ("downwell_clone.py", "."),
        "pi_slot": "Il Pozzo",
        "pi_data_dir": True,
        "editors": [
            ("Modifica Livello", "level_editor.py"),
            ("Modifica Sprite", "asset_editor.py"),
            ("Modifica Suoni", "sound_editor.py"),
        ],
    },
    "space_invaders": {
        "label": "Space Invaders",
        "blurb": "Il classico arcade: difendi la Terra dagli alieni che scendono.",
        "template": os.path.join(TEMPLATES_DIR, "space_invaders"),
        "run": (os.path.join("Code", "Main.py"), "."),
        "pi_slot": "Space Invaders",
        "editors": [],
    },
    "platformer": {
        "label": "Game of Crowns",
        "blurb": "Un platform 2D: salta di piattaforma in piattaforma, prendi le monete, evita il fuoco.",
        "template": os.path.join(TEMPLATES_DIR, "platformer"),
        "run": ("index.py", "."),
        "pi_slot": "Game of Crowns",
        "editors": [],
    },
    "racing": {
        "label": "Corsa Retro",
        "blurb": "Sfreccia sulla strada, schiva le auto in arrivo e fai piu punti che puoi.",
        "template": os.path.join(TEMPLATES_DIR, "racing"),
        "run": ("race.py", "."),
        "pi_slot": "Corsa Retro",
        "editors": [],
    },
}

GUARDRAILS = (
    "Sei un assistente che modifica un piccolo videogioco in Python (Pygame) per un "
    "visitatore di una fiera. Regole tassative:\n"
    "- Modifica SOLTANTO i file di gioco dentro la cartella di lavoro corrente.\n"
    "- Non uscire mai da questa cartella e non toccare altri file del computer.\n"
    "- Fai la modifica piu piccola e mirata possibile per soddisfare la richiesta.\n"
    "- Non aggiungere nuove librerie o dipendenze, non scaricare nulla da internet.\n"
    "- Non cancellare file. Dopo la modifica il gioco deve restare eseguibile.\n"
    "- Il codice deve restare compatibile con Python 3.5: NIENTE f-string "
    "(usa \"...{}\".format(...)), niente operatore walrus, niente novita' "
    "sintattiche successive alla 3.5.\n"
    "- NON toccare le righe che riguardano il cabinato: qualsiasi cosa con "
    "ON_PI, SPD, FRAME_CAP, kiosk_joy, kiosk_screen, platform.machine, "
    "pygame.display.set_mode. Modifica solo la logica di gioco.\n"
    "- Mantieni tutto adatto a famiglie e bambini.\n"
    "- Non eseguire comandi di shell e non provare a lanciare o compilare il gioco: "
    "limitati a leggere e modificare i file.\n"
    "- Alla fine rispondi in italiano, in 1-2 frasi, dicendo cosa hai cambiato.\n\n"
    "Richiesta del visitatore: "
)

# Gemini non ha tool Read/Edit: gli mandiamo l'intero file e ci aspettiamo
# indietro l'intero file modificato, testo puro (nessun markdown/spiegazione).
GEMINI_GUARDRAILS = (
    "Sei un assistente che modifica un piccolo videogioco in Python (Pygame) per un "
    "visitatore di una fiera. Regole tassative:\n"
    "- Modifica SOLTANTO la logica di gioco nel file che ti viene fornito.\n"
    "- Fai la modifica piu piccola e mirata possibile per soddisfare la richiesta.\n"
    "- Non aggiungere nuove librerie o dipendenze, non scaricare nulla da internet.\n"
    "- Non cancellare funzionalita' esistenti. Dopo la modifica il gioco deve restare eseguibile.\n"
    "- Il codice deve restare compatibile con Python 3.5: NIENTE f-string "
    "(usa \"...{}\".format(...)), niente operatore walrus, niente novita' "
    "sintattiche successive alla 3.5.\n"
    "- NON toccare le righe che riguardano il cabinato: qualsiasi cosa con "
    "ON_PI, SPD, FRAME_CAP, kiosk_joy, kiosk_screen, platform.machine, "
    "pygame.display.set_mode. Modifica solo la logica di gioco.\n"
    "- Mantieni tutto adatto a famiglie e bambini.\n\n"
    "Rispondi SOLO con il contenuto completo e aggiornato del file, dalla prima "
    "riga all'ultima, senza markdown, senza ``` attorno al codice, senza "
    "spiegazioni prima o dopo.\n\n"
    "Richiesta del visitatore: "
)


def safe_session_name(name):
    keep = [c if c.isalnum() else "_" for c in name.strip()]
    cleaned = "".join(keep).strip("_") or "ospite"
    return cleaned[:40]


def env_for(game_key, session_dir):
    env = os.environ.copy()
    env.pop("SDL_VIDEODRIVER", None)
    env.pop("SDL_AUDIODRIVER", None)
    if game_key == "downwell":
        env["DOWNWELL_DATA_DIR"] = session_dir
    return env


def load_hints(game_key):
    """Return the pre-computed {'analysis': str, 'suggestions': [str]*6} for a
    game, or None. Generated once by generate_hints.py into each template."""
    path = os.path.join(TEMPLATES_DIR, game_key, "ai_hints.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("analysis") and len(data.get("suggestions", [])) == 6:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def list_saved():
    """Saved games in SAVED_DIR, newest first: {dir, game_key, name, label, when}."""
    out = []
    if not os.path.isdir(SAVED_DIR):
        return out
    for entry in sorted(os.listdir(SAVED_DIR), reverse=True):
        folder = os.path.join(SAVED_DIR, entry)
        if not os.path.isdir(folder):
            continue
        game_key, name, when = None, entry, ""
        meta_path = os.path.join(folder, "session_meta.json")
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            game_key = m.get("game_key")
            name = m.get("name") or entry
            when = m.get("saved_at", "")
        except (OSError, json.JSONDecodeError):
            # older folders: parse "YYYYMMDD_HHMMSS_<gamekey>_<name>"
            rest = entry[16:] if len(entry) > 16 else entry
            for gk in GAMES:
                if rest.startswith(gk + "_"):
                    game_key, name = gk, rest[len(gk) + 1:]
                    break
            when = entry[:15]
        if game_key not in GAMES:
            continue
        out.append({
            "dir": folder, "game_key": game_key, "name": name,
            "label": GAMES[game_key]["label"], "when": when,
        })
    return out


def launch_game_dir(game_key, folder):
    """Run the game located in `folder` (a template, session, or saved copy)."""
    script_rel, cwd_rel = GAMES[game_key]["run"]
    subprocess.Popen(
        [sys.executable, os.path.join(folder, script_rel)],
        cwd=os.path.join(folder, cwd_rel), env=env_for(game_key, folder),
    )


def snapshot_game(game_key, folder):
    """Best-effort: render the game headless and save folder/thumb.png. Silent on failure."""
    if not os.path.exists(GAME_SHOT):
        return
    script_rel, cwd_rel = GAMES[game_key]["run"]
    out = os.path.join(folder, "thumb.png")
    frames = THUMB_FRAMES.get(game_key, 150)
    env = env_for(game_key, folder)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    try:
        subprocess.run(
            [sys.executable, GAME_SHOT, os.path.join(folder, script_rel), out, str(frames)],
            cwd=os.path.join(folder, cwd_rel), env=env,
            capture_output=True, timeout=45,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


_THUMB_CACHE = {}

def get_thumb(game_key, folder=None, size=(240, 168)):
    """A Tk image for a game: the folder's own thumb.png if present, else the
    template's. Returns None if PIL is missing or nothing can be loaded."""
    if ImageTk is None:
        return None
    candidates = []
    if folder:
        candidates.append(os.path.join(folder, "thumb.png"))
    candidates.append(os.path.join(TEMPLATES_DIR, game_key, "thumb.png"))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        key = (path, size, os.path.getmtime(path))
        if key not in _THUMB_CACHE:
            try:
                img = Image.open(path).convert("RGB")
                img.thumbnail(size, Image.LANCZOS)
                _THUMB_CACHE[key] = ImageTk.PhotoImage(img)
            except Exception:
                continue
        return _THUMB_CACHE[key]
    return None


def compile_check(session_dir):
    """Return a list of (path, error) for any .py file that no longer parses."""
    errors = []
    buf = io.StringIO()
    for root, _dirs, files in os.walk(session_dir):
        if os.path.basename(root) == "__pycache__":
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                ok = compileall.compile_file(path, quiet=2, force=True)
            if not ok:
                rel = os.path.relpath(path, session_dir)
                errors.append(rel)
    return errors


class Dashboard:
    def __init__(self, root):
        self.root = root
        root.title("Postazione Fiera - Modifica il Gioco con l'IA")
        root.geometry("1400x880")
        root.configure(bg="#12141a")

        self.title_font = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.subtitle_font = tkfont.Font(family="Segoe UI", size=11)
        self.button_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.big_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        self.mono_font = tkfont.Font(family="Consolas", size=20, weight="bold")

        self.session_dir = None
        self.session_name = None
        self.game_key = None
        self.ai_model = CLAUDE_MODEL
        self.deadline = None
        self.timer_job = None

        self.usage_totals = load_usage_totals()
        self.session_usage = dict(ZERO_USAGE)

        self.ai_queue = queue.Queue()
        self.ai_running = False
        self.ai_proc = None
        self.can_undo = False
        self.pi_sending = False

        self.container = tk.Frame(root, bg="#12141a")
        self.container.pack(fill="both", expand=True)

        self.show_login()

    def _clear(self):
        if self.timer_job:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None
        for w in self.container.winfo_children():
            w.destroy()

    # ------------------------------------------------------------ Login screen
    def show_login(self):
        self._clear()
        self.session_dir = None
        self.session_name = None
        self.game_key = None
        self.can_undo = False

        tk.Label(
            self.container, text="Modifica il Gioco con l'IA", font=self.title_font,
            fg="#7fd8c8", bg="#12141a",
        ).pack(pady=(56, 6))
        tk.Label(
            self.container,
            text="Scrivi il tuo nome, scegli un gioco e hai 30 minuti per trasformarlo a parole.",
            font=self.subtitle_font, fg="#c8ccd6", bg="#12141a",
        ).pack(pady=(0, 26))

        name_var = tk.StringVar()
        entry = tk.Entry(self.container, textvariable=name_var, font=self.button_font, width=24, justify="center")
        entry.pack(pady=(0, 16))
        entry.focus_set()

        model_var = tk.StringVar(value=self.ai_model)
        model_row = tk.Frame(self.container, bg="#12141a")
        model_row.pack(pady=(0, 22))
        tk.Label(
            model_row, text="Modello IA:", font=self.subtitle_font, fg="#c8ccd6", bg="#12141a",
        ).pack(side="left", padx=(0, 10))
        model_buttons = {}

        def pick_model(m):
            model_var.set(m)
            for key, btn in model_buttons.items():
                btn.config(bg="#3ea88f" if key == m else "#20242e")

        for key, label, hint in MODEL_CHOICES:
            btn = tk.Button(
                model_row, text=f"{label}\n{hint}", font=("Segoe UI", 9, "bold"),
                fg="white", relief="flat", padx=14, pady=6, justify="center",
                activeforeground="white", command=lambda k=key: pick_model(k),
            )
            btn.pack(side="left", padx=4)
            model_buttons[key] = btn
        pick_model(model_var.get())

        cards = tk.Frame(self.container, bg="#12141a")
        cards.pack(pady=(0, 10))

        def start(game_key):
            name = name_var.get().strip() or "Ospite"
            self.start_session(name, game_key, model=model_var.get())

        for game_key, meta in GAMES.items():
            card = tk.Frame(cards, bg="#181b22", highlightbackground="#2a2f36", highlightthickness=1)
            card.pack(side="left", padx=14, ipadx=8, ipady=8)
            thumb = get_thumb(game_key, size=(240, 165))
            if thumb is not None:
                tk.Label(card, image=thumb, bg="#181b22").pack(pady=(14, 4), padx=14)
            tk.Label(card, text=meta["label"], font=self.big_font, fg="#7fd8c8", bg="#181b22").pack(pady=(6, 4), padx=18)
            tk.Label(
                card, text=meta["blurb"], font=self.subtitle_font, fg="#c8ccd6", bg="#181b22",
                wraplength=240, justify="center",
            ).pack(pady=(0, 12), padx=18)
            tk.Button(
                card, text="Scegli", font=self.button_font, bg="#3ea88f", fg="white",
                activebackground="#4fc2a8", activeforeground="white", relief="flat", padx=22, pady=10,
                command=lambda k=game_key: start(k),
            ).pack(pady=(0, 14))

        self.totals_usage_label = tk.Label(
            self.container, text="", font=("Segoe UI", 9), fg="#5a5f6a", bg="#12141a",
        )
        self.totals_usage_label.pack(pady=(4, 0))
        self._update_usage_labels()

        # ---- saved games: play again, or resume improving ----
        saved = list_saved()
        if not saved:
            return

        tk.Label(
            self.container, text="Giochi salvati", font=("Segoe UI", 13, "bold"),
            fg="#7fd8c8", bg="#12141a",
        ).pack(pady=(24, 2))
        tk.Label(
            self.container,
            text="\"Gioca\" apre la versione salvata. \"Riprendi\" la carica per continuare a migliorarla (serve il nome sopra).",
            font=("Segoe UI", 9), fg="#8a8f9c", bg="#12141a",
        ).pack(pady=(0, 8))

        outer = tk.Frame(self.container, bg="#181b22")
        outer.pack(fill="both", expand=True, padx=120, pady=(0, 20))
        canvas = tk.Canvas(outer, bg="#181b22", highlightthickness=0, height=260)
        sb = tk.Scrollbar(outer, command=canvas.yview)
        inner = tk.Frame(canvas, bg="#181b22")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=840)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def play(s):
            launch_game_dir(s["game_key"], s["dir"])

        def resume(s):
            name = name_var.get().strip() or "Ospite"
            self.start_session(name, s["game_key"], source_dir=s["dir"], model=model_var.get())

        def delete(s):
            if not messagebox.askyesno(
                "Elimina", f"Eliminare definitivamente il gioco salvato\n\"{s['label']} - {s['name']}\"?"
            ):
                return
            shutil.rmtree(s["dir"], ignore_errors=True)
            self.show_login()

        for s in saved:
            row = tk.Frame(inner, bg="#20242e")
            row.pack(fill="x", pady=3, padx=4)
            rthumb = get_thumb(s["game_key"], folder=s["dir"], size=(72, 54))
            if rthumb is not None:
                tk.Label(row, image=rthumb, bg="#20242e").pack(side="left", padx=(8, 4), pady=6)
            txt = f"{s['label']}  -  {s['name']}"
            if s["when"]:
                txt += f"   ({s['when']})"
            tk.Label(
                row, text=txt, font=("Segoe UI", 10), fg="white", bg="#20242e", anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=10, pady=8)
            tk.Button(
                row, text="Elimina", font=("Segoe UI", 9, "bold"), bg="#8a3a3a", fg="white",
                relief="flat", padx=10, pady=4, command=lambda s=s: delete(s),
            ).pack(side="right", padx=(4, 8), pady=6)
            tk.Button(
                row, text="Riprendi", font=("Segoe UI", 9, "bold"), bg="#3ea88f", fg="white",
                relief="flat", padx=10, pady=4, command=lambda s=s: resume(s),
            ).pack(side="right", padx=4, pady=6)
            tk.Button(
                row, text="Gioca", font=("Segoe UI", 9, "bold"), bg="#4a7fd6", fg="white",
                relief="flat", padx=10, pady=4, command=lambda s=s: play(s),
            ).pack(side="right", padx=4, pady=6)

    def start_session(self, name, game_key, source_dir=None, model=None):
        meta = GAMES[game_key]
        source = source_dir or meta["template"]
        if not os.path.isdir(source):
            messagebox.showerror("Errore", f"Cartella di origine mancante:\n{source}")
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        session_dir = os.path.join(SESSIONS_DIR, f"{stamp}_{game_key}_{safe_session_name(name)}")
        shutil.copytree(source, session_dir)

        self.session_name = name
        self.game_key = game_key
        self.session_dir = session_dir
        self.ai_model = model or CLAUDE_MODEL
        self.session_usage = dict(ZERO_USAGE)
        self.deadline = time.time() + SESSION_MINUTES * 60
        self.can_undo = False
        self.show_main()
        self.tick_timer()
        self.root.after(120, self.poll_ai_queue)

    # ------------------------------------------------------------- Main screen
    def show_main(self):
        self._clear()
        meta = GAMES[self.game_key]

        top = tk.Frame(self.container, bg="#12141a")
        top.pack(fill="x", padx=20, pady=(16, 6))
        tk.Label(
            top, text=f"{meta['label']} - sessione di {self.session_name}",
            font=self.title_font, fg="#7fd8c8", bg="#12141a",
        ).pack(side="left")
        self.timer_label = tk.Label(top, text="30:00", font=self.mono_font, fg="#f0c674", bg="#12141a")
        self.timer_label.pack(side="right")

        info_row = tk.Frame(self.container, bg="#12141a")
        info_row.pack(fill="x", padx=24, pady=(0, 8))
        tk.Label(
            info_row, text=f"Modello IA: {self.ai_model.capitalize()}",
            font=("Segoe UI", 9), fg="#8a8f9c", bg="#12141a",
        ).pack(side="left")
        self.session_usage_label = tk.Label(
            info_row, text="", font=("Segoe UI", 9), fg="#8a8f9c", bg="#12141a",
        )
        self.session_usage_label.pack(side="left", padx=(18, 0))
        self._update_usage_labels()

        tools = tk.Frame(self.container, bg="#12141a")
        tools.pack(fill="x", padx=20, pady=(10, 10))
        self.play_btn = tk.Button(
            tools, text="Gioca", font=self.button_font, bg="#4a7fd6", fg="white",
            activebackground="#5c8fe0", activeforeground="white", relief="flat", padx=18, pady=10,
            command=self.play_game,
        )
        self.play_btn.pack(side="left", padx=(0, 10))

        self.pi_btn = None
        if RETROPIE_CFG and meta.get("pi_slot"):
            self.pi_btn = tk.Button(
                tools, text="Invia al cabinato (RetroPie)", font=self.button_font,
                bg="#7a5cd0", fg="white", activebackground="#8f72e0", activeforeground="white",
                relief="flat", padx=16, pady=10, command=self.send_to_retropie,
            )
            self.pi_btn.pack(side="left", padx=(0, 10))

        for text, script in meta["editors"]:
            tk.Button(
                tools, text=text, font=self.button_font, bg="#2a2f3a", fg="white",
                activebackground="#3a4150", activeforeground="white", relief="flat", padx=16, pady=10,
                command=lambda s=script: self.launch_script(s),
            ).pack(side="left", padx=(0, 10))
        self.undo_btn = tk.Button(
            tools, text="Annulla ultima modifica", font=self.button_font, bg="#3a3f4a", fg="white",
            activebackground="#484f5c", activeforeground="white", relief="flat", padx=16, pady=10,
            command=self.undo_last, state="disabled",
        )
        self.undo_btn.pack(side="right")

        self._build_hints_panel()

        ai_frame = tk.Frame(self.container, bg="#181b22")
        ai_frame.pack(fill="both", expand=True, padx=20, pady=(4, 10))
        tk.Label(
            ai_frame, text="Assistente IA - descrivi a parole come vuoi cambiare il gioco",
            font=self.subtitle_font, fg="#8a8f9c", bg="#181b22",
        ).pack(anchor="w", padx=12, pady=(10, 4))

        entry_row = tk.Frame(ai_frame, bg="#181b22")
        entry_row.pack(fill="x", padx=12, pady=(0, 8))
        self.ai_entry = tk.Entry(entry_row, font=self.subtitle_font)
        self.ai_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=6)
        self.ai_entry.bind("<Return>", lambda e: self.apply_ai_request())
        self.ai_button = tk.Button(
            entry_row, text="Applica", font=self.button_font, bg="#4a7fd6", fg="white",
            activebackground="#5c8fe0", activeforeground="white", relief="flat", padx=16, pady=6,
            command=self.apply_ai_request,
        )
        self.ai_button.pack(side="left")

        self.ai_log = tk.Text(
            ai_frame, height=9, bg="#0b0d11", fg="#c8ccd6", font=("Consolas", 10),
            relief="flat", highlightthickness=1, highlightbackground="#2a2f36", wrap="word",
        )
        self.ai_log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.ai_log.config(state="disabled")

        if not os.path.exists(CLAUDE_EXE):
            self._log_ai("Claude Code non trovato - l'assistente IA non e' disponibile.")
            self.ai_button.config(state="disabled")
        else:
            self._log_ai(
                f"Pronto. Stai modificando {meta['label']}. Esempi: "
                "\"rendi il giocatore piu veloce\", \"aggiungi un punteggio piu alto per i nemici gialli\", "
                "\"cambia il colore dello sfondo in blu notte\"."
            )

        bottom = tk.Frame(self.container, bg="#12141a")
        bottom.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(
            bottom, text="Termina e Salva", font=self.button_font, bg="#3ea88f", fg="white",
            activebackground="#4fc2a8", activeforeground="white", relief="flat", padx=20, pady=10,
            command=lambda: self.end_session(save=True),
        ).pack(side="left", padx=(0, 10))
        tk.Button(
            bottom, text="Termina Senza Salvare", font=self.button_font, bg="#3a3f4a", fg="white",
            activebackground="#484f5c", activeforeground="white", relief="flat", padx=20, pady=10,
            command=lambda: self.end_session(save=False),
        ).pack(side="left")

    def _build_hints_panel(self):
        hints = load_hints(self.game_key)
        frame = tk.Frame(self.container, bg="#181b22")
        frame.pack(fill="x", padx=20, pady=(4, 0))

        if not hints:
            tk.Label(
                frame, text="(Nessun consiglio dell'IA disponibile per questo gioco.)",
                font=self.subtitle_font, fg="#8a8f9c", bg="#181b22",
            ).pack(anchor="w", padx=12, pady=10)
            return

        tk.Label(
            frame, text="Consiglio dell'IA per questo gioco",
            font=("Segoe UI", 12, "bold"), fg="#7fd8c8", bg="#181b22",
        ).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Message(
            frame, text=hints["analysis"], width=1040,
            font=self.subtitle_font, fg="#dfe3ea", bg="#181b22", justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        tk.Label(
            frame, text="Idee veloci - clicca per metterle nel riquadro qui sotto",
            font=self.subtitle_font, fg="#8a8f9c", bg="#181b22",
        ).pack(anchor="w", padx=12, pady=(0, 4))

        grid = tk.Frame(frame, bg="#181b22")
        grid.pack(fill="x", padx=10, pady=(0, 12))
        for i in range(3):
            grid.columnconfigure(i, weight=1, uniform="hint")
        for idx, text in enumerate(hints["suggestions"][:6]):
            r, c = divmod(idx, 3)
            tk.Button(
                grid, text=text, font=("Segoe UI", 10), bg="#252a35", fg="white",
                activebackground="#333a48", activeforeground="white", relief="flat",
                wraplength=320, justify="left", padx=10, pady=8,
                command=lambda t=text: self.use_suggestion(t),
            ).grid(row=r, column=c, sticky="nsew", padx=4, pady=4)

    def use_suggestion(self, text):
        if self.ai_running:
            return
        self.ai_entry.delete(0, "end")
        self.ai_entry.insert(0, text)
        self.ai_entry.focus_set()

    def tick_timer(self):
        remaining = int(self.deadline - time.time())
        if remaining <= 0:
            self.timer_label.config(text="00:00")
            messagebox.showinfo("Tempo scaduto", "I 30 minuti sono terminati! Grazie per aver giocato.")
            self.end_session(save=True)
            return
        mins, secs = divmod(remaining, 60)
        self.timer_label.config(text=f"{mins:02d}:{secs:02d}")
        if remaining <= 60:
            self.timer_label.config(fg="#e05a5a")
        self.timer_job = self.root.after(1000, self.tick_timer)

    # ------------------------------------------------------------- Launch game
    def _launch(self, script_rel, cwd_rel="."):
        script_path = os.path.join(self.session_dir, script_rel)
        cwd = os.path.join(self.session_dir, cwd_rel)
        subprocess.Popen(
            [sys.executable, script_path], cwd=cwd, env=env_for(self.game_key, self.session_dir)
        )

    def play_game(self):
        script_rel, cwd_rel = GAMES[self.game_key]["run"]
        self._launch(script_rel, cwd_rel)

    def launch_script(self, script):
        self._launch(script, ".")

    # ------------------------------------------------------------ AI assistant
    def _log_ai(self, text, tag=None):
        self.ai_log.config(state="normal")
        self.ai_log.insert("end", text + "\n")
        self.ai_log.see("end")
        self.ai_log.config(state="disabled")

    def apply_ai_request(self):
        if self.ai_running or self.pi_sending:
            return
        prompt = self.ai_entry.get().strip()
        if not prompt:
            return
        self.ai_entry.delete(0, "end")
        self._log_ai(f"\n> {prompt}")

        # Snapshot for undo.
        undo_path = os.path.join(UNDO_DIR, os.path.basename(self.session_dir))
        if os.path.isdir(undo_path):
            shutil.rmtree(undo_path)
        shutil.copytree(self.session_dir, undo_path)

        self.ai_running = True
        self.ai_button.config(state="disabled", text="Lavoro...")
        self.ai_entry.config(state="disabled")
        self.undo_btn.config(state="disabled")
        if self.pi_btn:
            self.pi_btn.config(state="disabled")
        self._log_ai("  L'IA sta leggendo e modificando il gioco...")
        target = self._run_gemini if self.ai_model == "gemini" else self._run_claude
        threading.Thread(target=target, args=(prompt,), daemon=True).start()

    def _run_claude(self, prompt):
        cmd = [
            CLAUDE_EXE, "-p", GUARDRAILS + prompt,
            "--add-dir", self.session_dir,
            "--allowedTools", "Read", "Edit", "Write", "Glob", "Grep",
            "--disallowedTools", "Bash", "PowerShell", "KillShell", "BashOutput",
            "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
            "--permission-mode", "acceptEdits",
            "--model", self.ai_model,
            "--output-format", "stream-json", "--verbose",
        ]
        try:
            proc = subprocess.Popen(
                cmd, cwd=self.session_dir, env=os.environ.copy(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            self.ai_queue.put(("error", f"Impossibile avviare Claude Code: {exc}"))
            return
        self.ai_proc = proc
        final_text = ""
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        self.ai_queue.put(("text", block["text"].strip()))
                    elif block.get("type") == "tool_use":
                        self.ai_queue.put(("tool", self._describe_tool(block)))
            elif etype == "result":
                final_text = event.get("result", "") or final_text
                usage = event.get("usage") or {}
                self.ai_queue.put(("usage", {
                    "input_tokens": (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                    ),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cost_usd": event.get("total_cost_usd") or 0.0,
                }))
                if event.get("is_error"):
                    self.ai_queue.put(("error", final_text or "L'IA ha riportato un errore."))
                else:
                    self.ai_queue.put(("done", final_text))
        err = proc.stderr.read()
        rc = proc.wait()
        if rc != 0 and not final_text:
            self.ai_queue.put(("error", (err or f"Claude Code terminato con codice {rc}").strip()))

    def _run_gemini(self, prompt):
        """Sperimentale: niente tool Read/Edit come Claude Code, un'unica
        chiamata HTTP che manda l'intero file "run" del gioco e si aspetta
        indietro l'intero file modificato. Non tocca gli altri file (editor,
        moduli separati) - per giochi multi-file la copertura e' parziale."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.ai_queue.put(("error", "Gemini non configurato: manca GEMINI_API_KEY."))
            return

        script_rel, _ = GAMES[self.game_key]["run"]
        path = os.path.join(self.session_dir, script_rel)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                original = fh.read()
        except OSError as exc:
            self.ai_queue.put(("error", f"Impossibile leggere {script_rel}: {exc}"))
            return

        full_prompt = (
            GEMINI_GUARDRAILS + prompt
            + "\n\n--- " + script_rel + " ---\n" + original
        )
        body = json.dumps({"contents": [{"parts": [{"text": full_prompt}]}]}).encode("utf-8")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + GEMINI_MODEL + ":generateContent?key=" + api_key
        )
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            self.ai_queue.put(("error", f"Gemini ha risposto con errore {exc.code}: {detail[:300]}"))
            return
        except Exception as exc:  # noqa: BLE001 - rete/JSON, non deve far crashare la UI
            self.ai_queue.put(("error", f"Impossibile contattare Gemini: {exc}"))
            return

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            self.ai_queue.put(("error", "Gemini non ha restituito codice utilizzabile."))
            return

        text = re.sub(r"^```(?:python)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)

        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            self.ai_queue.put(("error", f"Impossibile scrivere {script_rel}: {exc}"))
            return

        usage = data.get("usageMetadata", {})
        in_tok = usage.get("promptTokenCount", 0)
        out_tok = usage.get("candidatesTokenCount", 0)
        cost = in_tok / 1_000_000 * GEMINI_PRICE_IN_PER_M + out_tok / 1_000_000 * GEMINI_PRICE_OUT_PER_M
        self.ai_queue.put(("usage", {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": cost,
        }))

        # Gemini non ha potuto leggere gli altri file (Alien.py, gli assets, ...)
        # quindi puo' scrivere codice sintatticamente valido ma che va in crash
        # all'avvio (es. un colore/asset inventato che non esiste). Un
        # py_compile non lo scoprirebbe: proviamo a far partire il gioco
        # headless, e se crasha ripristiniamo subito il file di prima.
        crash = self._smoke_test_game()
        if crash:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(original)
            self.ai_queue.put((
                "error",
                "Gemini ha scritto codice che va in crash all'avvio (probabilmente un "
                "riferimento a qualcosa che non esiste, es. un colore/immagine). "
                "Modifica annullata automaticamente, il file e' tornato com'era prima.\n"
                "  Dettaglio: " + crash
            ))
            return

        self.ai_queue.put(("done", f"Fatto con Gemini: modificato {script_rel}."))

    def _smoke_test_game(self):
        """Run the session's game headless for a few frames to catch runtime
        crashes Gemini's blind single-file edits can introduce. Returns None
        if it ran fine, or a short error string if it crashed/hung."""
        if not os.path.exists(GAME_SHOT):
            return None
        script_rel, cwd_rel = GAMES[self.game_key]["run"]
        out_png = os.path.join(self.session_dir, "_smoke_test.png")
        frames = THUMB_FRAMES.get(self.game_key, 150)
        env = env_for(self.game_key, self.session_dir)
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        try:
            proc = subprocess.run(
                [sys.executable, GAME_SHOT, os.path.join(self.session_dir, script_rel), out_png, str(frames)],
                cwd=os.path.join(self.session_dir, cwd_rel), env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
            )
        except subprocess.TimeoutExpired:
            return "il gioco non ha risposto entro 40 secondi."
        finally:
            if os.path.exists(out_png):
                try:
                    os.remove(out_png)
                except OSError:
                    pass
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()
            return tail[-1] if tail else f"uscito con codice {proc.returncode}."
        return None

    @staticmethod
    def _describe_tool(block):
        name = block.get("name", "?")
        inp = block.get("input", {}) or {}
        target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
        if target:
            target = os.path.basename(str(target))
        labels = {"Read": "Leggo", "Edit": "Modifico", "Write": "Riscrivo", "Glob": "Cerco", "Grep": "Cerco"}
        return f"  - {labels.get(name, name)} {target}".rstrip()

    def poll_ai_queue(self):
        try:
            while True:
                kind, payload = self.ai_queue.get_nowait()
                if kind in ("text", "tool"):
                    self._log_ai(payload)
                elif kind == "usage":
                    self._record_usage(payload)
                elif kind == "done":
                    self._finish_ai(payload, ok=True)
                elif kind == "error":
                    self._finish_ai(payload, ok=False)
        except queue.Empty:
            pass
        self.root.after(150, self.poll_ai_queue)

    def _record_usage(self, usage):
        for d in (self.session_usage, self.usage_totals):
            d["edits"] += 1
            d["input_tokens"] += usage["input_tokens"]
            d["output_tokens"] += usage["output_tokens"]
            d["cost_usd"] += usage["cost_usd"]
        save_usage_totals(self.usage_totals)
        self._update_usage_labels()

    def _update_usage_labels(self):
        label = getattr(self, "session_usage_label", None)
        if label is not None and label.winfo_exists():
            u = self.session_usage
            total_tokens = u["input_tokens"] + u["output_tokens"]
            label.config(
                text=f"Questa sessione: {u['edits']} modifiche - "
                     f"{total_tokens:,} token - ${u['cost_usd']:.3f}"
            )
        label = getattr(self, "totals_usage_label", None)
        if label is not None and label.winfo_exists():
            t = self.usage_totals
            total_tokens = t["input_tokens"] + t["output_tokens"]
            label.config(
                text=f"Totale fiera: {t['edits']} modifiche - "
                     f"{total_tokens:,} token - ${t['cost_usd']:.3f}"
            )

    def _finish_ai(self, message, ok):
        self.ai_running = False
        self.ai_proc = None
        self.ai_button.config(state="normal", text="Applica")
        self.ai_entry.config(state="normal")
        if self.pi_btn:
            self.pi_btn.config(state="normal")

        errors = compile_check(self.session_dir)
        if errors:
            self._log_ai(
                "  ATTENZIONE: dopo la modifica alcuni file non sono validi: "
                + ", ".join(errors)
                + "\n  Premi 'Annulla ultima modifica' per tornare indietro."
            )
        elif ok:
            if message:
                self._log_ai(f"  {message}")
            self._log_ai("  Fatto. Premi 'Gioca' per provare.")
        else:
            self._log_ai(f"  Non e' andata a buon fine: {message}")
            self._log_ai("  Puoi riprovare, o premere 'Annulla ultima modifica'.")

        self.can_undo = True
        self.undo_btn.config(state="normal")

    def undo_last(self):
        if self.ai_running or not self.can_undo:
            return
        undo_path = os.path.join(UNDO_DIR, os.path.basename(self.session_dir))
        if not os.path.isdir(undo_path):
            self._log_ai("  Niente da annullare.")
            return
        shutil.rmtree(self.session_dir)
        shutil.copytree(undo_path, self.session_dir)
        self.can_undo = False
        self.undo_btn.config(state="disabled")
        self._log_ai("  Ultima modifica annullata: il gioco e' tornato com'era prima.")

    # ---------------------------------------------------------- Send to RetroPie
    def send_to_retropie(self):
        if self.pi_sending or self.ai_running or not self.session_dir or not self.pi_btn:
            return
        meta = GAMES[self.game_key]
        slot = meta["pi_slot"]
        run_rel = meta["run"][0].replace("\\", "/")   # POSIX path for the Pi
        self.pi_sending = True
        self.pi_btn.config(state="disabled", text="Invio al cabinato...")
        self._log_ai(f"\n> Invio \"{meta['label']}\" al cabinato RetroPie")
        threading.Thread(
            target=self._run_pi_push,
            args=(slot, run_rel, self.session_dir, bool(meta.get("pi_data_dir"))),
            daemon=True,
        ).start()

    def _run_pi_push(self, slot, run_rel, local_dir, data_dir_env):
        def progress(msg):
            self.root.after(0, lambda m=msg: self._log_ai(f"  [RetroPie] {m}"))
        try:
            ok, message = retropie_push.push(
                slot, run_rel, local_dir, data_dir_env=data_dir_env, progress=progress
            )
        except Exception as exc:  # noqa: BLE001 - never let the thread die silently
            ok, message = False, f"Errore imprevisto: {exc}"
        self.root.after(0, lambda: self._finish_pi(ok, message))

    def _finish_pi(self, ok, message):
        self.pi_sending = False
        if self.pi_btn:
            self.pi_btn.config(state="normal", text="Invia al cabinato (RetroPie)")
        self._log_ai(f"  {'OK' if ok else 'ERRORE'}: {message}")
        if ok:
            messagebox.showinfo("RetroPie", message)
        else:
            messagebox.showwarning("RetroPie", message)

    # ------------------------------------------------------------- Session end
    def end_session(self, save):
        if self.ai_proc is not None:
            try:
                self.ai_proc.kill()
            except OSError:
                pass
        if save and self.session_dir:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(
                SAVED_DIR, f"{stamp}_{self.game_key}_{safe_session_name(self.session_name)}"
            )
            shutil.copytree(self.session_dir, dest)
            try:
                with open(os.path.join(dest, "session_meta.json"), "w", encoding="utf-8") as f:
                    json.dump({"game_key": self.game_key, "name": self.session_name,
                               "saved_at": time.strftime("%Y-%m-%d %H:%M")}, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
            gk = self.game_key
            threading.Thread(target=snapshot_game, args=(gk, dest), daemon=True).start()
            messagebox.showinfo("Salvato", f"Partita salvata come {os.path.basename(dest)}")
        undo_path = os.path.join(UNDO_DIR, os.path.basename(self.session_dir)) if self.session_dir else None
        if undo_path and os.path.isdir(undo_path):
            shutil.rmtree(undo_path, ignore_errors=True)
        self.show_login()


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
