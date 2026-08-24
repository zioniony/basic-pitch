"""Finalize: (1) reprocess any files missing a config-B detection, (2) set every
deliverable X-converted.mid to the config-B result, (3) print a final report."""
from __future__ import annotations
import json, warnings
from pathlib import Path
from batch import MIDI_ROOT, OUT_ROOT, load_manifest, process, CONFIGS, aggregate

warnings.filterwarnings("ignore")
B = CONFIGS[1]  # best config: B onset=0.7 frame=0.65 seg=0.2


def main():
    man = load_manifest()
    files = man["train"] + man["val"]
    detdir = OUT_ROOT / "_det" / B["id"]

    missing = [r for r in files if not (detdir / r).exists()]
    print(f"files missing config-{B['id']} detection: {len(missing)}")
    for rel in missing:
        det, r = process(rel, B)
        print("  reprocessed", rel, "->", "ok" if r and "error" not in r else r)

    # normalize all deliverables to config B
    copied, skipped = 0, []
    for rel in files:
        det = detdir / rel
        if not det.exists():
            skipped.append(rel)
            continue
        base = OUT_ROOT / rel
        out = base.with_name(base.stem + "-converted.mid")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(det.read_bytes())
        copied += 1
    print(f"normalized {copied} deliverables to config {B['id']}; skipped {len(skipped)}")
    for s in skipped:
        print("  SKIPPED", s)

    # final report
    report = {"best_config": B["id"], "configs": CONFIGS}
    for split in ["train", "val", "all"]:
        # recompute split aggregate from _det/B directly
        from eval_det import aggregate_from_det, agg
        rr, errs = aggregate_from_det(split, B["id"])
        report[split] = {**agg(rr), "n_errors": len(errs)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    (OUT_ROOT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("wrote", OUT_ROOT / "report.json")


if __name__ == "__main__":
    main()