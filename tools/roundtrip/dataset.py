"""Discover all MIDIs under midi/ (recursively), flag lyric-bearing ones,
and split the rest into train (2/3) / validation (1/3) with a fixed seed.
"""
from __future__ import annotations
import json, random, warnings
from pathlib import Path
import mido
import pretty_midi

warnings.filterwarnings("ignore")

MIDI_ROOT = Path("/workspace/midi")
OUT_ROOT = Path("/workspace/rt")          # experiment root
SEED = 12345
MUSIC_EXTS = {".mid", ".midi", ".kar"}


def has_lyrics(path: Path) -> bool:
    try:
        mid = mido.MidiFile(str(path))
    except Exception:
        return False
    lyric = text = note_on = 0
    for track in mid.tracks:
        for msg in track:
            if msg.is_meta:
                if msg.type == "lyrics":
                    lyric += 1
                elif msg.type == "text":
                    text += 1
            elif msg.type == "note_on" and msg.velocity > 0:
                note_on += 1
    if lyric > 0:
        return True
    if text > 20 and note_on > 20:
        return True
    return False


def has_pitched_notes(path: Path) -> bool:
    try:
        m = pretty_midi.PrettyMIDI(str(path))
    except Exception:
        return False
    return any((not inst.is_drum and inst.notes) for inst in m.instruments)


def discover():
    files = sorted(p for p in MIDI_ROOT.rglob("*")
                   if p.is_file() and p.suffix.lower() in MUSIC_EXTS)
    kept, lyric_excluded = [], []
    for p in files:
        if has_lyrics(p):
            lyric_excluded.append(str(p.relative_to(MIDI_ROOT)))
            continue
        if not has_pitched_notes(p):
            continue
        kept.append(str(p.relative_to(MIDI_ROOT)))
    random.Random(SEED).shuffle(kept)
    n_train = int(round(len(kept) * 2 / 3))
    man = {
        "seed": SEED, "n_total": len(files),
        "n_lyric_excluded": len(lyric_excluded),
        "n_train": n_train, "n_val": len(kept) - n_train,
        "train": kept[:n_train], "val": kept[n_train:],
        "lyric_excluded": lyric_excluded,
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))
    print(f"total={len(files)} lyric_excluded={len(lyric_excluded)} "
          f"train={len(man['train'])} val={len(man['val'])}")
    return man


if __name__ == "__main__":
    discover()