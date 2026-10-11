"""Bounded local document text extraction and conservative field parsing.

OCR is optional (``EVIDENCE_OCR_ENABLED=true``) and uses a locally installed
Tesseract executable through pytesseract. Extracted fields are consistency
signals only; neither extraction nor matching establishes authenticity.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StructuredDocumentData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document_type: str | None = None
    document_number: str | None = Field(default=None, max_length=150)
    certificate_id: str | None = Field(default=None, max_length=150)
    invoice_id: str | None = Field(default=None, max_length=150)
    producer: str | None = Field(default=None, max_length=200)
    recycler: str | None = Field(default=None, max_length=200)
    transporter: str | None = Field(default=None, max_length=200)
    facility: str | None = Field(default=None, max_length=200)
    claim_reference: str | None = Field(default=None, max_length=150)
    vehicle_registration: str | None = Field(default=None, max_length=40)
    batch_number: str | None = Field(default=None, max_length=100)
    quantity: float | None = Field(default=None, ge=0)
    quantity_unit: str | None = None
    net_weight_kg: float | None = Field(default=None, ge=0)
    gross_weight_kg: float | None = Field(default=None, ge=0)
    tare_weight_kg: float | None = Field(default=None, ge=0)
    received_quantity_kg: float | None = Field(default=None, ge=0)
    processing_input_kg: float | None = Field(default=None, ge=0)
    recovered_quantity_kg: float | None = Field(default=None, ge=0)
    residual_quantity_kg: float | None = Field(default=None, ge=0)
    date: str | None = Field(default=None, max_length=50)
    dispatch_date: str | None = Field(default=None, max_length=50)
    arrival_date: str | None = Field(default=None, max_length=50)
    material_type: str | None = Field(default=None, max_length=200)
    origin: str | None = Field(default=None, max_length=250)
    destination: str | None = Field(default=None, max_length=250)


class DocumentExtractor(Protocol):
    def extract(self, *, filename: str, content_type: str, content: bytes,
                supplied_data: dict | None = None) -> dict | None: ...


class LocalStructuredDocumentExtractor:
    """Extract embedded PDF text, optionally OCR scans, then parse labeled lines."""
    VERSION = "local-label-parser-v2"
    MAX_PAGES = 30
    MAX_OCR_SECONDS = 20
    LABELS = {
        "certificate_id": r"certificate\s*(?:id|no\.?|number)",
        "invoice_id": r"invoice\s*(?:id|no\.?|number)",
        "document_number": r"(?:document|receipt|transport)\s*(?:id|no\.?|number|ref(?:erence)?)",
        "claim_reference": r"claim\s*(?:id|ref(?:erence)?|no\.?|number)",
        "producer": r"producer|sender", "recycler": r"recycler|recipient",
        "transporter": r"transporter|carrier", "facility": r"facility",
        "vehicle_registration": r"vehicle\s*(?:registration|reg(?:istration)?\s*no|number)",
        "batch_number": r"(?:processing\s*)?batch\s*(?:id|no\.?|number|ref(?:erence)?)",
        "quantity": r"(?:declared\s*)?quantity|weight",
        "net_weight_kg": r"net\s*(?:weight)?", "gross_weight_kg": r"gross\s*(?:weight)?",
        "tare_weight_kg": r"tare\s*(?:weight)?", "received_quantity_kg": r"received\s*(?:quantity|weight)",
        "processing_input_kg": r"processing\s*input", "recovered_quantity_kg": r"recovered\s*(?:quantity|weight|total)",
        "residual_quantity_kg": r"residual\s*(?:waste\s*)?(?:quantity|weight|total)",
        "date": r"(?:collection\s*|issue\s*|receipt\s*|processing\s*)?date",
        "dispatch_date": r"dispatch\s*date", "arrival_date": r"arrival\s*date",
        "material_type": r"material\s*type|material|waste\s*category",
        "origin": r"origin|from", "destination": r"destination|to",
    }

    def _read_pdf(self, content: bytes) -> list[str]:
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content), strict=True)
            if len(reader.pages) > self.MAX_PAGES:
                raise ValueError(f"PDF exceeds the {self.MAX_PAGES}-page extraction limit")
            return [page.extract_text() or "" for page in reader.pages]
        except ImportError:
            # Extraction remains unavailable in minimal local installs, but the
            # upload itself is still retained and any explicitly supplied data
            # remains separately labeled as uploader-provided.
            return []
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"PDF could not be read: {type(exc).__name__}") from exc

    def _ocr(self, content: bytes, content_type: str) -> list[str]:
        if os.getenv("EVIDENCE_OCR_ENABLED", "false").lower() not in {"1", "true", "yes"}:
            return []
        try:
            import io
            import pytesseract
            from PIL import Image
            if content_type == "application/pdf":
                from pdf2image import convert_from_bytes
                pages = convert_from_bytes(content, first_page=1, last_page=self.MAX_PAGES,
                                           timeout=self.MAX_OCR_SECONDS)
            else:
                pages = [Image.open(io.BytesIO(content))]
            if len(pages) > self.MAX_PAGES:
                raise ValueError(f"Document exceeds the {self.MAX_PAGES}-page OCR limit")
            return [pytesseract.image_to_string(page, timeout=self.MAX_OCR_SECONDS) for page in pages]
        except ImportError as exc:
            raise ValueError("OCR is enabled but Pillow, pytesseract, or pdf2image is unavailable") from exc
        except Exception as exc:
            raise ValueError(f"OCR failed: {type(exc).__name__}") from exc

    @staticmethod
    def _quantity(raw: str) -> tuple[float | None, str | None]:
        unit_match = re.search(r"\b(kg|kgs|kilograms?|tonnes?|tons?)\b", raw, re.I)
        unit = unit_match.group(1).lower() if unit_match else None
        # A comma followed by one or two digits may be a decimal separator.
        # Leave it unresolved instead of silently treating it as grouping.
        if re.search(r"\d+,\d{1,2}(?:\s|$)", raw):
            return None, unit
        # Commas are accepted only in an unambiguous grouped integer (1,234).
        candidate = re.search(r"(?<!\w)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\w)", raw)
        if not candidate:
            return None, unit
        number = float(candidate.group(1).replace(",", ""))
        if unit in {"tonne", "tonnes"}:
            unit = "tonnes"
        elif unit in {"kg", "kgs", "kilogram", "kilograms"}:
            unit = "kg"
        elif unit in {"ton", "tons"}:
            # “Ton” varies by document and region; do not guess a conversion.
            unit = None
        return number, unit

    def extract(self, *, filename: str, content_type: str, content: bytes,
                supplied_data: dict | None = None) -> dict | None:
        if not content or len(content) > 10 * 1024 * 1024:
            raise ValueError("Document is empty or exceeds the extraction size limit")
        extraction_reason = None
        if content_type == "application/pdf":
            method = "PDF_TEXT"
            try:
                pages = self._read_pdf(content)
            except ValueError as exc:
                pages = []
                extraction_reason = str(exc)
            if not any(len(p.strip()) > 30 for p in pages):
                try:
                    ocr_pages = self._ocr(content, content_type)
                    if ocr_pages:
                        pages, method = ocr_pages, "LOCAL_OCR"
                        extraction_reason = None
                except ValueError as exc:
                    extraction_reason = str(exc)
        elif content_type in {"image/jpeg", "image/png", "image/webp"}:
            pages, method = [], "LOCAL_OCR"
            pages = self._ocr(content, content_type)
        else:
            raise ValueError("Unsupported document content type")

        text_pages = [page for page in pages if page.strip()]
        parsed: dict = {}
        field_sources: dict[str, str] = {}
        field_details: dict[str, dict] = {}
        ambiguous_fields: list[str] = []
        for page_number, page in enumerate(pages, 1):
            for field, label in self.LABELS.items():
                if field in parsed:
                    continue
                match = re.search(rf"(?im)^\s*(?:{label})\s*[:=#-]\s*([^\r\n]+)", page)
                if not match:
                    continue
                original = match.group(1).strip().rstrip(";,")
                if field in {"quantity", "net_weight_kg", "gross_weight_kg", "tare_weight_kg",
                             "received_quantity_kg", "processing_input_kg", "recovered_quantity_kg",
                             "residual_quantity_kg"}:
                    number, unit = self._quantity(original)
                    if number is None:
                        continue
                    if field != "quantity" and unit == "tonnes":
                        number *= 1000
                    parsed[field] = number
                    if field == "quantity":
                        parsed["quantity_unit"] = unit
                    if unit is None:
                            ambiguous_fields.append("quantity")
                else:
                    parsed[field] = original
                field_sources[field] = method
                field_details[field] = {"original_text": original, "page": page_number,
                    "location": {"line": page[:match.start()].count("\n") + 1},
                    "method": method, "confidence": 0.92 if method == "PDF_TEXT" else 0.72}

        supplied = dict(supplied_data or {})
        try:
            validated_supplied = StructuredDocumentData.model_validate(supplied).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        # Explicit uploader metadata remains supported for backward compatibility,
        # but its provenance is kept distinct and it cannot confer authenticity.
        for key, value in validated_supplied.items():
            if key not in parsed:
                parsed[key] = value
                field_sources[key] = "UPLOADER_PROVIDED"
                field_details[key] = {"original_text": str(value), "page": None, "location": None,
                    "method": "UPLOADER_PROVIDED", "confidence": None}
        if parsed.get("certificate_id") and not parsed.get("document_type"):
            parsed["document_type"] = "CERTIFICATE"
        elif parsed.get("invoice_id") and not parsed.get("document_type"):
            parsed["document_type"] = "INVOICE"
        data = StructuredDocumentData.model_validate(parsed).model_dump(exclude_none=True)
        if extraction_reason:
            extraction_status = "FAILED"
        elif text_pages:
            extraction_status = "COMPLETED" if len(data) >= 3 else "PARTIAL"
        elif field_sources and all(source == "UPLOADER_PROVIDED" for source in field_sources.values()):
            extraction_status = "MANUAL_REVIEW"
            extraction_reason = "No embedded text was extracted; supplied metadata is unverified."
        else:
            extraction_status = "MANUAL_REVIEW"
            extraction_reason = "No readable embedded text was found; scanned evidence requires manual review or configured OCR."
        data["_provenance"] = {
            "method": method if field_sources else "NONE", "extractor_version": self.VERSION,
            "processed_at": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(content).hexdigest(),
            "page_count": len(pages), "extraction_status": extraction_status,
            "extraction_reason": extraction_reason,
            "authenticity_status": "NOT_VERIFIED", "field_sources": field_sources,
            "field_details": field_details, "ambiguous_fields": ambiguous_fields,
            "text_pages": len(text_pages),
        }
        return data


def get_document_extractor() -> DocumentExtractor:
    return LocalStructuredDocumentExtractor()
