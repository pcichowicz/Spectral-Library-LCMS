from pydantic import BaseModel, ConfigDict
from typing import Literal, Optional, TypedDict

class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mz: float
    rt: float
    intensity: float
    charge: int

class LibraryEntry(TypedDict):
    """
    One row of the final output table
    """

    entry_id: str
    compound_name: str
    precursor_mz: float
    rt_sec: float
    adduct: str
    charge: int
    mass_error_ppm: float
    ms2_spectrum: list[tuple[float, float]]
    spectral_purity: float
    source_sample_id: str
    blank_flagged: bool
    library_match_id: Optional[str]
    match_score: Optional[float]
    known_identity: Optional[str]
    is_correct_match: Optional[bool]


class QCMetrics(TypedDict):
    """
    Run-level QC summary.
    """

    blank_background: dict
    mass_accuracy: dict
    identification_rate: dict
    spectral_purity: dict


class ProvenanceRecord(TypedDict):
    """
    Shape of one entry in LCMSContext.processing_log
    """

    stage: str
    timestamp: str
    config_version: str
    input_files: list[str]
    output_files: list[str]
    parameters: dict
    metrics: dict
    warnings: list[str]
    software_versions: dict

class QCReport(TypedDict):

    study_id: str
    config_version: Optional[str]
    dataset_profile: str
    qc_metrics: QCMetrics
    processing_log: list[ProvenanceRecord]
    raw_qc_metrics: dict
