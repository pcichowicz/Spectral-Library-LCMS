"""
Stage 1: Ingestion (mzML-provided mode).

This deployment starts from mzML, not RAW -- so this stage does NOT run
ThermoRawFileParser or any RAW->mzML conversion. It exists to (a) validate
that every sample in sample_metadata.csv has a corresponding mzML file,
(b) populate context.mzml_directory, and (c) log provenance, so every
downstream stage can assume "mzml_directory is populated and validated"
regardless of how the mzML got there.
"""
from __future__ import annotations

from pathlib import Path

from v3.analysis.context import LCMSContext
from v3.analysis.pipeline import FatalStageError, RecoverableStageError

class MzMLIngestionStage:
    name = "ingestion"

    def __init__(self, mzml_dir: Path):
        self.mzml_dir = Path(mzml_dir)

    def validate_input(self, context: LCMSContext) -> bool:
        if context.sample_metadata is None:
            raise FatalStageError("ingestion: sample_metadata not loaded on context")
        if not self.mzml_dir.exists():
            raise FatalStageError(f"ingestion: mzml_dir does not exist: {self.mzml_dir}")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        sample_ids = list(context.sample_metadata["sample_id"])
        found: dict[str, Path] = {}
        missing: list[str] = []

        for sample_id in sample_ids:
            candidate = self.mzml_dir / f"{sample_id}.mzML"
            if candidate.exists():
                found[sample_id] = candidate
            else:
                missing.append(sample_id)

        if not found:
            raise FatalStageError(
                f"ingestion: no mzML files found for any of {len(sample_ids)} samples "
                f"in {self.mzml_dir}"
            )

        context.qc_metrics["ingestion"] = {
            "n_expected": len(sample_ids),
            "n_found": len(found),
            "missing_sample_ids": missing,
        }

        warnings = [f"missing mzML for sample: {s}" for s in missing]
        context.log_step(
            self.name,
            parameters={"mzml_dir": str(self.mzml_dir)},
            metrics={"n_found": len(found), "n_missing": len(missing)},
            warnings=warnings,
            input_files=[str(p) for p in found.values()],
        )

        if missing:
            # Individual missing files are recoverable -- downstream stages
            # just won't have data for those sample_ids. If every sample is
            # missing, that's caught above as fatal.
            raise RecoverableStageError(
                f"{len(missing)}/{len(sample_ids)} samples missing mzML files: {missing}"
            )

        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return context.mzml_dir is not None