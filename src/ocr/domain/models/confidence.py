"""Measured confidence is optional; absence must never imply certainty."""
from typing import Optional

from pydantic import BaseModel, Field, model_serializer, model_validator


class ConfidenceModel(BaseModel):
    confidence: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    confidence_source: Optional[str] = "unavailable"

    @model_validator(mode="after")
    def normalize_confidence_source(self):
        self.confidence_source = self._confidence_source()
        return self

    def _confidence_source(self) -> str:
        if self.confidence is None:
            return "unavailable"
        return self.confidence_source if self.confidence_source not in (None, "unavailable") else "unspecified"

    @model_serializer(mode="wrap")
    def serialize_confidence(self, handler):
        payload = handler(self)
        # Application code may update a score after construction. Serialize
        # its current state, including a real measured zero.
        payload["confidence_source"] = self._confidence_source()
        return payload
