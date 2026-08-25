"""Synthesize a MIDI to WAV for the round-trip experiment.

PROFILES let us vary the *preprocessing timbre* in a controlled way so we can
test whether a timbre closer to real instruments fixes the detection bottleneck
(the 29% missed notes). Use a single additive voice (harmonic series) so the
differences we measure are attributable to the timbre profile, not the synth.
"""
from __future__ import annotations
import warnings
from pathlib import Path
import numpy as np
import pretty_midi
import soundfile as sf

warnings.filterwarnings("ignore")
SR = 44100

# A = 440.0 * 2**((pitch-69)/12)
def freq(pitch: int) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)

# Generic ADSR default; profiles override.
# A sharp, clean attack with enough harmonic energy tends to raise the model's
# per-frame confidence -> fewer missed notes.
PROFILES = {
    # simple pluck: few harmonics, quick decay (our earlier default feel)
    "pluck": {
        "n_harm": 4, "rolloff": 1.2, "atk": 0.004, "decay": 0.35,
        "sustain": 0.55, "rel": 0.05, "vib": 0.0,
    },
    # warm/brighter instrument: many harmonics, longer sustain -> more spectral
    # content the model can lock onto.
    "rich": {
        "n_harm": 14, "rolloff": 0.8, "atk": 0.006, "decay": 0.50,
        "sustain": 0.78, "rel": 0.10, "vib": 0.05,
    },
}

def _envelope(dur: float, sr: int, atk: float, decay: float, sustain: float, rel: float):
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    e = np.zeros(n)
    na = max(1, int(atk * sr))
    at = min(na, n)
    e[:at] = np.linspace(0.0, 1.0, at)
    # exponential decay from 1.0 to sustain over decay window
    nd = int(decay * sr)
    tail = n - at
    nd = min(nd, tail)
    tt = np.arange(tail)
    dec = np.exp(-tt / max(1, nd)) * (1.0 - sustain) + sustain
    e[at:] = dec[: tail]
    # short release taper at the very end to avoid clicks
    nr = int(rel * sr)
    nr = min(nr, n)
    if nr > 0:
        ramp = np.linspace(1.0, 0.0, nr) ** 2
        e[n - nr:] *= ramp
    return e

def _voice(t: np.ndarray, n_harm: int, rolloff: float, pitch: int, vib: float):
    f0 = freq(pitch)
    base = np.arange(1, n_harm + 1)
    amps = 1.0 / (base ** rolloff)
    # normalize so fundamental ~ dominates but harmonics give body
    amps = amps / amps.sum()
    phase = np.exp(1j * 2 * np.pi * base[:, None] * f0 * t[None, :])
    sig = (amps[:, None] * phase).sum(axis=0).real
    return sig

def midi_to_wav(src: str, out: str, profile: str = "rich") -> None:
    pm = pretty_midi.PrettyMIDI(str(src))
    p = PROFILES[profile]
    end_t = max((max((n.end for n in inst.notes), default=0.0) for inst in pm.instruments), default=0.0)
    total = end_t + 1.0
    buf = np.zeros(int(total * SR) + int(1 * SR), dtype=np.float64)
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            start = int(n.start * SR)
            dur = n.end - n.start
            if dur <= 0 or start < 0:
                continue
            env = _envelope(dur, SR, p["atk"], p["decay"], p["sustain"], p["rel"])
            if env.size == 0:
                continue
            nenv = min(env.size, len(buf) - start)
            if nenv <= 0:
                continue
            t = np.arange(nenv) / SR
            sig = _voice(t, p["n_harm"], p["rolloff"], n.pitch, p["vib"]) * env[:nenv]
            # velocity drives loudness (muted -> quieter amplitude); cap
            gain = (n.velocity / 127.0) ** 1.5
            buf[start:start + nenv] += gain * sig
    # normalize peak to a healthy input level (loud, uniform SNR for the model)
    peak = np.max(np.abs(buf))
    if peak > 0:
        buf = buf / peak * 0.9
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, buf, SR)


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(Path(src).with_suffix(".wav"))
    prof = sys.argv[3] if len(sys.argv) > 3 else "rich"
    midi_to_wav(src, out, prof)
    print(f"wrote {out} ({prof})")