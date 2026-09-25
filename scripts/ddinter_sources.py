"""DDInter 2.0 source URLs and per-ATC-category CSV file list.

Kept as a plain data module so build script logic is testable without
network access.
"""

from __future__ import annotations

DDINTER_BASE_URL = "https://ddinter2.scbdd.com/static/media/download/"

# DDInter publishes one CSV per ATC top-level category: the 14 of them.
#
# This used to say "categories C/G/J/M/N/S are not available" and loaded only
# A B D H L P R V. It was false. Measured 2026-09-25 with
# `curl -sI <DDINTER_BASE_URL>ddinter_downloads_code_{C,G,J,M,N,S}.csv`: all six
# answer 200 with real CSVs in the same format
# (DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level); C has 60,455 lines and N
# 91,596. Without them, classic Major pairs (tramadol + fluoxetine, digoxin +
# amiodarone, sildenafil + nitroglycerin) only reached us as openFDA "unknown".
ATC_CATEGORIES: tuple[str, ...] = (
    "A", "B", "C", "D", "G", "H", "J", "L", "M", "N", "P", "R", "S", "V",
)

CSV_FILENAMES: tuple[str, ...] = tuple(
    f"ddinter_downloads_code_{c}.csv" for c in ATC_CATEGORIES
)


def csv_url(filename: str) -> str:
    """Return the absolute URL for a DDInter CSV asset."""
    return f"{DDINTER_BASE_URL}{filename}"


def atc_category(filename: str) -> str:
    """Extract the ATC category letter from a DDInter CSV filename.

    Raises ValueError if the filename does not match the expected pattern.
    """
    prefix = "ddinter_downloads_code_"
    suffix = ".csv"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        raise ValueError(f"Not a DDInter CSV filename: {filename!r}")
    code = filename[len(prefix):-len(suffix)]
    if code not in ATC_CATEGORIES:
        raise ValueError(f"Unknown ATC category: {code!r}")
    return code
