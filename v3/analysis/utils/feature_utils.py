"""
Simplified custom feature-picking algorithm: groups MS1 centroid peaks
across consecutive scans into mass traces, then reduces each trace to a
single feature at its intensity apex.
"""

from __future__ import annotations

from typing import Optional, Any
import numpy as np

def group_into_features(
    scans: list[dict],
    mz_ppm_tolerance: float = 5.0,
    min_scans: int = 1,
    noise_threshold: float = 0.0,
    max_gaps: int = 2
) -> list[dict]:
    """Group MS1 peaks across scans into mass traces, return one feature
    (at the intensity apex) per trace with >= min_scans points.

    Parameters
    ----------
    scans: list of {"rt": float, "mz": np.ndarray, "intensity": np.ndarray},
        one dict per MS1 scan, in RT order.
    mz_ppm_tolerance: max ppm difference to extend an existing trace.
    min_scans: traces shorter than this are discarded as noise.
    noise_threshold: peaks below this intensity are ignored entirely.
    max_gaps: allow trace to survive this many consecutive missed scans
    Returns
    -------
    list of {"mz": float, "rt": float, "intensity": float, "charge": int}
    """
    open_traces: list[dict] = []  # each: {"last_mz": float, "points": [(rt, mz, intensity), ...]}
    closed_traces: list[dict] = []

    for scan in scans:
        rt = scan["rt"]
        mzs = scan["mz"]
        intensities = scan["intensity"]

        extended_trace_indices: set[int] = set()

        # Sort peaks by intensity descending so the strongest peak in a
        # scan gets first claim on extending a trace (reduces cross-talk
        # when two traces are close together).
        order = np.argsort(intensities)[::-1]

        for i in order:
            mz = float(mzs[i])
            intensity = float(intensities[i])
            if intensity < noise_threshold:
                continue

            best_trace_idx: Optional[int] = None
            best_ppm = None
            for idx, trace in enumerate(open_traces):
                if idx in extended_trace_indices:
                    continue
                ppm_error = abs(mz - trace["last_mz"]) / trace["last_mz"] * 1e6
                if ppm_error <= mz_ppm_tolerance and (best_ppm is None or ppm_error < best_ppm):
                    best_trace_idx = idx
                    best_ppm = ppm_error

            if best_trace_idx is not None:
                trace = open_traces[best_trace_idx]
                trace["points"].append((rt, mz, intensity))
                trace["last_mz"] = mz
                trace["missed_scans"] = 0
                extended_trace_indices.add(best_trace_idx)
            else:
                open_traces.append({"last_mz": mz, "points": [(rt, mz, intensity)], "missed_scans": 0})
                extended_trace_indices.add(len(open_traces) - 1)

        # Any trace not extended this scan is done (no gap tolerance).
        still_open = []
        for idx, trace in enumerate(open_traces):
            if idx in extended_trace_indices:
                still_open.append(trace)
            else:
                trace["missed_scans"] += 1
                if trace["missed_scans"] > max_gaps:
                    closed_traces.append(trace)
                else:
                    still_open.append(trace)


        open_traces = still_open

    closed_traces.extend(open_traces)  # whatever's left at the end also closes

    features = []
    for trace in closed_traces:
        if len(trace["points"]) < min_scans:
            continue
        apex_rt, apex_mz, apex_intensity = max(trace["points"], key=lambda p: p[2])
        features.append(
            {
                "mz": apex_mz,
                "rt": apex_rt,
                "intensity": apex_intensity,
                "charge": -1,  # negative mode assumed throughout this pipeline
            }
        )

    return features

def summarize_features(features: list[dict]) -> dict[str, Any]:
    """Reduce a full feature list down to a small summary dict.

    Pure function -- no I/O -- so it's testable independently of whatever
    detected the features.
    """
    if not features:
        return {
            "n_features": 0,
            "mz_range": None,
            "rt_range": None,
            "total_intensity": 0.0,
        }

    mzs = [f["mz"] for f in features]
    rts = [f["rt"] for f in features]
    intensities = [f["intensity"] for f in features]

    return {
        "n_features": len(features),
        "mz_range": (min(mzs), max(mzs)),
        "rt_range": (min(rts), max(rts)),
        "total_intensity": sum(intensities),
    }