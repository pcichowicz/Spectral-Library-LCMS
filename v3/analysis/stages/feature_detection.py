"""
Stage 3: Feature Detection.

Runs peak picking (via FeatureDetector) on every sample that has an mzML
file, writes full results (featureJSON) to context.featurejson_dir,
and keeps a lightweight in-memory summary per sample in context.qc_metrics.

Failure handling:
- One sample producing zero features, or failing outright -> recoverable,
  logged as a warning, pipeline continues.
- Every sample producing zero features -> fatal. That's not "this
  standard didn't ionize," that's "something is wrong with the config
  or the whole batch".
"""
from __future__ import annotations

from pathlib import Path

from v3.analysis.context import LCMSContext
from v3.analysis.utils.protocols import FeatureDetector
from v3.analysis.pipeline import FatalStageError
from v3.analysis.utils.constants import FEATURE_FILE_SUFFIX
from v3.analysis.utils.feature_utils import summarize_features
from v3.analysis.utils.cache_utils import load_filehash_cache, save_filehash_cache, hash_file, hash_files, compute_cache_key

# Bump this whenever the peak-picking/feature-detection logic changes --
# file hashes alone won't catch an algorithm change.
CACHE_SCHEMA_VERSION = "v1"

class FeatureDetectionStage:
    name = "feature_detection"

    def __init__(
        self,
        detector: FeatureDetector,
        output_dir: Path,
        params: dict | None = None,
    ):
        self.detector = detector
        self.output_dir = Path(output_dir)
        self.params = params or {}

    def cache_key(self, context: LCMSContext) -> str:
        hash_cache = load_filehash_cache(context.results_dir)
        candidate_paths = (context.mzml_dir / f"{sid}.mzML" for sid in context.sample_metadata["sample_id"])
        mzml_paths = [p for p in candidate_paths if p.exists()]
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "params": self.params,
            "sample_metadata_hash": hash_file(context.sample_metadata_path, hash_cache),
            "mzml_hashes": hash_files(mzml_paths, hash_cache),
        }
        save_filehash_cache(context.results_dir, hash_cache)
        return compute_cache_key(payload)

    def validate_input(self, context: LCMSContext) -> bool:
        if context.mzml_dir is None:
            raise FatalStageError("feature_detection: mzml_directory not set (run ingestion first)")
        if context.sample_metadata is None:
            raise FatalStageError("feature_detection: sample_metadata not loaded on context")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        results: dict[str, dict] = {}
        warnings: list[str] = []
        n_with_features = 0
        n_attempted = 0
        input_files: list[str] = []
        output_files: list[str] = []

        for _, row in context.sample_metadata.iterrows():
            sample_id = row["sample_id"]
            mzml_path = context.mzml_dir / f"{sample_id}.mzML"

            if not mzml_path.exists():
                warnings.append(f"{sample_id}: mzML missing, skipped")
                results[sample_id] = {"status": "skipped_missing_mzml"}
                continue

            n_attempted += 1
            output_path = self.output_dir / f"{sample_id}{FEATURE_FILE_SUFFIX}"
            input_files.append(str(mzml_path))

            try:
                features = self.detector.detect_features(mzml_path, output_path, self.params)
            except Exception as exc:  #  one bad file shouldn't kill the run
                warnings.append(f"{sample_id}: feature detection failed: {exc}")
                results[sample_id] = {"status": "failed", "error": str(exc)}
                continue

            summary = summarize_features(features)
            results[sample_id] = {"status": "ok", "summary": summary}
            output_files.append(str(output_path))

            if summary["n_features"] > 0:
                n_with_features += 1
            else:
                warnings.append(f"{sample_id}: zero features detected")

        if n_attempted > 0 and n_with_features == 0:
            print("WARNINGS", warnings)
            raise FatalStageError(
                "feature_detection: zero features detected across all "
                f"{n_attempted} attempted samples -- likely a config or "
                "instrument-file problem, not a single-compound problem"
            )

        context.featurejson_dir = self.output_dir
        context.qc_metrics["feature_detection"] = {
            "results": results,
            "n_attempted": n_attempted,
            "n_with_features": n_with_features,
        }

        context.log_step(
            self.name,
            parameters=self.params,
            metrics={"n_attempted": n_attempted, "n_with_features": n_with_features},
            warnings=warnings,
            input_files=input_files,
            output_files=output_files
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return context.featurejson_dir is not None