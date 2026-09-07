import os
import math
import random
import struct
import wave
import tkinter as tk
from tkinter import font as tkfont

import pygame

SAMPLE_RATE = 22050

BASE_DIR = os.environ.get("DOWNWELL_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
SOUND_DIR = os.path.join(BASE_DIR, "downwell_assets", "sounds")
os.makedirs(SOUND_DIR, exist_ok=True)

ACTIONS = [
    ("jump", "Salto"),
    ("shoot", "Spara"),
    ("hit", "Colpito"),
    ("gem", "Raccogli Gemma"),
    ("kill", "Nemico Ucciso"),
    ("gameover", "Game Over"),
    ("win", "Vittoria"),
]

WAVE_TYPES = ["Sine", "Square", "Sawtooth", "Triangle", "Noise"]


def generate_samples(wave_type, freq_start, freq_end, duration, volume, fade_out):
    n = max(1, int(SAMPLE_RATE * duration))
    samples = [0.0] * n
    attack = max(1, int(n * 0.02))
    release = max(1, int(n * 0.05))
    phase_acc = 0.0
    prev_t = 0.0
    for i in range(n):
        t = i / SAMPLE_RATE
        frac = i / max(1, n - 1)
        freq = freq_start + (freq_end - freq_start) * frac
        # integrate phase so frequency sweeps don't produce discontinuities
        phase_acc += 2 * math.pi * freq * (t - prev_t)
        prev_t = t

        if wave_type == "Sine":
            val = math.sin(phase_acc)
        elif wave_type == "Square":
            val = 1.0 if math.sin(phase_acc) >= 0 else -1.0
        elif wave_type == "Sawtooth":
            cyc = (phase_acc / (2 * math.pi)) % 1.0
            val = 2 * cyc - 1
        elif wave_type == "Triangle":
            cyc = (phase_acc / (2 * math.pi)) % 1.0
            val = 2 * abs(2 * cyc - 1) - 1
        else:  # Noise
            val = random.uniform(-1, 1)

        env = 1.0
        if i < attack:
            env = i / attack
        elif fade_out:
            env = max(0.0, 1.0 - (i - attack) / max(1, n - attack))
        elif i > n - release:
            env = max(0.0, (n - i) / release)

        samples[i] = val * volume * env
    return samples


def samples_to_pcm_bytes(samples):
    data = bytearray()
    for s in samples:
        s = max(-1.0, min(1.0, s))
        data += struct.pack("<h", int(s * 32767))
    return bytes(data)


def save_wav(path, samples):
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples_to_pcm_bytes(samples))


class SoundEditor:
    def __init__(self, root):
        self.root = root
        root.title("Editor Suoni - Downwell")
        root.geometry("760x680")
        root.configure(bg="#12141a")

        pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1)

        title_font = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        subtitle_font = tkfont.Font(family="Segoe UI", size=11)
        button_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        tk.Label(root, text="Editor Suoni", font=title_font, fg="#7fd8c8", bg="#12141a").pack(pady=(14, 4))
        tk.Label(
            root, text="Crea un effetto sonoro semplice e assegnalo a un'azione del gioco.",
            font=subtitle_font, fg="#c8ccd6", bg="#12141a",
        ).pack(pady=(0, 12))

        main = tk.Frame(root, bg="#12141a")
        main.pack(fill="both", expand=True, padx=20)

        # --- Wave type ---
        tk.Label(main, text="Tipo di onda:", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w")
        wave_frame = tk.Frame(main, bg="#12141a")
        wave_frame.pack(anchor="w", pady=(4, 14))
        self.wave_var = tk.StringVar(value="Square")
        for wt in WAVE_TYPES:
            tk.Radiobutton(
                wave_frame, text=wt, variable=self.wave_var, value=wt, command=self.redraw_preview,
                font=subtitle_font, fg="white", bg="#12141a", selectcolor="#3ea88f",
                activebackground="#12141a", activeforeground="white",
            ).pack(side="left", padx=(0, 12))

        # --- Sliders ---
        self.freq_start_var = tk.IntVar(value=440)
        self.freq_end_var = tk.IntVar(value=440)
        self.duration_var = tk.DoubleVar(value=0.25)
        self.volume_var = tk.IntVar(value=70)
        self.fade_var = tk.BooleanVar(value=True)

        self._make_slider(main, "Frequenza iniziale (Hz):", self.freq_start_var, 50, 2000)
        self._make_slider(main, "Frequenza finale (Hz):", self.freq_end_var, 50, 2000)
        self._make_slider(main, "Durata (secondi x100):", self.duration_var, 5, 150)
        self._make_slider(main, "Volume (%):", self.volume_var, 0, 100)

        tk.Checkbutton(
            main, text="Dissolvenza in uscita (fade out)", variable=self.fade_var, command=self.redraw_preview,
            font=subtitle_font, fg="white", bg="#12141a", selectcolor="#1d2028",
            activebackground="#12141a", activeforeground="white",
        ).pack(anchor="w", pady=(4, 14))

        # --- Waveform preview ---
        tk.Label(main, text="Forma d'onda:", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w")
        self.preview_canvas = tk.Canvas(main, width=700, height=140, bg="#0b0d11", highlightthickness=1, highlightbackground="#3a3f4a")
        self.preview_canvas.pack(pady=(4, 14))

        # --- Play button ---
        tk.Button(
            main, text="Ascolta", font=button_font, bg="#4a7fd6", fg="white",
            activebackground="#5c8fe0", activeforeground="white", relief="flat", padx=20, pady=8,
            command=self.play_preview,
        ).pack(pady=(0, 16))

        # --- Action assignment ---
        tk.Label(main, text="Assegna a quale azione:", font=subtitle_font, fg="#8a8f9c", bg="#12141a").pack(anchor="w")
        action_frame = tk.Frame(main, bg="#12141a")
        action_frame.pack(pady=(4, 14), anchor="w")
        self.action_var = tk.StringVar(value=ACTIONS[0][0])
        for key, label in ACTIONS:
            tk.Radiobutton(
                action_frame, text=label, variable=self.action_var, value=key,
                font=subtitle_font, fg="white", bg="#12141a", selectcolor="#3ea88f",
                activebackground="#12141a", activeforeground="white", indicatoron=True,
            ).pack(anchor="w", pady=1)

        tk.Button(
            main, text="Salva per questa Azione", font=button_font, bg="#3ea88f", fg="white",
            activebackground="#4fc2a8", activeforeground="white", relief="flat", padx=20, pady=10,
            command=self.save_for_action,
        ).pack(pady=(0, 10))

        self.status_label = tk.Label(root, text="", font=subtitle_font, fg="#f0c674", bg="#12141a")
        self.status_label.pack(pady=(0, 14))

        self.redraw_preview()

    def _make_slider(self, parent, label, var, frm, to):
        row = tk.Frame(parent, bg="#12141a")
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, font=("Segoe UI", 10), fg="#8a8f9c", bg="#12141a", width=26, anchor="w").pack(side="left")
        tk.Scale(
            row, from_=frm, to=to, orient="horizontal", variable=var, command=lambda v: self.redraw_preview(),
            bg="#12141a", fg="white", troughcolor="#1d2028", highlightthickness=0, length=380,
        ).pack(side="left")

    def _current_params(self):
        return (
            self.wave_var.get(),
            self.freq_start_var.get(),
            self.freq_end_var.get(),
            self.duration_var.get() / 100.0,
            self.volume_var.get() / 100.0,
            self.fade_var.get(),
        )

    def redraw_preview(self):
        wave_type, f0, f1, dur, vol, fade = self._current_params()
        samples = generate_samples(wave_type, f0, f1, dur, vol, fade)
        self.preview_canvas.delete("all")
        w, h = 700, 140
        mid = h // 2
        step = max(1, len(samples) // w)
        points = []
        for i in range(0, len(samples), step):
            x = int(i / max(1, len(samples) - 1) * w)
            y = mid - int(samples[i] * (h // 2 - 6))
            points.extend([x, y])
        if len(points) >= 4:
            self.preview_canvas.create_line(*points, fill="#7fd8c8", width=1)
        self.preview_canvas.create_line(0, mid, w, mid, fill="#2a2f36", dash=(2, 2))

    def play_preview(self):
        wave_type, f0, f1, dur, vol, fade = self._current_params()
        samples = generate_samples(wave_type, f0, f1, dur, vol, fade)
        sound = pygame.mixer.Sound(buffer=samples_to_pcm_bytes(samples))
        sound.play()

    def save_for_action(self):
        wave_type, f0, f1, dur, vol, fade = self._current_params()
        samples = generate_samples(wave_type, f0, f1, dur, vol, fade)
        key = self.action_var.get()
        path = os.path.join(SOUND_DIR, f"{key}.wav")
        save_wav(path, samples)
        label = dict(ACTIONS)[key]
        self.status_label.config(text=f"Salvato per '{label}' in {os.path.basename(path)} - riavvia downwell_clone.py per sentirlo.")


def main():
    root = tk.Tk()
    SoundEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
