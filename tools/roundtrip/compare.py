"""Compare a converted MIDI against the original at note level.

Runs basic-pitch-style evaluation: missing notes (GT not detected),
extra/false notes (detected without GT), and timing statistics on matched notes.
A note matches if same pitch and onset within tolerance.
"""
import sys, warnings
warnings.filterwarnings("ignore")
import pretty_midi


def seq(path):
    mid = pretty_midi.PrettyMIDI(path)
    out = []
    for inst in mid.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            out.append((n.pitch, n.start, n.end))
    out.sort(key=lambda x: (x[1], x[0]))
    return out, mid


def compare(gt_path, det_path, onset_tol=0.05, pitch_tol=0):
    gt, mid_gt = seq(gt_path)
    det, mid_det = seq(det_path)
    matched = []          # (gt_idx, det_idx)
    used_det = set()
    # for each GT note, find best detected note (same pitch, smallest |onset|)
    for gi, (gp, gs, ge) in enumerate(gt):
        best = None
        for di, (dp, ds, de) in enumerate(det):
            if di in used_det:
                continue
            if dp == gp:
                dt = abs(ds - gs)
                if dt <= onset_tol and (best is None or dt < best[0]):
                    best = (dt, di)
        if best:
            matched.append((gi, best[1]))
            used_det.add(best[1])
    matched_set = {gi for gi, _ in matched}
    det_used_set = {di for _, di in matched}
    missed = [i for i in range(len(gt)) if i not in matched_set]
    extra = [i for i in range(len(det)) if i not in det_used_set]

    onset_deltas = [det[j][1] - gt[i][1] for i, j in matched]
    offset_deltas = [det[j][2] - gt[i][2] for i, j in matched]
    def med(xs): return sorted(xs)[len(xs)//2] if xs else 0.0
    def mean(xs): return sum(xs)/len(xs) if xs else 0.0

    return {
        "gt_notes": len(gt), "det_notes": len(det),
        "matched": len(matched), "missed": len(missed), "extra": len(extra),
        "recall": len(matched)/max(1,len(gt)),
        "precision": len(matched)/max(1,len(det)),
        "onset_shift_med": med(onset_deltas), "onset_shift_mean": mean(onset_deltas),
        "offset_shift_med": med(offset_deltas), "offset_shift_mean": mean(offset_deltas),
    }


def fmt(r):
    return (f"GT={r['gt_notes']} det={r['det_notes']} matched={r['matched']} "
            f"missed={r['missed']} extra={r['extra']}\n"
            f"recall={r['recall']:.3f} precision={r['precision']:.3f}\n"
            f"onset_shift med={r['onset_shift_med']*1000:.1f}ms mean={r['onset_shift_mean']*1000:.1f}ms\n"
            f"offset_shift med={r['offset_shift_med']*1000:.1f}ms mean={r['offset_shift_mean']*1000:.1f}ms")


if __name__ == "__main__":
    r = compare(sys.argv[1], sys.argv[2],
                onset_tol=float(sys.argv[3]) if len(sys.argv) > 3 else 0.05)
    print(fmt(r))