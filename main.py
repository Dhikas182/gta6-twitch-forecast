"""GTA VI launch-day Twitch viewer forecaster.

Reads one case (makefun/twitch-ccu-case/v1) from $MAKEFUN_INPUT_DIR (else /input/)
and writes one forecast file per case to $MAKEFUN_OUTPUT_DIR (else /output/):
for each of hours 2..24 of the release day, five quantiles (5/25/50/75/95%)
of that hour's Twitch concurrent-viewer count.

Method
------
The count in hour 1 anchors everything.  Past big launches show that the
shape of the launch-day curve -- the log ratio of each later hour's viewers
to hour 1's -- depends strongly on how big hour 1 already is: the biggest
launches (hour 1 in the hundreds of thousands) stay almost flat, peaking
around 1.0-1.35x hour 1 with a dip to ~0.5x in the late morning, while
small launches explode 10-1000x later in the day (correlation between
log hour-1 viewers and peak log ratio is about -0.94 across the
comparables).  So, per hour, I fit the log ratio as a smooth function of
log hour-1 viewers with a Gaussian-kernel local-linear regression over
the case's comparables (each comparable contributes its own release-day
curve), and take the per-hour kernel-weighted residual spread as the
log-scale uncertainty.  Quantiles are the fitted centre plus standard
normal quantiles times that spread.  The effective log hour-1 size is
clamped to the comparables' observed range, so an unprecedentedly large
hour 1 (GTA VI may exceed every comparable) is treated like the largest
launch seen rather than extrapolated linearly.  Comparables that are not
launches (the GTA VI category's own pre-release history) and any
comparable missing an hour of its release day are left out.  With fewer
than three usable comparables the forecast falls back to a flat curve
with a spread that widens over the day.

Everything is deterministic: no randomness, no clock, no network.
Standard library only.
"""

import json
import math
import os
import sys

# Standard normal quantiles at the case's levels (0.05, 0.25, 0.5, 0.75, 0.95).
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)

# Kernel bandwidth (in log-viewer units) for the local-linear fit.
BANDWIDTH = 1.2
# Smallest log-scale spread allowed, so no hour is ever over-confident.
SPREAD_FLOOR = 0.15
# Fallback spread growth (used only when comparables are too few).
FALLBACK_SPREAD = 0.15


def _parse_hour(ts):
    """Hour (1..24) of an ISO timestamp within its release day, or None."""
    # Timestamps are "YYYY-MM-DDTHH:MM:SSZ"; the hour field is enough
    # once the date has been checked by the caller.
    try:
        return int(ts[11:13]) + 1
    except (ValueError, IndexError, TypeError):
        return None


def _release_day_curve(comparable):
    """Return (hour1_viewers, {hour: viewers for hours 1..24}) or None.

    A comparable counts only if it is a real launch with a complete
    release day: hour 1 and every hour 2..24 present with > 0 viewers.
    """
    unlock = (comparable.get("unlock") or "").lower()
    if "not a launch" in unlock:
        return None
    day_start = comparable.get("day_start") or ""
    day = day_start[:10]
    if not day:
        return None
    by_hour = {}
    for point in comparable.get("hourly") or []:
        stamp = point.get("from") or ""
        if stamp[:10] != day:
            continue
        hour = _parse_hour(stamp)
        if hour is None:
            continue
        viewers = point.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            by_hour[hour] = float(viewers)
    if by_hour.get(1) is None:
        return None
    for hour in range(2, 25):
        if by_hour.get(hour) is None:
            return None
    return by_hour[1], by_hour


def _local_linear_forecast(p, curves):
    """Quantile rows for hours 2..24 from comparable log-ratio curves.

    curves: list of (log_hour1, [log ratio for hours 2..24]).
    """
    # Clamp the target's size to the observed range: never extrapolate
    # the fitted line past the biggest (or smallest) launch seen.
    sizes = [c[0] for c in curves]
    lo, hi = min(sizes), max(sizes)
    target = min(max(math.log(p), lo), hi)

    rows = []
    for index in range(23):  # hours 2..24
        xs = [c[0] for c in curves]
        ys = [c[1][index] for c in curves]
        weights = [math.exp(-0.5 * ((x - target) / BANDWIDTH) ** 2)
                   for x in xs]
        total = sum(weights)
        mean_x = sum(w * x for w, x in zip(weights, xs)) / total
        mean_y = sum(w * y for w, y in zip(weights, ys)) / total
        sxx = sum(w * (x - mean_x) ** 2 for w, x in zip(weights, xs))
        if sxx > 1e-9:
            slope = sum(w * (x - mean_x) * (y - mean_y)
                        for w, x, y in zip(weights, xs, ys)) / sxx
        else:
            slope = 0.0
        centre = mean_y + slope * (target - mean_x)
        var = sum(w * (y - (mean_y + slope * (x - mean_x))) ** 2
                  for w, x, y in zip(weights, xs, ys)) / total
        spread = max(math.sqrt(var), SPREAD_FLOOR)
        quantiles = []
        for z in Z:
            q = p * math.exp(centre + z * spread)
            q = min(max(q, 1.0), 1e9)
            quantiles.append(round(q, 2))
        # Keep the row non-decreasing after rounding.
        for i in range(1, 5):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        rows.append({"hour": index + 2, "q": quantiles})
    return rows


def _fallback_forecast(p):
    """Flat curve with a spread that widens over the day.

    Only used when the case carries too few usable comparables.
    """
    rows = []
    for hour in range(2, 25):
        spread = FALLBACK_SPREAD * math.sqrt(hour - 1)
        quantiles = []
        for z in Z:
            q = p * math.exp(z * spread)
            q = min(max(q, 1.0), 1e9)
            quantiles.append(round(q, 2))
        for i in range(1, 5):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        rows.append({"hour": hour, "q": quantiles})
    return rows


def forecast_case(case):
    """Build the 23-row forecast for one case dict."""
    known = case.get("known") or []
    p = None
    for row in known:
        if row.get("hour") != 1:
            continue
        viewers = row.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            p = float(viewers)
            break
    if p is None:
        history = case.get("history") or []
        for point in reversed(history):
            viewers = point.get("viewers")
            if isinstance(viewers, (int, float)) and viewers > 0:
                p = float(viewers)
                break
    if p is None:
        p = 1.0

    curves = []
    for comparable in case.get("comparables") or []:
        got = _release_day_curve(comparable)
        if got is None:
            continue
        hour1, by_hour = got
        curves.append((math.log(hour1),
                       [math.log(by_hour[h] / hour1) for h in range(2, 25)]))

    if len(curves) >= 3:
        return _local_linear_forecast(p, curves)
    return _fallback_forecast(p)


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input/"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output/"
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(name for name in os.listdir(input_dir)
                   if name.endswith(".in"))
    for name in names:
        with open(os.path.join(input_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        case_id = case.get("id") or name[:-3]
        rows = forecast_case(case)
        text = json.dumps({"hours": rows}, separators=(",", ":"))
        with open(os.path.join(output_dir, case_id + ".out"),
                  "w", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
