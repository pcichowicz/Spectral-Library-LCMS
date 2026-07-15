from v3.analysis.context import LCMSContext
from v3.analysis.utils.logging_utils import setup_logging
from v3.analysis.pipeline import LCMSPipeline
from v3.analysis.utils.mzml_reader import PymzmlPrecursorReader, PymzmlFeatureDetector, PymzmlSpectralPurityReader, PymzmlMS2SpectrumReader
from v3.analysis.utils.json_reader import JSONFeatureReader

from v3.analysis.stages.ingestion import MzMLIngestionStage
from v3.analysis.stages.system_suitability import SystemSuitabilityStage
from v3.analysis.stages.feature_detection import FeatureDetectionStage
from v3.analysis.stages.blank_qc import BlankQCStage
from v3.analysis.stages.adduct_annotation import AdductAnnotationStage
from v3.analysis.stages.spectral_purity import SpectralPurityStage
from v3.analysis.stages.library_assembly import LibraryAssemblyStage
from v3.analysis.stages.library_matching import SpectralLibraryMatchingStage
from v3.analysis.stages.export import ExportStage


def main(project_name: str):

    # --------------------------------------------------------------------------------------------- #
    #   Analysis pipeline setup
    # --------------------------------------------------------------------------------------------- #

    # Logging
    setup_logging()

    context = LCMSContext(study_id=project_name)

    # Pipeline
    pipeline = (LCMSPipeline()
                .register_stage(MzMLIngestionStage(mzml_dir=context.mzml_dir))
                .register_stage(SystemSuitabilityStage(reader=PymzmlPrecursorReader(), ppm_tolerance=5.0))
                .register_stage(FeatureDetectionStage(detector=PymzmlFeatureDetector(),output_dir=context.featurejson_dir, params=context.yaml_config["feature_detection"]))
                .register_stage(BlankQCStage(reader=JSONFeatureReader()))
                .register_stage(AdductAnnotationStage(PymzmlPrecursorReader(),
                                context.yaml_config["adduct_annotation"]["candidate_adducts"],
                                context.yaml_config["adduct_annotation"]["primary_adduct"],
                                context.yaml_config["adduct_annotation"]["ppm_tolerance"]))
                .register_stage(SpectralPurityStage(PymzmlSpectralPurityReader(),
                                context.yaml_config["spectral_purity"]["isolation_window_da"],
                                context.yaml_config["spectral_purity"]["min_purity"]
                                ))
                .register_stage(SpectralLibraryMatchingStage(
                                PymzmlMS2SpectrumReader(),
                                reference_library_path=context.base_dir / context.yaml_config["library_matching"]["reference_library_path"],
                                reference_library_format=context.yaml_config["library_matching"]["reference_library_format"],
                                precursor_mz_tolerance_ppm=context.yaml_config["library_matching"]["precursor_mz_tolerance_ppm"],
                                fragment_mz_tolerance_da=context.yaml_config["library_matching"]["fragment_mz_tolerance_da"],
                                min_match_score=context.yaml_config["library_matching"]["min_match_score"],
                                ))
                .register_stage(LibraryAssemblyStage(JSONFeatureReader()))
                .register_stage(ExportStage())

                )
    #
    context = pipeline.run(context)

    print("\n--- MzML Ingestion Summary ---")
    ss = context.qc_metrics.get("ingestion", {})
    print(f"Checked: {ss.get('n_expected')}  Confirmed: {ss.get('n_found')}"
          )

    print("\n--- System Suitability Summary ---")
    ss = context.qc_metrics.get("system_suitability", {})
    print(f"Checked: {ss.get('n_checked')}  Confirmed: {ss.get('n_confirmed')}  "
          f"Identification rate: {ss.get('identification_rate')}")

    print("\n--- Feature Detection Summary ---")
    fd = context.qc_metrics.get("feature_detection", {})
    print(f"Attempted: {fd.get('n_attempted')}  With features: {fd.get('n_with_features')}")
    for sample_id, result in fd.get("results", {}).items():
        if result.get("status") == "ok":
            print(f"  {sample_id}: {result['summary']['n_features']} features")
        else:
            print(f"  {sample_id}: {result.get('status')}")

    print("\n--- Blank Background QC Summary ---")
    bq = context.qc_metrics.get("blank_qc", {})
    print(f"Blank features pooled: {bq.get('n_blank_features')}")
    for sample_id, result in bq.get("results", {}).items():
        if result.get("status") == "checked":
            print(f"  {sample_id}: {result['n_flagged']}/{result['n_features']} features flagged")
        else:
            print(f"  {sample_id}: {result.get('status')}")

    print("\n--- Adduct Annotation Summary ---")
    aa = context.qc_metrics.get("adduct_annotation", {})
    print(f"Compounds checked: {aa.get('n_compounds_checked')}  "
          f"With extra adducts: {aa.get('n_with_extra_adducts')}")

    print("\n--- Spectral Purity Summary ---")
    sp = context.qc_metrics.get("spectral_purity", {})
    print(f"Attempted: {sp.get('n_attempted')}  Computed: {sp.get('n_computed')}  "
          f"Below threshold: {sp.get('n_below_threshold')}  Median purity: {sp.get('median_purity')}")
    # print(context.qc_metrics)

    print("\n--- Spectral Library Matching Summary ---")
    lm = context.qc_metrics.get("library_matching", {})
    print(f"Attempted: {lm.get('n_attempted')}  With MS2: {lm.get('n_with_ms2')}  "
          f"Matched: {lm.get('n_matched')}  Correct identity: {lm.get('n_correct')}  "
          f"Validation rate: {lm.get('validation_rate')}")
    for sample_id, result in lm.get("results", {}).items():
        for m in result.get("matches", []):
            print(f"  {sample_id} / {m['compound']}: -> {m.get('match_compound_name')} "
                  f"(score={m.get('match_score')}, correct={m.get('is_correct_match')})")


    print("\n--- Library Assembly + Export ---")
    print(f"Entries assembled: {len(context.library_entries)}")
    print(f"Library file: {context.library_path}")
    print(f"QC report: {context.qc_report_path}")

if __name__ == '__main__':
    main(project_name="mtbls1861")