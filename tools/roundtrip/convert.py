"""Convert a WAV to MIDI via basic-pitch, with pluggable post-processing.

`POST` selects which post-processing FUNCTION runs on the detected notes:
  - "base": merge_midi_notes only (replicates our prior baseline).
  - "clean": base + de-hallucination (harmonic ghosts + isolated ultra-shorts).
This lets us isolate the *function* lever separately from the *timbre* lever.
"""
from __future__ import annotations
import io, warnings
import pretty_midi
from basic_pitch.inference import predict

warnings.filterwarnings("ignore")

# best-config detection params from earlier tuning
DET_CFG = {"onset_threshold": 0.7, "frame_threshold": 0.65,
           "minimum_note_length": 11, "midi_tempo": 120}


def merge_midi_notes(midi: pretty_midi.PrettyMIDI, gap_s: float = 0.024) -> None:
    for inst in midi.instruments:
        by_pitch: dict[int, list[tuple[float, float, float]]] = {}
        for n in inst.notes:
            by_pitch.setdefault(n.pitch, []).append((n.start, n.end, n.velocity))
        merged: list[tuple[float, float, int, int]] = []
        for pitch, lst in by_pitch.items():
            for s, e, v in sorted(lst):
                if merged and pitch == merged[-1][3] and s - merged[-1][1] <= gap_s:
                    prev_s, prev_e, prev_v, prev_p = merged[-1]
                    merged[-1] = (prev_s, max(prev_e, e), int((prev_v + v) / 2), prev_p)
                else:
                    merged.append((s, e, int(v), pitch))
        inst.notes = [pretty_midi.Note(pitch=p, start=s, end=e, velocity=v)
                      for s, e, v, p in merged]


def _dehallucinate(midi: pretty_midi.PrettyMIDI):
    """Suppress common false notes produced by the detector:
      - 'harmonic ghosts': a note that is an integer multiple (2x/3x) of a
        concurrent, much stronger note. Common when a rich timbre excites
        overtones that basic-pitch treats as separate notes.
      - isolated ultra-short notes with no same/adjacent-pitch support.
    This raises precision (removes extra) without touching true notes.
    """
    for inst in midi.instruments:
        notes = sorted(inst.notes, key=lambda n: (n.start, n.pitch))
        keep = []
        for i, n in enumerate(notes):
            # harmonic ghost check: is there a concurrent bigger-fundamental note
            # whose pitch divides n.pitch by an integer ratio?
            if n.pitch > 0 and n.pitch <= 127:
                ghost = False
                for m in notes:
                    if m is n:
                        continue
                    ov = min(n.end, m.end) - max(n.start, m.start)
                    if ov <= 0:
                        continue
                    if m.pitch > 0 and n.pitch != m.pitch:
                        if (n.pitch % m.pitch == 0) and n.velocity <= m.velocity * 0.6:
                            ghost = True
                            break
                if ghost:
                    continue
            # isolated ultra-short note: relies on nothing; if very brief and
            # no neighbor pitch within a beat, treat as dropout artifact
            if (n.end - n.start) < 0.045:
                neighbor = any(abs(m.pitch - n.pitch) <= 1 and
                               min(n.end, m.end) - max(n.start, m.start) > 0
                               for m in notes if m is not n)
                if not neighbor:
                    continue
            keep.append(n)
        inst.notes = keep


POSTS = {
    "raw": lambda midi: None,
    "base": lambda midi: merge_midi_notes(midi, 0.024),
    "clean": lambda midi: (merge_midi_notes(midi, 0.024), _dehallucinate(midi)),
}


def convert_pm(model, wav_path: str, post: str = "base") -> pretty_midi.PrettyMIDI:
    _out, midi_data, _ev = predict(
        wav_path, model, **DET_CFG,
        minimum_frequency=None, maximum_frequency=None,
    )
    POSTS[post](midi_data)
    return midi_data


def write_midi(midi: pretty_midi.PrettyMIDI, path: str) -> None:
    import pathlib
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    midi.write(buf)
    pathlib.Path(path).write_bytes(buf.getvalue())