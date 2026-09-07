"""One-off: render a thumbnail (thumb.png) into each game template folder.
Re-run if a template's look changes."""
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT = os.path.join(BASE_DIR, "_game_shot.py")

# game_key: (template rel path, entry script, cwd rel, frames to render before shot)
JOBS = {
    "downwell": ("game_templates/downwell", "downwell_clone.py", ".", 160),
    "space_invaders": ("game_templates/space_invaders", os.path.join("Code", "Main.py"), ".", 130),
    "platformer": ("game_templates/platformer", "index.py", ".", 220),
    "racing": ("game_templates/racing", "race.py", ".", 150),
}


def make_thumb(script_path, out_png, cwd, frames, env=None):
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    try:
        subprocess.run(
            [sys.executable, SHOT, script_path, out_png, str(frames)],
            cwd=cwd, env=run_env, capture_output=True, text=True, timeout=45,
        )
    except subprocess.TimeoutExpired:
        pass
    return os.path.exists(out_png)


def main():
    for key, (rel, script, cwd_rel, frames) in JOBS.items():
        gdir = os.path.join(BASE_DIR, rel)
        out = os.path.join(gdir, "thumb.png")
        ok = make_thumb(os.path.join(gdir, script), out, os.path.join(gdir, cwd_rel), frames)
        print(f"{key:15} -> {'OK ' + out if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
