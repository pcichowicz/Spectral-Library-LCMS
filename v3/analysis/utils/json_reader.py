from pathlib import Path
import json

from pydantic_core._pydantic_core import ValidationError

from v3.analysis.utils.schemas import Feature
from v3.analysis.pipeline import RecoverableStageError

class JSONFeatureReader:
    """
    Reads back feature lists written by PymzmlFeatureDetector.
    """

    def read_features(self, path: Path) -> list[dict]:

        try:
            with open(path) as f:
                raw = json.load(f)

        except json.decoder.JSONDecodeError as exc:
            raise RecoverableStageError(f"{path.name}: corrupt featurejson: {exc}") from exc

        try:
            features = [Feature.model_validate(f).model_dump() for f in raw]
        except ValidationError as exc:
            raise RecoverableStageError(f"{path.name}: featurejson failed schema check: {exc}") from exc

        return features