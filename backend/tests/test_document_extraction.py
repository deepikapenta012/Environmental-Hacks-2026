from app.services.document_extraction import LocalStructuredDocumentExtractor
from app.verification.rules import check_document_consistency


def _text_pdf(lines: list[str]) -> bytes:
    """Build a small valid PDF with embedded text, without mocking the reader."""
    commands = ["BT", "/F1 12 Tf", "50 760 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -18 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(pdf)


def test_extracts_fields_from_real_text_pdf():
    pdf = _text_pdf([
        "Claim Reference: EWC-2026-00123",
        "Producer: Green Devices Ltd",
        "Recycler: Circular Works",
        "Facility: Bengaluru Plant",
        "Material: WEEE",
        "Quantity: 2.5 tonnes",
        "Date: 2026-09-10",
        "Vehicle Registration: KA01AB1234",
        "Transport Reference: TR-98",
    ])
    result = LocalStructuredDocumentExtractor().extract(
        filename="receipt.pdf", content_type="application/pdf", content=pdf
    )
    assert result is not None
    assert result["claim_reference"] == "EWC-2026-00123"
    assert result["producer"] == "Green Devices Ltd"
    assert result["recycler"] == "Circular Works"
    assert result["facility"] == "Bengaluru Plant"
    assert result["material_type"] == "WEEE"
    assert result["quantity"] == 2.5
    assert result["quantity_unit"] == "tonnes"
    assert result["vehicle_registration"] == "KA01AB1234"
    assert result["document_number"] == "TR-98"
    assert result["_provenance"]["field_details"]["producer"]["page"] == 1
    assert result["_provenance"]["authenticity_status"] == "NOT_VERIFIED"


def test_extracts_labeled_fields_with_location_and_keeps_authenticity_unverified(monkeypatch):
    extractor = LocalStructuredDocumentExtractor()
    monkeypatch.setattr(extractor, "_read_pdf", lambda _content: [
        "Receipt No: R-14\nNet weight: 2.5 tonnes\nProducer: Green Devices Ltd\n"
    ])
    result = extractor.extract(filename="receipt.pdf", content_type="application/pdf",
                               content=b"%PDF-fake")
    assert result["document_number"] == "R-14"
    assert result["net_weight_kg"] == 2500
    assert result["_provenance"]["authenticity_status"] == "NOT_VERIFIED"
    assert result["_provenance"]["field_details"]["net_weight_kg"]["page"] == 1
    assert result["_provenance"]["field_details"]["net_weight_kg"]["original_text"] == "2.5 tonnes"


def test_quantity_without_unit_remains_unitless(monkeypatch):
    extractor = LocalStructuredDocumentExtractor()
    monkeypatch.setattr(extractor, "_read_pdf", lambda _content: ["Quantity: 2500\n"])
    result = extractor.extract(filename="receipt.pdf", content_type="application/pdf",
                               content=b"%PDF-fake")
    assert result["quantity"] == 2500
    assert result.get("quantity_unit") is None


def test_ambiguous_decimal_comma_is_not_parsed_as_a_weight(monkeypatch):
    extractor = LocalStructuredDocumentExtractor()
    monkeypatch.setattr(extractor, "_read_pdf", lambda _content: ["Quantity: 2,5 kg\n"])
    result = extractor.extract(filename="receipt.pdf", content_type="application/pdf",
                               content=b"%PDF-fake")
    assert result is None or "quantity" not in result


def test_blank_image_without_ocr_enabled_reports_manual_review(monkeypatch):
    monkeypatch.delenv("EVIDENCE_OCR_ENABLED", raising=False)
    result = LocalStructuredDocumentExtractor().extract(
        filename="scan.png", content_type="image/png", content=b"\x89PNG\r\n\x1a\nimage"
    )
    assert result is not None
    assert result["_provenance"]["extraction_status"] == "MANUAL_REVIEW"
    assert "manual review" in result["_provenance"]["extraction_reason"]


def _document_flags(quantity, unit):
    return check_document_consistency(
        {"producer_name": "Green Devices", "recycler_name": "Circular Works",
         "declared_weight_kg": 2500, "received_weight_kg": None,
         "collection_date": "2026-09-10", "waste_category": "WEEE"},
        [{"id": "evidence-1", "status": "ACTIVE", "source": "PRODUCER",
          "extracted_data": {"quantity": quantity, "quantity_unit": unit}}],
        [], quantity_tolerance_pct=5, date_tolerance_days=0,
        mismatch_risk_contribution=15, duplicate_identifier_risk_contribution=10,
    )


def test_document_quantity_comparison_requires_recognized_unit_and_converts_tonnes():
    assert not any(flag.code == "DOC_QUANTITY_MISMATCH" for flag in _document_flags(2.5, "tonnes"))
    flags = _document_flags(2500, None)
    assert any(flag.code == "DOC_QUANTITY_UNIT_REVIEW" and flag.score_delta == 0 for flag in flags)
    assert not any(flag.code == "DOC_QUANTITY_MISMATCH" for flag in flags)


def test_generic_ton_unit_is_not_assumed_to_be_metric():
    parsed, unit = LocalStructuredDocumentExtractor._quantity("2 tons")
    assert parsed == 2
    assert unit is None
