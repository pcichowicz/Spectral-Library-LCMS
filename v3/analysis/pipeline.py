"""
Pipeline orchestrator: runs registered stages in order over an LCMSContext.
"""
from __future__ import annotations

import logging
from typing import Protocol

from .context import LCMSContext
from v3.analysis.utils.cache_utils import load_checkpoint, save_checkpoint

logger = logging.getLogger("lcms_pipeline")


class StageError(Exception):
    """Base class for stage-level errors."""

class RecoverableStageError(StageError):
    """Stage failed for this input, but the pipeline should continue.

    Example: one standard's expected ion wasn't detected. Log it, flag
    it, move on -- don't kill the whole run over one compound.
    """

class FatalStageError(StageError):
    """Stage failed in a way that invalidates the whole run; pipeline stops.

    Example: the reference library file is missing, or every sample
    failed feature detection (instrument/config problem, not a
    single-compound problem)
    """

class PipelineStage(Protocol):
    """Every stage (ingestion, feature detection, ...) implements this."""

    name: str

    def validate_input(self, context: LCMSContext) -> bool:
        """Check prerequisites are present before running. Return False
        (not raise) for "not ready yet"; raise FatalStageError for
        "something is actually wrong"."""
        ...

    def execute(self, context: LCMSContext) -> LCMSContext:
        """Do the work; return the (mutated) context. Raise
        RecoverableStageError or FatalStageError as appropriate."""
        ...

    def validate_output(self, context: LCMSContext) -> bool:
        """Sanity-check output before moving on to the next stage."""
        ...

class LCMSPipeline:
    """Registers stages, then runs them in order over a context."""

    def __init__(self) -> None:
        self._stages: list[PipelineStage] = []

    def register_stage(self, stage: PipelineStage) -> "LCMSPipeline":
        self._stages.append(stage)
        return self

    def run(self, context: LCMSContext, force_stages: set[str] | None = None) -> LCMSContext:
        """
        force_stages: rerun stage even if cache matches, {*} forces all stages
        """
        for stage in self._stages:
            print(f"Running stage: {stage.name}")
            force = bool(force_stages) and {"*" in force_stages or stage.name in force_stages}
            context = self.run_stage(stage, context, force = force)
            print("")
        return context

    def run_stage(self, stage: PipelineStage, context: LCMSContext, force: bool = False) -> LCMSContext:
        """Run a single stage with validation, error handling, and logging, and cache checkpoint.

        Kept separate from run() so a single stage can be re-executed on
        its own while debugging (see run_by_name below).
        """
        logger.info("stage.start", extra={"stage": stage.name})

        if not stage.validate_input(context):
            raise FatalStageError(f"{stage.name}: input validation failed")

        cache_key_fn = getattr(stage, "cache_key", None)
        key: str | None = None

        if cache_key_fn is not None and not force:
            try:
                key = cache_key_fn(context)
                checkpoint = load_checkpoint(context.results_dir, stage.name)
            except Exception as exc:
                # Caching is an optimization, not a correctness requirement --
                # a problem computing the cache key (e.g. a file that
                # vanished/was renamed between an exists() check and being
                # hashed) should degrade to "don't cache this run", never
                # crash the pipeline.
                logger.warning(
                    "stage.cache_key_error",
                    extra={"stage": stage.name, "error": str(exc)},
                )
                print(f"  cache check failed for {stage.name} ({exc}) -- running normally")
                key = None
                checkpoint = None

            if key is not None and checkpoint is not None and checkpoint.get("key") == key:
                context.qc_metrics[stage.name] = checkpoint["qc_metrics"]
                if checkpoint.get("log_entry"):
                    context.processing_log.append(checkpoint["log_entry"])
                logger.info("stage.cache_hit", extra={"stage": stage.name})
                print(f"  cached (inputs unchanged) -- skipping {stage.name}")
                return context

        try:
            context = stage.execute(context)
        except RecoverableStageError as exc:
            logger.warning(
                "stage.recoverable_error",
                extra={"stage": stage.name, "error": str(exc)},
            )
            context.log_step(stage.name, parameters={}, warnings=[str(exc)])
            return context

        except FatalStageError:
            raise
        except Exception as exc:  # deliberate catch-all at the stage boundary
            raise FatalStageError(f"{stage.name}: unexpected error: {exc}") from exc

        if not stage.validate_output(context):
            raise FatalStageError(f"{stage.name}: output validation failed")

        if cache_key_fn is not None:
            try:
                save_key = key if key is not None else cache_key_fn(context)
                log_entry = context.processing_log[-1] if context.processing_log else None
                save_checkpoint(
                    context.results_dir,
                    stage.name,
                    save_key,
                    context.qc_metrics.get(stage.name),
                    log_entry,
                )
            except Exception as exc:
                # Same principle as above: a checkpoint-writing problem
                # should not undo a stage that just completed successfully.
                logger.warning(
                    "stage.checkpoint_save_error",
                    extra={"stage": stage.name, "error": str(exc)},
                )
                print(f"  couldn't save checkpoint for {stage.name} ({exc}) -- will re-run next time")

        logger.info("stage.complete", extra={"stage": stage.name})
        return context

    def run_by_name(self, stage_name: str, context: LCMSContext) -> LCMSContext:
        """Re-run a single registered stage by name -- for debugging one
        stage at a time without re-running everything before it."""
        for stage in self._stages:
            if stage.name == stage_name:
                return self.run_stage(stage, context)
        raise ValueError(f"No registered stage named {stage_name!r}")