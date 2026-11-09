"""sing.py -- make the neural TTS voice SING a melody: speech -> Praat PSOLA with a melody pitch tier and a
duration tier that lands each note's slice on its beat.

Method (PDAugment-style, F0 replacement; Praat instead of WORLD because pyworld has no py3.14 wheel):
  1. edge-tts speaks the line (cached), decoded to 44.1 kHz mono.
  2. Praat finds the voiced frames; the total voiced time is split among the notes in proportion to
     their beats, so note k owns one slice of the sung material (vowels carry the notes).
  3. Pitch tier: each slice held at its note (+ light vibrato on long notes, glides between).
     Duration tier: each slice (from its start to the next slice's start, consonants included) is
     stretched to the note's length, so note onsets fall on the beat.
  4. Overlap-add resynthesis.
API: sing(text, notes, bpm, voice) -> float32 mono at 44100 Hz. notes = [(midi, beats), ...]
CLI: python sing.py  -> voices/sing-demo-{raw,sung}.wav
"""
import asyncio
import hashlib
import math
import os
import subprocess

import numpy as np
import parselmouth
from parselmouth.praat import call

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "voices", "cache")
SR = 44100


def tts(text, voice="es-CL-LorenzoNeural", rate="+0%"):
    os.makedirs(CACHE, exist_ok=True)
    h = hashlib.sha1(("sing|" + voice + "|" + rate + "|" + text).encode("utf-8")).hexdigest()[:16]
    mp3 = os.path.join(CACHE, h + ".mp3")
    if not os.path.exists(mp3):
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(mp3 + ".part.mp3"))
        os.replace(mp3 + ".part.mp3", mp3)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp3, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    nz = np.nonzero(np.abs(y) > 0.01)[0]
    return y[max(0, nz[0] - 200): nz[-1] + 2000] if len(nz) else y


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def voiced_runs(snd, floor=70, ceil=400):
    pitch = snd.to_pitch(time_step=0.005, pitch_floor=floor, pitch_ceiling=ceil)
    f0 = pitch.selected_array["frequency"]
    ts = pitch.xs()
    runs, start = [], None
    for t, f in zip(ts, f0):
        if f > 0 and start is None:
            start = t
        elif f == 0 and start is not None:
            runs.append([start, t])
            start = None
    if start is not None:
        runs.append([start, ts[-1]])
    merged = []
    for r in runs:                          # bridge tiny gaps (pitch-tracker dropouts)
        if merged and r[0] - merged[-1][1] < 0.03:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [r for r in merged if r[1] - r[0] >= 0.04]


def voiced_time_to_real(runs, v):
    """Map a position v in cumulative voiced time to real time in the original sound."""
    acc = 0.0
    for a, b in runs:
        if v <= acc + (b - a):
            return a + (v - acc)
        acc += b - a
    return runs[-1][1]


def sing(text, notes, bpm, voice="es-CL-LorenzoNeural", vibrato=0.25):
    y = tts(text, voice, rate="-25%")   # slower source = less PSOLA stretch (5.36 vs 6.82 s short at +0%)
    snd = parselmouth.Sound(y.astype(np.float64), sampling_frequency=SR)
    dur = snd.get_total_duration()
    runs = voiced_runs(snd)
    if not runs:
        return y
    # move the melody by whole octaves toward the speaker's own register (big F0 shifts sound buzzy)
    f0 = snd.to_pitch(time_step=0.01, pitch_floor=70, pitch_ceiling=400).selected_array["frequency"]
    speak = float(np.median(12 * np.log2(f0[f0 > 0] / 440) + 69)) if np.any(f0 > 0) else 48.0
    mel_mid = float(np.mean([m for m, _ in notes]))
    octs = round((speak + 3 - mel_mid) / 12)
    notes = [(m + 12 * octs, b) for m, b in notes]
    total_v = sum(b - a for a, b in runs)
    total_beats = sum(b for _, b in notes)
    beat = 60.0 / bpm
    # slice boundaries in real (original) time
    cuts, acc = [], 0.0
    for _, b in notes:
        cuts.append(voiced_time_to_real(runs, acc / total_beats * total_v))
        acc += b
    starts = [0.0] + cuts[1:]            # note 0 owns the leading consonant too
    ends = starts[1:] + [dur]
    manip = call(snd, "To Manipulation", 0.01, 70, 400)
    pt = call(manip, "Extract pitch tier")
    call(pt, "Remove points between", 0, dur)
    dt = call(manip, "Extract duration tier")
    call(dt, "Remove points between", 0, dur)
    eps = 0.002
    for k, ((midi, beats), s, e) in enumerate(zip(notes, starts, ends)):
        f = hz(midi)
        a = max(s, cuts[k]) + 0.015
        b = max(a + 0.01, e - 0.02)
        call(pt, "Add point", a, f)
        target = beats * beat
        factor = min(5.0, max(0.4, target / max(e - s, 1e-3)))
        if target > 0.35 and vibrato > 0:   # vibrato after the attack, in original time
            n = int((b - a) * 40)
            for i in range(1, n):
                t = a + (b - a) * i / n
                real_t = (t - a) * factor
                depth = vibrato * min(1.0, real_t / 0.3)
                call(pt, "Add point", t, f * 2 ** (depth * math.sin(2 * math.pi * 5.5 * real_t) / 12))
        call(pt, "Add point", b, f)
        call(dt, "Add point", s + eps, factor)
        call(dt, "Add point", e - eps, factor)
    call([manip, pt], "Replace pitch tier")
    call([manip, dt], "Replace duration tier")
    out = call(manip, "Get resynthesis (overlap-add)")
    return out.values[0].astype(np.float32)


def write_wav(path, y):
    import wave
    y = y / (np.abs(y).max() + 1e-9) * 0.9
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    text = "Misma sangre, distinto camino."
    # mis-ma san-gre dis-tin-to ca-mi-no: 10 syllables, A minor, male range
    notes = [(57, 1), (60, 0.5), (57, 0.5), (55, 1), (53, 1), (55, 0.5), (57, 0.5), (59, 1), (62, 1), (64, 2)]
    raw = tts(text)
    sung = sing(text, notes, 88)
    write_wav(os.path.join(HERE, "voices", "sing-demo-raw.wav"), raw)
    write_wav(os.path.join(HERE, "voices", "sing-demo-sung.wav"), sung)
    print("raw %.2fs  sung %.2fs  target %.2fs" % (len(raw) / SR, len(sung) / SR, sum(b for _, b in notes) * 60 / 88))
