"""
Stage 5: Adduct Annotation.

This does not re-run system_suitability's confirmation logic -- it only
looks for *additional* corroborating adducts once Stage 2 has already
confirmed the primary one.
"""
from __future__ import annotations

from v3.analysis.utils.adducts import compute_adduct_mz, compute_neutral_mass
from v3.analysis.context import LCMSContext
from v3.analysis.utils.protocols import PrecursorReader
from v3.analysis.pipeline import FatalStageError
from v3.analysis.stages.system_suitability import find_best_match


class AdductAnnotationStage:
    name = "adduct_annotation"

    def __init__(
        self,
        reader: PrecursorReader,
        candidate_adducts: list[str],
        primary_adduct: str = "[M-H]-",
        ppm_tolerance: float = 5.0,
    ):
        self.reader = reader
        self.candidate_adducts = candidate_adducts
        self.primary_adduct = primary_adduct
        self.ppm_tolerance = ppm_tolerance

    def validate_input(self, context: LCMSContext) -> bool:
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("adduct_annotation: system_suitability must run first")
        if context.mzml_dir is None:
            raise FatalStageError("adduct_annotation: mzml_directory not set")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        ss_results = context.qc_metrics["system_suitability"]["results"]
        results: dict[str, dict] = {}
        warnings: list[str] = []
        n_compounds_checked = 0
        n_with_extra_adducts = 0

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue

            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                continue

            mzml_path = context.mzml_dir / f"{sample_id}.mzML"
            if not mzml_path.exists():
                warnings.append(f"{sample_id}: mzML missing, adduct annotation skipped")
                continue

            observed_mzs = self.reader.get_precursor_mzs(mzml_path)
            compounds = []

            for match in confirmed_matches:
                n_compounds_checked += 1
                neutral_mass = compute_neutral_mass(match["matched_mz"], self.primary_adduct)

                adducts_detected = [
                    {
                        "adduct": self.primary_adduct,
                        "mz": match["matched_mz"],
                        "mass_error_ppm": match["mass_error_ppm"],
                    }
                ]

                for adduct in self.candidate_adducts:
                    if adduct == self.primary_adduct:
                        continue
                    expected_mz = compute_adduct_mz(neutral_mass, adduct)
                    found = find_best_match(expected_mz, observed_mzs, self.ppm_tolerance)
                    if found is not None:
                        matched_mz, ppm_error = found
                        adducts_detected.append(
                            {"adduct": adduct, "mz": matched_mz, "mass_error_ppm": ppm_error}
                        )

                if len(adducts_detected) > 1:
                    n_with_extra_adducts += 1

                compounds.append(
                    {
                        "compound": match["compound"],
                        "neutral_mass_estimate": neutral_mass,
                        "adducts_detected": adducts_detected,
                    }
                )

            results[sample_id] = {"status": "checked", "compounds": compounds}

        context.qc_metrics["adduct_annotation"] = {
            "results": results,
            "n_compounds_checked": n_compounds_checked,
            "n_with_extra_adducts": n_with_extra_adducts,
        }
        context.log_step(
            self.name,
            parameters={"candidate_adducts": self.candidate_adducts, "ppm_tolerance": self.ppm_tolerance},
            metrics={"n_compounds_checked": n_compounds_checked, "n_with_extra_adducts": n_with_extra_adducts},
            warnings=warnings,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return "adduct_annotation" in context.qc_metrics