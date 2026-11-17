"""Backtest for this entry (test tooling, not part of the submission).

Runs main.py on each practice case in the kit and scores the pinball loss
on the log scale against the true hours 2..24, fetched from SullyGnome
(the same source the house used; the fetched hour-1 prints match the
cases' `known` rows exactly).  Hour 24 has no point in the fetched month
data, so it is unscored here (22 scored hours per case).  Also runs the
kit starter the same way, checks determinism (two runs, byte-identical
outputs) and reports wall time per case.

Usage: python3 backtest.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KIT = Path.home() / "workspace/makefun/kit/gta6-twitch-ccu-forecast-01-kit"
BOT = Path(__file__).resolve().parent
ANSWERS = json.load(open("/tmp/sully/practice-answers.json"))
# case hour h (2..24) = SullyGnome label hour h-1
P1 = {"p00": 23357, "p01": 116550, "p02": 269517, "p03": 119087}

TAUS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]


def pinball(y, qs):
    ly = math.log(max(1, y))
    tot = 0.0
    for tau, q in zip(TAUS, qs):
        d = ly - math.log(max(1.0, q))
        tot += 2 * max(tau * d, (tau - 1) * d)
    return tot / len(TAUS)


def run_entry(entry_path, case_id):
    """Run one entry program on one practice case; return (forecast, secs)."""
    with tempfile.TemporaryDirectory() as tmp:
        in_dir = Path(tmp) / "in"
        out_dir = Path(tmp) / "out"
        in_dir.mkdir()
        (in_dir / f"{case_id}.in").write_bytes((KIT / "input" / f"{case_id}.in").read_bytes())
        env = dict(os.environ, MAKEFUN_INPUT_DIR=str(in_dir), MAKEFUN_OUTPUT_DIR=str(out_dir))
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, str(entry_path)], env=env,
            capture_output=True, text=True, timeout=30,
        )
        secs = time.time() - t0
        if proc.returncode != 0:
            raise RuntimeError(f"{entry_path} on {case_id} failed: {proc.stderr}")
        return json.loads((out_dir / f"{case_id}.out").read_text()), secs


def score(forecast, case_id):
    """Mean pinball loss over the scored (case, hour, level) items."""
    rows = {r["hour"]: r["q"] for r in forecast["hours"]}
    losses = []
    for ch in range(2, 25):
        y = ANSWERS[case_id].get(str(ch - 1))
        if y is None:
            continue
        losses.append(pinball(y, rows[ch]))
    return sum(losses) / len(losses), len(losses)


def starter_forecast(p1, h):
    return [p1 * math.exp(z * 0.15 * math.sqrt(h - 1)) for z in Z]


def main():
    print(f"{'case':6s} {'ours':>8s} {'starter':>8s} {'n_hours':>7s} {'secs':>6s}")
    ours_all, starter_all = [], []
    for case_id in ["p00", "p01", "p02", "p03"]:
        fc, secs = run_entry(BOT / "main.py", case_id)
        loss, n = score(fc, case_id)
        # starter scored directly (same formula as starter/main.py)
        sl = [pinball(ANSWERS[case_id][str(ch - 1)], starter_forecast(P1[case_id], ch))
              for ch in range(2, 25) if ANSWERS[case_id].get(str(ch - 1)) is not None]
        sloss = sum(sl) / len(sl)
        print(f"{case_id:6s} {loss:8.4f} {sloss:8.4f} {n:7d} {secs:6.2f}")
        ours_all.append(loss * n)
        starter_all.append(sloss * n)
    n_items = sum(len([1 for ch in range(2, 25)
                       if ANSWERS[c].get(str(ch - 1)) is not None])
                  for c in ["p00", "p01", "p02", "p03"])
    print(f"\nmean pinball (per scored hour): ours {sum(ours_all)/n_items:.6f}, "
          f"starter {sum(starter_all)/n_items:.6f}")

    # determinism: run twice on p00, compare bytes
    outs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "in"
            out_dir = Path(tmp) / "out"
            in_dir.mkdir()
            (in_dir / "p00.in").write_bytes((KIT / "input" / "p00.in").read_bytes())
            env = dict(os.environ, MAKEFUN_INPUT_DIR=str(in_dir), MAKEFUN_OUTPUT_DIR=str(out_dir))
            subprocess.run([sys.executable, str(BOT / "main.py")], env=env,
                           capture_output=True, check=True, timeout=30)
            outs.append((out_dir / "p00.out").read_bytes())
    print("determinism:", "IDENTICAL" if outs[0] == outs[1] else "DIFFERENT!!")


if __name__ == "__main__":
    main()
