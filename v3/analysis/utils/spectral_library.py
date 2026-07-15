"""
Loads a pre-built reference spectral library (e.g. EMBL-MCF, downloaded
directly from curatr.mcf.embl.de/MS2/export/ as MSP or MGF) into a flat
list of ReferenceSpectrum records for Stage 9 matching.

This module does NOT build a library from MTBLS1861's own raw files --
per architecture.md's clarification, the reference library is an
independent, pre-curated download; MTBLS1861's raw runs are only ever the
*query* side of Stage 9, never the reference side.

Parsing is intentionally tolerant of field-name variants (different
MSP/MGF exporters spell "PRECURSORMZ" a few different ways) since we
can't pin down curatr's exact export dialect without a live file to
inspect -- verify field names against a real downloaded export and adjust
_MSP_NAME_KEYS/_MSP_MZ_KEYS/_MSP_ADDUCT_KEYS below if names go unparsed
(see `n_parsed` / `n_skipped` in the stage's logged warnings).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class ReferenceSpectrum:
    library_id: str
    compound_name: str
    precursor_mz: float
    adduct: str | None
    peaks: list[tuple[float, float]] = field(default_factory=list)


# Case-insensitive header-key aliases seen across common MSP exporters.
_MSP_NAME_KEYS = {"name", "compound", "compoundname"}
_MSP_MZ_KEYS = {"precursormz", "precursor_mz", "exactmass", "precursor"}
_MSP_ADDUCT_KEYS = {"precursortype", "adduct", "ionmode_adduct", "adducttype"}
_MSP_NUMPEAKS_KEYS = {"numpeaks", "num peaks", "num_peaks"}


def load_library(path: Path, fmt: str) -> list[ReferenceSpectrum]:
    """Dispatch to the right parser by format string ('msp' or 'mgf')."""
    fmt = fmt.strip().lower()
    if fmt == "msp":
        return list(_parse_msp(path))
    if fmt == "mgf":
        return list(_parse_mgf(path))
    raise ValueError(f"Unsupported reference_library_format: {fmt!r} (expected 'msp' or 'mgf')")


def _parse_msp(path: Path) -> Iterator[ReferenceSpectrum]:
    """MSP: blocks separated by blank lines, each block is
    'KEY: VALUE' header lines followed by 'mz intensity' peak lines."""
    text = path.read_text(errors="replace")
    entry_id = 0

    for block in text.split("\n\n"):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue

        header: dict[str, str] = {}
        peaks: list[tuple[float, float]] = []

        for line in lines:
            if ":" in line and _looks_like_header(line):
                key, _, value = line.partition(":")
                header[key.strip().lower().replace(" ", "")] = value.strip()
            else:
                peak = _parse_peak_line(line)
                if peak is not None:
                    peaks.append(peak)

        name = _first_present(header, _MSP_NAME_KEYS)
        mz_raw = _first_present(header, _MSP_MZ_KEYS)
        if name is None or mz_raw is None:
            continue  # not a usable block -- skipped, caller logs the count

        try:
            precursor_mz = float(mz_raw.split()[0])
        except (ValueError, IndexError):
            continue

        entry_id += 1
        yield ReferenceSpectrum(
            library_id=f"MSP_{entry_id:06d}",
            compound_name=name,
            precursor_mz=precursor_mz,
            adduct=_first_present(header, _MSP_ADDUCT_KEYS),
            peaks=peaks,
        )


def _looks_like_header(line: str) -> bool:
    """Distinguish 'NAME: Glycine' (header) from '74.0247: 999' style peak
    lines some exporters emit with a colon separator instead of whitespace."""
    key = line.split(":", 1)[0].strip()
    try:
        float(key)
    except ValueError:
        return True
    return False  # the "key" parses as a number -> this is a peak line


def _parse_peak_line(line: str) -> tuple[float, float] | None:
    parts = line.replace(",", " ").replace(":", " ").split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _first_present(header: dict[str, str], keys: set[str]) -> str | None:
    for key in keys:
        if key in header:
            return header[key]
    return None


def _parse_mgf(path: Path) -> Iterator[ReferenceSpectrum]:
    """MGF: BEGIN IONS / END IONS blocks, 'KEY=VALUE' headers, PEPMASS
    for precursor m/z, bare 'mz intensity' peak lines."""
    entry_id = 0
    header: dict[str, str] = {}
    peaks: list[tuple[float, float]] = []
    in_block = False

    for raw_line in path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.upper() == "BEGIN IONS":
            in_block = True
            header = {}
            peaks = []
            continue

        if line.upper() == "END IONS":
            in_block = False
            name = header.get("title") or header.get("name")
            mz_raw = header.get("pepmass")
            if name and mz_raw:
                try:
                    precursor_mz = float(mz_raw.split()[0])
                except (ValueError, IndexError):
                    continue
                entry_id += 1
                yield ReferenceSpectrum(
                    library_id=f"MGF_{entry_id:06d}",
                    compound_name=name,
                    precursor_mz=precursor_mz,
                    adduct=header.get("adduct") or header.get("precursortype"),
                    peaks=peaks,
                )
            continue

        if not in_block:
            continue

        if "=" in line and line.split("=", 1)[0].isalpha():
            key, _, value = line.partition("=")
            header[key.strip().lower()] = value.strip()
        else:
            peak = _parse_peak_line(line)
            if peak is not None:
                peaks.append(peak)
