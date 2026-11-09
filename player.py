"""player.py -- tokens-to-tones: a live score player. Tails score.txt and PLAYS every new line the moment it lands.

Token grammar, one phrase per line, tokens separated by spaces:
  C4 E4 G4        notes (letter, optional # or b, octave); a plain note lasts one beat
  C4:2  G4:0.5    note with a length in beats
  [C4 E4 G4]:2    chord (space-separated notes inside brackets)
  R  R:0.5        rest
  tempo=120       beats per minute (persists)
  wave=sine|tri|saw|square|pluck   timbre (persists)
  vol=0.3         0..1 (persists)
  # anything      comment, ignored
Teseo appends lines with `printf '...\n' >> scratch/live/score.txt`; this process never reads anything else.
Stop: kill this PID (written to player.pid). Log: player.log.
"""
import math
import os
import re
import sys
import time

import numpy as np
import sounddevice as sd

HERE = os.path.dirname(os.path.abspath(__file__))
SCORE = os.path.join(HERE, "score.txt")
LOG = os.path.join(HERE, "player.log")
SR = 44100
NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_RX = re.compile(r"^([A-Ga-g])([#b]?)(\d)$")

state = {"tempo": 100.0, "wave": "pluck", "vol": 0.35}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def freq(name):
    m = NOTE_RX.match(name)
    if not m:
        return None
    semis = NAMES[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)] + 12 * (int(m.group(3)) + 1)
    return 440.0 * 2 ** ((semis - 69) / 12)


def tone(f, secs, wave, vol):
    n = int(SR * secs)
    t = np.arange(n) / SR
    ph = 2 * math.pi * f * t
    if wave == "sine":
        y = np.sin(ph)
    elif wave == "tri":
        y = 2 / math.pi * np.arcsin(np.sin(ph))
    elif wave == "saw":
        y = 2 * (f * t - np.floor(0.5 + f * t))
    elif wave == "square":
        y = np.sign(np.sin(ph)) * 0.6
    else:  # pluck: sine + 2 soft partials, fast decay
        y = np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.15 * np.sin(3 * ph)
        y *= np.exp(-3.0 * t / max(secs, 0.05))
    a = min(0.01, secs / 4)
    env = np.ones(n)
    ra = int(SR * a)
    if ra > 0:
        env[:ra] = np.linspace(0, 1, ra)
        env[-ra:] *= np.linspace(1, 0, ra)
    return (y * env * vol).astype(np.float32)


def render(line):
    """A phrase -> one float32 buffer (so the whole line plays gapless)."""
    parts = []
    beat = 60.0 / state["tempo"]
    for tok in re.findall(r"\[[^\]]*\](?::[\d.]+)?|\S+", line):   # a chord keeps its spaces
        if tok.startswith("#"):
            break
        if "=" in tok:
            k, v = tok.split("=", 1)
            if k == "tempo":
                state["tempo"] = max(20.0, min(400.0, float(v)))
                beat = 60.0 / state["tempo"]
            elif k == "wave":
                state["wave"] = v
            elif k == "vol":
                state["vol"] = max(0.0, min(1.0, float(v)))
            continue
        length = 1.0
        body = tok
        if tok.startswith("["):
            close = tok.find("]")
            if close < 0:
                log("skip token %r (no ])" % tok)
                continue
            body, rest = tok[:close + 1], tok[close + 1:]
            if rest.startswith(":"):
                length = float(rest[1:])
        elif ":" in tok:
            body, l = tok.rsplit(":", 1)
            length = float(l)
        secs = beat * length
        if body.upper() == "R":
            parts.append(np.zeros(int(SR * secs), dtype=np.float32))
            continue
        notes = body.strip("[]").split() if body.startswith("[") else [body]
        buf = None
        for nm in notes:
            f = freq(nm)
            if f is None:
                log("skip token %r" % tok)
                continue
            y = tone(f, secs, state["wave"], state["vol"] / math.sqrt(len(notes)))
            buf = y if buf is None else buf + y
        if buf is not None:
            parts.append(buf)
    return np.concatenate(parts) if parts else None


def main():
    open(SCORE, "a").close()
    with open(os.path.join(HERE, "player.pid"), "w") as f:
        f.write(str(os.getpid()))
    log("player up, pid %d, device %s" % (os.getpid(), sd.query_devices(kind="output")["name"]))
    with open(SCORE, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)          # only NEW lines play: the past is not replayed on restart
        while True:
            line = fh.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                buf = render(line)
                if buf is not None:
                    sd.play(buf, SR, blocking=True)
                log("played: " + line[:100])
            except Exception as e:
                log("error on %r: %s" % (line[:60], e))


if __name__ == "__main__":
    sys.exit(main())
