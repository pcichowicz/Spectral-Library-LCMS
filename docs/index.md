---
layout: default
title: Home
nav_order: 1
description: "LC-MS/MS pipeline docs and QC report"
permalink: /
---

# LC-MS Pipeline
{: .fs-9 }

A validation-first LC-MS/MS pipeline built against MTBLS1861's reference
standards, and structured to generalize to real untargeted metabolomics
cohorts later without a rewrite.
{: .fs-6 .fw-300 }

[Read the architecture](./architecture){: .btn .btn-primary .mr-2 }
[See the latest QC report](./qc-report){: .btn }

---

## What this is

[MTBLS1861](https://www.ebi.ac.uk/metabolights/MTBLS1861) contains no
biological samples -- it's entirely reference standards. That makes the
honest use of this dataset **not** a metabolomics discovery result, but a
**validation harness**: since the true identity of every injection is
known in advance, the pipeline's job is to prove, against ground truth,
that:

1. **Feature detection** correctly finds the expected ion for each known
   standard, and
2. **Spectral library matching** correctly recovers the right identity at
   a reasonable match score.

That's the actual measure of success here -- not a curated
unknown-metabolite table. See the [QC Report](./qc-report) for where the
pipeline currently stands against that bar.

## Where to start

| If you want to... | Go to |
|---|---|
| Understand the pipeline's design and data flow | [Architecture](./architecture) |
| See what each stage does and its current implementation status | [Pipeline Stages](./pipeline-stages) |
| Run this yourself | [Running the Pipeline](./running-the-pipeline) |
| See the latest validation numbers | [QC Report](./qc-report) |

## Status at a glance

This is a dev pipeline, not a finished product. A few things worth
knowing before you dig in -- covered in detail on the relevant pages:

- Stages 4 (RT alignment) and 6 (feature linking / consensus map) aren't
  implemented yet -- not needed for isolated standards, but required
  before this can run on a real cohort with shared analytes across
  samples.
- The `cohort_with_qc` dataset profile (for a future dataset with pooled
  QC samples) is designed in the architecture notes but not yet coded --
  today only `standards_only` actually branches in code.
- Spectral library matching (Stage 9) is implemented and is the
  pipeline's primary validation signal -- see the [QC report](./qc-report)
  for current match rates.
