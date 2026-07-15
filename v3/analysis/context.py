"""
Core context object that flows through every pipeline stage.

LCMSContext carries file *paths* and small in-memory metadata/results between
stages -- NOT full DataFrames, spectra, or raw arrays. Large intermediate
data (mzML, featureXML, etc.) lives on disk; the context just tracks where.
This keeps memory bounded regardless of dataset size and makes every stage
independently re-runnable/debuggable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from v3.analysis.utils.schemas import LibraryEntry

DEFAULT_MARKERS = ("pyproject.toml", ".git", "README.md")
def find_project_root(markers = DEFAULT_MARKERS) -> Path | None:
    p = Path.cwd()
    for parent in [p, *p.parents]:
        if any((parent / m).exists() for m in markers):
            return parent
    return Path(__file__).resolve().parent

DEFAULT_BASE_DIR = find_project_root() / "v3"

@dataclass
class LCMSContext:
    """
    Shared state passed through the LC-MS pipeline.
    """

    study_id: str
    base_dir: Path = field(default=DEFAULT_BASE_DIR)

    yaml_path: Path = field(init=False)
    sample_metadata_path: Path = field(init=False)
    project_data_dir: Path = field(init=False)
    mzml_dir: Path = field(init=False)
    featurejson_dir: Path = field(init=False)
    library_path: Path = field(init=False)
    qc_report_path: Path = field(init=False)

    # Runtime Configurations (loads from yaml)
    dataset_profile: str = "standards_only"
    polarity: str = "negative"
    instrument_type: str = "Orbitrap"
    yaml_config: dict[str, Any] = field(default_factory=dict, repr=False)

    # In memory Data / State
    mzml_file_paths: list[Path] = field(default_factory=list, repr=False)
    sample_metadata: Optional[pd.DataFrame] = field(default=None, repr=False)
    qc_metrics: dict[str, Any] = field(default_factory=dict)
    processing_log: list[dict[str, Any]] = field(default_factory=list)

    #Final outputs

    library_entries: list[LibraryEntry] = field(default_factory=list)

    def __post_init__(self):
        """
        Resolves paths, validates files, creates dirs, loads configs
        """
        self.base_dir = self.base_dir.resolve()
        self.yaml_path = self.base_dir / "config" / f"{self.study_id}.yaml"
        self.project_data_dir = self.base_dir / "data" / f"{self.study_id}"
        self.sample_metadata_path = self.project_data_dir / f"{self.study_id}_sample_metadata.csv"
        self.results_dir = self.base_dir / "results" / f"{self.study_id}"


        self._validate_dirs()
        self._load_yaml_config()
        self.sample_metadata = pd.read_csv(self.sample_metadata_path)

        self.mzml_dir = self.base_dir / self.yaml_config["input_paths"]["mzml_dir"] / f"{self.study_id}"
        self.mzml_file_paths = list(self.mzml_dir.glob("*.mzML"))

        #outputs dir
        self.featurejson_dir = self.results_dir / self.yaml_config["output_paths"]["features"]
        self.library_path = self.results_dir / self.yaml_config["output_paths"]["library"]
        self.qc_report_path = self.results_dir / self.yaml_config["output_paths"]["qc_report"]

        self.make_dirs(subdirs=self.yaml_config["output_paths"])

    def log_step(
        self,
        step_name: str,
        parameters: dict[str, Any],
        metrics: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        input_files: list[str] | None = None,
        output_files: list[str] | None = None,
    ) -> None:
        """Record a provenance entry for a completed (or partially-failed) stage.

        Every stage should call this exactly once, even on a recoverable
        failure
        """
        self.processing_log.append(
            {
                "stage": step_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "parameters": parameters,
                "metrics": metrics or {},
                "warnings": warnings or [],
                "input_files": input_files or [],
                "output_dirs": output_files or [],
            }
        )

    def _validate_dirs(self):
        """
        Checks if yaml config and cvs sample data files are upload prior with api
        """
        if not self.yaml_path.exists():
            raise FileNotFoundError(f"ERROR: YAML configuration file missing at {self.yaml_path}")
        if not self.sample_metadata_path.exists():
            raise FileNotFoundError(f"ERROR: Metadata CSV missing at {self.sample_metadata_path}")

    def _load_yaml_config(self):
        """
        Parses YAML config file and updates/overrides settings
        """
        with open(self.yaml_path, "r") as f:
            self.yaml_config = yaml.safe_load(f)

        study_cfg = self.yaml_config.get("study", {})
        self.polarity = study_cfg.get("polarity", self.polarity)
        self.instrument_type = study_cfg.get("instrument_type", self.instrument_type)
        self.dataset_profile = self.yaml_config.get("dataset_profile", self.dataset_profile)

    def make_dirs(self, exist_ok: bool = True, subdirs: list[str] | None = None) -> None:
        self.results_dir.mkdir(exist_ok=exist_ok, parents=True)

        if subdirs:
            for s in subdirs:
                (self.results_dir / s).mkdir(exist_ok=exist_ok, parents=True)

    def resolve(self, *path_parts) -> Path:
        p = Path(*[part for part in path_parts if part is not None])
        out = p if p.is_absolute() else self.results_dir / p
        out.parent.mkdir(exist_ok=True, parents=True)
        return out

    def path_for(self, stem: str, ext: str = "", subdir: str | None = None) -> Path:
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        name = f"{stem}{ext}"
        return self.resolve(subdir, name)
