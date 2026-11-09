"""composer.py -- generate a piece for player.py from a few knobs, deterministic by seed.

    python composer.py --minutes 8 --key A --mode minor --tempo 80 --seed 11 >> score.txt

Structure: 8-bar sections; each section picks a progression from the mode, a wave, and a melody built as a random
walk on the scale that leans back to the chord tones on strong beats. Every 4th section is a quiet bridge (sine,
longer notes). The last line is a held tonic chord. Duration is exact: sum of beats / tempo (see dur.py).
"""
import argparse
import random

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MODES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11], "dorian": [0, 2, 3, 5, 7, 9, 10]}
PROGS = {"minor": [[0, 5, 2, 6], [0, 3, 6, 4], [0, 6, 2, 4], [5, 2, 6, 0]],
         "major": [[0, 4, 5, 3], [0, 5, 3, 4], [3, 4, 0, 0], [0, 3, 4, 0]],
         "dorian": [[0, 3, 0, 6], [0, 6, 3, 0]]}


def note(idx, octave, root, scale):
    deg = scale[idx % 7]
    oct_shift = idx // 7
    semis = (root + deg)
    return "%s%d" % (NOTES[semis % 12], octave + oct_shift + semis // 12)


def chord(deg, root, scale, octave=3):
    return "[%s %s %s]" % (note(deg, octave, root, scale), note(deg + 2, octave, root, scale), note(deg + 4, octave, root, scale))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=8)
    ap.add_argument("--key", default="A")
    ap.add_argument("--mode", default="minor", choices=sorted(MODES))
    ap.add_argument("--tempo", type=int, default=80)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    root = NOTES.index(a.key)
    scale = MODES[a.mode]
    beat = 60.0 / a.tempo
    total = 0.0
    out = ["tempo=%d wave=pluck vol=0.3" % a.tempo,
           "# composer seed=%d key=%s %s tempo=%d, %.0f min" % (a.seed, a.key, a.mode, a.tempo, a.minutes)]
    section = 0
    melody_idx = 7  # start an octave above the chord root
    while total < a.minutes * 60:
        prog = rnd.choice(PROGS[a.mode])
        bridge = section % 4 == 3
        if bridge:
            out.append("wave=sine vol=0.24")
            for deg in prog:
                line = [chord(deg, root, scale) + ":4"]
                out.append(" ".join(line))
                total += 4 * beat
            for deg in prog:
                steps = []
                for k in range(4):
                    melody_idx += rnd.choice([-2, -1, 1, 2])
                    melody_idx = max(5, min(13, melody_idx))
                    steps.append("%s:%s" % (note(melody_idx, 3, root, scale), "2" if k % 2 else "1"))
                    total += (2 if k % 2 else 1) * beat
                out.append(" ".join(steps))
            out.append("wave=%s vol=0.3" % rnd.choice(["pluck", "tri"]))
        else:
            for rep in range(2):
                for deg in prog:
                    toks = [chord(deg, root, scale)]
                    total += beat
                    # three melody notes after the chord beat: eighth, eighth, quarter
                    target = deg + 7 + rnd.choice([0, 2, 4])
                    for k, ln in enumerate((0.5, 0.5, 1.0)):
                        if k == 2 and rnd.random() < 0.6:
                            melody_idx = target
                        else:
                            melody_idx += rnd.choice([-1, 1, 1, 2, -2])
                        melody_idx = max(5, min(13, melody_idx))
                        toks.append("%s:%s" % (note(melody_idx, 3, root, scale), ("%g" % ln)))
                        total += ln * beat
                    out.append(" ".join(toks))
                if rnd.random() < 0.5:
                    out.append("R:1")
                    total += beat
        section += 1
    out.append(chord(0, root, scale) + ":6")
    total += 6 * beat
    out.append("# end, %.0f s" % total)
    print("\n".join(out))


if __name__ == "__main__":
    main()
