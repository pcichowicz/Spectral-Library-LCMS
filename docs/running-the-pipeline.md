---
layout: default
title: Running the Pipeline
nav_order: 4
---

# Running the Pipeline
{: .no_toc }

1. TOC
{:toc}

---

## Requirements

```bash
pip install pandas pyyaml pydantic numpy pymzml --break-system-packages
```

(drop `--break-system-packages` if you're in a virtualenv, which is
recommended)

## Directory layout

The pipeline expects to find itself relative to a project root marked
by `.git`, `pyproject.toml`, or `README.md` (see
`find_project_root()` in `context.py`). Everything else hangs off that
root's `v3/` folder:

```
<project_root>/
  v3/
    config/
      <study_id>.yaml
    data/
      <study_id>/
        <sample_id>.mzML   ...one per row in sample_metadata.csv
        <study_id>_sample_metadata.csv
    results/
      <study_id>/          # created automatically
        features/
        library/
        qc_report/
        checkpoints/
```

## sample_metadata.csv

One row per sample. `expected_compounds` and `expected_mz` are
JSON-array-as-string cells (parsed by `metadata_utils.parse_list_field`):

```csv
sample_id,sample_role,expected_compounds,expected_mz
Amino_acid_Std_neg_Glycine-414,standard,"[""Glycine""]","[74.02332]"
BLK_MEOH_IPA-380,solvent_blank,,
```

## Config

See `config/mtbls1861.yaml` for the full schema. The knobs you'll touch
most often while tuning:

```yaml
dataset_profile: "standards_only"   # only profile with real code paths today

feature_detection:
  mass_error_ppm: 5.0
  peak_width: [10, 60]
  noise_threshold: 8000.0

library_matching:
  reference_library_path: "reference_libraries/EMBL-MCF_negative.msp"
  reference_library_format: "msp"
  precursor_mz_tolerance_ppm: 10.0
  fragment_mz_tolerance_da: 0.02
  min_match_score: 0.7
```

## Reference library

Spectral library matching (Stage 9) needs a local copy of EMBL-MCF --
it is **not** fetched automatically.

1. Go to [curatr.mcf.embl.de/MS2/export/](https://curatr.mcf.embl.de/MS2/export/)
2. Download the **negative-mode** export as MSP (or MGF)
3. Save it at the path set in `library_matching.reference_library_path`
   (default: `v3/reference_libraries/EMBL-MCF_negative.msp`)

The parser (`analysis/utils/spectral_library.py`) is tolerant of a few
common MSP/MGF field-name variants, but curatr's exact export dialect
wasn't verified against a live file while this was built -- if
`library_matching`'s logged warnings show zero entries parsed, check
the field names against `_MSP_NAME_KEYS` / `_MSP_MZ_KEYS` /
`_MSP_ADDUCT_KEYS` at the top of that file.

## Run

```bash
python -m v3.run_dev
```

(or `python v3/run_dev.py` from the project root -- `run_dev.py`'s
`main()` currently hardcodes `project_name="mtbls1861"`; change that
argument or add a CLI flag for other studies)

This runs every registered stage in order, prints a per-stage summary,
and writes `results/<study_id>/{library,qc_report}/`.

Re-running is cheap for stages with content-hash caching (feature
detection, system suitability, blank QC) -- unchanged inputs skip
straight to the cached result. Force a re-run of everything with:

```python
context = pipeline.run(context, force_stages={"*"})
```

or a specific stage by name (`{"feature_detection"}`).

## Publishing the QC report to docs

After a run you're happy with, publish its results to the docs site:

```bash
python scripts/publish_docs_data.py --study mtbls1861
```

This copies a trimmed `qc_report.json` (summary + processing log, not
the full per-feature blank-flag lists -- those stay local under
`results/`) and `library.csv` into `docs/data/`, which the
[QC Report page](./qc-report) renders client-side. Commit the updated
`docs/data/*` files to update the published report.

## Enabling GitHub Pages

Repo Settings → Pages → Source: **Deploy from a branch** → Branch:
`main`, folder: **`/docs`**. GitHub builds Jekyll sites automatically
from that folder -- no Actions workflow needed for this setup.
