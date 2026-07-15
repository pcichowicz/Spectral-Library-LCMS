"""
Stage 4: Solvent Blank Background QC.

Compares every standard/mix's detected features against the pooled feature
set from blanks. A matching feature
is FLAGGED, not dropped for a spectral library, a
false negative -- dropping a real analyte peak because it happens to share
a background ion's m/z/RT -- is worse than a false positive here. A human
reviews flags before anything is excluded.
"""
from __future__ import annotations

from typing import Optional

from v3.analysis.context import LCMSContext
from v3.analysis.utils.json_reader import JSONFeatureReader
from v3.analysis.utils.constants import FEATURE_FILE_SUFFIX
from v3.analysis.pipeline import FatalStageError
from v3.analysis.utils.cache_utils import load_filehash_cache, save_filehash_cache, hash_file, hash_files, compute_cache_key


def is_blank_match(
    feature: dict,
    blank_features: list[dict],
    mz_tolerance_ppm: float,
    rt_tolerance_sec: float,
) -> Optional[dict]:
    """Return the first blank feature that matches `feature` within
    tolerance, or None. Pure function -- no I/O, easy to unit test."""
    for blank in blank_features:
        mz_ppm_error = abs(feature["mz"] - blank["mz"]) / blank["mz"] * 1e6
        rt_diff = abs(feature["rt"] - blank["rt"])
        if mz_ppm_error <= mz_tolerance_ppm and rt_diff <= rt_tolerance_sec:
            return blank
    return None

# Bump this whenever is_blank_match's matching logic changes -- file
# hashes alone won't catch an algorithm change.
CACHE_SCHEMA_VERSION = "v1"

class BlankQCStage:
    name = "blank_qc"

    def __init__(
        self,
        reader: JSONFeatureReader,
        mz_tolerance_ppm: float = 20.0,
        rt_tolerance_sec: float = 20.0,
    ):
        self.reader = reader
        self.mz_tolerance_ppm = mz_tolerance_ppm
        self.rt_tolerance_sec = rt_tolerance_sec

    def cache_key(self, context: LCMSContext) -> str:
        hash_cache = load_filehash_cache(context.results_dir)
        featurejson_paths = list(context.featurejson_dir.glob(f"*{FEATURE_FILE_SUFFIX}"))
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "mz_tolerance_ppm": self.mz_tolerance_ppm,
            "rt_tolerance_sec": self.rt_tolerance_sec,
            "sample_metadata_hash": hash_file(context.sample_metadata_path, hash_cache),
            # blank_qc reads feature_detection's results dict directly out of
            # qc_metrics (for status/skip decisions), not just the files --
            # so that needs to be part of the key too.
            "feature_detection_qc": context.qc_metrics.get("feature_detection", {}),
            "featurejson_hashes": hash_files(featurejson_paths, hash_cache),
        }
        save_filehash_cache(context.results_dir, hash_cache)
        return compute_cache_key(payload)

    def validate_input(self, context: LCMSContext) -> bool:
        if context.featurejson_dir is None:
            raise FatalStageError("blank_qc: featurejson_dir not set (run feature_detection first)")
        if context.sample_metadata is None:
            raise FatalStageError("blank_qc: sample_metadata not loaded on context")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        warnings: list[str] = []
        blank_ids = list(
            context.sample_metadata.loc[
                context.sample_metadata["sample_role"] == "solvent_blank", "sample_id"
            ]
        )

        if not blank_ids:
            raise FatalStageError(
                "blank_qc: no samples with sample_role='solvent_blank'/'blank' found in sample_metadata "
            )

        blank_features: list[dict] = []
        input_files: list[str] = []
        for sample_id in blank_ids:
            path = context.featurejson_dir / f"{sample_id}{FEATURE_FILE_SUFFIX}"
            if not path.exists():
                warnings.append(f"{sample_id}: featureJSON missing, excluded from blank background")
                continue
            blank_features.extend(self.reader.read_features(path))
            input_files.append(str(path))

        if not blank_features:
            warnings.append("blank_qc: no blank features could be loaded; background flagging skipped entirely")
            context.qc_metrics["blank_qc"] = {"results": {}, "n_blank_features": 0}
            context.log_step(
                self.name,
                parameters={"mz_tolerance_ppm": self.mz_tolerance_ppm, "rt_tolerance_sec": self.rt_tolerance_sec},
                metrics={"n_blank_features": 0},
                warnings=warnings,
                input_files=input_files,
            )
            return context

        fd_results = context.qc_metrics.get("feature_detection", {}).get("results", {})
        results: dict[str, dict] = {}

        for _, row in context.sample_metadata.iterrows():
            sample_id = row["sample_id"]
            if row["sample_role"] in  ["blank", "solvent_blank"]:
                continue

            fd_result = fd_results.get(sample_id)
            if not fd_result or fd_result.get("status") != "ok":
                results[sample_id] = {"status": "skipped_no_features"}
                continue

            path = context.featurejson_dir / f"{sample_id}{FEATURE_FILE_SUFFIX}"
            if not path.exists():
                results[sample_id] = {"status": "skipped_missing_featurejson"}
                continue

            features = self.reader.read_features(path)
            flagged = []
            for feature in features:
                match = is_blank_match(feature, blank_features, self.mz_tolerance_ppm, self.rt_tolerance_sec)
                if match is not None:
                    flagged.append(
                        {
                            "feature_mz": feature["mz"],
                            "feature_rt": feature["rt"],
                            "matched_blank_mz": match["mz"],
                            "matched_blank_rt": match["rt"],
                        }
                    )

            results[sample_id] = {
                "status": "checked",
                "n_features": len(features),
                "n_flagged": len(flagged),
                "flagged": flagged,
            }
            if flagged:
                warnings.append(
                    f"{sample_id}: {len(flagged)}/{len(features)} features overlap with blank background"
                )

        context.qc_metrics["blank_qc"] = {
            "results": results,
            "n_blank_features": len(blank_features),
        }
        context.log_step(
            self.name,
            parameters={"mz_tolerance_ppm": self.mz_tolerance_ppm, "rt_tolerance_sec": self.rt_tolerance_sec},
            metrics={"n_blank_features": len(blank_features)},
            warnings=warnings,
            input_files=input_files,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return "blank_qc" in context.qc_metrics