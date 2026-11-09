"""player.py -- a live score player. Tails score.txt and PLAYS every new line the moment it lands.

Token grammar, one phrase per line, tokens separated by spaces:
  C4 E4 G4        notes (letter, optional # or b, octave); a plain note lasts one beat
  C4:2  G4:0.5    note with a length in beats
  [C4 E4 G4]:2    chord (space-separated notes inside brackets)
  R  R:0.5        rest
  tempo=120       beats per minute (persists)
  wave=sine|tri|saw|square|pluck   numpy synth timbre; also switches back to the synth (persists)
  inst=0..127     General MIDI program on the Windows GS Wavetable Synth; switches to MIDI (persists)
                  e.g. 0 piano, 4 e-piano, 24 nylon guitar, 33 bass, 48 strings, 52 choir, 73 flute, 80 lead
  vol=0.3         0..1 (persists)
  voice=es-CL-LorenzoNeural | es-CL-CatalinaNeural | piper | sapi   speaking voice (persists)
  say=texto ...   SPEAKS the rest of the line (after the notes before it); synchronous
  # anything      comment, ignored
Speech chain: edge-tts neural (network) -> Piper es_MX local -> SAPI Sabina. Spoken audio is cached by
(voice, text) in voices/cache, so a repeated line is instant.
Usage: python player.py [score_path]. Stop: kill this PID (written to player.pid). Log: player.log.
"""
import hashlib
import io
import math
import os
import re
import sys
import time
import wave

import numpy as np
import sounddevice as sd

HERE = os.path.dirname(os.path.abspath(__file__))
SCORE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "score.txt")
TEST = len(sys.argv) > 1
LOG = os.path.join(HERE, "player-test.log" if TEST else "player.log")
VOICES = os.path.join(HERE, "voices")
CACHE = os.path.join(VOICES, "cache")
PIPER_MODEL = os.path.join(VOICES, "es_MX-claude-high.onnx")
SR = 44100
NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_RX = re.compile(r"^([A-Ga-g])([#b]?)(\d)$")
MIDI_OUT_NAME = b"Microsoft GS Wavetable Synth"

state = {"tempo": 100.0, "wave": "pluck", "vol": 0.35, "inst": None, "voice": "es-CL-LorenzoNeural"}
_midi = {"out": None, "program": None}
_piper = {"voice": None}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def midi_num(name):
    m = NOTE_RX.match(name)
    if not m:
        return None
    return NAMES[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)] + 12 * (int(m.group(3)) + 1)


def freq(name):
    n = midi_num(name)
    return None if n is None else 440.0 * 2 ** ((n - 69) / 12)


def tone(f, secs, wave_, vol):
    n = int(SR * secs)
    t = np.arange(n) / SR
    ph = 2 * math.pi * f * t
    if wave_ == "sine":
        y = np.sin(ph)
    elif wave_ == "tri":
        y = 2 / math.pi * np.arcsin(np.sin(ph))
    elif wave_ == "saw":
        y = 2 * (f * t - np.floor(0.5 + f * t))
    elif wave_ == "square":
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


# ---------------------------------------------------------------- MIDI backend
def midi_out():
    if _midi["out"] is None:
        import pygame.midi
        pygame.midi.init()
        dev = None
        for i in range(pygame.midi.get_count()):
            _, name, _, is_out, _ = pygame.midi.get_device_info(i)
            if is_out and name == MIDI_OUT_NAME:
                dev = i
        if dev is None:
            dev = pygame.midi.get_default_output_id()
        _midi["out"] = pygame.midi.Output(dev)
        log("midi out device %s" % dev)
    return _midi["out"]


def midi_program(p):
    out = midi_out()
    if _midi["program"] != p:
        out.set_instrument(p, 0)
        _midi["program"] = p


# ---------------------------------------------------------------- speech
def _cache_path(voice, text, ext):
    os.makedirs(CACHE, exist_ok=True)
    h = hashlib.sha1((voice + "\0" + text).encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE, h + ext)


def _play_wav_file(path):
    with wave.open(path) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        y = y.reshape(-1, ch)
    sd.play(y * min(1.0, state["vol"] * 2.5), sr, blocking=True)


def _play_mp3(path):
    import pygame.mixer as mx
    if not mx.get_init():
        mx.init()
    mx.music.load(path)
    mx.music.set_volume(min(1.0, state["vol"] * 2.5))
    mx.music.play()
    while mx.music.get_busy():
        time.sleep(0.02)
    mx.music.unload()


def _say_edge(text, voice):
    path = _cache_path(voice, text, ".mp3")
    if not os.path.exists(path):
        import asyncio
        import edge_tts
        tmp = path + ".part"
        asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, voice).save(tmp), timeout=15))
        os.replace(tmp, path)
    _play_mp3(path)


def _say_piper(text):
    path = _cache_path("piper", text, ".wav")
    if not os.path.exists(path):
        if _piper["voice"] is None:
            from piper import PiperVoice
            _piper["voice"] = PiperVoice.load(PIPER_MODEL)
        tmp = path + ".part"
        with wave.open(tmp, "wb") as w:
            _piper["voice"].synthesize_wav(text, w)
        os.replace(tmp, path)
    _play_wav_file(path)


def _say_sapi(text):
    import win32com.client
    sp = win32com.client.Dispatch("SAPI.SpVoice")
    for v in sp.GetVoices():
        if "Sabina" in v.GetDescription():
            sp.Voice = v
    sp.Volume = int(100 * min(1.0, state["vol"] * 2.5))
    sp.Speak(text)


def say(text):
    text = text.strip()
    if not text:
        return
    v = state["voice"]
    chain = []
    if v not in ("piper", "sapi"):
        chain.append(("edge", lambda: _say_edge(text, v)))
    if v != "sapi" and os.path.exists(PIPER_MODEL):
        chain.append(("piper", lambda: _say_piper(text)))
    chain.append(("sapi", lambda: _say_sapi(text)))
    for name, fn in chain:
        try:
            t0 = time.perf_counter()
            fn()
            log("said via %s (%.1fs): %s" % (name, time.perf_counter() - t0, text[:80]))
            return
        except Exception as e:
            log("say via %s failed: %s" % (name, e))


# ---------------------------------------------------------------- phrase
def parse(line):
    """A phrase -> list of events: ('notes', [midi numbers], secs) | ('rest', secs) | ('say', text).
    Settings tokens update state in order, so a tempo change mid-line takes effect from there."""
    events = []
    c = re.search(r"(?:^|\s)#", line)
    m = re.search(r"(?:^|\s)say=", line)
    if c and (not m or c.start() < m.start()):   # a comment before say= swallows it
        line, m = line[:c.start()], None
    speech = None
    if m:
        speech = line[m.end():]
        line = line[:m.start()]
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
                state["inst"] = None
            elif k == "inst":
                state["inst"] = max(0, min(127, int(v)))
            elif k == "vol":
                state["vol"] = max(0.0, min(1.0, float(v)))
            elif k == "voice":
                state["voice"] = v
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
            events.append(("rest", secs))
            continue
        names = body.strip("[]").split() if body.startswith("[") else [body]
        nums = [n for n in (midi_num(x) for x in names) if n is not None]
        if len(nums) < len(names):
            log("skip notes in %r" % tok)
        if nums:
            events.append(("notes", nums, secs))
    if speech is not None:
        events.append(("say", speech))
    return events


def play_synth(events):
    parts = []
    for ev in events:
        if ev[0] == "rest":
            parts.append(np.zeros(int(SR * ev[1]), dtype=np.float32))
        else:
            nums, secs = ev[1], ev[2]
            buf = None
            for n in nums:
                y = tone(440.0 * 2 ** ((n - 69) / 12), secs, state["wave"], state["vol"] / math.sqrt(len(nums)))
                buf = y if buf is None else buf + y
            parts.append(buf)
    if parts:
        sd.play(np.concatenate(parts), SR, blocking=True)


def play_midi(events):
    out = midi_out()
    midi_program(state["inst"])
    vel = max(1, min(127, int(state["vol"] * 2.5 * 127)))
    t = time.perf_counter()
    for ev in events:
        if ev[0] == "rest":
            t += ev[1]
            time.sleep(max(0.0, t - time.perf_counter()))
            continue
        nums, secs = ev[1], ev[2]
        for n in nums:
            out.note_on(n, vel, 0)
        t += secs
        time.sleep(max(0.0, t - 0.01 - time.perf_counter()))   # release just before the next onset
        for n in nums:
            out.note_off(n, 0, 0)
        time.sleep(max(0.0, t - time.perf_counter()))


def play_line(line):
    events = parse(line)
    music = [e for e in events if e[0] != "say"]
    if music:
        (play_midi if state["inst"] is not None else play_synth)(music)
    for e in events:
        if e[0] == "say":
            say(e[1])


def main():
    open(SCORE, "a").close()
    if not TEST:
        with open(os.path.join(HERE, "player.pid"), "w") as f:
            f.write(str(os.getpid()))
    log("player up, pid %d, score %s, device %s" % (os.getpid(), SCORE, sd.query_devices(kind="output")["name"]))
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
                play_line(line)
                log("played: " + line[:100])
            except Exception as e:
                log("error on %r: %s" % (line[:60], e))


if __name__ == "__main__":
    sys.exit(main())
