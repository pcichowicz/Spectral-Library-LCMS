"""
Spectral similarity scoring for Stage 9 (library matching).

Pure functions only -- no I/O -- so these are exhaustively unit testable
independent of mzML/library parsing. `peaks` throughout is a list of
(mz, intensity) tuples.

Scoring follows the standard "greedy matched-peak dot product" cosine
used across GNPS/MassBank-style spectral matching:
  1. Pair query peaks to reference peaks within `mz_tolerance_da`,
     greedily by descending intensity product, each peak used at most
     once (highest-signal peaks get first claim, same principle as
     feature_utils.group_into_features's trace-extension ordering).
  2. Score = sum(matched intensity products) / (||query|| * ||reference||),
     where the norms are over *all* peaks in each spectrum, not just the
     matched subset -- this is what penalizes spectra with lots of
     unmatched signal (contamination, wrong compound) rather than just
     rewarding however many peaks happened to line up.
"""
from __future__ import annotations

import math
from typing import Optional

Peak = tuple[float, float]  # (mz, intensity)


def match_peaks(
    query_peaks: list[Peak],
    reference_peaks: list[Peak],
    mz_tolerance_da: float,
) -> list[tuple[int, int]]:
    """Greedily pair query/reference peak indices within tolerance,
    highest intensity-product first, each index used at most once.

    Returns list of (query_index, reference_index) pairs.
    """
    candidates: list[tuple[float, int, int]] = []
    for qi, (qmz, qint) in enumerate(query_peaks):
        for ri, (rmz, rint) in enumerate(reference_peaks):
            if abs(qmz - rmz) <= mz_tolerance_da:
                candidates.append((qint * rint, qi, ri))

    candidates.sort(key=lambda c: c[0], reverse=True)

    used_q: set[int] = set()
    used_r: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, qi, ri in candidates:
        if qi in used_q or ri in used_r:
            continue
        used_q.add(qi)
        used_r.add(ri)
        pairs.append((qi, ri))
    return pairs


def cosine_similarity(
    query_peaks: list[Peak],
    reference_peaks: list[Peak],
    mz_tolerance_da: float = 0.02,
) -> float:
    """Matched-peak cosine similarity, in [0, 1]. Returns 0.0 for empty
    input or zero-overlap spectra (never None -- absence of a match is a
    score of 0, not a missing measurement; use match_peaks separately if
    you need to distinguish "no peaks at all" from "peaks but no overlap")."""
    if not query_peaks or not reference_peaks:
        return 0.0

    pairs = match_peaks(query_peaks, reference_peaks, mz_tolerance_da)
    if not pairs:
        return 0.0

    numerator = sum(query_peaks[qi][1] * reference_peaks[ri][1] for qi, ri in pairs)
    q_norm = math.sqrt(sum(intensity ** 2 for _, intensity in query_peaks))
    r_norm = math.sqrt(sum(intensity ** 2 for _, intensity in reference_peaks))
    if q_norm == 0.0 or r_norm == 0.0:
        return 0.0

    score = numerator / (q_norm * r_norm)
    # Clamp for float noise -- shouldn't exceed 1.0 mathematically, but
    # guard against it so a downstream >= threshold check never trips
    # on a 1.0000000000000002 rounding artifact.
    return min(score, 1.0)


def normalize_compound_name(name: str) -> str:
    """Loose normalization for known-identity comparison: case, whitespace,
    and common formatting differences between sample-sheet names and
    library compound names (e.g. 'L-Tryptophan' vs 'Tryptophan')."""
    cleaned = name.strip().lower()
    for prefix in ("l-", "d-", "dl-"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.replace("_", " ").replace("-", " ").strip()


def names_match(known_identity: str, candidate_name: str) -> bool:
    """Whether a library candidate's compound name should count as the
    same identity as the sample sheet's known identity. Exact match after
    normalization, or one containing the other (covers 'Glycine' vs
    'Glycine (standard)' style suffixes some exporters add)."""
    a = normalize_compound_name(known_identity)
    b = normalize_compound_name(candidate_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a
