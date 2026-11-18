# GTA VI Twitch Forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Dhikas182/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Dhikas182/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Built for [make.fun bounty gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01).

A forecaster for Grand Theft Auto VI's launch-day Twitch viewers: given
the first hour's count, it predicts five quantiles (5%, 25%, 50%, 75%,
95%) of the concurrent-viewer count for each of hours 2 to 24 of the
release day (UTC, 19 November 2026).

## How it works

`main.py` (Python 3.13, standard library only) reads one case file
(`makefun/twitch-ccu-case/v1`) from `$MAKEFUN_INPUT_DIR` (else `/input/`)
and writes one `/output/<id>.out` per case. It is fully deterministic:
no randomness, no clock, no network.

The method is an hour-1-anchored analog model. Past big launches show
that the shape of a launch-day curve — the log ratio of each later
hour's viewers to hour 1's — depends strongly on how big hour 1 already
is: the biggest launches (hour 1 in the hundreds of thousands) stay
almost flat, peaking around 1.0–1.35x hour 1 with a dip to ~0.5x in the
late morning, while small launches explode 10–1000x later in the day
(correlation between log hour-1 viewers and peak log ratio ≈ −0.94
across the kit's comparables). So, per hour, the program fits the log
ratio as a smooth function of log hour-1 viewers with a Gaussian-kernel
local-linear regression (bandwidth 1.2 in log units) over the case's
comparables, and takes the per-hour kernel-weighted residual spread as
the log-scale uncertainty. Quantiles are the fitted centre plus standard
normal quantiles times that spread.

Details that matter:

- The effective log hour-1 size is clamped to the comparables' observed
  range, so an unprecedentedly large hour 1 is treated like the largest
  launch seen instead of extrapolated linearly.
- Comparables that are not launches (the GTA VI category's own
  pre-release history) and any comparable missing an hour of its
  release day are left out. With fewer than three usable comparables
  the forecast falls back to a flat curve with a spread that widens
  over the day.
- Adding hour-1 channel counts as a second feature, using empirical
  residual quantiles instead of normal ones, and restricting training
  to rolling-midnight launches were all tried and measured worse, so
  the entry uses the single-feature local-linear fit.

## Validation (local, leave-one-out on the kit's comparables)

Each of the 37 comparable launches was held out in turn, a synthetic
case built from its hour 1 and the other 36 comparables, and the entry
run on it as a subprocess and scored with the kit's pinball loss on the
log scale (verified against the worked example in `RULES.txt`):

| | mean pinball loss |
|---|---|
| This entry, all 37 launches | **0.388** |
| House baseline, all 37 | 0.930 |
| This entry, big launches (hour 1 ≥ 100k, the GTA VI regime) | **0.207** |
| House baseline, big launches | 0.261 |

It beats the house baseline on 27 of 37 launches and 12 of 16 big ones.
The worst cases are tiny launches (hour 1 under 5,000 viewers) whose
curves are inherently wild — not the regime GTA VI is in.

On the kit's four practice cases the program runs in ~0.12 s per case
(limit 8 s) and two runs produce byte-identical outputs.

## Run it

```
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## License

0BSD, see LICENSE.
