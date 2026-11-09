# tokens-to-tones

A score that grows while it plays: tokens in, tones out. Four tiny Pliny Python scripts, no DAW, no MIDI:

- `player.py` tails `score.txt` and **plays every new line the moment it lands**. Lines are phrases of tokens
  (notes, chords, rests, tempo, timbre, volume). The queue never waits for the author: write a whole piece
  and go work, or feed it one phrase at a time from a chat, a script, or a model.
- `composer.py` generates a piece from a few knobs (key, mode, tempo, minutes, seed), deterministic by seed.
- `dur.py` tells you exactly how long a piece will play, before you queue it.
- `listen.py` records what the speakers are playing (Stereo Mix / loopback, or the microphone) and names the
  notes it finds, window by window, with cents of error. The ear for a program that otherwise only writes.

Built in one night (2026-11-09) between two humans-and-a-model conversations about whether a language model can
play live. It can, at the granularity of a phrase per turn, and it can check its own output through the speakers.

## Token grammar

One phrase per line, tokens separated by spaces:

```
C4 E4 G4          notes: letter, optional # or b, octave; a plain note lasts one beat
C4:2  G4:0.5      a note with a length in beats
[C4 E4 G4]:2      a chord (notes inside brackets), with a length
R  R:0.5          rest
tempo=120         beats per minute (persists)
wave=pluck        sine | tri | saw | square | pluck (persists)
vol=0.3           0..1 (persists)
# comment         ignored
```

## Run

```
pip install numpy sounddevice
python player.py            # in one terminal (or detached); it writes player.pid and player.log
printf 'tempo=84 wave=pluck\n[A3 C4 E4]:2 E5:0.5 D5:0.5 C5\n' >> score.txt
python composer.py --minutes 8 --key A --mode minor --tempo 80 --seed 11 >> score.txt
python dur.py some-piece.txt
python listen.py 9          # records 9 s and prints the notes it hears
python listen.py 3 mic      # force the microphone
python listen.py 0 file     # re-analyse the last take.wav
```

On restart the player only plays lines added after it started: the past is not replayed.

## Honest limits

- A language model does not run between turns, so its "live" is one phrase per turn, or a queued piece.
- `listen.py` measures, it does not hear: FFT peaks mapped to the nearest note. Stereo Mix on Realtek is
  post-volume (a quiet speaker gives a quiet take), so the loudness floor is relative to the take.
- Monophonic timbres, no effects. It is a sketchpad, not an instrument.

## License

MIT.
