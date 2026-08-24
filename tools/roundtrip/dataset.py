"""Build the round-trip dataset: discover all MIDIs under midi/ (recursively),
flag lyric-bearing ones, and split the rest into train (2/3) / validation (1/3).

Written to handled the FULL corpus (including subfolders). Splitting uses a
fixed seed so results are reproducible. A MIDI is kept only if it parses and
contains at least one pitched (non-drum) note that the synthesizer can render.
"""
from __future__ import annotations
import json, random, sys, warnings
from pathlib import Path
import mido
import pretty_midi

warnings.filterwarnings("ignore")

MIDI_ROOT = Path("/workspace/midi")
OUT_ROOT = Path("/workspace/midi_roundtrip")
SEED = 12345

MUSIC_EXTS = {".mid", ".midi", ".kar"}


def has_lyrics(path: Path) -> bool:
    """Detect lyric content via SMF Lyric (0x05) / text meta events carrying words."""
    try:
        mid = mido.MidiFile(str(path))
    except Exception:
        return False
    lyric = 0
    text = 0
    note_on = 0
    for track in mid.tracks:
        for msg in track:
            if msg.is_meta:
                if msg.type == "lyrics":
                    lyric += 1
                elif msg.type == "text":
                    text += 1
            elif msg.type == "note_on" and msg.velocity > 0:
                note_on += 1
    # karaoke-style: lyric meta present, or lots of text with notes
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
    for inst in m.instruments:
        if not inst.is_drum and inst.notes:
            return True
    return False


def discover():
    files = sorted(MIDI_ROOT.rglob("*"))
    files = [p for p in files
             if p.suffix.lower() in MUSIC_EXTS and p.is_file()]
    kept, lyric_excluded, failed = [], [], []
    for p in files:
        if has_lyrics(p):
            lyric_excluded.append(str(p.relative_to(MIDI_ROOT)))
            continue
        if not has_pitched_notes(p):
            failed.append(str(p.relative_to(MIDI_ROOT)))
            continue
        kept.append(str(p.relative_to(MIDI_ROOT)))

    random.Random(SEED).shuffle(kept)
    n_train = int(round(len(kept) * 2 / 3))
    train, val = kept[:n_train], kept[n_train:]

    manifest = {
        "seed": SEED,
        "n_total": len(files),
        "n_lyric_excluded": len(lyric_excluded),
        "n_no_pitched": len(failed),
        "n_train": len(train),
        "n_val": len(val),
        "train": train,
        "val": val,
        "lyric_excluded": lyric_excluded,
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(OUT_ROOT / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"total={len(files)} lyric_excluded={len(lyric_excluded)} "
          f"no_pitched={len(failed)} train={len(train)} val={len(val)}")
    print("LYRIC-EXCLUDED:", lyric_excluded[:20], "..." if len(lyric_excluded) > 20 else "")


if __name__ == "__main__":
    discover()