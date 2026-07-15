"""
Stage 2: System Suitability (standards_only profile).

For each non-blank sample, confirm that at least one detected MS2
precursor matches the sample's expected m/z within the configured ppm
tolerance. This is the "standards_only" equivalent of a generic biological
pipeline's system-suitability check, it confirms
the instrument actually saw what was injected, before any feature
detection or library matching is attempted.

Samples with no expected_mz on record are skipped with a warning
rather than failing -- there's nothing to check them against until their
component lists are filled in.
"""
from __future__ import annotations

from typing import Optional

from v3.analysis.context import LCMSContext
from v3.analysis.utils.metadata_utils import parse_list_field
from v3.analysis.utils.protocols import PrecursorReader
from v3.analysis.pipeline import FatalStageError
from v3.analysis.utils.cache_utils import load_filehash_cache, save_filehash_cache, hash_file, hash_files, compute_cache_key

# Bump this whenever find_best_match / match_within_ppm logic changes --
# file hashes alone won't catch an algorithm change.
CACHE_SCHEMA_VERSION = "v1"

class SystemSuitabilityStage:
    name = "system_suitability"

    def __init__(self, reader: PrecursorReader, ppm_tolerance: float = 5.0):
        self.reader = reader
        self.ppm_tolerance = ppm_tolerance

    def cache_key(self, context: LCMSContext) -> str:
        hash_cache = load_filehash_cache(context.results_dir)
        mzml_paths = [
            context.mzml_dir / f"{sid}.mzML"
            for sid in context.sample_metadata["sample_id"]
            if (context.mzml_dir / f"{sid}.mzML").exists()
        ]
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "ppm_tolerance": self.ppm_tolerance,
            "sample_metadata_hash": hash_file(context.sample_metadata_path, hash_cache),
            "mzml_hashes": hash_files(mzml_paths, hash_cache),
        }
        save_filehash_cache(context.results_dir, hash_cache)
        return compute_cache_key(payload)

    def validate_input(self, context: LCMSContext) -> bool:
        if context.mzml_dir is None:
            raise FatalStageError("system_suitability: mzml_directory not set (run ingestion first)")
        if context.sample_metadata is None:
            raise FatalStageError("system_suitability: sample_metadata not loaded on context")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        results: dict[str, dict] = {}
        warnings: list[str] = []
        confirmed = 0
        checked = 0
        input_files: list[str] = [str(context.sample_metadata_path)]

        for _, row in context.sample_metadata.iterrows():
            sample_id = row["sample_id"]
            role = row["sample_role"]

            if role == "solvent_blank":
                continue  # nothing to expected-mass-match in a blank

            expected_compounds = parse_list_field(row["expected_compounds"])
            expected_mzs = parse_list_field(row["expected_mz"])

            if not expected_mzs:
                warnings.append(f"{sample_id}: no expected_mz on record, skipped")
                results[sample_id] = {"status": "skipped_no_expected_mz"}
                continue

            mzml_path = context.mzml_dir / f"{sample_id}.mzML"
            if not mzml_path.exists():
                warnings.append(f"{sample_id}: mzML file missing, skipped")
                results[sample_id] = {"status": "skipped_missing_mzml"}
                continue

            observed_mzs = self.reader.get_precursor_mzs(mzml_path)
            input_files.append(str(mzml_path))
            sample_matches = []
            for compound, expected_mz in zip(expected_compounds or [None] * len(expected_mzs), expected_mzs):
                checked += 1
                match = find_best_match(expected_mz, observed_mzs, self.ppm_tolerance)
                if match is not None:
                    confirmed += 1
                    sample_matches.append(
                        {
                            "compound": compound,
                            "expected_mz": expected_mz,
                            "matched_mz": match[0],
                            "mass_error_ppm": match[1],
                            "confirmed": True,
                        }
                    )
                else:
                    warnings.append(
                        f"{sample_id}: expected compound {compound!r} "
                        f"(m/z {expected_mz}) not confirmed within {self.ppm_tolerance} ppm"
                    )
                    sample_matches.append(
                        {
                            "compound": compound,
                            "expected_mz": expected_mz,
                            "matched_mz": None,
                            "mass_error_ppm": None,
                            "confirmed": False,
                        }
                    )

            results[sample_id] = {"status": "checked", "matches": sample_matches}

        identification_rate = (confirmed / checked) if checked else None
        context.qc_metrics["system_suitability"] = {
            "results": results,
            "identification_rate": identification_rate,
            "n_checked": checked,
            "n_confirmed": confirmed,
        }

        context.log_step(
            self.name,
            parameters={"ppm_tolerance": self.ppm_tolerance},
            metrics={"n_checked": checked, "n_confirmed": confirmed},
            warnings=warnings,
            input_files=input_files,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return "system_suitability" in context.qc_metrics


def match_within_ppm(
    observed_mz: float, expected_mz: float, ppm_tolerance: float
) -> Optional[float]:
    """Return the ppm error if observed_mz is within tolerance of expected_mz,
    else None. Pure function -- no I/O, easy to unit test exhaustively."""
    ppm_error = (observed_mz - expected_mz) / expected_mz * 1e6
    if abs(ppm_error) <= ppm_tolerance:
        return ppm_error
    return None


def find_best_match(
    expected_mz: float, observed_mzs: list[float], ppm_tolerance: float
) -> Optional[tuple[float, float]]:
    """Find the observed m/z closest to expected_mz within tolerance.

    Returns (matched_mz, ppm_error) or None if nothing in observed_mzs
    is within tolerance.
    """
    best: Optional[tuple[float, float]] = None
    for observed in observed_mzs:
        ppm_error = match_within_ppm(observed, expected_mz, ppm_tolerance)
        if ppm_error is None:
            continue
        if best is None or abs(ppm_error) < abs(best[1]):
            best = (observed, ppm_error)
    return best