# GTA VI Twitch CCU forecast — launch-shape forecaster

Forecasts Grand Theft Auto VI's Twitch viewers hour by hour on release
day, from the hour-1 print plus the launch shapes of past big games.

## Model

- **Anchor:** the case's hour-1 print `p1` sets the scale.
- **Shape:** for each comparable launch in the case, take its release-day
  curve as log-ratios to its own hour 1, `ln(v_h / v_1)`.
- **Size effect:** per forecast hour, regress the log-ratio on the
  launch's (log) hour-1 print, capped at `ln(50000)` — small hour-1
  launches surge much more later in the day (the Americas still to
  unlock) than big ones, and the effect flattens past ~50k. The
  regression is fitted fresh at run time from the case's own
  comparables (38 in practice, 42 in the final).
- **Spread:** per-hour sigma = 1.4826 × MAD of that hour's regression
  residuals (floor 0.15, cap 1.5 log units); quantiles are the fitted
  median × `exp(z_tau × sigma)` at the five scored levels.
- **Fallbacks:** too few donors → persistence with the starter's
  widening spread; fitted centres are clamped to ratios 0.08×–55×.

Stdlib only, no network, no randomness, deterministic.

**Owner:** Bangzo1708 · **Referral code:** dkj7ja9h

## Run

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Backtest (practice cases, true hours 2–24 from SullyGnome)

Mean pinball loss on the log scale, per scored hour:

| case | this entry | starter (persistence) |
|------|-----------|----------------------|
| p00 Marvel's Wolverine | 0.2552 | 0.7436 |
| p01 Red Dead Redemption 2 | 0.2449 | 0.2868 |
| p02 God of War Ragnarök | 0.1375 | 0.2146 |
| p03 Marvel's Spider-Man 2 | 0.2005 | 0.3033 |
| **mean** | **0.2095** | **0.3871** |

The starter figure reproduces the house's quoted practice loss (0.387)
exactly, which validates the scoring. Leave-one-out over all 41 known
launch days: 0.369 vs the starter's 0.877.

Determinism: two runs on p00 produce byte-identical output.
Runtime: ~0.07–0.11 s per case (limit 8 s).

`backtest.py` reproduces the table above (it needs the kit at
`~/workspace/makefun/kit/gta6-twitch-ccu-forecast-01-kit/` and the
fetched answers at `/tmp/sully/practice-answers.json`).
