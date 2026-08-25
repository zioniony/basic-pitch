"""Synthesize a MIDI to WAV for the round-trip experiment.

PROFILES let us vary the *preprocessing timbre* in a controlled way: either an
additive harmonic voice (pluck/rich) burned into wav ourselves, or a real GM
soundfont rendered through fluidsynth. The point is to test whether audio that
is close to what basic-pitch was trained on fixes the missed-note bottleneck.
"""
from __future__ import annotations
import os
import subprocess
import warnings
from pathlib import Path
import numpy as np
import pretty_midi
import soundfile as sf

warnings.filterwarnings("ignore")
SR = 44100

FLUIDSYNTH = "/usr/bin/fluidsynth"
# Real GM soundfonts installed with the `fluid-soundfont-gm` package. FluidR3
# renders close to the real-instrument audio basic-pitch was trained on, so it
# should help the missed-note bottleneck; fall back to the tiny TimGM6mb if it
# is not present.
def _pick_sf():
    for cand in (
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/sounds/sf2/TimGM6mb.sf2",
        Path(pretty_midi.__file__).parent / "TimGM6mb.sf2",
    ):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("no GM soundfont found")
SF_PATH = _pick_sf()


def freq(pitch: int) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


# Generic ADSR default; profiles override.
PROFILES = {
    # simple pluck: few harmonics, quick decay
    "pluck": {
        "n_harm": 4, "rolloff": 1.2, "atk": 0.004, "decay": 0.35,
        "sustain": 0.55, "rel": 0.05, "vib": 0.0,
    },
    # warm/brighter instrument: many harmonics, longer sustain
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
    nd = int(decay * sr)
    tail = n - at
    nd = min(nd, tail)
    tt = np.arange(tail)
    dec = np.exp(-tt / max(1, nd)) * (1.0 - sustain) + sustain
    e[at:] = dec[: tail]
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
    amps = amps / amps.sum()
    phase = np.exp(1j * 2 * np.pi * base[:, None] * f0 * t[None, :])
    sig = (amps[:, None] * phase).sum(axis=0).real
    return sig


# Seconds of audio rendered per _voice() call. A whole-piece pedal note with 14
# harmonics would otherwise allocate a ~3GB complex matrix and blow the 4GB
# container limit mid-synthesis (leaving a torn wav).
VOICE_CHUNK_S = 2.0


def _stereo_to_mono_peak(wav: str) -> None:
    """fluidsynth emits 16-bit stereo; basic-pitch wants mono float in [-1,1].
    Fold to mono (average channels) and normalize the peak so the model sees a
    healthy, uniform level. Rewrites ATOMICALLY: a process killed mid-write
    must never leave a torn .wav behind (predict would then allocate from a
    garbage header and OOM the container)."""
    data, sr = sf.read(wav, always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    peak = np.max(np.abs(data))
    if peak > 0:
        data = data / peak * 0.9
    tmp = wav + ".tmp.wav"
    sf.write(tmp, data.astype(np.float32), sr, format="WAV", subtype="FLOAT")
    os.replace(tmp, wav)


def _render_note(buf: np.ndarray, start: int, dur: float, pitch: int, vel: float,
                 p: dict) -> None:
    """Add one note into buf, rendering in bounded chunks so a note of ANY
    duration costs the same peak memory."""
    env = _envelope(dur, SR, p["atk"], p["decay"], p["sustain"], p["rel"])
    if env.size == 0:
        return
    nenv = min(env.size, len(buf) - start)
    if nenv <= 0:
        return
    gain = (vel / 127.0) ** 1.5
    step = int(VOICE_CHUNK_S * SR)
    for ofs in range(0, nenv, step):
        k = min(step, nenv - ofs)
        t = (np.arange(ofs, ofs + k)) / SR
        sig = _voice(t, p["n_harm"], p["rolloff"], pitch, p["vib"])
        buf[start + ofs:start + ofs + k] += gain * sig * env[ofs:ofs + k]


def _synthesize(src, out, profile):
    """Additive-harmonic fallback (pluck / rich)."""
    p = PROFILES[profile]
    pm = pretty_midi.PrettyMIDI(str(src))
    end_t = max((max((n.end for n in inst.notes), default=0.0) for inst in pm.instruments), default=0.0)
    total = end_t + 1.0
    buf = np.zeros(int(total * SR) + int(1 * SR), dtype=np.float64)
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            start = int(n.start * SR)
            if start < 0 or n.end - n.start <= 0:
                continue
            _render_note(buf, start, n.end - n.start, n.pitch, n.velocity, p)
    peak = np.max(np.abs(buf))
    if peak > 0:
        buf = buf / peak * 0.9
    tmp = str(out) + ".tmp.wav"
    sf.write(tmp, buf, SR, format="WAV", subtype="FLOAT")
    os.replace(tmp, str(out))


def midi_to_wav(src: str, out: str, profile: str = "rich") -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if profile == "fluidsynth":
        # -R 0 / -C 0: disable reverb+chorus. The bundled timgm soundfont has
        # echo on by default, which smears note tails into sustained harmonics
        # that basic-pitch mis-reads as extra ghost notes (extra benchmark).
        cmd = [FLUIDSYNTH, "-ni", "-R", "0", "-C", "0",
               "-F", out, "-r", str(SR), "-g", "0.9",
               str(SF_PATH), str(src)]
        subprocess.run(cmd, check=True, capture_output=True)
        _stereo_to_mono_peak(out)
        return
    _synthesize(src, out, profile)


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(Path(src).with_suffix(".wav"))
    prof = sys.argv[3] if len(sys.argv) > 3 else "rich"
    midi_to_wav(src, out, prof)
    print(f"wrote {out} ({prof})")