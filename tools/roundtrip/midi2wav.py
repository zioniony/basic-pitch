"""Preprocessing: synthesize a MIDI file to 22.05kHz mono WAV.

The project's /convert pipeline normalizes audio to 22.05kHz mono and runs the
basic-pitch ICASSP 2022 model. We synthesize each note as a plucked-string /
piano-like oscillator whose spectrum is dominated by the fundamental and low
partials (reduces detector octave errors) with a clear attack (helps onset
detection) and a sustained level high enough to keep the note audible for its
full MIDI length (so detected note length tracks MIDI length).
"""
import sys, wave, struct, math
import numpy as np
import pretty_midi

SR = 22050


def note_wave(pitch, vel, t_start, t_end, sr=SR):
    """Return rendered samples [t_start*sr : t_end*sr] for one note."""
    f0 = 440.0 * 2.0 ** ((pitch - 69) / 12.0)
    dur = t_end - t_start
    n = max(1, int(round(dur * sr)))
    t = np.arange(n, dtype=np.float64) / sr
    # Harmonic weights: fundamental strong, realistic decay -> avoids pitch errors.
    # Slight inharmonicity drift (piano-like) to keep it realistic yet spectrally clean.
    weights = np.array([1.00, 0.50, 0.27, 0.17, 0.11, 0.07, 0.05, 0.03, 0.02])
    phase = 0.0
    sig = np.zeros(n, dtype=np.float64)
    for k, amp in enumerate(weights, start=1):
        fk = f0 * k * (1.0 + 0.00035 * k * k)  # mild inharmonicity
        sig += amp * np.sin(2 * math.pi * fk * t + phase)
    phase = 0.0
    sig /= weights.sum()
    # ADSR-like envelope: 4ms attack, ~25% exponential decay to sustain floor,
    # gentle release near the end so the note keeps energy through note_end.
    # Lengths are clamped to the note length n (robust to ultra-short notes).
    atk = min(n, int(round(0.004 * sr)))
    sus_frac = 0.55
    env = np.ones(n, dtype=np.float64)
    if atk > 0:
        env[:atk] = np.linspace(0.0, 1.0, atk)
    ndecay = max(0, min(n - atk, int(round(0.020 * sr))))
    if ndecay > 0:
        env[atk:atk + ndecay] = np.linspace(1.0, sus_frac, ndecay)
    # soft release on last 12ms to avoid clicks
    rls = max(0, min(n, int(round(0.012 * sr))))
    if rls > 0:
        env[-rls:] *= np.linspace(1.0, 0.0, rls)
    amp = (vel / 127.0) ** 1.2 * 0.6
    return (sig * env * amp).astype(np.float64)


def midi_to_wav(midi_path, wav_path, sr=SR):
    mid = pretty_midi.PrettyMIDI(midi_path)
    end = mid.get_end_time()
    total = np.zeros(int(math.ceil(end * sr)) + sr, dtype=np.float64)
    # drop drum channel (percussion) and synthesize pitched tracks
    n_notes = 0
    for inst in mid.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            s = note_wave(note.pitch, note.velocity, note.start, note.end, sr)
            i0 = int(round(note.start * sr))
            i1 = i0 + s.size
            if i1 > total.size:
                total = np.concatenate([total, np.zeros(i1 - total.size)])
            total[i0:i1] += s
            n_notes += 1
    if n_notes == 0:
        raise RuntimeError(f"No pitched notes in {midi_path}")
    # normalize to peak 0.9
    peak = np.max(np.abs(total)) or 1.0
    total = (total / peak) * 0.9
    pcm = (total * 32767).astype(np.int16)
    with wave.open(str(wav_path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(pcm.tobytes())


if __name__ == "__main__":
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + ".wav"
    midi_to_wav(src, dst)
    print(f"rendered {dst}")