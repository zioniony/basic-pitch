"""Command-line entry points for the round-trip experiment.

Keeps multi-step Python logic out of the Makefile (heredocs + TAB-required
recipes do not mix) and gives `make synth/convert/eval-resume` something
simple to call:

    python tools/roundtrip/cli.py synth   --timbre rich
    python tools/roundtrip/cli.py convert --file midi/foo.mid --timbre rich
    python tools/roundtrip/cli.py resume  --split val --timbres rich fluidsynth
"""
from __future__ import annotations
import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[2]
MIDI_ROOT = ROOT / "midi"
RT = ROOT / "rt"


def _manifest() -> dict:
    f = RT / "manifest.json"
    if not f.exists():
        sys.exit("rt/manifest.json missing — run `make dataset` first")
    return json.loads(f.read_text())


def cmd_synth(args) -> None:
    from midi2wav import midi_to_wav
    man = _manifest()
    files = man["train"] + man["val"]
    out_root = RT / "wav" / args.timbre
    for i, rel in enumerate(files, 1):
        src = MIDI_ROOT / rel
        out = (out_root / rel).with_suffix(".wav")
        if out.exists():
            continue
        print(f"[{i}/{len(files)}] {rel}", flush=True)
        midi_to_wav(str(src), str(out), args.timbre)
    print(f"synth done: {out_root}")


def cmd_convert(args) -> None:
    from midi2wav import midi_to_wav
    from convert import convert_pm
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import Model

    src = Path(args.file)
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        sys.exit(f"not found: {src}")
    out_dir = RT / "out"
    wav = out_dir / (src.stem + ".wav")
    det = out_dir / (src.stem + "-converted.mid")
    print(f"midi -> wav  ({args.timbre})", flush=True)
    midi_to_wav(str(src), str(wav), args.timbre)
    print("wav -> midi  (basic-pitch + merge post-processing)", flush=True)
    model = Model(ICASSP_2022_MODEL_PATH)
    pm = convert_pm(model, str(wav), post="base")
    pm.write(str(det))
    print(f"done: {det}")


def cmd_resume(args) -> None:
    """Run `eval.run` and exit 0 only when the checkpoint covers the split.

    The eval loop itself is resumable (rt/ckpt_<split>.jsonl, one JSON line per
    finished file), so the Makefile can simply restart us after an OOM kill
    and work continues where it stopped.
    """
    from eval import run
    man = _manifest()
    target = len(man[args.split])
    while True:
        run(split=args.split, timbres=tuple(args.timbres), posts=("base", "clean"))
        ck = RT / f"ckpt_{args.split}.jsonl"
        done = len(ck.read_text().splitlines()) if ck.exists() else 0
        if done >= target:
            print(f"resume: checkpoint complete ({done}/{target})")
            return


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("synth", help="render every corpus midi to wav")
    p.add_argument("--timbre", default="rich", choices=("pluck", "rich", "fluidsynth"))
    p.set_defaults(fn=cmd_synth)

    p = sub.add_parser("convert", help="round-trip a single file")
    p.add_argument("--file", required=True, help="path to the .mid file")
    p.add_argument("--timbre", default="rich", choices=("pluck", "rich", "fluidsynth"))
    p.set_defaults(fn=cmd_convert)

    p = sub.add_parser("resume", help="run eval, restarting after kills until done")
    p.add_argument("--split", default="val", choices=("train", "val", "all"))
    p.add_argument("--timbres", nargs="+", default=["fluidsynth", "rich"])
    p.set_defaults(fn=cmd_resume)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
