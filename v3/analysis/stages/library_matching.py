"""
Stage 9: Spectral Library Matching -- the primary validation step
(see architecture.md Goal Statement, §0).

For every compound confirmed in Stage 2 (system_suitability), extracts
its MS2 spectrum from the sample's mzML and scores it against every
reference spectrum in a *pre-built, independently downloaded* library
(e.g. EMBL-MCF from curatr.mcf.embl.de/MS2/export/ -- NOT built from
MTBLS1861's own raw files; see spectral_library.py's module docstring).

This is the actual pass/fail signal for the dev run: `is_correct_match`
compares the top scoring library hit's compound name against the known
identity already recorded on the sample sheet.

Failure handling, matching architecture.md's table (§6.1):
- No match found for one compound/feature -> recoverable, logged,
  library_match_id/match_score stay None, is_correct_match = False.
- Reference library file missing or unparseable -> fatal (nothing in
  this run can be validated without it).
- MS2 extraction failing for every confirmed compound in the whole run
  -> fatal (instrument/acquisition-mode problem, not a single-compound
  problem) -- same "broad failure vs single failure" split used by
  feature_detection.py and spectral_purity.py.
"""
from __future__ import annotations

from pathlib import Path

from v3.analysis.context import LCMSContext
from v3.analysis.pipeline import FatalStageError
from v3.analysis.utils.protocols import MS2SpectrumReader
from v3.analysis.utils.spectral_library import ReferenceSpectrum, load_library
from v3.analysis.utils.spectral_matching import cosine_similarity, names_match

# Bump whenever cosine_similarity/match_peaks or the reference library
# parsing logic changes -- file hashes alone won't catch an algorithm
# change, and the reference library file itself isn't in filehash_cache
# (it's outside results_dir), so this stage does not implement
# cache_key() at all for now: always re-run. Safer than a stale match
# silently surviving a scoring-logic change.
STAGE_LOGIC_VERSION = "v1"


def find_best_library_match(
    query_peaks: list[tuple[float, float]],
    query_precursor_mz: float,
    library: list[ReferenceSpectrum],
    precursor_mz_tolerance_ppm: float,
    fragment_mz_tolerance_da: float,
) -> tuple[ReferenceSpectrum, float] | None:
    """Search the whole library for the best-scoring candidate whose
    precursor m/z is within tolerance of query_precursor_mz. Pure
    function -- no I/O -- easy to unit test with a small in-memory
    library list.

    Returns (best_reference_spectrum, score) or None if no reference
    spectrum's precursor falls within tolerance at all (a real "nothing
    to compare against", distinct from "compared but scored low").
    """
    best: tuple[ReferenceSpectrum, float] | None = None

    for ref in library:
        ppm_error = abs(query_precursor_mz - ref.precursor_mz) / ref.precursor_mz * 1e6
        if ppm_error > precursor_mz_tolerance_ppm:
            continue
        score = cosine_similarity(query_peaks, ref.peaks, fragment_mz_tolerance_da)
        if best is None or score > best[1]:
            best = (ref, score)

    return best


class SpectralLibraryMatchingStage:
    name = "library_matching"

    def __init__(
        self,
        ms2_reader: MS2SpectrumReader,
        reference_library_path: Path,
        reference_library_format: str,
        precursor_mz_tolerance_ppm: float = 10.0,
        fragment_mz_tolerance_da: float = 0.02,
        min_match_score: float = 0.7,
    ):
        self.ms2_reader = ms2_reader
        self.reference_library_path = Path(reference_library_path)
        self.reference_library_format = reference_library_format
        self.precursor_mz_tolerance_ppm = precursor_mz_tolerance_ppm
        self.fragment_mz_tolerance_da = fragment_mz_tolerance_da
        self.min_match_score = min_match_score
        self._library: list[ReferenceSpectrum] | None = None

    def validate_input(self, context: LCMSContext) -> bool:
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("library_matching: system_suitability must run first")
        if context.mzml_dir is None:
            raise FatalStageError("library_matching: mzml_directory not set")
        if not self.reference_library_path.exists():
            raise FatalStageError(
                f"library_matching: reference library not found at "
                f"{self.reference_library_path} -- download it from "
                f"curatr.mcf.embl.de/MS2/export/ and set "
                f"library_matching.reference_library_path in the config"
            )
        return True

    def _load_library(self) -> list[ReferenceSpectrum]:
        if self._library is None:
            try:
                self._library = load_library(self.reference_library_path, self.reference_library_format)
            except Exception as exc:
                raise FatalStageError(
                    f"library_matching: reference library unreadable "
                    f"({self.reference_library_path}): {exc}"
                ) from exc
            if not self._library:
                raise FatalStageError(
                    f"library_matching: reference library at "
                    f"{self.reference_library_path} parsed to zero usable "
                    f"entries -- check reference_library_format matches the file"
                )
        return self._library

    def execute(self, context: LCMSContext) -> LCMSContext:
        library = self._load_library()
        ss_results = context.qc_metrics["system_suitability"]["results"]

        results: dict[str, dict] = {}
        warnings: list[str] = []
        input_files: list[str] = [str(self.reference_library_path)]
        n_attempted = 0
        n_with_ms2 = 0
        n_matched = 0
        n_correct = 0

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue

            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                continue

            mzml_path = context.mzml_dir / f"{sample_id}.mzML"
            if not mzml_path.exists():
                warnings.append(f"{sample_id}: mzML missing, library matching skipped")
                continue
            input_files.append(str(mzml_path))

            sample_matches = []
            for match in confirmed_matches:
                n_attempted += 1
                compound = match["compound"]
                precursor_mz = match["matched_mz"]

                ms2_spectrum = self.ms2_reader.get_ms2_spectrum(
                    mzml_path, precursor_mz, precursor_tolerance_da=0.01
                )

                if not ms2_spectrum:
                    warnings.append(
                        f"{sample_id}: no MS2 spectrum extracted for {compound!r} "
                        f"(m/z {precursor_mz}) -- library matching skipped for this compound"
                    )
                    sample_matches.append(
                        _empty_match_record(compound, precursor_mz, "no_ms2_spectrum")
                    )
                    continue

                n_with_ms2 += 1
                found = find_best_library_match(
                    ms2_spectrum,
                    precursor_mz,
                    library,
                    self.precursor_mz_tolerance_ppm,
                    self.fragment_mz_tolerance_da,
                )

                if found is None:
                    warnings.append(
                        f"{sample_id}: no library entry within "
                        f"{self.precursor_mz_tolerance_ppm} ppm of {compound!r} "
                        f"(m/z {precursor_mz}) -- no match found"
                    )
                    sample_matches.append(
                        {
                            "compound": compound,
                            "expected_mz": precursor_mz,
                            "ms2_spectrum": ms2_spectrum,
                            "n_ms2_peaks": len(ms2_spectrum),
                            "library_match_id": None,
                            "match_compound_name": None,
                            "match_score": None,
                            "match_adduct": None,
                            "known_identity": compound,
                            "is_correct_match": False,
                            "status": "no_precursor_candidates",
                        }
                    )
                    continue

                ref, score = found
                n_matched += 1
                passes_threshold = score >= self.min_match_score
                correct = passes_threshold and names_match(compound, ref.compound_name)
                if correct:
                    n_correct += 1
                elif passes_threshold:
                    warnings.append(
                        f"{sample_id}: top match for {compound!r} is "
                        f"{ref.compound_name!r} (score {score:.3f}) -- name mismatch"
                    )
                else:
                    warnings.append(
                        f"{sample_id}: best match for {compound!r} scored "
                        f"{score:.3f}, below threshold {self.min_match_score}"
                    )

                sample_matches.append(
                    {
                        "compound": compound,
                        "expected_mz": precursor_mz,
                        "ms2_spectrum": ms2_spectrum,
                        "n_ms2_peaks": len(ms2_spectrum),
                        "library_match_id": ref.library_id,
                        "match_compound_name": ref.compound_name,
                        "match_score": score,
                        "match_adduct": ref.adduct,
                        "known_identity": compound,
                        "is_correct_match": correct,
                        "status": "matched" if passes_threshold else "below_threshold",
                    }
                )

            results[sample_id] = {"status": "checked", "matches": sample_matches}

        if n_attempted > 0 and n_with_ms2 == 0:
            raise FatalStageError(
                "library_matching: could not extract an MS2 spectrum for any "
                f"confirmed compound across all {n_attempted} attempted -- "
                "likely an acquisition-mode/precursor-list problem, not a "
                "single-compound problem"
            )

        context.qc_metrics["library_matching"] = {
            "results": results,
            "n_attempted": n_attempted,
            "n_with_ms2": n_with_ms2,
            "n_matched": n_matched,
            "n_correct": n_correct,
            "validation_rate": (n_correct / n_attempted) if n_attempted else None,
            "reference_library_size": len(library),
        }
        context.log_step(
            self.name,
            parameters={
                "reference_library_path": str(self.reference_library_path),
                "reference_library_format": self.reference_library_format,
                "precursor_mz_tolerance_ppm": self.precursor_mz_tolerance_ppm,
                "fragment_mz_tolerance_da": self.fragment_mz_tolerance_da,
                "min_match_score": self.min_match_score,
                "logic_version": STAGE_LOGIC_VERSION,
            },
            metrics={
                "n_attempted": n_attempted,
                "n_with_ms2": n_with_ms2,
                "n_matched": n_matched,
                "n_correct": n_correct,
            },
            warnings=warnings,
            input_files=input_files,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return "library_matching" in context.qc_metrics


def _empty_match_record(compound: str, precursor_mz: float, status: str) -> dict:
    return {
        "compound": compound,
        "expected_mz": precursor_mz,
        "ms2_spectrum": [],
        "n_ms2_peaks": 0,
        "library_match_id": None,
        "match_compound_name": None,
        "match_score": None,
        "match_adduct": None,
        "known_identity": compound,
        "is_correct_match": None,
        "status": status,
    }
