"""Versioned catalog for deterministic rules currently executed by ChainGuard.

Weights and tolerances stay in settings so operators can tune a release without
changing detector code. This catalog intentionally lists only implemented rules.
"""
from dataclasses import dataclass


RULESET_VERSION = "risk-rules-v3.0.0"


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    name: str
    category: str
    rationale: str
    score_group: str
    reviewer_action: str
    blocking: bool = False
    enabled: bool = True


_DEFINITIONS = [
    ("MB-001", "Processed output exceeds received input", "mass_balance", "Output mass cannot exceed the input recorded by the recycler; check units and weighbridge records.", "MASS_BALANCE", "Compare receipt and processing records."),
    ("MB-002", "Producer and recycler weights differ", "mass_balance", "A material difference between declared and received weight needs reconciliation against calibrated weights.", "MASS_BALANCE", "Review origin and destination weight slips."),
    ("MB-003", "Recovered and residual totals do not reconcile", "mass_balance", "Recovered material plus residual should account for processed output within the configured tolerance.", "MASS_BALANCE", "Review the processing report and recorded units."),
    ("MB-004", "Mass-balance inputs are incomplete", "data_quality", "Missing measurements limit reconciliation and are a completeness issue, not proof of wrongdoing.", "COMPLETENESS", "Request the missing workflow-stage measurements."),
    ("GEO-001", "Arrival precedes departure", "transport", "A non-positive journey duration is inconsistent with the recorded dispatch and arrival times.", "TRANSPORT", "Compare transport records and timestamp sources."),
    ("GEO-002", "Transport timestamps cannot be parsed", "data_quality", "The provided timestamps cannot be compared reliably.", "TRANSPORT", "Confirm and correct the recorded timestamps."),
    ("GEO-003", "Recorded journey speed is implausible", "transport", "The straight-line distance and recorded duration imply an average speed above the configured heavy-vehicle threshold.", "TRANSPORT", "Review route, timestamps, and location accuracy."),
    ("IMG-002", "Image perceptual hash match", "evidence", "A similarity match can indicate reused imagery but requires human review.", "DUPLICATE", "Inspect both original image files."),
    ("EVD-001", "Evidence is associated with a different claim", "evidence", "Evidence ownership metadata does not match its claim relationship.", "EVIDENCE_INTEGRITY", "Check the evidence registry relationship."),
    ("EVD-002", "Exact evidence hash reused", "evidence", "Identical SHA-256 hashes prove byte equality, but legitimate reuse still needs contextual review.", "DUPLICATE", "Compare the referenced records and their purpose."),
    ("EVIDENCE-COMPLETENESS", "Stage evidence is missing", "data_quality", "Required records depend on workflow stage; absence is a completeness reminder only.", "COMPLETENESS", "Request evidence due at the current workflow stage."),
    ("CLM-001", "Claim resembles a prior accessible claim", "historical", "A high similarity across multiple claim fields may indicate a duplicate submission; common parties alone are insufficient.", "DUPLICATE", "Compare the related claim and matched fields."),
    ("EV-REPL-001", "Evidence changed after review began", "evidence", "A replacement after review can affect the basis of the decision.", "EVIDENCE_INTEGRITY", "Review all versions and the replacement reason."),
    ("EV-REPL-002", "Evidence was replaced repeatedly", "evidence", "Repeated document replacement warrants a data-quality check, but is not proof of misconduct.", "EVIDENCE_INTEGRITY", "Review version history and replacement reasons."),
    ("EV-DUP-001", "Active evidence has an identical hash", "evidence", "Identical active files may have been uploaded under multiple categories.", "DUPLICATE", "Confirm whether the repeated attachment is intentional."),
]

for code, title in (
    ("DOC_ENTITY_MISMATCH", "Document party differs from claim"),
    ("DOC_QUANTITY_MISMATCH", "Document quantity differs from claim"),
    ("DOC_DATE_MISMATCH", "Document date differs from claim"),
    ("DOC_MATERIAL_MISMATCH", "Document material differs from claim"),
    ("DOC_CERTIFICATE_INVOICE_MISMATCH", "Certificate and invoice conflict"),
    ("DOC_EVIDENCE_CONFLICT", "Uploaded documents conflict"),
):
    _DEFINITIONS.append((code.replace("DOC_", "DOC-"), title, "evidence", "Extracted or uploader-provided fields disagree with structured claim data or another uploaded document. A mismatch is a review signal; supplied metadata is not proof of authenticity.", "DOCUMENT_CONSISTENCY", "Compare the source file with the structured claim and related documents."))

for code, title in (
    ("DUPLICATE_DOCUMENT_IDENTIFIER", "Document identifier reused"),
):
    _DEFINITIONS.append((code, title, "evidence", "A normalized invoice or certificate identifier appears in multiple evidence records.", "DUPLICATE", "Check the original documents and related claims."))

RULE_CATALOG = {
    code: RuleDefinition(code, name, category, rationale, group, action)
    for code, name, category, rationale, group, action in _DEFINITIONS
}

# Static/base points used when no per-rule override is configured. Dynamic rules
# are documented by string because their point value depends on measured variance.
DEFAULT_RULE_WEIGHTS: dict[str, int | None] = {
    "MB-001": 18, "MB-002": None, "MB-003": 18, "MB-004": 0,
    "GEO-001": 25, "GEO-002": 8, "GEO-003": 22,
    "IMG-002": 28, "EVD-001": 30, "EVD-002": 15,
    "EVIDENCE-COMPLETENESS": 0, "CLM-001": 30,
    "EV-REPL-001": 8, "EV-REPL-002": 5, "EV-DUP-001": 3,
    "DOC-ENTITY_MISMATCH": 12, "DOC-QUANTITY_MISMATCH": 12,
    "DOC-DATE_MISMATCH": 12, "DOC-MATERIAL_MISMATCH": 12,
    "DOC-CERTIFICATE_INVOICE_MISMATCH": 12, "DOC-EVIDENCE_CONFLICT": 12,
    "DUPLICATE_DOCUMENT_IDENTIFIER": 28,
}
SCORING_NOTES = {
    "MB-002": "12 points when outside tolerance below 20%; 18 points at 20% or more; 0 within tolerance.",
    "EVD-002": "15 points per additional exact match; capped by the DUPLICATE group limit.",
    "EVIDENCE-COMPLETENESS": "0 points; informational completeness only.",
}
DISABLED_RULES = {"IMG-002", "EVD-001"}
RULE_CATALOG = {
    key: RuleDefinition(**{**value.__dict__, "enabled": key not in DISABLED_RULES})
    for key, value in RULE_CATALOG.items()
}


def get_rule_definition(rule_id: str) -> RuleDefinition | None:
    return RULE_CATALOG.get(rule_id)
