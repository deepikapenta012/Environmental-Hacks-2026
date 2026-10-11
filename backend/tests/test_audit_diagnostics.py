from types import SimpleNamespace

from app.services.audit import calculate_event_hash, event_hash_fields, verify_event_chain_diagnostics


def _event(sequence: int, previous_hash: str):
    event = SimpleNamespace(
        id=f"event-{sequence}", claim_id="claim-1", sequence_no=sequence,
        entity_type="CLAIM", related_entity_id=None, actor_user_id=None,
        actor_role=None, actor_display_name=None, action_type="CREATED",
        occurred_at=None, previous_values=None, new_values={"status": "PENDING"},
        reason=None, related_flag_id=None, related_adjustment_id=None,
        request_correlation_id=None, legacy_event=False, legacy_source_key=None,
        legacy_payload=None, previous_hash=previous_hash, event_hash="",
    )
    event.event_hash = calculate_event_hash(event_hash_fields(event))
    return event


def test_audit_diagnostics_identify_first_invalid_hash_event():
    first = _event(1, "")
    second = _event(2, first.event_hash)
    valid = verify_event_chain_diagnostics([first, second])
    assert valid["valid"] is True

    second.action_type = "ALTERED"
    invalid = verify_event_chain_diagnostics([first, second])
    assert invalid == {
        "valid": False,
        "first_invalid_sequence": 2,
        "event_id": "event-2",
        "reason": "Event hash does not match its stored fields.",
    }


def test_audit_diagnostics_report_sequence_gap():
    invalid = verify_event_chain_diagnostics([_event(2, "")])
    assert invalid["valid"] is False
    assert invalid["first_invalid_sequence"] == 2
    assert invalid["reason"] == "Expected sequence 1."
