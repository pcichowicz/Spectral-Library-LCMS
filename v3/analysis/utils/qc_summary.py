"""
This is a summary, not a re-export -- ExportStage keeps the full
stage-keyed dict too (as QCReport.raw_qc_metrics) since this view is
necessarily lossy (e.g. it doesn't carry per-feature flagged m/z/rt pairs).
"""
from __future__ import annotations

import statistics
from typing import Any

from v3.analysis.utils.schemas import QCMetrics


def build_qc_metrics_summary(qc_metrics: dict[str, Any]) -> QCMetrics:
    return QCMetrics(
        blank_background=_blank_background(qc_metrics.get("blank_qc", {})),
        mass_accuracy=_mass_accuracy(qc_metrics.get("system_suitability", {})),
        identification_rate=_identification_rate(qc_metrics.get("system_suitability", {})),
        spectral_purity=_spectral_purity(qc_metrics.get("spectral_purity", {})),
    )


def _blank_background(bq: dict[str, Any]) -> dict:
    per_sample = {}
    for sample_id, result in bq.get("results", {}).items():
        if result.get("status") != "checked":
            continue
        n_features = result.get("n_features") or 0
        n_flagged = result.get("n_flagged") or 0
        per_sample[sample_id] = {
            "n_features": n_features,
            "n_flagged": n_flagged,
            "flag_rate": (n_flagged / n_features) if n_features else None,
        }
    return {
        "n_blank_features_pooled": bq.get("n_blank_features"),
        "per_sample": per_sample,
    }


def _mass_accuracy(ss: dict[str, Any]) -> dict:
    ppm_errors = [
        match["mass_error_ppm"]
        for result in ss.get("results", {}).values()
        if result.get("status") == "checked"
        for match in result.get("matches", [])
        if match.get("confirmed") and match.get("mass_error_ppm") is not None
    ]
    return {
        "n_measurements": len(ppm_errors),
        "mean_ppm": statistics.mean(ppm_errors) if ppm_errors else None,
        "max_abs_ppm": max((abs(e) for e in ppm_errors), default=None),
        "std_ppm": statistics.pstdev(ppm_errors) if len(ppm_errors) > 1 else None,
    }


def _identification_rate(ss: dict[str, Any]) -> dict:
    return {
        "n_checked": ss.get("n_checked"),
        "n_confirmed": ss.get("n_confirmed"),
        "rate": ss.get("identification_rate"),
    }


def _spectral_purity(sp: dict[str, Any]) -> dict:
    return {
        "n_attempted": sp.get("n_attempted"),
        "n_computed": sp.get("n_computed"),
        "n_below_threshold": sp.get("n_below_threshold"),
        "median_purity": sp.get("median_purity"),
    }
