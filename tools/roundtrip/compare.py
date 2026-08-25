"""Evaluate pitch/duration fidelity between a ground-truth MIDI and a converted one."""
from __future__ import annotations
import warnings
import pretty_midi

warnings.filterwarnings("ignore")


def _notes(path: str):
    pm = pretty_midi.PrettyMIDI(str(path))
    out = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            out.append((n.pitch, n.start, n.end))
    return out


def compare(src: str, det: str):
    try:
        gts = sorted(_notes(src), key=lambda x: (x[1], x[0]))
        dets = sorted(_notes(det), key=lambda x: (x[1], x[0]))
    except Exception as exc:
        return {"error": str(exc)}
    matched = 0
    used = set()
    for gp, gs, ge in gts:
        best = None
        for di, (dp, ds, de) in enumerate(dets):
            if di in used:
                continue
            if dp != gp:
                continue
            ov = min(ge, de) - max(gs, ds)
            if ov <= 0:
                continue
            # same pitch, onset within tolerance, meaningful overlap
            on_drift = abs(ds - gs)
            if on_drift > 0.25:
                continue
            if on_drift < (best[0] if best else 1e9):
                best = (on_drift, ov, di)
        if best is not None:
            matched += 1
            used.add(best[2])
    n_gt, n_det = len(gts), len(dets)
    recall = matched / n_gt if n_gt else 0.0
    precision = matched / n_det if n_det else 0.0
    f = 2 * recall * precision / (recall + precision) if (recall + precision) else 0.0
    return {
        "gt_notes": n_gt, "det_notes": n_det,
        "matched": matched, "missed": n_gt - matched, "extra": n_det - matched,
        "recall": recall, "precision": precision, "f": f,
    }


AGG = ["n_files", "matched", "missed", "extra"]


def aggregate(rows, subset: str = "all"):
    rows = [r for r in rows if "error" not in r]
    n = len(rows)
    out = {"subset": subset,
           "mean_recall": 0.0, "mean_precision": 0.0, "mean_f": 0.0,
           "matched": 0, "missed": 0, "extra": 0, "n_files": n, "n_err": 0}
    if not rows:
        return out
    out["matched"] = sum(r["matched"] for r in rows)
    out["missed"] = sum(r["missed"] for r in rows)
    out["extra"] = sum(r["extra"] for r in rows)
    out["mean_recall"] = sum(r["recall"] for r in rows) / n
    out["mean_precision"] = sum(r["precision"] for r in rows) / n
    out["mean_f"] = sum(r["f"] for r in rows) / n
    return out