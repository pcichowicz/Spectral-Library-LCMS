"""
Stage 7: Library Entry Assembly.

Pulls together everything computed in Stages 2-6 into one LibraryEntry
record per confirmed compound (schemas.py's LibraryEntry TypedDict):

- system_suitability  -> compound identity, matched_mz, mass_error_ppm
- feature_detection    -> precursor_mz (refined), rt_sec, charge, intensity
- adduct_annotation    -> primary adduct (falls back to "[M-H]-" if that
                          stage wasn't run)
- blank_qc             -> blank_flagged
- spectral_purity      -> spectral_purity score

A confirmed compound with no matching feature (system_suitability found a
precursor, but feature_detection's peak picker didn't independently detect
a feature there) is logged as a warning and skipped -- that's a real
disagreement between two stages worth knowing about, not something to
paper over with placeholder RT/intensity values.
"""
from __future__ import annotations

from typing import Optional

from v3.analysis.context import LCMSContext
from v3.analysis.utils.json_reader import JSONFeatureReader
from v3.analysis.utils.constants import FEATURE_FILE_SUFFIX
from v3.analysis.pipeline import FatalStageError


def find_feature_for_mz(
    features: list[dict], target_mz: float, ppm_tolerance: float
) -> Optional[dict]:
    """Find the detected feature closest to target_mz within tolerance.
    Pure function -- no I/O, easy to unit test."""
    best: Optional[dict] = None
    best_ppm = None
    for feature in features:
        ppm_error = abs(feature["mz"] - target_mz) / target_mz * 1e6
        if ppm_error <= ppm_tolerance and (best_ppm is None or ppm_error < best_ppm):
            best = feature
            best_ppm = ppm_error
    return best


class LibraryAssemblyStage:
    name = "library_assembly"

    def __init__(self, reader: JSONFeatureReader, mz_tolerance_ppm: float = 5.0):
        self.reader = reader
        self.mz_tolerance_ppm = mz_tolerance_ppm

    def validate_input(self, context: LCMSContext) -> bool:
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("library_assembly: system_suitability must run first")
        if context.featurejson_dir is None:
            raise FatalStageError("library_assembly: featurejson_directory not set")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        ss_results = context.qc_metrics["system_suitability"]["results"]
        adduct_results = context.qc_metrics.get("adduct_annotation", {}).get("results", {})
        blank_results = context.qc_metrics.get("blank_qc", {}).get("results", {})
        purity_results = context.qc_metrics.get("spectral_purity", {}).get("results", {})
        library_match_results = context.qc_metrics.get("library_matching", {}).get("results", {})

        entries: list[dict] = []
        warnings: list[str] = []
        entry_counter = 1
        input_files: list[str] = []

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue
            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                continue

            featurejson_path = context.featurejson_dir / f"{sample_id}{FEATURE_FILE_SUFFIX}"
            if not featurejson_path.exists():
                warnings.append(f"{sample_id}: featureXML missing, no entries assembled")
                continue
            features = self.reader.read_features(featurejson_path)
            input_files.append(str(featurejson_path))

            blank_result = blank_results.get(sample_id, {})
            flagged_mzs = {
                round(f["feature_mz"], 6) for f in blank_result.get("flagged", [])
            } if blank_result.get("status") == "checked" else set()

            purity_by_compound = {
                p["compound"]: p for p in purity_results.get(sample_id, {}).get("purities", [])
            }

            adducts_by_compound = {
                c["compound"]: c["adducts_detected"]
                for c in adduct_results.get(sample_id, {}).get("compounds", [])
            }

            library_match_by_compound = {
                m["compound"]: m
                for m in library_match_results.get(sample_id, {}).get("matches", [])
            }

            for match in confirmed_matches:
                compound = match["compound"]
                feature = find_feature_for_mz(features, match["matched_mz"], self.mz_tolerance_ppm)
                if feature is None:
                    warnings.append(
                        f"{sample_id}: confirmed precursor for {compound!r} has no "
                        f"matching detected feature -- skipped from library"
                    )
                    continue

                adducts_detected = adducts_by_compound.get(
                    compound, [{"adduct": "[M-H]-", "mz": match["matched_mz"], "mass_error_ppm": match["mass_error_ppm"]}]
                )
                primary_adduct = adducts_detected[0]["adduct"]

                purity_info = purity_by_compound.get(compound)
                library_match = library_match_by_compound.get(compound)

                entries.append(
                    {
                        "entry_id": f"LIB_{entry_counter:06d}",
                        "compound_name": compound,
                        "precursor_mz": feature["mz"],
                        "rt_sec": feature["rt"],
                        "adduct": primary_adduct,
                        "charge": feature.get("charge", -1),
                        "mass_error_ppm": match["mass_error_ppm"],
                        "ms2_spectrum": library_match["ms2_spectrum"] if library_match else [],
                        "spectral_purity": purity_info["purity"] if purity_info else None,
                        "source_sample_id": sample_id,
                        "blank_flagged": round(feature["mz"], 6) in flagged_mzs,
                        "library_match_id": library_match["library_match_id"] if library_match else None,
                        "match_score": library_match["match_score"] if library_match else None,
                        "known_identity": compound,
                        "is_correct_match": library_match["is_correct_match"] if library_match else None,
                    }
                )
                entry_counter += 1

        if not entries:
            raise FatalStageError(
                "library_assembly: zero library entries produced -- nothing "
                "confirmed anywhere, or no confirmed compound had a matching feature"
            )
        print(entries)
        context.library_entries = entries
        context.qc_metrics["library_assembly"] = {"n_entries": len(entries)}
        context.log_step(
            self.name,
            parameters={"mz_tolerance_ppm": self.mz_tolerance_ppm},
            metrics={"n_entries": len(entries)},
            warnings=warnings,
            input_files=input_files
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return len(context.library_entries) > 0