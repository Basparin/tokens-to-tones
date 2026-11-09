# tokens-to-tones

A score that grows while it plays: tokens in, tones out. A few small Python scripts, no DAW:

- `player.py` tails `score.txt` and **plays every new line the moment it lands**. Lines are phrases of tokens
  (notes, chords, rests, tempo, timbre, volume). The queue never waits for the author: write a whole piece
  and go work, or feed it one phrase at a time from a chat, a script, or a model.
- `composer.py` generates a piece from a few knobs (key, mode, tempo, minutes, seed), deterministic by seed.
- `dur.py` tells you exactly how long a piece will play, before you queue it.
- `sing.py` makes a neural TTS voice **sing** a melody: Praat PSOLA replaces the speech pitch with the notes
  (one slice of voiced time per note, by beats) and stretches each slice onto its beat.
- `audible.py` says whether a process is actually making sound (per-process Windows audio peak meter), so
  "it is playing" is measured, not inferred from a live PID.
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
wave=pluck        sine | tri | saw | square | pluck: numpy synth, also switches back from MIDI (persists)
inst=48           General MIDI program (0 piano, 24 nylon guitar, 48 strings, 52 choir...) on the Windows
                  "Microsoft GS Wavetable Synth": real instruments, zero assets (persists)
voice=es-CL-LorenzoNeural   speaking voice: any edge-tts voice, or piper, or sapi (persists)
say=any text      speaks the rest of the line after the notes before it (edge-tts -> Piper -> SAPI)
vol=0.3           0..1 (persists)
# comment         ignored
```

## Run

```
pip install numpy sounddevice pygame edge-tts piper-tts pywin32 praat-parselmouth pycaw
python player.py            # in one terminal (or detached); it writes player.pid and player.log
printf 'tempo=84 wave=pluck\n[A3 C4 E4]:2 E5:0.5 D5:0.5 C5\n' >> score.txt
python composer.py --minutes 8 --key A --mode minor --tempo 80 --seed 11 >> score.txt
python dur.py some-piece.txt
python listen.py 9          # records 9 s and prints the notes it hears
python listen.py 3 mic      # force the microphone
python listen.py 0 file     # re-analyse the last take.wav
python sing.py              # writes voices/sing-demo-{raw,sung}.wav
python audible.py          # every audio session and its peak; audible.py <pid|name> 3 -> exit 0 if audible
```

On restart the player only plays lines added after it started: the past is not replayed.

## Honest limits

- A language model does not run between turns, so its "live" is one phrase per turn, or a queued piece.
- `listen.py` measures, it does not hear: FFT peaks mapped to the nearest note. Stereo Mix on Realtek is
  post-volume (a quiet speaker gives a quiet take), so the loudness floor is relative to the take.
- One instrument per line in the live player; layered songs are rendered offline (SoundFont + voice mix).
- `sing.py` is pitch-correct, not a singer: measured 88-91% of voiced frames within half a semitone of the
  scale on two test lines (Praat pitch track), with exact note durations when the source is spoken 25% slower.
  Whether it sounds natural is for an ear to judge, not for the meter.
- `say=` needs the network for edge-tts; without it Piper (local es_MX model) and then SAPI take over.

## License

MIT.
