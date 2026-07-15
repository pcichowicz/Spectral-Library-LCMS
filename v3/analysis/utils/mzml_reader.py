"""
mzML reading, isolated behind a small interface.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
from typing import Optional

from v3.analysis.utils.feature_utils import group_into_features

class PymzmlPrecursorReader:
    """Reads DDA MS2 precursor m/z values via pymzml."""

    def get_precursor_mzs(self, mzml_path: Path) -> list[float]:
        import pymzml

        precursor_mzs = []
        run = pymzml.run.Reader(str(mzml_path), build_index_from_scratch=True)
        for spectrum in run:
            if spectrum.ms_level != 2:
                continue
            for precursor in spectrum.selected_precursors:
                if "mz" in precursor:
                    precursor_mzs.append(float(precursor["mz"]))
        return precursor_mzs

class PymzmlFeatureDetector:
    """Feature detection via pymzml + the custom feature_picking algorithm.
       Writes JSON (FEATURE_FILE_SUFFIX)
    """

    def detect_features(self, mzml_path: Path, output_path: Path, params: dict) -> list[dict]:
        import json

        scans = _load_ms1_scans(mzml_path)
        peaks_width_sec = params.get("peak_width", [10,60])
        min_peak_width_sec =peaks_width_sec[0]

        rts = [s["rt"] for s in scans]
        scan_interval_sec = float(np.median(np.diff(sorted(rts))))

        min_scans = max(params.get("min_scans"), int(round(min_peak_width_sec / scan_interval_sec)))

        features = group_into_features(
            scans,
            mz_ppm_tolerance=float(params.get("mass_error_ppm", 5.0)),
            min_scans=min_scans,
            noise_threshold=float(params.get("noise_threshold", 8000.0)),
            max_gaps=int(params.get("max_gaps", 2)),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(features, f, indent=2)
        #
        return features


class PymzmlSpectralPurityReader:
    """Precursor isolation purity : for each MS2 scan matching the
    target precursor, look at the preceding MS1 scan's peaks within the
    isolation window and compute what fraction belongs to the target ion."""

    TARGET_WINDOW_DA = 0.01

    def compute_precursor_purity(
            self, mzml_path: Path, precursor_mz: float, isolation_window_da: float
    ) -> Optional[float]:
        import pymzml

        half_window = isolation_window_da / 2.0
        purities: list[float] = []
        last_ms1_peaks: Optional[np.ndarray] = None

        run = pymzml.run.Reader(str(mzml_path))
        for spectrum in run:
            if spectrum.ms_level == 1:
                peaks = spectrum.peaks("centroided")
                last_ms1_peaks = np.asarray(peaks) if len(peaks) else None
                continue

            if spectrum.ms_level != 2 or last_ms1_peaks is None:
                continue

            matched_precursor = False
            for precursor in spectrum.selected_precursors:
                if "mz" in precursor and abs(precursor["mz"] - precursor_mz) <= 0.01:
                    matched_precursor = True
                    break
            if not matched_precursor:
                continue

            mz_array = last_ms1_peaks[:, 0]
            intensity_array = last_ms1_peaks[:, 1]

            window_mask = (mz_array >= precursor_mz - half_window) & (
                    mz_array <= precursor_mz + half_window
            )
            window_total = intensity_array[window_mask].sum()
            if window_total <= 0:
                continue

            target_mask = (mz_array >= precursor_mz - self.TARGET_WINDOW_DA) & (
                    mz_array <= precursor_mz + self.TARGET_WINDOW_DA
            )
            target_total = intensity_array[target_mask].sum()
            purities.append(float(target_total / window_total))

        if not purities:
            return None
        return sum(purities) / len(purities)

class PymzmlMS2SpectrumReader:
    """Extracts a representative MS2 peak list for a given precursor m/z.

    A precursor can be selected for MS2 in multiple scans across a run
    (different collision energies, repeated triggers). Rather than
    merging them -- which risks smearing together spectra from different
    fragmentation energies -- this picks the single matching MS2 scan
    with the highest total ion current, on the assumption that's the
    cleanest/most complete fragmentation spectrum. Peaks below
    `min_relative_intensity` of the scan's base peak are dropped as noise
    before matching, since library reference spectra are typically
    curated down to real fragments only.
    """

    def __init__(self, min_relative_intensity: float = 0.01):
        self.min_relative_intensity = min_relative_intensity

    def get_ms2_spectrum(
        self, mzml_path: Path, precursor_mz: float, precursor_tolerance_da: float = 0.01
    ) -> list[tuple[float, float]]:
        import pymzml

        best_peaks: Optional[np.ndarray] = None
        best_tic = -1.0

        run = pymzml.run.Reader(str(mzml_path), build_index_from_scratch=True)
        for spectrum in run:
            if spectrum.ms_level != 2:
                continue

            matched = any(
                "mz" in precursor and abs(precursor["mz"] - precursor_mz) <= precursor_tolerance_da
                for precursor in spectrum.selected_precursors
            )
            if not matched:
                continue

            peaks = spectrum.peaks("centroided")
            if len(peaks) == 0:
                continue

            peaks = np.asarray(peaks)
            tic = float(peaks[:, 1].sum())
            if tic > best_tic:
                best_tic = tic
                best_peaks = peaks

        if best_peaks is None:
            return []

        base_peak_intensity = float(best_peaks[:, 1].max())
        if base_peak_intensity <= 0:
            return []

        floor = base_peak_intensity * self.min_relative_intensity
        filtered = best_peaks[best_peaks[:, 1] >= floor]

        return [(float(mz), float(intensity)) for mz, intensity in filtered]


def _load_ms1_scans(mzml_path: Path) -> list[dict]:
    """Pull all MS1 scans out of an mzML file as plain dicts of numpy
    arrays. Shared by PymzmlFeatureDetector and PymzmlSpectralPurityReader
    so both use the exact same extraction logic."""
    import pymzml

    scans = []
    run = pymzml.run.Reader(str(mzml_path), build_index_from_scratch=True)
    for spectrum in run:
        if spectrum.ms_level != 1:
            continue
        peaks = spectrum.peaks("centroided")  # Nx2 array: [mz, intensity]
        if len(peaks) == 0:
            continue
        peaks = np.asarray(peaks)
        scans.append(
            {
                "rt": spectrum.scan_time_in_minutes() * 60.0,  # normalize to seconds
                "mz": peaks[:, 0],
                "intensity": peaks[:, 1],
            }
        )
    return scans