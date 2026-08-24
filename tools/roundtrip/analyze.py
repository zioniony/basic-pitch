"""Analyze candidate midi files: tracks, tempo, duration, note count, polyphony."""
import sys, pretty_midi

def analyze(path):
    try:
        mid = pretty_midi.PrettyMIDI(path)
    except Exception as e:
        return f"{path}\n  ERROR {e}"
    tempo = mid.estimate_tempo()
    dur = mid.get_end_time()
    notes = []
    prog_names = []
    for inst in mid.instruments:
        notes.extend(inst.notes)
        prog_names.append((inst.program, inst.is_drum, len(inst.notes)))
    events = []
    for inst in mid.instruments:
        for n in inst.notes:
            events.append((n.start, 1))
            events.append((n.end, -1))
    events.sort()
    cur = 0; maxpoly = 0
    for t, d in events:
        cur += d
        maxpoly = max(maxpoly, cur)
    n_notes = len(notes)
    avg_vel = sum(n.velocity for n in notes)/max(1,n_notes)
    pmin = min((n.pitch for n in notes), default=0)
    pmax = max((n.pitch for n in notes), default=0)
    return (f"{path}\n"
            f"  tempo={tempo:.1f} dur={dur:.2f}s notes={n_notes} maxpoly={maxpoly} "
            f"pitch_range=[{pmin},{pmax}] avg_vel={avg_vel:.0f} programs={prog_names}")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(analyze(p))