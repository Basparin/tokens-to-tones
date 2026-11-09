"""audible.py -- is a process actually making sound? Liveness for audio, measured, never inferred.

Born 2026-11-09: Teseo said "está sonando" twice from a live PID (hidden ffplay, then Windows Media
Player) without checking that any audio reached the speakers. A live process is not sound.

Usage:
  python audible.py                 list every audio session with its current peak
  python audible.py <pid|name> [s]  sample that process for s seconds (default 3);
                                    exit 0 = AUDIBLE (peak > 0.01), 1 = SILENT, 2 = no audio session
Reads the Windows per-session peak meter (pycaw / IAudioMeterInformation) of the default output device.
"""
import sys
import time

from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

THRESHOLD = 0.01


def sessions():
    out = []
    for s in AudioUtilities.GetAllSessions():
        name = s.Process.name() if s.Process else "system"
        out.append((s.ProcessId, name, s._ctl.QueryInterface(IAudioMeterInformation)))
    return out


def main():
    if len(sys.argv) < 2:
        for pid, name, m in sessions():
            print("%6d %-24s peak %.4f" % (pid, name, m.GetPeakValue()))
        return 0
    target = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    match = [(p, n, m) for p, n, m in sessions() if str(p) == target or n.lower() == target.lower()]
    if not match:
        print("NO-SESSION %s: the process has no audio session (not playing, or not running)" % target)
        return 2
    peak, t_end = 0.0, time.time() + secs
    while time.time() < t_end:
        peak = max(peak, max(m.GetPeakValue() for _, _, m in match))
        time.sleep(0.05)
    verdict = "AUDIBLE" if peak > THRESHOLD else "SILENT"
    print("%s %s peak %.4f over %.1fs (pids %s)" % (verdict, target, peak, secs, ",".join(str(p) for p, _, _ in match)))
    return 0 if verdict == "AUDIBLE" else 1


if __name__ == "__main__":
    sys.exit(main())
