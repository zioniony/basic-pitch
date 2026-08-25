"""Compare timbre (preprocessing) x post-processing function on the dataset.

For each (timbre, post) combo, aggregate pitch-fidelity metrics on a split.
The detector runs once per (file, timbre); both post options are derived from
copies of the same detected notes, so the function lever is isolated cheaply.
"""
from __future__ import annotations
import copy, json, sys, time, warnings
from pathlib import Path
import pretty_midi
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import Model

warnings.filterwarnings("ignore")

MIDI_ROOT = Path("/workspace/midi")
OUT = Path("/workspace/rt")
from compare import compare, aggregate
from midi2wav import midi_to_wav
from convert import POSTS, convert_pm


def load_manifest():
    man_f = OUT / "manifest.json"
    if not man_f.exists():
        import dataset
        return dataset.discover()
    return json.loads(man_f.read_text())


def run(split="val", timbres=("pluck", "rich"), posts=("base", "clean"), files=None):
    man = load_manifest()
    rels = files or (man["train"] + man["val"] if split == "all" else man[split])
    model = Model(ICASSP_2022_MODEL_PATH)
    print(f"split={split} n_files={len(rels)} timbres={timbres} posts={posts}")
    # rows[timbre][post] = list of compare dicts
    results = {t: {p: [] for p in posts} for t in timbres}
    errs = {t: [] for t in timbres}

    for i, rel in enumerate(rels):
        src = MIDI_ROOT / rel
        for t in timbres:
            wav = OUT / "wav" / t / rel
            wav = wav.with_suffix(".wav")
            if not wav.exists():
                midi_to_wav(str(src), str(wav), t)
            try:
                pm = convert_pm(model, str(wav), post="raw")  # raw detected notes
            except Exception as exc:
                errs[t].append(rel)
                for p in posts:
                    results[t][p].append({"error": str(exc)[:80]})
                continue
            for p in posts:
                m = copy.deepcopy(pm)
                POSTS[p](m)
                det = OUT / "det" / p / rel
                det.parent.mkdir(parents=True, exist_ok=True)
                det.write_bytes(_write(m, det))
                results[t][p].append(compare(str(src), str(det)))
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(rels)} done", flush=True)

    print("\n=== AGGREGATE (pitch fidelity) ===")
    for t in timbres:
        for p in posts:
            a = aggregate(results[t][p])
            print(f"[{t:5s}/{p:5s}] n={a['n_files']} err={a['n_err']} "
                  f"recall={a['mean_recall']:.3f} prec={a['mean_precision']:.3f} "
                  f"F={a['mean_f']:.3f} missed={a['missed']} extra={a['extra']}")
    (OUT / f"results_{split}.json").write_text(printable(man, timbres, posts, results))
    print("wrote", OUT / f"results_{split}.json")


def _write(pm, path):
    import io
    buf = io.BytesIO(); pm.write(buf); return buf.getvalue()


def printable(man, timbres, posts, results):
    out = {"split_manifest": man, "by_combo": {}}
    for t in timbres:
        for p in posts:
            out["by_combo"][f"{t}/{p}"] = aggregate(results[t][p])
    return json.dumps(out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    split = sys.argv[1] if len(sys.argv) > 1 else "val"
    run(split=split)