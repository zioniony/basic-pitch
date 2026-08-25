# Round-trip experiment: MIDI → WAV → MIDI

Goal: quantify how faithfully our `convert` service (basic-pitch) can recover a
MIDI file after synthesizing it to audio, and tune every stage we control —
preprocessing (synthesis timbre), detection thresholds and post-processing
functions — to maximize pitch fidelity.

The experiment answers three questions:

1. Which synthesis timbre gives the detector the best chance?
2. Are tuned detection thresholds worth more than smarter post-processing?
3. How do we run all of this reliably inside a memory-capped sandbox?

## Pipeline

```
midi/*.mid ──(dataset.py)──> rt/manifest.json        # 2/3 train, 1/3 val, lyric files excluded
      │
      ├──(midi2wav.py, TIMBRE)──> rt/wav/<timbre>/*.wav
      │         timbre = pluck | rich | fluidsynth
      │
      └──(convert.py)──> rt/det/<post>/*.mid
                basic-pitch predict (tuned DET_CFG)
                + post-processing: base | clean

compare.py scores each round trip at note level:
a GT note counts as matched iff same pitch, onset within 0.25 s, time overlap.
```

## Usage (Makefile)

```sh
make deps                        # uv sync + fluidsynth + FluidR3 soundfont
make dataset                     # (re)build the train/val split
make synth TIMBRE=rich           # render corpus wavs for one timbre
make convert FILE=midi/foo.mid   # single round trip -> rt/out/foo-converted.mid
make eval TIMBRES="rich"         # batch evaluate on the val split
make eval-resume                 # eval that auto-restarts after OOM kills
make serve                       # run the local web app
```

Tunables: `TIMBRE` (pluck|rich|fluidsynth), `TIMBRES` (space-separated list
for `eval`), `SPLIT` (train|val|all).

## Results (88 held-out validation files)

| timbre / post | recall | precision | F1    | missed | extra |
|---------------|--------|-----------|-------|--------|-------|
| rich / base   | 0.708  | 0.931     | 0.788 | 41 450 | 5 475 |
| rich / clean  | 0.701  | 0.937     | 0.785 | 42 367 | 4 830 |
| fluidsynth / base | 0.673 | 0.884   | 0.738 | 44 955 | 7 646 |
| fluidsynth / clean | 0.663 | 0.896  | 0.736 | 45 962 | 6 523 |

Full aggregates live in `rt/results_val.json`; per-file rows in
`rt/ckpt_val.jsonl` (regenerable, not committed).

### Findings

- **Timbre is the big lever, post-processing is not.** The additive `rich`
  voice beats the FluidR3 soundfont render by ~5 F1 points. Even though
  fluidsynth audio is "more realistic", it also costs precision (harmonic
  ghosts, extra notes). Switching the *preprocessing function* moved F1 by
  0.05; switching the *post-processing function* (`clean` vs `base`) moved it
  by 0.003.
- **Losses are dominated by missed notes** (~41 k missed vs ~5 k extra).
  Post-processing can delete ghosts (−12% extra) but cannot resurrect notes
  the model never detected — that ceiling belongs to timbre and thresholds.
  Hence the tuned config (onset 0.7 / frame 0.65) is now the default of the
  `/convert` endpoint and of the web UI slider.
- **"More realistic" ≠ "better detected".** Reverb off (`-R 0 -C 0`) barely
  changed fluidsynth scores; the soundfont's softer attacks are what hurt.

## Engineering notes (running under a 4 GB cgroup)

Long eval runs kept dying with SIGKILL. Root cause chain, worth remembering:

1. A process killed mid-`sf.write()` leaves a **torn wav** that still passes
   `.exists()` — and even `sf.info()` (valid header, truncated data).
2. basic-pitch then allocates buffers from garbage lengths → RSS spikes to
   4 GB → OOM killer strikes → more torn files. A vicious cycle.
3. Separately, synthesizing one whole-piece pedal note (5 min × 14 harmonics,
   complex128) allocated a ~3 GB phase matrix by itself.

Fixes now baked into the tools:

- **Atomic writes** — wavs are written to `*.tmp.wav` then `os.replace`d
  ([midi2wav.py](midi2wav.py)); a kill can never leave a half-written wav.
- **Chunked synthesis** — notes render in 2 s blocks, so peak memory is
  independent of note duration (`_render_note`).
- **Duration validation** — `_ensure_wav` in [eval.py](eval.py) compares each
  cached wav's duration against the source midi and re-renders anything short
  before predict.
- **Per-file checkpoints** — eval appends one JSON line per finished file to
  `rt/ckpt_<split>.jsonl`; any killed run resumes exactly where it stopped
  (`make eval-resume`).

## Files

| file | role |
|------|------|
| [dataset.py](dataset.py) | discover corpus, exclude lyric tracks, write 2/3–1/3 split |
| [midi2wav.py](midi2wav.py) | synth backends: additive `pluck`/`rich`, `fluidsynth` + GM soundfont |
| [convert.py](convert.py) | basic-pitch predict (tuned `DET_CFG`) + pluggable post (`base`/`clean`) |
| [compare.py](compare.py) | note-level matching and aggregate metrics |
| [eval.py](eval.py) | batch driver: timbre × post grid, checkpoints, torn-wav guard |
| [cli.py](cli.py) | `synth` / `convert` / `resume` subcommands used by the Makefile |
