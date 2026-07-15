"""
Stage 6: Spectral Purity Check.

For every compound confirmed in Stage 2 (system suitability), checks how
"clean" its precursor isolation was -- i.e. whether something else
co-eluted and contaminated the MS/MS spectrum.

Depends on Stage 2 (system_suitability) having already run -- this stage
only checks purity for m/z values that were already confirmed present,
not raw expected values.
"""
from __future__ import annotations

import statistics
from typing import Optional

from v3.analysis.context import LCMSContext
from v3.analysis.pipeline import FatalStageError
from v3.analysis.utils.mzml_reader import PymzmlSpectralPurityReader


def classify_purity(purity: Optional[float], min_purity: float) -> str:
    """Pure function -- no I/O, easy to unit test exhaustively."""
    if purity is None:
        return "unknown"
    return "pass" if purity >= min_purity else "below_threshold"


class SpectralPurityStage:
    name = "spectral_purity"

    def __init__(
        self,
        reader: PymzmlSpectralPurityReader,
        isolation_window_da: float = 1.0,
        min_purity: float = 0.7,
    ):
        self.reader = reader
        self.isolation_window_da = isolation_window_da
        self.min_purity = min_purity

    def validate_input(self, context: LCMSContext) -> bool:
        if context.mzml_dir is None:
            raise FatalStageError("spectral_purity: mzml_directory not set")
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("spectral_purity: system_suitability must run first")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        ss_results = context.qc_metrics["system_suitability"]["results"]
        results: dict[str, dict] = {}
        warnings: list[str] = []
        n_attempted = 0
        n_computed = 0
        n_below_threshold = 0

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue

            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                results[sample_id] = {"status": "skipped_no_confirmed_matches"}
                continue

            mzml_path = context.mzml_dir / f"{sample_id}.mzML"
            sample_purities = []

            for match in confirmed_matches:
                n_attempted += 1
                purity = self.reader.compute_precursor_purity(
                    mzml_path, match["matched_mz"], self.isolation_window_da
                )
                status = classify_purity(purity, self.min_purity)

                if purity is not None:
                    n_computed += 1
                    if status == "below_threshold":
                        n_below_threshold += 1
                        warnings.append(
                            f"{sample_id}: purity {purity:.2f} for "
                            f"{match['compound']!r} below threshold {self.min_purity}"
                        )
                else:
                    warnings.append(
                        f"{sample_id}: could not compute purity for {match['compound']!r}"
                    )

                sample_purities.append(
                    {
                        "compound": match["compound"],
                        "mz": match["matched_mz"],
                        "purity": purity,
                        "status": status,
                    }
                )

            results[sample_id] = {"status": "checked", "purities": sample_purities}

        if n_attempted > 0 and n_computed == 0:
            raise FatalStageError(
                "spectral_purity: could not compute purity for any confirmed match "
                "across the whole run -- likely no MS2 spectra present, not a "
                "single-compound problem"
            )

        all_purities = [
            p["purity"]
            for r in results.values()
            if r.get("status") == "checked"
            for p in r["purities"]
            if p["purity"] is not None
        ]
        median_purity = statistics.median(all_purities) if all_purities else None

        context.qc_metrics["spectral_purity"] = {
            "results": results,
            "n_attempted": n_attempted,
            "n_computed": n_computed,
            "n_below_threshold": n_below_threshold,
            "median_purity": median_purity,
        }
        context.log_step(
            self.name,
            parameters={
                "isolation_window_da": self.isolation_window_da,
                "min_purity": self.min_purity,
            },
            metrics={
                "n_attempted": n_attempted,
                "n_computed": n_computed,
                "n_below_threshold": n_below_threshold,
            },
            warnings=warnings,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return "spectral_purity" in context.qc_metrics