"""
src/data/availability.py

THE central no-look-ahead mechanism (spec sections 1 and 19).

Every COT observation carries two dates:
  - report_date:       the Tuesday the positioning data describes.
  - availability_date: the date a trader could actually have seen it.

Rule, and where it comes from
------------------------------
CFTC's own "Release Schedule" page states (fetched verbatim 2026-08-27,
https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm):

    "The Commitments of Traders reports are released at 3:30 p.m. Eastern
    time. The Futures Only reports and Futures and Options Combined reports
    are usually released on Friday. The release usually includes data from
    the previous Tuesday."

That page also publishes a *specific* tentative release-date list for 2026,
reproduced in CFTC_2026_RELEASE_DATES below, with holiday delays already
baked in (marked with '*' on the CFTC page). We use that exact list for any
report_date whose corresponding release falls in 2026. For any other date
we do NOT have an exact CFTC-published date for, we fall back to a plainly
documented derivation rule and tag it as such -- see `derive_availability_date`.

Known gap (do not paper over this): CFTC suspended COT publication during
the Oct-Nov 2025 lapse in federal appropriations (govt shutdown) and cleared
the resulting backlog by 2026-01-05 in a compressed catch-up schedule (CFTC
press releases 9138-25 and 9147-25, fetched 2026-08-27). Report dates from
approximately 2025-09-30 through late 2025 were NOT released on their
"normal" Friday -- they were bulk-released later, out of the normal cadence.
The derived fallback rule below does NOT know this and will be WRONG for
that window. We tag rows in that window with a warning rather than silently
using a rule we know is inaccurate there. See LIMITATIONS.md.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# Exact release dates CFTC itself published for 2026 (source: CFTC Release
# Schedule page, fetched 2026-08-27). Each is the Friday (or holiday-shifted
# day, marked '*' on the source page) on which that week's TFF report was/
# will be made public at 3:30pm Eastern.
CFTC_2026_RELEASE_DATES: list[date] = [
    date(2026, 1, 5), date(2026, 1, 9), date(2026, 1, 16), date(2026, 1, 23), date(2026, 1, 30),
    date(2026, 2, 6), date(2026, 2, 13), date(2026, 2, 20), date(2026, 2, 27),
    date(2026, 3, 6), date(2026, 3, 13), date(2026, 3, 20), date(2026, 3, 27),
    date(2026, 4, 3), date(2026, 4, 10), date(2026, 4, 17), date(2026, 4, 24),
    date(2026, 5, 1), date(2026, 5, 8), date(2026, 5, 15), date(2026, 5, 22), date(2026, 5, 29),
    date(2026, 6, 5), date(2026, 6, 12), date(2026, 6, 22), date(2026, 6, 26),
    date(2026, 7, 6), date(2026, 7, 10), date(2026, 7, 17), date(2026, 7, 24), date(2026, 7, 31),
    date(2026, 8, 7), date(2026, 8, 14), date(2026, 8, 21), date(2026, 8, 28),
    date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18), date(2026, 9, 25),
    date(2026, 10, 2), date(2026, 10, 9), date(2026, 10, 16), date(2026, 10, 23), date(2026, 10, 30),
    date(2026, 11, 6), date(2026, 11, 16), date(2026, 11, 20), date(2026, 11, 30),
    date(2026, 12, 4), date(2026, 12, 11), date(2026, 12, 18), date(2026, 12, 28),
]

# report_date -> release_date, derived programmatically (not by hand) as
# "the most recent Tuesday strictly before the release date". This formula
# is uniform whether or not that particular release was holiday-delayed,
# because a delayed release is still after the Tuesday it describes.
_REPORT_TO_RELEASE_2026: dict[date, date] = {}
for _rd in CFTC_2026_RELEASE_DATES:
    _d = _rd - timedelta(days=1)
    while _d.isoweekday() != 2:  # 2 = Tuesday
        _d -= timedelta(days=1)
    _REPORT_TO_RELEASE_2026[_d] = _rd

SHUTDOWN_BACKLOG_REPORT_START = date(2025, 9, 23)   # first report_date affected by the 2025 lapse
SHUTDOWN_BACKLOG_REPORT_END = date(2025, 12, 30)    # backlog cleared by release on 2026-01-05


@dataclass(frozen=True)
class Availability:
    report_date: date
    availability_date: date
    source: str          # "cftc_published_schedule" | "derived_rule"
    warning: Optional[str] = None


def _next_friday_on_or_after(d: date) -> date:
    # date.isoweekday(): Monday=1 ... Sunday=7, so Friday=5.
    days_ahead = (5 - d.isoweekday()) % 7
    return d + timedelta(days=days_ahead)


def _is_us_federal_holiday(d: date) -> bool:
    """
    Minimal, explicit US federal holiday check used ONLY for the derived
    fallback rule (dates outside CFTC_2026_RELEASE_DATES). This is
    intentionally conservative (fixed-date + fixed-weekday holidays only)
    and documented as an approximation -- see METHODOLOGY.md. It is not
    used at all for 2026 report dates, which use the exact published table.
    """
    if (d.month, d.day) in {(1, 1), (6, 19), (7, 4), (11, 11), (12, 25)}:
        return True
    if d.month == 1 and d.weekday() == 0 and 15 <= d.day <= 21:   # MLK day, 3rd Monday
        return True
    if d.month == 2 and d.weekday() == 0 and 15 <= d.day <= 21:   # Presidents Day, 3rd Monday
        return True
    if d.month == 5 and d.weekday() == 0 and d.day >= 25:         # Memorial Day, last Monday
        return True
    if d.month == 9 and d.weekday() == 0 and d.day <= 7:          # Labor Day, 1st Monday
        return True
    if d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28:  # Thanksgiving, 4th Thursday
        return True
    return False


def derive_availability_date(report_date: date) -> Availability:
    """
    Fallback rule for report_dates NOT covered by CFTC_2026_RELEASE_DATES.
    Rule (documented, not hidden): availability_date = the Friday on/after
    (report_date + 3 days), shifted forward one business day for each US
    federal holiday encountered. This matches CFTC's own stated general
    pattern ("usually Friday... previous Tuesday") but is NOT a substitute
    for an actual published schedule, hence source="derived_rule".
    """
    candidate = _next_friday_on_or_after(report_date + timedelta(days=3))
    while _is_us_federal_holiday(candidate):
        candidate += timedelta(days=1)

    warning = None
    if SHUTDOWN_BACKLOG_REPORT_START <= report_date <= SHUTDOWN_BACKLOG_REPORT_END:
        warning = (
            "report_date falls in the Oct-Dec 2025 CFTC publication lapse "
            "(government shutdown). The derived Friday-based rule is known "
            "to be WRONG for this window -- CFTC bulk-released these reports "
            "later on a compressed catch-up schedule. Do not trust this "
            "availability_date for precise no-look-ahead backtests spanning "
            "this period; look up the actual release date from CFTC press "
            "releases 9138-25 / 9147-25 instead."
        )
    return Availability(report_date, candidate, "derived_rule", warning)


def get_availability(report_date: date) -> Availability:
    """
    Single entry point used by the whole pipeline. Prefers the exact
    CFTC-published 2026 schedule; falls back to the documented derived rule
    (with an explicit warning) otherwise. Never fabricates precision it
    does not have.
    """
    if report_date in _REPORT_TO_RELEASE_2026:
        return Availability(report_date, _REPORT_TO_RELEASE_2026[report_date], "cftc_published_schedule")
    return derive_availability_date(report_date)
