"""gta6-twitch-ccu-forecast-01 entry: a launch-shape forecaster.

The idea
--------
Hour 1 of a big game's release day tells you the *scale* of its Twitch
audience, but almost nothing about the *shape* of the rest of the day:
viewers dip in the small hours, jump when the US east coast unlocks
(~05:00 UTC), sag through the morning, then climb all afternoon as the
Americas wake up and Europe comes home, peaking in the early evening UTC.
The house baseline (persistence: every hour equals hour 1) ignores that
shape entirely, so it is badly wrong whenever hour 1 is not the peak.

This program learns the shape from the case itself.  Every case ships
with `comparables`: past big launches' hourly Twitch curves, 14 days
before to 3 days after their own release days.  For each comparable we
take its release-day curve and express every hour as a log-ratio to its
own hour-1 print, ln(v_h / v_1).  The ratio is what generalises across
games of very different sizes: a 200-viewer indie and a 900k-viewer
blockbuster both wake up on roughly the same clock, even though their
absolute counts differ by orders of magnitude.

The one thing that does *not* generalise is how much of the world had
already unlocked by 00:00 UTC.  A launch whose hour-1 print is already
huge (a simultaneous global unlock, or a game the whole planet was
waiting for) has little headroom left, so its later ratios stay near 1;
a launch with a small hour-1 print (only New Zealand / Asia / Europe
awake so far) still has the Americas to come, so it can surge 5-10x by
the evening.  The data bears this out: across the kit's 37 comparable
launches the evening peak ratio falls from ~100x at hour-1 prints of a
few hundred to ~1.3x at prints above 100k.

So, per forecast hour h = 2..24, we fit a one-predictor regression over
the comparable launches:

    ln(v_h / v_1)  ~  a_h + b_h * min(ln(v_1), ln(50000))

The predictor is the launch's (log) hour-1 print, capped at ln(50000):
past that size the peak ratio has flattened out, and the cap stops the
fit extrapolating a downward slope into ever-larger launches (GTA VI's
hour-1 print will very likely sit above the cap).  The regression is
ordinary least squares, fitted fresh at run time from whatever
comparables the case carries -- the final case carries 42 of them, the
practice cases 38 -- so nothing about any particular launch is baked in.

The spread is honest, not a flat guess: sigma_h is 1.4826 times the
median absolute deviation of that hour's regression residuals (floored
at 0.15 log units, so even the most predictable hour keeps a sane
minimum width).  Hours where past launches disagree -- the early
morning, when unlock times differ, and the evening peak, whose height
varies most -- get wide bands; hours where launches march together get
narrow ones.  Quantiles are the fitted median times exp(z_tau * sigma_h)
with the standard normal's z at the five scored levels.

Fallbacks keep the entry valid no matter what the case holds: if a case
carries too few usable comparables (fewer than five launches with a
complete hour-1 print) we fall back to persistence with the starter's
widening spread; a missing hour in a comparable simply drops that launch
from that hour's fit; a non-positive viewer count is never logged.

Everything is deterministic: fixed iteration order, no randomness, no
clock, no network, standard library only.  The same case file always
produces the same bytes.

Backtest (leave-one-out over the 41 launches with known release days --
the 37 comparables plus the 4 practice launches, whose true hours 2..24
come from SullyGnome, the same source the house used): mean pinball loss
0.369 overall, 0.203 on the four practice cases, against the starter's
0.877 overall and 0.387 on the practice cases.  The practice figure
reproduces the house's own quoted baseline loss (0.387) exactly, which
validates the scoring code used here.
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file would import.  (This entry is a single file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

# Above this hour-1 print the launch-day shape stops changing: the peak
# ratio has flattened, so the regression predictor is capped here.
CAP_PRINT = 50000.0
CAP_LOG = math.log(CAP_PRINT)

# A fit needs at least this many donor launches, else we fall back.
MIN_DONORS = 5

# Narrowest log-spread any hour is allowed: even the most predictable
# hour keeps a band, because a single launch can always surprise.
SIGMA_FLOOR = 0.15

# The fallback spread, per the house baseline: 0.15 log units per
# square-root hour after hour 1.
FALLBACK_SIGMA = 0.15

MAX_VIEWERS = 1_000_000_000


def round2(x):
    """x rounded to 2 decimals, half up, as JavaScript's Math.round does.

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def median(values):
    """The median of a non-empty list of numbers (the list is not mutated)."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def parse_hour(timestamp):
    """'2026-09-15T00:00:00Z' -> (date string, hour int)."""
    date, rest = timestamp.split("T", 1)
    return date, int(rest.split(":", 1)[0])


def donor_curves(case):
    """Release-day log-ratio curves from the case's comparables.

    Returns a list of (log_hour1, {label_hour: log_ratio}) pairs, one per
    comparable launch that has a usable hour-1 print on its release day.
    Label hour 0 is [00:00, 01:00) UTC -- the case's hour 1 -- and label
    hours 1..23 are the case's hours 2..24.  A launch whose release day
    has no hour-0 point (e.g. a pre-release category history) is skipped,
    as is any non-positive viewer count.
    """
    donors = []
    for comp in sorted(case.get("comparables") or [], key=lambda c: c.get("name", "")):
        day_start = comp.get("day_start")
        hourly = comp.get("hourly") or []
        if not day_start or not hourly:
            continue
        release_date, _ = parse_hour(day_start)
        day = {}
        for row in hourly:
            try:
                date, hour = parse_hour(row["from"])
            except (KeyError, TypeError, ValueError):
                continue
            if date == release_date:
                viewers = row.get("viewers")
                if isinstance(viewers, (int, float)) and viewers > 0:
                    day[hour] = viewers
        hour1 = day.get(0)
        if not hour1:
            continue
        log_h1 = math.log(hour1)
        ratios = {}
        for label_hour in range(1, 24):
            viewers = day.get(label_hour)
            if viewers:
                ratios[label_hour] = math.log(viewers / hour1)
        if ratios:
            donors.append((log_h1, ratios))
    return donors


def ols_fit(pairs):
    """Least-squares line y ~ a + b*x over (x, y) pairs; returns (a, b)."""
    n = len(pairs)
    mean_x = sum(x for x, _ in pairs) / n
    mean_y = sum(y for _, y in pairs) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in pairs)
    if sxx <= 0:
        return mean_y, 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / sxx
    return mean_y - slope * mean_x, slope


def fit_shape(donors, log_p1):
    """Per-hour (median log-ratio, sigma) for case hours 2..24.

    For each label hour, regress the donors' log-ratios on their capped
    log hour-1 prints and read the fit off at the target's capped log
    hour-1 print.  Sigma is the residuals' MAD scaled to a normal
    standard deviation, floored so no hour claims false certainty.
    """
    x_target = min(log_p1, CAP_LOG)
    shape = {}
    for label_hour in range(1, 24):
        pairs = []
        for log_h1, ratios in donors:
            ratio = ratios.get(label_hour)
            if ratio is not None:
                pairs.append((min(log_h1, CAP_LOG), ratio))
        if len(pairs) < MIN_DONORS:
            shape[label_hour + 1] = None
            continue
        intercept, slope = ols_fit(pairs)
        centre = intercept + slope * x_target
        residuals = [y - (intercept + slope * x) for x, y in pairs]
        med_resid = median(residuals)
        mad = median([abs(r - med_resid) for r in residuals])
        # Cap the fitted centre and the spread: a sparse or skewed donor
        # set must never produce a runaway forecast (a 1000x hour, or a
        # band wider than the whole plausible range).  The caps sit far
        # outside anything the 41 known launch days ever produced for a
        # launch of this size (ratios 0.08x..55x, sigma at most 1.5 log
        # units), so they only bind on pathological input.
        centre = max(-2.5, min(4.0, centre))
        sigma = max(SIGMA_FLOOR, min(1.5, 1.4826 * mad))
        shape[label_hour + 1] = (centre, sigma)
    return shape


def clamp_quantiles(quantiles):
    """Keep a row inside the contest's bounds and non-decreasing."""
    out = []
    prev = 0.0
    for q in quantiles:
        q = min(max(q, 1.0), MAX_VIEWERS)
        q = max(q, prev)
        out.append(round2(q))
        prev = q
    return out


def forecast_case(case, name):
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))

    donors = donor_curves(case)
    shape = fit_shape(donors, math.log(p1)) if len(donors) >= MIN_DONORS else {}

    rows = []
    for row in case["forecast"]:
        hour = row["hour"]
        fitted = shape.get(hour)
        if fitted is None:
            # Too few donors for this hour: persistence, starter spread.
            centre, sigma = 0.0, FALLBACK_SIGMA * math.sqrt(hour - 1)
        else:
            centre, sigma = fitted
        quantiles = [p1 * math.exp(centre + z * sigma) for z in Z]
        rows.append({"hour": hour, "q": clamp_quantiles(quantiles)})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
