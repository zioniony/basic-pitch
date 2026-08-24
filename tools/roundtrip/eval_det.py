"""Evaluate a split under a config from cached _det files OR from CONFIGS re-run.

Usage:
  eval_det.py <split> <config_id>   # recompute from _det/<config_id> (no model re-run)
"""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
from compare import compare

warnings.filterwarnings("ignore")
MIDI_ROOT = Path("/workspace/midi")
OUT_ROOT = Path("/workspace/midi_roundtrip")


def aggregate_from_det(split, cid):
    man = json.loads((OUT_ROOT / "manifest.json").read_text())
    files = man["train"] + man["val"] if split == "all" else man[split]
    detdir = OUT_ROOT / "_det" / cid
    rows, errs = [], []
    for rel in files:
        det = detdir / rel
        if not det.exists():
            errs.append(rel)
            continue
        r = compare(str(MIDI_ROOT / rel), str(det))
        if "error" in r:
            errs.append(rel)
            continue
        rows.append(r)
    return rows, errs


def agg(rows):
    if not rows:
        return {"n_files": 0, "mean_recall": 0, "mean_precision": 0, "mean_f": 0,
                "matched": 0, "missed": 0, "extra": 0}
    def f(r): return 2 * r["recall"] * r["precision"] / ((r["recall"] + r["precision"]) or 1e-9)
    return {
        "n_files": len(rows),
        "mean_recall": sum(r["recall"] for r in rows) / len(rows),
        "mean_precision": sum(r["precision"] for r in rows) / len(rows),
        "mean_f": sum(f(r) for r in rows) / len(rows),
        "matched": sum(r["matched"] for r in rows),
        "missed": sum(r["missed"] for r in rows),
        "extra": sum(r["extra"] for r in rows),
    }


if __name__ == "__main__":
    split, cid = sys.argv[1], sys.argv[2]
    rows, errs = aggregate_from_det(split, cid)
    a = agg(rows)
    print(f"[{split}/{cid}] n={a['n_files']} err={len(errs)} "
          f"recall={a['mean_recall']:.3f} prec={a['mean_precision']:.3f} "
          f"F={a['mean_f']:.3f} missed={a['missed']} extra={a['extra']}")
    if errs:
        print("MISSING/ERR:", errs[:10])