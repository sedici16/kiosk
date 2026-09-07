"""One-off: have Claude Code read each game template and write ai_hints.json
(a short 'what would make it more fun' analysis + 6 one-line improvement ideas)
into that template folder. Re-run if a template's code changes meaningfully."""
import subprocess
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")

GAMES = {
    "downwell": "game_templates/downwell",
    "space_invaders": "game_templates/space_invaders",
    "platformer": "game_templates/platformer",
    "racing": "game_templates/racing",
}

# optional: pass game keys on the command line to regenerate just those
if len(sys.argv) > 1:
    GAMES = {k: v for k, v in GAMES.items() if k in sys.argv[1:]}

PROMPT = (
    "Analizza il codice di questo videogioco Pygame: leggi i file .py nella cartella "
    "di lavoro corrente. Pensa a un pubblico di famiglie e bambini a una fiera.\n\n"
    "Produci:\n"
    "1) \"analysis\": 2-4 frasi in italiano su cosa renderebbe questo gioco piu "
    "divertente o cosa gli manca. Massimo 400 caratteri. Concreto e riferito a QUESTO "
    "gioco specifico (nomina meccaniche reali che vedi nel codice).\n"
    "2) \"suggestions\": ESATTAMENTE 6 idee di miglioramento in italiano, ognuna "
    "scritta come istruzione breve che un visitatore darebbe all'IA (imperativo, "
    "massimo 70 caratteri, una sola riga). Devono essere varie: difficolta, nuovi "
    "elementi, aspetto grafico, feedback/suoni, ritmo, premi.\n\n"
    "Rispondi SOLO con JSON valido su una riga, senza altro testo e senza backtick:\n"
    "{\"analysis\": \"...\", \"suggestions\": [\"...\",\"...\",\"...\",\"...\",\"...\",\"...\"]}"
)


def strip_fences(t):
    t = t.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    return t.strip()


def main():
    for key, rel in GAMES.items():
        path = os.path.join(BASE_DIR, rel)
        print("===", key, "->", path)
        proc = subprocess.run(
            [
                CLAUDE, "-p", PROMPT,
                "--add-dir", path,
                "--allowedTools", "Read", "Glob", "Grep",
                "--disallowedTools", "Bash", "PowerShell", "Edit", "Write",
                "WebFetch", "WebSearch", "Task",
                "--permission-mode", "acceptEdits",
                "--model", "sonnet",
                "--output-format", "json",
            ],
            cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        try:
            outer = json.loads(proc.stdout)
        except json.JSONDecodeError:
            print("  ! could not parse claude output:", proc.stdout[:400], proc.stderr[:300])
            continue
        text = strip_fences(outer.get("result", ""))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print("  ! model did not return JSON:", text[:400])
            continue
        sugg = data.get("suggestions", [])
        if "analysis" not in data or len(sugg) != 6:
            print("  ! unexpected shape:", data)
            continue
        out = os.path.join(path, "ai_hints.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"analysis": data["analysis"].strip(),
                       "suggestions": [s.strip() for s in sugg]},
                      f, ensure_ascii=False, indent=2)
        print("  saved", out)
        print("  cost usd:", outer.get("total_cost_usd"))


if __name__ == "__main__":
    main()
