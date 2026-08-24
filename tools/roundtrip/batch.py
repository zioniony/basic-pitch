"""Batch round-trip driver.

For each file (train/val/all) and each convert config: synthesize wav (cached),
POST to /convert, save the converted MIDI, and evaluate note-pitch fidelity.

Aggregates per (config, split): mean recall / precision / F across files,
plus pooled matched/missed/extra note counts.
"""
from __future__ import annotations
import io, json, sys, time, warnings
from pathlib import Path
import requests
import pretty_midi
from compare import compare
from midi2wav import midi_to_wav

warnings.filterwarnings("ignore")

MIDI_ROOT = Path("/workspace/midi")
OUT_ROOT = Path("/workspace/midi_roundtrip")
BASE = "http://127.0.0.1:8000/convert"

CONFIGS = [
    {"id": "A", "onset": 0.6, "frame": 0.55, "minlen": 11, "seg": 0.3},
    {"id": "B", "onset": 0.7, "frame": 0.65, "minlen": 11, "seg": 0.2},
    {"id": "C", "onset": 0.7, "frame": 0.75, "minlen": 11, "seg": 0.3},
]


def load_manifest():
    return json.loads((OUT_ROOT / "manifest.json").read_text())


def relkey(rel):
    # group path key
    return rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def process(rel, cfg, keep_output=True):
    src = MIDI_ROOT / rel
    base = OUT_ROOT / rel                  # e.g. midi_roundtrip/吉他/X.mid
    wav = base.with_suffix(".wav")         # X.wav
    converted = base.with_name(base.stem + "-converted.mid")  # X-converted.mid
    if not wav.exists():
        wav.parent.mkdir(parents=True, exist_ok=True)
        midi_to_wav(src, wav)
    files = {"file": (wav.name, open(wav, "rb"), "audio/wav")}
    data = {"onset_threshold": cfg["onset"], "frame_threshold": cfg["frame"],
            "min_note_length": cfg["minlen"], "note_seg_threshold": cfg["seg"]}
    r = requests.post(BASE, files=files, data=data, timeout=900)
    if r.status_code != 200:
        return None, {"error": f"http{r.status_code} {r.text[:120]}"}
    if keep_output and cfg.get("id"):
        converted.parent.mkdir(parents=True, exist_ok=True)
        converted.write_bytes(r.content)
    # unique path for comparison (per split-config)
    detdir = OUT_ROOT / "_det" / (cfg.get("id") or "x")
    det = detdir / rel
    det.parent.mkdir(parents=True, exist_ok=True)
    det.write_bytes(r.content)
    return det, compare(str(src), str(det))


def aggregate(results):
    rows = [r for r in results if r is not None and "error" not in r]
    n_ok = len(rows)
    if n_ok == 0:
        return {"n_files": 0, "mean_recall": 0, "mean_precision": 0, "mean_f": 0,
                "matched": 0, "missed": 0, "extra": 0}
    def f(r): return 2 * r["recall"] * r["precision"] / ((r["recall"] + r["precision"]) or 1e-9)
    return {
        "n_files": n_ok,
        "mean_recall": sum(r["recall"] for r in rows) / n_ok,
        "mean_precision": sum(r["precision"] for r in rows) / n_ok,
        "mean_f": sum(f(r) for r in rows) / n_ok,
        "matched": sum(r["matched"] for r in rows),
        "missed": sum(r["missed"] for r in rows),
        "extra": sum(r["extra"] for r in rows),
    }


if __name__ == "__main__":
    split = sys.argv[1] if len(sys.argv) > 1 else "train"   # train | val | all | single:x
    man = load_manifest()
    if split == "all":
        files = man["train"] + man["val"]
    elif split.startswith("single:"):
        files = [split.split(":", 1)[1]]
    else:
        files = man[split]
    only_ids = [a for a in sys.argv[2:]]

    for cfg in CONFIGS:
        if only_ids and cfg["id"] not in only_ids and cfg["id"] != "X":
            continue
        results = []
        t0 = time.time()
        for rel in files:
            det, r = process(rel, cfg)
            results.append(r)
        agg = aggregate(results)
        resf = OUT_ROOT / "results"
        resf.mkdir(parents=True, exist_ok=True)
        (resf / f"{split}.json").write_text(
            json.dumps({"config": cfg, "aggregate": agg}, ensure_ascii=False, indent=2))
        print(f"[{split}] {cfg['id']} onset={cfg['onset']} fr={cfg['frame']} "
              f"seg={cfg['seg']} ({time.time()-t0:.0f}s) n={agg['n_files']} "
              f"recall={agg['mean_recall']:.3f} prec={agg['mean_precision']:.3f} "
              f"F={agg['mean_f']:.3f} missed={agg['missed']} extra={agg['extra']}")
        sys.stdout.flush()