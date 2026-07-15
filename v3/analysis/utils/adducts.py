"""
Adduct m/z <-> neutral mass conversions for negative-mode LC-MS.

Pure functions only -- no I/O -- so these are exhaustively unit testable.
Mass shifts are standard literature values (electron mass folded in where
relevant); ELECTRON_MASS itself is negligible at ppm-level tolerances but
included for correctness.
"""
from __future__ import annotations

ELECTRON_MASS = 0.000549
PROTON_MASS = 1.007276
CHLORINE_MASS = 34.968853
SODIUM_MASS = 22.989770
HYDROGEN_MASS = 1.007825
FORMIC_ACID_MASS = 46.005480  # HCOOH

# Mass shift applied to the neutral monoisotopic mass M to get the adduct m/z.
ADDUCT_MASS_SHIFTS: dict[str, float] = {
    "[M-H]-": -PROTON_MASS,
    "[M+Cl]-": CHLORINE_MASS + ELECTRON_MASS,
    "[M+FA-H]-": FORMIC_ACID_MASS - PROTON_MASS,
    "[M+Na-2H]-": SODIUM_MASS - 2 * HYDROGEN_MASS + ELECTRON_MASS,
}
# [2M-H]- handled separately below since it scales with 2x the neutral mass.


def compute_adduct_mz(neutral_mass: float, adduct: str) -> float:
    """Given a compound's neutral monoisotopic mass, compute the expected
    m/z for a given adduct."""
    if adduct == "[2M-H]-":
        return 2 * neutral_mass - PROTON_MASS
    if adduct not in ADDUCT_MASS_SHIFTS:
        raise ValueError(f"Unknown adduct: {adduct!r}")
    return neutral_mass + ADDUCT_MASS_SHIFTS[adduct]


def compute_neutral_mass(observed_mz: float, adduct: str) -> float:
    """Inverse of compute_adduct_mz: given an observed m/z assumed to be a
    specific adduct, back-calculate the neutral monoisotopic mass."""
    if adduct == "[2M-H]-":
        return (observed_mz + PROTON_MASS) / 2
    if adduct not in ADDUCT_MASS_SHIFTS:
        raise ValueError(f"Unknown adduct: {adduct!r}")
    return observed_mz - ADDUCT_MASS_SHIFTS[adduct]


def known_adducts() -> list[str]:
    return list(ADDUCT_MASS_SHIFTS.keys()) + ["[2M-H]-"]