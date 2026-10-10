"""Local structured-document extractor behind a replaceable service boundary.

The local implementation consumes supplied JSON or labeled text embedded in a
text-readable PDF. It deliberately performs no OCR; a Textract adapter can
implement the same protocol later without changing verification rules.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StructuredDocumentData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_type: str | None = Field(default=None, pattern="^(CERTIFICATE|INVOICE|OTHER)$")
    certificate_id: str | None = Field(default=None, min_length=1, max_length=150)
    invoice_id: str | None = Field(default=None, min_length=1, max_length=150)
    producer: str | None = Field(default=None, min_length=1, max_length=200)
    recycler: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: float | None = Field(default=None, ge=0)
    date: str | None = Field(default=None, min_length=1, max_length=50)
    material_type: str | None = Field(default=None, min_length=1, max_length=200)


class DocumentExtractor(Protocol):
    def extract(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        supplied_data: dict | None = None,
    ) -> dict | None: ...


class LocalStructuredDocumentExtractor:
    _LABELS = {
        "certificate_id": r"certificate\s*(?:id|no\.?|number)",
        "invoice_id": r"invoice\s*(?:id|no\.?|number)",
        "producer": r"producer",
        "recycler": r"recycler",
        "quantity": r"(?:quantity|weight)\s*(?:kg)?",
        "date": r"(?:collection\s*)?date",
        "material_type": r"(?:material\s*type|material|waste\s*category)",
    }

    def extract(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        supplied_data: dict | None = None,
    ) -> dict | None:
        parsed = dict(supplied_data or {})
        field_sources = {key: "UPLOADER_PROVIDED" for key in parsed}
        if content_type == "application/pdf":
            text = content.decode("latin-1", errors="ignore")
            for field, label in self._LABELS.items():
                if field in parsed:
                    continue
                match = re.search(
                    rf"(?im)(?:^|[<(])\s*{label}\s*[:=#-]\s*([^\r\n)>]+)",
                    text,
                )
                if match:
                    value = match.group(1).strip().rstrip(";,")
                    if field == "quantity":
                        number = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value)
                        if number:
                            value = number.group(0).replace(",", "")
                    parsed[field] = value
                    field_sources[field] = "LOCAL_TEXT_PARSER"

        if not parsed:
            return None
        try:
            document = StructuredDocumentData.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        values = document.model_dump(exclude_none=True)
        if not values:
            return None
        if "document_type" not in values:
            if values.get("certificate_id"):
                values["document_type"] = "CERTIFICATE"
            elif values.get("invoice_id"):
                values["document_type"] = "INVOICE"
        # The metadata's origin is part of the result. Local PDF text parsing is
        # still not an authenticity check; caller-supplied fields remain untrusted.
        values["_provenance"] = {
            "method": ("MIXED" if {"UPLOADER_PROVIDED", "LOCAL_TEXT_PARSER"} <= set(field_sources.values())
                       else "LOCAL_TEXT_PARSER" if "LOCAL_TEXT_PARSER" in field_sources.values()
                       else "UPLOADER_PROVIDED"),
            "field_sources": {key: field_sources[key] for key in values if key in field_sources},
        }
        return values


def get_document_extractor() -> DocumentExtractor:
    """Return the active implementation; future OCR can replace this provider."""
    return LocalStructuredDocumentExtractor()
