"""Canonical serialization and verification helpers for audit-event chains."""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from datetime import datetime, timezone

request_correlation_id: ContextVar[str | None] = ContextVar("request_correlation_id", default=None)


def canonical_event_payload(values: dict) -> bytes:
    return json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def calculate_event_hash(values: dict) -> str:
    return hashlib.sha256(canonical_event_payload(values)).hexdigest()


def event_hash_fields(event) -> dict:
    occurred_at = None
    if isinstance(event.occurred_at, datetime):
        timestamp = event.occurred_at
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        occurred_at = timestamp.isoformat()
    return {
        "id": event.id,
        "claim_id": event.claim_id,
        "sequence_no": event.sequence_no,
        "entity_type": event.entity_type,
        "related_entity_id": event.related_entity_id,
        "actor_user_id": event.actor_user_id,
        "actor_role": event.actor_role,
        "actor_display_name": event.actor_display_name,
        "action_type": event.action_type,
        "occurred_at": occurred_at,
        "previous_values": event.previous_values,
        "new_values": event.new_values,
        "reason": event.reason,
        "related_flag_id": event.related_flag_id,
        "related_adjustment_id": event.related_adjustment_id,
        "request_correlation_id": event.request_correlation_id,
        "legacy_event": event.legacy_event,
        "legacy_source_key": event.legacy_source_key,
        "legacy_payload": event.legacy_payload,
        "previous_hash": event.previous_hash,
    }


def verify_event_chain_diagnostics(events) -> dict:
    previous_hash = ""
    expected_sequence = 1
    for event in events:
        if event.sequence_no != expected_sequence:
            return {"valid": False, "first_invalid_sequence": event.sequence_no,
                    "event_id": event.id, "reason": f"Expected sequence {expected_sequence}."}
        if event.previous_hash != previous_hash:
            return {"valid": False, "first_invalid_sequence": event.sequence_no,
                    "event_id": event.id, "reason": "Previous-hash link does not match the preceding event."}
        if calculate_event_hash(event_hash_fields(event)) != event.event_hash:
            return {"valid": False, "first_invalid_sequence": event.sequence_no,
                    "event_id": event.id, "reason": "Event hash does not match its stored fields."}
        previous_hash = event.event_hash
        expected_sequence += 1
    return {"valid": True, "first_invalid_sequence": None, "event_id": None, "reason": None}


def verify_event_chain(events) -> bool:
    return verify_event_chain_diagnostics(events)["valid"]
