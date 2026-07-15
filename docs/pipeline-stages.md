---
layout: default
title: Pipeline Stages
nav_order: 3
---

# Pipeline Stages
{: .no_toc }

Status reflects what's actually registered and running in
`run_dev.py`, not the original design doc's numbering -- some stages
were added, some described in the design aren't built yet. Keeping this
page honest is the point: it's a validation pipeline, it should be
possible to trust its own status page.

1. TOC
{:toc}

---

## Summary table

| # | Stage | File | Status |
|---|---|---|---|
| 1 | Ingestion | `stages/ingestion.py` | `Implemented` |
| 2 | System Suitability | `stages/system_suitability.py` | `Implemented` (standards_only only) |
| 3 | Feature Detection | `stages/feature_detection.py` | `Implemented` |
| 4 | RT Alignment | -- | `Not implemented` |
| — | Blank QC | `stages/blank_qc.py` | `Implemented` |
| 5 | Adduct Annotation | `stages/adduct_annotation.py` | `Implemented` (precursor-list scope) |
| 6 | Feature Linking / Consensus Map | -- | `Not implemented` |
| — | Spectral Purity | `stages/spectral_purity.py` | `Implemented` |
| 9 | Spectral Library Matching | `stages/library_matching.py` | `Implemented` |
| — | Library Assembly | `stages/library_assembly.py` | `Implemented` |
| 8 | Normalization / Batch Correction | -- | `Not implemented` |
| 10 | Export | `stages/export.py` | `Implemented` |

## 1. Ingestion

Validates every sample in `sample_metadata.csv` has a corresponding
mzML file. Note: this deployment starts from mzML, not RAW -- it does
**not** run ThermoRawFileParser or any RAW→mzML conversion; that's
assumed to have already happened upstream.

## 2. System Suitability

For each non-blank sample, confirms at least one DDA MS2 precursor
matches the sample's expected m/z within tolerance. This is the
`standards_only` stand-in for a QC-pool-based suitability check.

{: .status-partial }
The architecture notes specify this should go **fatal** if
expected-ion detection fails broadly across many standards (an
instrument/calibration signal, not a single-compound issue). The
current code only ever logs warnings here, never raises fatal -- worth
deciding if that's intentional before scaling up sample count.

## 3. Feature Detection

A hand-rolled greedy mass-trace picker (`feature_utils.group_into_features`):
extends the nearest open trace within ppm tolerance scan-to-scan, closes
traces after `max_gaps` consecutive misses, reports the apex point per
trace.

{: .status-partial }
Fine for a handful of standards. Two things to revisit before pointing
this at real untargeted cohorts: no isotope-pattern grouping/deconvolution,
and it reports **apex intensity**, not integrated peak area -- both
matter once you're doing real quantification instead of "is this
standard present." Benchmark against an established picker (e.g.
pyOpenMS mass trace detection) before trusting this at scale.

## 4. RT Alignment

{: .status-todo }
**Not implemented.** The architecture notes describe a `standards_only`
behavior (samples with no replicate group pass through unaligned;
replicate groups get local alignment) and a `cohort_with_qc` behavior
(global alignment against the highest-feature-count QC pool sample).
Neither exists as a stage yet -- the pipeline currently goes straight
from feature detection to blank QC.

## Blank QC

Pools features from process-blank samples, flags (does not drop) any
sample feature that matches a pooled blank feature within m/z/RT
tolerance. Flags are surfaced for human review, not silently excluded --
a false negative (dropping a real analyte that happens to share a
background ion's coordinates) is worse than a false positive here.

## 5. Adduct Annotation

For each compound `system_suitability` already confirmed, checks
whether *additional* corroborating adducts (`[M+Cl]-`, `[2M-H]-`, etc.)
are also present.

{: .status-partial }
This only searches the DDA-selected precursor list, not the full MS1
spectrum. Fine for standards -- the analyte is almost always what gets
selected for MS2 -- but for untargeted work on real samples, most
features never get selected as precursors, so this scope would miss
most adduct relationships. Full MS1-peak adduct search is the natural
next step before untargeted use.

## 6. Feature Linking / Consensus Map

{: .status-todo }
**Not implemented.** No global consensus map is built across samples --
the architecture notes explain why for `standards_only` (unrelated
single-compound injections have no shared biological ground truth to
justify one), but the `cohort_with_qc` version (one consensusJSON across
the full cohort) doesn't exist in code either. Needed before this can
process a real multi-sample cohort.

## Spectral Purity

For each confirmed compound, checks how "clean" its precursor isolation
was: for MS2 scans matching the target precursor, what fraction of the
preceding MS1 scan's intensity in the isolation window actually belongs
to the target ion. Surfaces contamination/co-elution before it can
quietly corrupt a library entry.

## 9. Spectral Library Matching

**The pipeline's primary validation step.** Extracts each confirmed
compound's MS2 spectrum, scores it (matched-peak cosine similarity)
against every reference spectrum in a pre-built, independently
downloaded library (EMBL-MCF from
[curatr.mcf.embl.de](https://curatr.mcf.embl.de/MS2/export/)) whose
precursor m/z falls within tolerance, and compares the best hit's
compound name against the sample sheet's known identity.

This produces the run's actual pass/fail signal: what fraction of
confirmed standards get their correct identity back from library
matching. See the [QC Report](./qc-report) for current numbers.

Requires a local copy of the reference library (see
[Running the Pipeline](./running-the-pipeline#reference-library)) --
does not fetch it automatically.

## Library Assembly

Pulls together system suitability, feature detection, adduct
annotation, blank QC, spectral purity, and library matching results
into one `LibraryEntry` record per confirmed compound. A confirmed
compound with no matching detected feature (system suitability found a
precursor, but the feature-detection peak picker didn't independently
find a feature there) is logged as a warning and skipped, rather than
papered over with placeholder values.

## 8. Normalization / Batch Correction

{: .status-todo }
**Not implemented.** The architecture notes describe a `cohort_with_qc`
QC-pool-based drift correction (LOESS/spline vs. injection order) and a
`standards_only` no-op (nothing to fit a drift curve against, so the
feature matrix should pass through unmodified with replicate-group CV
surfaced as a monitoring proxy instead). Neither exists as a stage --
there's currently no explicit "this stage ran and chose to do nothing"
step; normalization is simply absent from the registered stage list.

## 10. Export

Writes `library.json` (full fidelity, including MS2 spectra),
`library.csv` (flattened for quick eyeballing), and `qc_report.json`
(summary metrics + full processing log + raw per-stage metrics).

{: .status-partial }
The architecture notes also call for a `qc_report.html` with
visualizations (PCA, CV distributions, drift before/after). Not built
yet -- the [QC Report page](./qc-report) on this site is currently
filling that role by rendering `qc_report.json` client-side instead.
