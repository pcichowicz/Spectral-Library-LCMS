---
layout: default
title: Architecture
nav_order: 2
---

# Architecture
{: .no_toc }

1. TOC
{:toc}

---

## Goal statement

MTBLS1861 contains no biological samples -- it is entirely reference
standards. Given that, the honest deliverable of this pipeline is **not**
a metabolomics study result; it's a **validation harness**: because the
true identity of every injection is known in advance (named in the
sample sheet), the pipeline's job is to prove, against ground truth,
that:

1. Feature detection correctly finds the expected ion for each known
   standard, and
2. Spectral library matching correctly recovers the right identity at a
   reasonable match score.

The output is best read as "pipeline precision/recall against known
answers" -- a prerequisite for ever trusting this pipeline on real
unknown biological data later.

### Portability requirement

This pipeline should be reusable on a future dataset that *does* have
pooled QC samples, blanks, and real experimental groups, without a
rewrite. The design intent is for stages that behave differently
depending on dataset shape to be implemented as **dataset-profile
strategies** selected by config (`standards_only` vs `cohort_with_qc`),
not as MTBLS1861-specific rewrites.

{: .status-partial }
**Current state:** `context.dataset_profile` is loaded from config and
threaded through, but no stage actually branches on it yet -- there is
no `cohort_with_qc` code path implemented. Every stage today only
implements the `standards_only` behavior. Swapping in a cohort dataset
currently means writing new stage logic, not flipping a config flag.
Tracked in [Pipeline Stages](./pipeline-stages).

## Dataset context

**Study:** [MTBLS1861](https://www.ebi.ac.uk/metabolights/MTBLS1861) --
Public LC-Orbitrap-MS/MS Spectral Library for Metabolite Identification
(EMBL-MCF)

| | |
|---|---|
| Data source | MetaboLights repository |
| File format | Thermo RAW → centroided mzML |
| Instrument | Orbitrap (high-resolution) |
| Acquisition | Data-Dependent Acquisition (DDA), MS1 + MS2 |
| Polarity | Negative mode only (current scope) |

**Confirmed sample composition** (from `s_MTBLS1861.txt`):
- 382 total samples, all `Standard solutions` / `Reference Standards` --
  no biological sample class in this study.
- Only 2 process blanks.
- Zero QC pool samples -- no pooled/QC-equivalent naming anywhere.
- A subset of standards are injected as technical replicates under
  different sample IDs; these replicate groups are the closest thing
  this dataset has to a QC-pool substitute.

### Reference spectral library

EMBL-MCF is **not** built by this pipeline. It's already curated and
downloadable at
[curatr.mcf.embl.de/MS2/export/](https://curatr.mcf.embl.de/MS2/export/)
(TSV/MGF/MSP, split by polarity), independent of MTBLS1861's raw files.
Spectral library matching pulls this pre-built library as the reference
and uses MTBLS1861's raw runs purely as the known-answer query set.

## Data flow & state management

**Where state lives:** `LCMSContext` carries file *paths*, not
in-memory DataFrames, for anything that could be large (featureJSON).
Small summary structures (QC metrics, config) live in memory.

**Config/schema versioning:** every `LCMSContext` carries a
`config_version` and every output's `qc_report.json` embeds the full
resolved config and per-stage parameters, so you can always tell which
config produced which output.

```python
@dataclass
class LCMSContext:
    study_id: str
    base_dir: Path
    dataset_profile: str = "standards_only"
    polarity: str = "negative"
    yaml_config: dict[str, Any]
    sample_metadata: Optional[pd.DataFrame]
    qc_metrics: dict[str, Any]
    processing_log: list[dict[str, Any]]
    library_entries: list[LibraryEntry]
```

## Error handling & provenance

Every stage implements a small protocol:

```python
class PipelineStage(Protocol):
    name: str
    def validate_input(self, context: LCMSContext) -> bool: ...
    def execute(self, context: LCMSContext) -> LCMSContext: ...
    def validate_output(self, context: LCMSContext) -> bool: ...
```

Two error classes, matching two very different situations:

- **`RecoverableStageError`** -- this input failed, the pipeline
  continues. Example: one standard's expected ion wasn't detected.
- **`FatalStageError`** -- this failure invalidates the whole run.
  Example: the reference library file is missing, or every sample
  failed feature detection.

| Stage | Recoverable | Fatal |
|---|---|---|
| Ingestion | Single file corruption | All files unreadable |
| System suitability | Single compound not confirmed | Broad detection failure across many standards |
| Feature detection | Low/zero feature count in one sample | Zero features across every sample |
| Blank QC | Feature dropped/flagged (expected) | No blank samples found at all |
| Spectral purity | Purity not computable for one match | Purity not computable for *any* match in the run |
| Library matching | No match found for one feature | Reference library missing/unreadable, or MS2 extraction fails for every confirmed compound |

Every stage logs a structured provenance entry (`context.log_step`) on
completion, even on a recoverable failure -- parameters, metrics,
warnings, and the real input/output file paths it touched. These roll up
into `qc_report.json`'s `processing_log`.

## Caching

Stages that define a `cache_key(context)` get content-hash-based
checkpointing: the pipeline hashes relevant input files + parameters,
and skips re-running a stage if nothing changed since the last run. This
is a file-size/mtime-aware hash cache (`filehash_cache.json`), not a
naive re-hash-everything-every-time approach.

One stage currently opts out deliberately: `library_matching`'s
reference library file lives outside `results_dir` and isn't
hash-tracked, so it always re-runs rather than risk silently skipping
on a stale key.
