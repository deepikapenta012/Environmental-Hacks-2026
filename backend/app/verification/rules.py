"""Deterministic checks used by the current claim verification pipeline.

Image similarity, graph analytics, and ML scores are not run by this pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import math
import re
import json
from datetime import date, datetime, timezone
from app.verification.catalog import get_rule_definition


SEVERITY = Literal["INFO", "WARNING", "CRITICAL"]
LAYER = Literal["DOCUMENT", "IMAGE", "GEOSPATIAL", "MASS_BALANCE", "DUPLICATE", "GRAPH", "ML"]

# pHash similarity threshold for duplicate detection (0–1)
PHASH_DUPLICATE_THRESHOLD = 0.90


@dataclass
class Flag:
    code: str
    layer: LAYER
    severity: SEVERITY
    description: str
    evidence_ids: list[str] = field(default_factory=list)
    rule_reference: str = ""
    score_delta: int = 0
    actual_values: dict[str, float | None] = field(default_factory=dict)
    expected_relationship: str = ""
    difference_kg: float | None = None
    variance_pct: float | None = None
    related_claim_ids: list[str] = field(default_factory=list)
    matched_fields: list[str] = field(default_factory=list)
    related_record_ids: list[str] = field(default_factory=list)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two GPS points in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def check_mass_balance(
    declared_input_kg: float | None,
    received_input_kg: float | None,
    processed_output_kg: float | None,
    evidence_ids: list[str],
    recovered_materials: list[dict] | None = None,
    residual_waste_kg: float | None = None,
    tolerance_pct: float | None = None,
) -> list[Flag]:
    from app.config import get_settings

    if tolerance_pct is None:
        tolerance_pct = get_settings().mass_balance_tolerance_pct

    flags: list[Flag] = []
    recovered_total = (
        sum(float(item.get("quantity_kg", 0) or 0) for item in recovered_materials)
        if recovered_materials is not None
        else None
    )

    # Rule MB-001: processed output cannot exceed what the recycler received.
    if (
        received_input_kg is not None
        and received_input_kg > 0
        and processed_output_kg is not None
        and processed_output_kg > received_input_kg
    ):
        difference = processed_output_kg - received_input_kg
        excess_pct = difference / received_input_kg * 100
        flags.append(Flag(
            code="MB_VARIANCE_CRITICAL",
            layer="MASS_BALANCE",
            severity="CRITICAL",
            description=(
                f"Processed output ({processed_output_kg:,.1f} kg) exceeds recycler-received input "
                f"({received_input_kg:,.1f} kg) by {difference:,.1f} kg ({excess_pct:.1f}%). "
                "Physical matter cannot increase through processing."
            ),
            evidence_ids=evidence_ids,
            rule_reference="MB-001",
            score_delta=18,
            actual_values={
                "received_input_kg": received_input_kg,
                "processed_output_kg": processed_output_kg,
            },
            expected_relationship="processed_output_kg <= received_input_kg",
            difference_kg=round(difference, 3),
            variance_pct=round(excess_pct, 3),
        ))

    # Rule MB-002: reconcile the producer declaration against recycler receipt.
    if (
        declared_input_kg is not None
        and declared_input_kg > 0
        and received_input_kg is not None
        and received_input_kg > 0
    ):
        difference = declared_input_kg - received_input_kg
        variance_pct = abs(difference) / declared_input_kg * 100
        outside_tolerance = variance_pct > tolerance_pct
        if outside_tolerance:
            flags.append(Flag(
            code="MB_TRANSPORT_SHORTFALL" if difference >= 0 else "MB_RECEIPT_EXCESS",
            layer="MASS_BALANCE",
            severity=("CRITICAL" if variance_pct >= 20 else "WARNING") if outside_tolerance else "INFO",
            description=(
                f"Declared: {declared_input_kg:,.1f} kg. Received: {received_input_kg:,.1f} kg. "
                f"Difference: {abs(difference):,.1f} kg ({variance_pct:.1f}%). "
                f"{('Outside' if outside_tolerance else 'Within')} configured tolerance "
                f"of {tolerance_pct:.1f}%."
            ),
            evidence_ids=evidence_ids,
            rule_reference="MB-002",
            score_delta=12 if variance_pct < 20 else 18,
            actual_values={
                "declared_input_kg": declared_input_kg,
                "received_input_kg": received_input_kg,
                "difference_kg": difference,
                "tolerance_pct": tolerance_pct,
            },
            expected_relationship=(
                f"abs(declared_input_kg - received_input_kg) / declared_input_kg "
                f"<= {tolerance_pct:.1f}%"
            ),
            difference_kg=round(difference, 3),
            variance_pct=round(variance_pct, 3),
            ))

    # Rule MB-003: processed quantity must be accounted for by recovered
    # materials plus residual. Do not calculate this when any measurement is absent.
    if (
        processed_output_kg is not None
        and processed_output_kg > 0
        and recovered_total is not None
        and residual_waste_kg is not None
    ):
        accounted_total = recovered_total + residual_waste_kg
        difference = processed_output_kg - accounted_total
        variance_pct = abs(difference) / processed_output_kg * 100
        if variance_pct > tolerance_pct:
            flags.append(Flag(
                code="MB_OUTPUT_RECONCILIATION",
                layer="MASS_BALANCE",
                severity="CRITICAL" if variance_pct >= 20 else "WARNING",
                description=(
                    f"Processed quantity is {processed_output_kg:,.1f} kg, but recovered "
                    f"materials ({recovered_total:,.1f} kg) plus residual "
                    f"({residual_waste_kg:,.1f} kg) account for {accounted_total:,.1f} kg. "
                    f"Unexplained difference: {difference:,.1f} kg ({variance_pct:.1f}%); "
                    f"tolerance is {tolerance_pct:.1f}%."
                ),
                evidence_ids=evidence_ids,
                rule_reference="MB-003",
                score_delta=18,
                actual_values={
                    "processed_output_kg": processed_output_kg,
                    "recovered_materials_total_kg": recovered_total,
                    "residual_waste_kg": residual_waste_kg,
                    "accounted_total_kg": accounted_total,
                    "tolerance_pct": tolerance_pct,
                },
                expected_relationship=(
                    "recovered_materials_total_kg + residual_waste_kg "
                    "~= processed_output_kg"
                ),
                difference_kg=round(difference, 3),
                variance_pct=round(variance_pct, 3),
            ))

    # Rule MB-004: identify missing values needed for the relevant balance.
    missing: list[str] = []
    if declared_input_kg is None or declared_input_kg <= 0:
        missing.append("declared_input_kg")
    if received_input_kg is None or received_input_kg <= 0:
        missing.append("received_input_kg")
    if processed_output_kg is None or processed_output_kg <= 0:
        missing.append("processed_output_kg")
    elif not recovered_materials:
        missing.append("recovered_materials")
    if processed_output_kg is not None and processed_output_kg > 0 and residual_waste_kg is None:
        missing.append("residual_waste_kg")
    if missing:
        actual_values = {
            "declared_input_kg": declared_input_kg,
            "received_input_kg": received_input_kg,
            "processed_output_kg": processed_output_kg,
            "recovered_materials_total_kg": recovered_total,
            "residual_waste_kg": residual_waste_kg,
            "missing_measurements": float(len(missing)),
        }
        flags.append(Flag(
            code="MB_MISSING_MEASUREMENTS",
            layer="MASS_BALANCE",
            severity="INFO",
            description=(
                f"Required mass-balance measurement(s) missing: {', '.join(missing)}. "
                "Provide declared and received weights; once processing is reported, "
                "provide processed output, recovered materials, and residual."
            ),
            evidence_ids=evidence_ids,
            rule_reference="MB-004",
            score_delta=0,
            actual_values=actual_values,
            expected_relationship="all measurements required for the reported processing stage are present",
        ))

    return flags


def check_transport_speed(
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    departed_iso: str, arrived_iso: str,
    vehicle_reg: str,
    evidence_ids: list[str],
    max_speed_kmh: float | None = None,
) -> list[Flag]:
    from datetime import datetime, timezone

    flags: list[Flag] = []
    if max_speed_kmh is None:
        from app.config import get_settings
        max_speed_kmh = get_settings().max_hgv_speed_kmh

    try:
        t_depart = datetime.fromisoformat(departed_iso.replace("Z", "+00:00"))
        t_arrive = datetime.fromisoformat(arrived_iso.replace("Z", "+00:00"))
        duration_hours = (t_arrive - t_depart).total_seconds() / 3600

        if duration_hours <= 0:
            flags.append(Flag(
                code="GEO_NEGATIVE_TRANSIT_TIME",
                layer="GEOSPATIAL",
                severity="CRITICAL",
                description=(
                    f"Vehicle {vehicle_reg}: arrival timestamp precedes departure timestamp. "
                    "Evidence may be fabricated or timestamps manipulated."
                ),
                evidence_ids=evidence_ids,
                rule_reference="GEO-001",
                score_delta=25,
            ))
            return flags

        distance_km = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
        avg_speed = distance_km / duration_hours

        if avg_speed > max_speed_kmh:
            multiplier = avg_speed / max_speed_kmh
            flags.append(Flag(
                code="GEO_IMPOSSIBLE_TRANSIT",
                layer="GEOSPATIAL",
                severity="CRITICAL",
                description=(
                    f"Vehicle {vehicle_reg}: {distance_km:.0f} km route completed in "
                    f"{duration_hours:.1f}h. Average speed {avg_speed:.0f} km/h exceeds "
                    f"configured heavy-vehicle threshold ({max_speed_kmh:.0f} km/h) by {multiplier:.1f}×."
                ),
                evidence_ids=evidence_ids,
                rule_reference="GEO-003",
                score_delta=22,
            ))
    except (ValueError, TypeError):
        flags.append(Flag(
            code="GEO_INVALID_TIMESTAMPS",
            layer="GEOSPATIAL",
            severity="WARNING",
            description=f"Could not parse transport timestamps for vehicle {vehicle_reg}.",
            evidence_ids=evidence_ids,
            rule_reference="GEO-002",
            score_delta=8,
        ))

    return flags


def check_photo_duplicate(
    phash: str,
    match_phash: str,
    claimed_id: str,
    matched_claim_id: str,
    similarity: float,
    evidence_ids: list[str],
    threshold: float | None = None,
) -> list[Flag]:
    if threshold is None:
        from app.config import get_settings
        threshold = get_settings().phash_duplicate_threshold
    flags: list[Flag] = []

    if similarity >= threshold:
        flags.append(Flag(
            code="IMG_DUPLICATE_DETECTED",
            layer="IMAGE",
            severity="CRITICAL",
            description=(
                f"Photo in claim {claimed_id} matches evidence from claim "
                f"{matched_claim_id} with {similarity * 100:.0f}% perceptual hash similarity. "
                "This photo was likely reused across claims."
            ),
            evidence_ids=evidence_ids,
            rule_reference="IMG-002",
            score_delta=28,
        ))

    return flags


def check_evidence_ownership(claim_id: str, evidence_records: list[dict]) -> list[Flag]:
    """Flag evidence rows accidentally included under a different claim."""
    flags = []
    for evidence in evidence_records:
        if evidence["claim_id"] != claim_id:
            flags.append(Flag(
                code="EVIDENCE_CLAIM_MISMATCH",
                layer="DOCUMENT",
                severity="CRITICAL",
                description=(
                    f"Evidence {evidence['id']} is associated with claim "
                    f"{evidence['claim_id']} but was included in claim {claim_id}."
                ),
                evidence_ids=[evidence["id"]],
                rule_reference="EVD-001",
                score_delta=30,
            ))
    return flags


def check_stage_evidence(
    evidence_records: list[dict],
    *,
    receipt_confirmed: bool,
    processing_completed: bool,
) -> list[Flag]:
    """Report missing stage-required documents as informational review flags."""
    present = {
        str(item.get("category", "")) for item in evidence_records
        if item.get("status", "ACTIVE") in {"ACTIVE", "PENDING_REVIEW"}
    }
    required = [
        ("COLLECTION_WEIGHT_SLIP", "Collection / origin weight slip"),
        ("TRANSPORT_CHALLAN", "Transport challan / delivery note"),
    ]
    if receipt_confirmed:
        required.append(("RECYCLER_RECEIPT", "Recycler receipt / destination weight slip"))
    if processing_completed:
        required.append(("PROCESSING_RECOVERY", "Processing and recovery record"))

    return [
        Flag(
            code=f"EVIDENCE_MISSING_{category}",
            layer="DOCUMENT",
            severity="INFO",
            description=f"Required stage evidence is missing: {label}. This is a completeness reminder for review, not a fraud finding.",
            rule_reference="EVIDENCE-COMPLETENESS",
            score_delta=0,
            actual_values={"evidence_count": 0},
            expected_relationship=f"at least one {category} file is linked to this claim",
        )
        for category, label in required
        if category not in present
    ]


def check_duplicate_evidence(claim_id: str, evidence_records: list[dict]) -> list[Flag]:
    """Flag exact SHA-256 matches involving one or more files on this claim."""
    by_hash: dict[str, list[dict]] = {}
    for evidence in evidence_records:
        digest = evidence.get("sha256")
        if digest:
            by_hash.setdefault(digest, []).append(evidence)

    duplicate_groups = [
        (digest, records)
        for digest, records in by_hash.items()
        if len({record["id"] for record in records}) > 1
        and any(record["claim_id"] == claim_id for record in records)
    ]
    if not duplicate_groups:
        return []

    evidence_ids = sorted({record["id"] for _, records in duplicate_groups for record in records})
    duplicate_count = sum(len({record["id"] for record in records}) - 1 for _, records in duplicate_groups)
    hashes = ", ".join(digest[:12] for digest, _ in duplicate_groups)
    return [Flag(
        code="DUPLICATE_SHA256",
        layer="DUPLICATE",
        severity="WARNING",
        description=(
            f"{duplicate_count} exact duplicate evidence file(s) detected by SHA-256 "
            f"({hashes}). Matching evidence IDs are listed below."
        ),
        evidence_ids=evidence_ids,
        rule_reference="EVD-002",
        score_delta=15 * duplicate_count,
    )]


def _normalise_match_value(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _document_identifiers(evidence_files: list[dict]) -> set[str]:
    ignored = {
        "invoice", "certificate", "cert", "manifest", "receipt", "document",
        "evidence", "weight", "slip", "proof", "scan", "photo", "image", "pdf",
    }
    identifiers: set[str] = set()
    for evidence in evidence_files:
        filename = str(evidence.get("filename") or "")
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9/-]{4,}", filename):
            canonical = _normalise_match_value(token)
            if (
                len(canonical) >= 5
                and canonical not in ignored
                and re.search(r"[a-z]", canonical)
                and re.search(r"\d", canonical)
            ):
                identifiers.add(canonical)
    return identifiers


def _temporal_distance_days(first: object, second: object) -> float | None:
    """Parse ISO dates/timestamps and return an absolute elapsed-day distance."""
    def parse(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
            except ValueError:
                parsed = None
                for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
                    try:
                        parsed = datetime.strptime(text, pattern)
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    left, right = parse(first), parse(second)
    if left is None or right is None:
        return None
    return abs((left - right).total_seconds()) / 86400


def check_duplicate_claims(
    current_claim: dict,
    previous_claims: list[dict],
    *,
    similarity_threshold_pct: float,
    quantity_tolerance_pct: float,
    date_window_days: int,
    risk_contribution: int,
) -> list[Flag]:
    """Compare a submitted claim with earlier claims using stable field matches."""
    matches: list[Flag] = []
    weights = {
        "producer identity": 18,
        "recycler identity": 14,
        "waste category": 10,
        "declared quantity": 16,
        "collection date/time": 14,
        "vehicle registration": 10,
        "invoice/certificate identifier": 8,
        "evidence SHA-256": 10,
    }

    current_category = _normalise_match_value(current_claim.get("waste_category"))
    current_quantity = float(current_claim.get("declared_weight_kg") or 0)
    current_vehicles = {
        _normalise_match_value(value)
        for value in current_claim.get("vehicle_registrations", [])
        if _normalise_match_value(value)
    }
    current_identifiers = _document_identifiers(current_claim.get("evidence_files", []))
    current_evidence = {
        item.get("sha256"): item.get("id")
        for item in current_claim.get("evidence_files", [])
        if item.get("sha256")
    }

    for prior in previous_claims:
        if prior.get("id") == current_claim.get("id"):
            continue
        score = 0.0
        matched_fields: list[str] = []

        for party, name in (("producer", "producer identity"), ("recycler", "recycler identity")):
            current_registration = _normalise_match_value(current_claim.get(f"{party}_registration_number"))
            prior_registration = _normalise_match_value(prior.get(f"{party}_registration_number"))
            current_name = _normalise_match_value(current_claim.get(f"{party}_name"))
            prior_name = _normalise_match_value(prior.get(f"{party}_name"))
            if current_registration and current_registration == prior_registration:
                score += weights[name]
                matched_fields.append(f"{party} registration")
            elif current_name and current_name == prior_name:
                score += weights[name] * 0.75
                matched_fields.append(f"{party} name")
        if current_category and current_category == _normalise_match_value(prior.get("waste_category")):
            score += weights["waste category"]
            matched_fields.append("waste category")

        prior_quantity = float(prior.get("declared_weight_kg") or 0)
        quantity_difference_pct = None
        if current_quantity > 0 and prior_quantity > 0:
            quantity_difference_pct = abs(current_quantity - prior_quantity) / max(current_quantity, prior_quantity) * 100
            if quantity_difference_pct <= quantity_tolerance_pct:
                score += weights["declared quantity"]
                matched_fields.append(f"declared quantity within {quantity_tolerance_pct:g}%")

        date_difference_days = _temporal_distance_days(
            current_claim.get("collection_date"), prior.get("collection_date")
        )
        if date_difference_days is None:
            current_departures = current_claim.get("departed_at", [])
            prior_departures = prior.get("departed_at", [])
            distances = [
                distance
                for first in current_departures
                for second in prior_departures
                if (distance := _temporal_distance_days(first, second)) is not None
            ]
            date_difference_days = min(distances) if distances else None
        if date_difference_days is not None and date_difference_days <= max(0, date_window_days):
            score += weights["collection date/time"]
            matched_fields.append(f"collection date/time within {max(0, date_window_days)} days")

        prior_vehicles = {
            _normalise_match_value(value)
            for value in prior.get("vehicle_registrations", [])
            if _normalise_match_value(value)
        }
        if current_vehicles & prior_vehicles:
            score += weights["vehicle registration"]
            matched_fields.append("vehicle registration")

        prior_identifiers = _document_identifiers(prior.get("evidence_files", []))
        if current_identifiers & prior_identifiers:
            score += weights["invoice/certificate identifier"]
            matched_fields.append("invoice/certificate identifier")

        prior_hashes = {
            item.get("sha256")
            for item in prior.get("evidence_files", [])
            if item.get("sha256")
        }
        matching_hashes = set(current_evidence) & prior_hashes
        if matching_hashes:
            score += weights["evidence SHA-256"]
            matched_fields.append("evidence SHA-256")

        if score < similarity_threshold_pct:
            continue

        related_id = str(prior.get("id", ""))
        similarity = round(score, 1)
        matched_evidence_ids = sorted({
            current_evidence[digest]
            for digest in matching_hashes
            if current_evidence.get(digest)
        } | {
            item["id"]
            for item in prior.get("evidence_files", [])
            if item.get("sha256") in matching_hashes and item.get("id")
        })
        matches.append(Flag(
            code="DUPLICATE_CLAIM",
            layer="DUPLICATE",
            severity="CRITICAL" if similarity >= 95 else "WARNING",
            description=(
                f"Claim {current_claim.get('id')} is {similarity:.0f}% similar to previously "
                f"submitted claim {related_id}. Matching fields: {', '.join(matched_fields)}."
            ),
            evidence_ids=matched_evidence_ids,
            rule_reference="CLM-001",
            score_delta=risk_contribution,
            actual_values={
                "similarity_pct": similarity,
                "current_declared_quantity_kg": current_quantity,
                "related_declared_quantity_kg": prior_quantity,
                "quantity_difference_pct": (
                    round(quantity_difference_pct, 3)
                    if quantity_difference_pct is not None else None
                ),
                "date_difference_days": (
                    round(date_difference_days, 3)
                    if date_difference_days is not None else None
                ),
            },
            expected_relationship=(
                f"claim similarity below {similarity_threshold_pct:g}% or not associated "
                "with a previously submitted claim"
            ),
            related_claim_ids=[related_id],
            matched_fields=matched_fields,
        ))
    return matches


def check_document_consistency(
    claim: dict,
    claim_evidence: list[dict],
    other_evidence: list[dict],
    *,
    quantity_tolerance_pct: float,
    date_tolerance_days: int,
    mismatch_risk_contribution: int,
    duplicate_identifier_risk_contribution: int,
) -> list[Flag]:
    """Compare locally extracted document fields with a claim and its evidence."""
    flags: list[Flag] = []
    document_records = [
        item for item in claim_evidence
        if item.get("status", "ACTIVE") in {"ACTIVE", "PENDING_REVIEW"}
        and isinstance(item.get("extracted_data"), dict) and item["extracted_data"]
    ]

    def mismatch_flag(
        code: str,
        description: str,
        evidence_ids: list[str],
        fields: list[str],
        actual_values: dict[str, float | None] | None = None,
        difference_kg: float | None = None,
        variance_pct: float | None = None,
        layer: LAYER = "DOCUMENT",
        risk: int | None = None,
        related_claim_ids: list[str] | None = None,
    ) -> Flag:
        return Flag(
            code=code,
            layer=layer,
            severity="WARNING",
            description=description,
            evidence_ids=evidence_ids,
            rule_reference=code.replace("DOC_", "DOC-"),
            score_delta=mismatch_risk_contribution if risk is None else risk,
            actual_values=actual_values or {},
            expected_relationship="uploaded documents should agree with claim and related evidence",
            difference_kg=difference_kg,
            variance_pct=variance_pct,
            related_claim_ids=related_claim_ids or [],
            matched_fields=fields,
        )

    claim_producer = _normalise_match_value(claim.get("producer_name"))
    claim_recycler = _normalise_match_value(claim.get("recycler_name"))
    producer_quantity = float(claim.get("declared_weight_kg") or 0)
    recycler_quantity = float(claim.get("received_weight_kg") or 0)
    producer_date = str(claim.get("collection_date") or "")
    recycler_date = str(claim.get("processing_date") or claim.get("received_at") or "")[:10]
    claim_material = _normalise_match_value(claim.get("waste_category"))

    for evidence in document_records:
        data = evidence["extracted_data"]
        evidence_id = str(evidence.get("id", ""))
        is_recycler_evidence = evidence.get("source") == "RECYCLER"
        claim_quantity = recycler_quantity if is_recycler_evidence and recycler_quantity > 0 else producer_quantity
        quantity_label = "recycler received quantity" if is_recycler_evidence else "producer declared quantity"
        claim_date = recycler_date if is_recycler_evidence and recycler_date else producer_date
        date_label = "recycler processing/receipt date" if is_recycler_evidence else "producer collection date"
        entity_mismatches: list[str] = []
        for field, claim_value in (("producer", claim_producer), ("recycler", claim_recycler)):
            doc_value = data.get(field)
            if doc_value and claim_value and _normalise_match_value(doc_value) != claim_value:
                entity_mismatches.append(f"document {field} '{doc_value}' does not match claim")
        if entity_mismatches:
            flags.append(mismatch_flag(
                "DOC_ENTITY_MISMATCH",
                f"Evidence {evidence_id}: " + "; ".join(entity_mismatches) + ".",
                [evidence_id], entity_mismatches,
            ))

        doc_quantity = data.get("quantity")
        if doc_quantity is not None and claim_quantity > 0:
            doc_quantity = float(doc_quantity)
            difference = doc_quantity - claim_quantity
            variance = abs(difference) / claim_quantity * 100
            if variance > quantity_tolerance_pct:
                flags.append(mismatch_flag(
                    "DOC_QUANTITY_MISMATCH",
                    f"Evidence {evidence_id} states {doc_quantity:g} kg, while the {quantity_label} is "
                    f"{claim_quantity:g} kg ({variance:.1f}% difference; tolerance "
                    f"{quantity_tolerance_pct:g}%).",
                    [evidence_id], ["document quantity", quantity_label],
                    actual_values={
                        "document_quantity_kg": doc_quantity,
                        "claim_quantity_kg": claim_quantity,
                        "quantity_variance_pct": round(variance, 3),
                    },
                    difference_kg=round(difference, 3),
                    variance_pct=round(variance, 3),
                ))

        doc_date = data.get("date")
        if doc_date and claim_date:
            date_difference = _temporal_distance_days(doc_date, claim_date)
            date_mismatch = (
                date_difference > max(0, date_tolerance_days)
                if date_difference is not None
                else str(doc_date).strip().casefold() != claim_date.strip().casefold()
            )
            if date_mismatch:
                flags.append(mismatch_flag(
                    "DOC_DATE_MISMATCH",
                    f"Evidence {evidence_id} date '{doc_date}' differs from {date_label} "
                    f"'{claim_date}' beyond the {max(0, date_tolerance_days)}-day tolerance.",
                    [evidence_id], ["document date", date_label],
                    actual_values={
                        "date_difference_days": round(date_difference, 3)
                        if date_difference is not None else None,
                        "date_tolerance_days": float(max(0, date_tolerance_days)),
                    },
                ))

        doc_material = data.get("material_type")
        if doc_material and claim_material and _normalise_match_value(doc_material) != claim_material:
            fields = [
                f"document material type '{doc_material}'",
                f"claim category '{claim.get('waste_category')}'",
            ]
            flags.append(mismatch_flag(
                "DOC_MATERIAL_MISMATCH",
                f"Evidence {evidence_id} material '{doc_material}' does not match claim category "
                f"'{claim.get('waste_category')}'.",
                [evidence_id], fields,
            ))

    # Reconcile facts across uploaded documents. A certificate/invoice pair gets
    # its own explicit code; other document pairs use the general evidence code.
    for index, first in enumerate(document_records):
        first_data = first["extracted_data"]
        for second in document_records[index + 1:]:
            second_data = second["extracted_data"]
            conflicts: list[str] = []
            for field in ("producer", "recycler", "material_type"):
                left, right = first_data.get(field), second_data.get(field)
                if left and right and _normalise_match_value(left) != _normalise_match_value(right):
                    conflicts.append(f"{field} differs ('{left}' vs '{right}')")
            left_qty, right_qty = first_data.get("quantity"), second_data.get("quantity")
            quantity_difference = None
            quantity_variance = None
            if left_qty is not None and right_qty is not None:
                left_qty, right_qty = float(left_qty), float(right_qty)
                quantity_difference = left_qty - right_qty
                quantity_variance = abs(quantity_difference) / max(left_qty, right_qty, 1e-9) * 100
                if quantity_variance > quantity_tolerance_pct:
                    conflicts.append(f"quantity differs ({left_qty:g} kg vs {right_qty:g} kg)")
            left_date, right_date = first_data.get("date"), second_data.get("date")
            if left_date and right_date:
                days = _temporal_distance_days(left_date, right_date)
                if (
                    days > max(0, date_tolerance_days)
                    if days is not None
                    else str(left_date).strip().casefold() != str(right_date).strip().casefold()
                ):
                    conflicts.append(f"date differs ('{left_date}' vs '{right_date}')")
            if not conflicts:
                continue

            first_kind = str(first_data.get("document_type") or "").upper()
            second_kind = str(second_data.get("document_type") or "").upper()
            is_certificate_invoice = {first_kind, second_kind} == {"CERTIFICATE", "INVOICE"}
            code = "DOC_CERTIFICATE_INVOICE_MISMATCH" if is_certificate_invoice else "DOC_EVIDENCE_CONFLICT"
            first_identifier = first_data.get("certificate_id") or first_data.get("invoice_id") or first["id"]
            second_identifier = second_data.get("certificate_id") or second_data.get("invoice_id") or second["id"]
            label = "Certificate and invoice" if is_certificate_invoice else "Uploaded documents"
            flags.append(mismatch_flag(
                code,
                f"{label} {first_identifier} and {second_identifier} disagree: "
                + "; ".join(conflicts) + ".",
                [str(first.get("id", "")), str(second.get("id", ""))],
                conflicts,
                actual_values={
                    "first_quantity_kg": float(left_qty) if left_qty is not None else None,
                    "second_quantity_kg": float(right_qty) if right_qty is not None else None,
                    "quantity_variance_pct": round(quantity_variance, 3)
                    if quantity_variance is not None else None,
                },
                difference_kg=round(quantity_difference, 3)
                if quantity_difference is not None else None,
                variance_pct=round(quantity_variance, 3)
                if quantity_variance is not None else None,
            ))

    # Identifiers are namespaced by type and checked across current and previous
    # claims, allowing exact reuse to be found even if file bytes differ.
    all_evidence = [*claim_evidence, *other_evidence]
    identifiers: dict[tuple[str, str], list[dict]] = {}
    current_ids = {str(item.get("id")) for item in claim_evidence}
    for evidence in all_evidence:
        data = evidence.get("extracted_data")
        if not isinstance(data, dict):
            continue
        for field in ("certificate_id", "invoice_id"):
            value = data.get(field)
            canonical = _normalise_match_value(value)
            if canonical:
                identifiers.setdefault((field, canonical), []).append(evidence)

    for (field, identifier), records in identifiers.items():
        evidence_ids = sorted({str(item.get("id")) for item in records if item.get("id")})
        if len(evidence_ids) < 2 or not current_ids.intersection(evidence_ids):
            continue
        related_claim_ids = sorted({
            str(item.get("claim_id"))
            for item in records
            if item.get("claim_id") and str(item.get("claim_id")) != str(claim.get("id"))
        })
        label = "certificate" if field == "certificate_id" else "invoice"
        flags.append(mismatch_flag(
            "DUPLICATE_DOCUMENT_IDENTIFIER",
            f"Duplicate {label} identifier '{identifier}' appears on evidence "
            f"{', '.join(evidence_ids)}.",
            evidence_ids,
            [f"duplicate {label} identifier"],
            actual_values={"matching_document_count": float(len(evidence_ids))},
            layer="DUPLICATE",
            risk=duplicate_identifier_risk_contribution,
            related_claim_ids=related_claim_ids,
        ))

    return flags


def check_evidence_replacements(
    claim_evidence: list[dict],
    *,
    claim_status: str = "",
    has_verification_result: bool = False,
) -> list[Flag]:
    """Flag suspicious evidence replacements or changes after review.

    This rule detects:
    - Evidence replaced after the claim was already reviewed/verified
    - Multiple replacements of the same logical document
    - Duplicate file hashes across replacement versions
    """
    flags: list[Flag] = []

    reviewed_statuses = {"PENDING", "FLAGGED", "APPROVED", "VERIFIED"}
    post_review = claim_status in reviewed_statuses and has_verification_result

    # Group by logical_id to find replacement chains
    logical_groups: dict[str, list[dict]] = {}
    for ev in claim_evidence:
        lid = ev.get("logical_id") or ev.get("id", "")
        logical_groups.setdefault(lid, []).append(ev)

    for logical_id, group in logical_groups.items():
        if len(group) <= 1:
            continue

        # Multiple versions exist
        active = [e for e in group if e.get("status") == "ACTIVE" or e.get("status") == "PENDING_REVIEW"]
        superseded = [e for e in group if e.get("status") == "SUPERSEDED"]

        if not superseded:
            continue

        evidence_ids = [e.get("id", "") for e in group if e.get("id")]

        # Flag: evidence replaced after review
        pending_review = [e for e in group if e.get("status") == "PENDING_REVIEW"]
        if pending_review and post_review:
            flags.append(Flag(
                code="EVIDENCE_REPLACED_AFTER_REVIEW",
                layer="DOCUMENT",
                severity="WARNING",
                description=(
                    f"Evidence document (logical ID {logical_id}) was replaced after "
                    f"the claim entered review status '{claim_status}'. "
                    f"{len(superseded)} previous version(s) exist."
                ),
                evidence_ids=evidence_ids,
                rule_reference="EV-REPL-001",
                score_delta=8,
                actual_values={"replacement_count": len(superseded)},
                expected_relationship="evidence should not change after review without justification",
            ))

        # Flag: excessive replacements (3+ versions)
        if len(group) >= 3:
            flags.append(Flag(
                code="EVIDENCE_EXCESSIVE_REPLACEMENTS",
                layer="DOCUMENT",
                severity="WARNING",
                description=(
                    f"Evidence document (logical ID {logical_id}) has been replaced "
                    f"{len(group) - 1} times. Frequent replacements may indicate data quality issues."
                ),
                evidence_ids=evidence_ids,
                rule_reference="EV-REPL-002",
                score_delta=5,
                actual_values={"version_count": len(group)},
                expected_relationship="evidence should be stable once uploaded",
            ))

    # Check for duplicate hashes across active evidence (same file uploaded under different logical IDs)
    hash_to_ids: dict[str, list[str]] = {}
    for ev in claim_evidence:
        if ev.get("status", "ACTIVE") not in ("ACTIVE", "PENDING_REVIEW"):
            continue
        sha = ev.get("sha256")
        if sha:
            hash_to_ids.setdefault(sha, []).append(ev.get("id", ""))

    for sha, ids in hash_to_ids.items():
        if len(ids) > 1:
            flags.append(Flag(
                code="EVIDENCE_DUPLICATE_HASH_ACTIVE",
                layer="DOCUMENT",
                severity="INFO",
                description=(
                    f"Multiple active evidence documents share the same SHA-256 hash ({sha[:12]}…). "
                    f"The same file may have been uploaded under different categories."
                ),
                evidence_ids=ids,
                rule_reference="EV-DUP-001",
                score_delta=3,
                actual_values={"duplicate_count": len(ids)},
                expected_relationship="each evidence document should be a distinct file",
            ))

    return flags


def score_flags(flags: list[Flag], *, weights: dict[str, int] | None = None,
                group_caps: dict[str, int] | None = None,
                bands: tuple[int, int, int] | None = None) -> tuple[int, str, list[int]]:
    """Return a bounded 0–100 prioritization score and effective per-flag points.

    Contributions from rules in the same catalog group are capped to limit
    inflation from correlated observations (for example, related mass-balance
    checks). Unknown/test rules retain their declared contribution independently.
    The score is not a probability and is never a disposition decision.
    """
    from app.config import get_settings

    settings = get_settings()
    if weights is None:
        try:
            parsed_weights = json.loads(settings.risk_rule_weights_json or "{}")
            weights = parsed_weights if isinstance(parsed_weights, dict) else {}
        except (TypeError, ValueError):
            weights = {}
    if group_caps is None:
        try:
            parsed_caps = json.loads(settings.risk_group_caps_json or "{}")
            group_caps = parsed_caps if isinstance(parsed_caps, dict) else {}
        except (TypeError, ValueError):
            group_caps = {}
    if bands is None:
        bands = (settings.risk_band_low_max, settings.risk_band_medium_max,
                 settings.risk_band_high_max)

    used_by_group: dict[str, int] = {}
    contributions: list[int] = []
    for flag in flags:
        try:
            raw = max(0, int(weights.get(flag.rule_reference, flag.score_delta)))
        except (TypeError, ValueError):
            raw = max(0, int(flag.score_delta))
        definition = get_rule_definition(flag.rule_reference)
        group = definition.score_group if definition else f"UNMAPPED:{flag.rule_reference or flag.code}"
        try:
            cap = max(0, int(group_caps.get(group, 100)))
        except (TypeError, ValueError):
            cap = 100
        applied = min(raw, max(0, cap - used_by_group.get(group, 0)))
        used_by_group[group] = used_by_group.get(group, 0) + applied
        contributions.append(applied)

    score = min(100, sum(contributions))
    low_max, medium_max, high_max = bands
    low_max = min(99, max(0, int(low_max)))
    medium_max = min(99, max(low_max, int(medium_max)))
    high_max = min(100, max(medium_max, int(high_max)))
    if score <= low_max:
        level = "LOW"
    elif score <= medium_max:
        level = "MEDIUM"
    elif score <= high_max:
        level = "HIGH"
    else:
        level = "CRITICAL"
    return score, level, contributions


def compute_risk_score(flags: list[Flag]) -> tuple[int, str]:
    """Compatibility wrapper for the current configured scoring model."""
    score, level, _ = score_flags(flags)
    return score, level

