"""Push a kiosk game to a RetroPie box's "Ports" menu over SSH.

One fixed slot per game: pushing again overwrites that slot, so the Pi never
accumulates versions. Local play and the local gallery are untouched by this.

Configuration lives in ``retropie.json`` next to this file (git-ignored)::

    {
      "host": "192.168.0.114",
      "user": "pi",
      "password": "raspberry",
      "ports_dir": "/home/pi/RetroPie/roms/ports"
    }

If that file is missing or incomplete, ``load_config()`` returns ``None`` and the
dashboard simply hides the "send to RetroPie" button.

Note: the target Pi runs Python 3.5 (no f-strings) - the game templates are kept
3.5-compatible so a pushed copy runs there unchanged.
"""
import ast
import json
import os
import posixpath

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retropie.json")

# never worth copying to the Pi (kiosk-only bookkeeping, caches, vcs)
_SKIP_NAMES = {
    "__pycache__", ".git", ".gitignore", ".gitattributes",
    "thumb.png", "ai_hints.json", "high_scores.txt", "session_meta.json",
}
_SKIP_SUFFIX = (".pyc", ".pyo")


def load_config():
    """Return the config dict, or None if retropie.json is absent/unusable."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    if not cfg.get("host") or not cfg.get("user"):
        return None
    cfg.setdefault("password", None)
    cfg.setdefault("ports_dir", "/home/pi/RetroPie/roms/ports")
    return cfg


def reachable(cfg, timeout=3):
    """Quick TCP probe of the Pi's SSH port - used to enable/disable the button."""
    import socket
    try:
        socket.create_connection((cfg["host"], 22), timeout).close()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- push

def _shq(path):
    """Single-quote a path for a POSIX shell."""
    return "'" + str(path).replace("'", "'\\''") + "'"


def _run(cli, cmd, timeout=60):
    _stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def _mkdir_p(sftp, remote_dir):
    parts = remote_dir.strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


def _keep(name):
    return name not in _SKIP_NAMES and not name.endswith(_SKIP_SUFFIX)


# --- Python 3.5 compatibility check (the Pi runs 3.5.3) -------------------
_BAD_NODES = {
    "JoinedStr": 'f-string (usa "...".format(...))',
    "NamedExpr": "operatore walrus :=",
}


def _reachable_py_files(entry_path):
    """entry_path plus every local .py module it (transitively) imports."""
    found, todo = set(), [os.path.abspath(entry_path)]
    while todo:
        p = todo.pop()
        if p in found or not os.path.isfile(p):
            continue
        found.add(p)
        try:
            tree = ast.parse(open(p, "r", encoding="utf-8").read(), p)
        except SyntaxError:
            continue
        here = os.path.dirname(p)
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                cand = os.path.join(here, m + ".py")
                if os.path.isfile(cand):
                    todo.append(cand)
    return found


def py35_issues(local_dir, entry_rel):
    """Return [(relpath, line, message)] for anything in the code that would run
    on the Pi will break under Python 3.5 (f-strings, walrus, syntax errors)."""
    out = []
    entry = os.path.join(local_dir, entry_rel.replace("/", os.sep))
    for path in sorted(_reachable_py_files(entry)):
        rel = os.path.relpath(path, local_dir)
        try:
            tree = ast.parse(open(path, "r", encoding="utf-8").read(), path)
        except SyntaxError as exc:
            out.append((rel, exc.lineno or 0, "errore di sintassi: %s" % exc.msg))
            continue
        seen = set()
        for node in ast.walk(tree):
            label = _BAD_NODES.get(type(node).__name__)
            if label:
                key = (rel, getattr(node, "lineno", 0))
                if key not in seen:
                    seen.add(key)
                    out.append((rel, key[1], label))
    return out


def _upload_tree(sftp, local_dir, remote_dir):
    _mkdir_p(sftp, remote_dir)
    for entry in sorted(os.listdir(local_dir)):
        if not _keep(entry):
            continue
        lp = os.path.join(local_dir, entry)
        rp = posixpath.join(remote_dir, entry)
        if os.path.isdir(lp):
            _upload_tree(sftp, lp, rp)
        else:
            sftp.put(lp, rp)


def _launcher(slot_dir, run_rel, data_dir_env):
    # cd into the script's own folder (some games chdir on import and assume
    # that's already the cwd - e.g. Space Invaders' Code/ modules)
    run_dir = posixpath.dirname(run_rel)
    run_file = posixpath.basename(run_rel)
    workdir = posixpath.join(slot_dir, run_dir) if run_dir else slot_dir
    lines = ["#!/bin/bash", "cd " + _shq(workdir)]
    if data_dir_env:
        lines.append("export DOWNWELL_DATA_DIR=" + _shq(slot_dir))
    lines.append("python3 " + run_file)
    return "\n".join(lines) + "\n"


def push(slot_name, run_rel, local_dir, data_dir_env=False, progress=None):
    """Copy ``local_dir`` to ``<ports_dir>/<slot_name>/`` and (re)write
    ``<slot_name>.sh``. Returns (ok, message). ``progress`` is an optional
    ``callable(str)`` for status lines."""
    def say(msg):
        if progress:
            progress(msg)

    cfg = load_config()
    if not cfg:
        return False, "retropie.json mancante o incompleto."

    bad = py35_issues(local_dir, run_rel)
    if bad:
        lines = "; ".join("%s riga %d: %s" % (r, ln, m) for r, ln, m in bad[:6])
        return False, ("Non invio: il codice non e' compatibile con il "
                       "Raspberry Pi (Python 3.5). " + lines)

    try:
        import paramiko
    except ImportError:
        return False, "Modulo 'paramiko' non installato (pip install paramiko)."

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        say("Mi collego al RetroPie...")
        cli.connect(cfg["host"], username=cfg["user"], password=cfg.get("password"),
                    timeout=10, allow_agent=False, look_for_keys=False)
    except Exception as exc:  # noqa: BLE001 - surface any conn(auth/net) error
        return False, "Connessione fallita: {}".format(exc)

    try:
        ports = cfg["ports_dir"]
        slot_dir = posixpath.join(ports, slot_name)
        slot_sh = posixpath.join(ports, slot_name + ".sh")
        sftp = cli.open_sftp()

        try:
            sftp.stat(slot_sh)
            was_new = False
        except IOError:
            was_new = True

        say("Rimuovo la versione precedente...")
        _run(cli, "rm -rf -- {0} {1}".format(_shq(slot_dir), _shq(slot_sh)))

        say("Copio i file del gioco...")
        _upload_tree(sftp, local_dir, slot_dir)

        say("Scrivo il launcher...")
        with sftp.open(slot_sh, "w") as fh:
            fh.write(_launcher(slot_dir, run_rel, data_dir_env))
        sftp.chmod(slot_sh, 0o755)
        sftp.close()

        note = ""
        if was_new:
            # NB: pgrep -x fails here - Linux truncates the process name to
            # "emulationstatio" (15 chars). Match the full command line instead.
            _rc, out, _ = _run(cli, "pgrep -f emulationstation >/dev/null && echo YES || echo NO")
            if "YES" in out:
                say("Aggiorno la lista giochi (riavvio EmulationStation)...")
                _run(cli, "touch /tmp/es-restart; pkill -f emulationstation || true")
                note = " EmulationStation si sta riavviando sul Pi."
            else:
                note = " Avvia EmulationStation sul Pi per vederlo nei Ports."
        return True, "Inviato: \"{}\" nei Ports del RetroPie.{}".format(slot_name, note)
    except Exception as exc:  # noqa: BLE001
        return False, "Errore durante l'invio: {}".format(exc)
    finally:
        cli.close()
