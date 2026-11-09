"""listen.py -- record what the speakers are playing and name the notes, window by window.

Picks an input device: "Stereo Mix"/"Mezcla estéreo"/"What U Hear" (loopback) if present, else the default microphone
(the laptop mic hears the speakers, plus the room). Records SECONDS, then per 250 ms window takes the FFT, keeps peaks
above a threshold, maps each to the nearest note name, and prints the strongest 1-3 notes per window with the time.
Writes the raw take to take.wav so a human can check what the machine "heard".
"""
import os
import sys
import time
import wave

import numpy as np
import sounddevice as sd

HERE = os.path.dirname(os.path.abspath(__file__))
TAKE = os.path.join(HERE, "take.wav")
SR = 44100
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def pick_input():
    devs = sd.query_devices()
    if "mic" in sys.argv[2:]:
        i = sd.default.device[0]
        return i, devs[i]["name"], "microphone (forced)"
    for i, d in enumerate(devs):
        n = d["name"].lower()
        if d["max_input_channels"] > 0 and any(k in n for k in ("stereo mix", "mezcla est", "what u hear", "loopback")):
            return i, d["name"], "loopback"
    i = sd.default.device[0]
    return i, devs[i]["name"], "microphone"


def note_name(f):
    if f <= 0:
        return None
    m = 69 + 12 * np.log2(f / 440.0)
    k = int(round(m))
    cents = (m - k) * 100
    return "%s%d" % (NAMES[k % 12], k // 12 - 1), cents


def main():
    if "file" in sys.argv[2:]:
        with wave.open(TAKE, "rb") as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32767
        print("re-analysing take.wav (%.1fs)" % (len(x) / SR))
    else:
        idx, name, kind = pick_input()
        print("input: %s (%s)" % (name, kind))
        t0 = time.strftime("%H:%M:%S")
        rec = sd.rec(int(SR * SECONDS), samplerate=SR, channels=1, dtype="float32", device=idx)
        sd.wait()
        x = rec[:, 0]
        with wave.open(TAKE, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        rms = float(np.sqrt(np.mean(x ** 2)))
        print("recorded %.1fs from %s, rms %.4f %s" % (SECONDS, t0, rms, "(silence?)" if rms < 1e-3 else ""))
    win = int(SR * 0.25)
    # the loudness floor is RELATIVE to the take, so a quiet take (speaker volume 2) still yields notes
    peak_all = max(float(np.abs(x).max()), 1e-6)
    for s in range(0, len(x) - win, win):
        seg = x[s:s + win] * np.hanning(win)
        spec = np.abs(np.fft.rfft(seg))
        freqs = np.fft.rfftfreq(win, 1 / SR)
        band = (freqs > 80) & (freqs < 2500)
        spec, freqs = spec[band], freqs[band]
        if spec.max() < 0.05 * peak_all * win:
            continue
        peaks = []
        order = np.argsort(spec)[::-1]
        for j in order:
            if spec[j] < 0.25 * spec.max():
                break
            f = freqs[j]
            if all(abs(f - p) > 25 for p, _ in peaks):
                peaks.append((f, spec[j]))
            if len(peaks) == 3:
                break
        names = ["%s%+.0fc" % note_name(f) for f, _ in sorted(peaks, key=lambda p: -p[1])]
        print("t=%4.2fs  %s" % (s / SR, "  ".join(names)))


if __name__ == "__main__":
    main()
