"""
Before/after comparison of diary averages around each course's start date.

Shared by the bot (which renders it as caption text under the chart) and the
API (which returns it as structured data for the app to render). Kept free of
matplotlib/aiogram imports so the API can use it without pulling either in.

Phrased by callers as "changed since", never "improved because of" — this is
a correlation from the user's own logs, not a clinical claim.
"""
from typing import NamedTuple

MIN_SIDE_ENTRIES = 3      # diary entries needed on each side of a course start to say anything
MIN_CHANGE = 0.3          # smaller average shifts are noise, not worth reporting

# (metric key, label used in the bot's caption, index into a diary row)
METRICS = (("sleep", "сон", 1), ("energy", "энергия", 2), ("stress", "стресс", 3))


class MetricChange(NamedTuple):
    metric: str   # "sleep" | "energy" | "stress"
    label: str
    before: float
    after: float


class CourseCorrelation(NamedTuple):
    product_key: str
    changes: list[MetricChange]


def course_correlations(entries: list, trackings: list) -> list[CourseCorrelation]:
    """entries: diary rows in chronological order, (entry_date, sleep, energy,
    stress, ...). trackings: rows of (id, product_key, start_date, status,
    ended_at). Only courses with enough diary data on both sides of their
    start date and at least one metric that moved are returned."""
    result = []
    for _tid, product_key, start_date_str, _status, _ended_at in trackings:
        start_date = start_date_str[:10]
        before = [e for e in entries if e[0] < start_date]
        after = [e for e in entries if e[0] >= start_date]
        if len(before) < MIN_SIDE_ENTRIES or len(after) < MIN_SIDE_ENTRIES:
            continue

        changes = []
        for metric, label, idx in METRICS:
            avg_before = sum(e[idx] for e in before) / len(before)
            avg_after = sum(e[idx] for e in after) / len(after)
            if abs(avg_after - avg_before) < MIN_CHANGE:
                continue
            changes.append(MetricChange(metric, label, avg_before, avg_after))

        if changes:
            result.append(CourseCorrelation(product_key, changes))
    return result
