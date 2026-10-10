# Verification rules and risk scoring

The implemented engine is deterministic and rule based. It does not run OCR, image recognition, graph analysis, external authorization checks, or ML. `check_photo_duplicate` is a standalone helper and is not called by the claim verification pipeline. The `image_score`, `graph_score`, and `ml_anomaly_score` values therefore remain unavailable (`null`).

The government-only `GET /api/v1/claims/verification/rules` endpoint returns the active rule catalog, rule set version, and configured risk bands. Rule weights, score-group caps, tolerances, and band boundaries are environment settings. Only administrators controlling the service configuration can change them; they are not writable by claim users.

## Implemented rule catalog

All weights below are default base contributions. `RISK_RULE_WEIGHTS_JSON` can override individual rule IDs. Group caps apply after individual weights. A score is a review-priority measure, not a fraud probability or an approval decision.

| Rule ID | Condition | Severity and default points | Rationale and review action |
|---|---|---:|---|
| MB-001 | Processed output exceeds positive recycler receipt | Critical, 18 | Output cannot exceed recorded input; inspect receipt, process records, and units. |
| MB-002 | Declared and received weights differ beyond `MASS_BALANCE_TOLERANCE_PCT`; critical at 20%+, warning below 20%; otherwise informational | 12 or 18; 0 in tolerance | Reconcile producer and recycler weighbridge records. |
| MB-003 | Recovered material plus residual differs from positive processed output beyond the configured tolerance; critical at 20%+, warning below | 18 | Review process records, rounding, units, and residual handling. |
| MB-004 | Measurements required for the current stage are absent or non-positive | Informational, 0 | Completeness request only; missing data alone adds no risk points. |
| GEO-001 | Arrival time is at or before dispatch time | Critical, 25 | Confirm timestamps against transport records. |
| GEO-002 | Timestamps cannot be parsed | Warning, 8 | Correct the recorded times; parsing failure is not evidence of fabrication. |
| GEO-003 | Great-circle distance divided by duration exceeds `MAX_HGV_SPEED_KMH` | Critical, 22 | Check location accuracy, route, and time records; straight-line distance can understate road distance. |
| EVD-001 | Evidence record claim ownership is inconsistent | Critical, 30 | Check registry linkage. The current pipeline passes claim-owned evidence to this check, so ordinary runs do not currently trigger it. |
| EVD-002 | Exact SHA-256 match is found among evidence in the current user's authorized scope | Warning, 15 per extra matching record | Byte equality indicates reuse; compare purpose and linked records before action. |
| EVIDENCE-COMPLETENESS | Evidence required by the recorded workflow stage is absent | Informational, 0 | Request the stage record. It does not increase score. |
| CLM-001 | Similarity to an earlier claim reaches `DUPLICATE_CLAIM_SIMILARITY_THRESHOLD_PCT` using multiple fields | Warning, 30 default | Compare referenced claim and matched fields. Historical comparisons are limited to claims visible to the evaluating actor. |
| EV-REPL-001 | A pending replacement exists after review started | Warning, 8 | Review prior/current versions and replacement rationale. |
| EV-REPL-002 | A logical evidence document has at least three versions | Warning, 5 | Inspect version history and reasons. |
| EV-DUP-001 | Same active hash is present under multiple logical documents on the claim | Informational, 3 | Confirm repeated attachment is intentional. |
| DOC-ENTITY_MISMATCH | Parsed/supplied producer or recycler differs from claim | Warning, 12 | Compare source file with structured claim. |
| DOC-QUANTITY_MISMATCH | Parsed/supplied quantity exceeds `DOCUMENT_QUANTITY_TOLERANCE_PCT` from the corresponding claim measurement | Warning, 12 | Confirm the measurement and its unit in the source document. |
| DOC-DATE_MISMATCH | Parsed/supplied date differs beyond `DOCUMENT_DATE_TOLERANCE_DAYS` | Warning, 12 | Confirm which workflow date the record represents. |
| DOC-MATERIAL_MISMATCH | Parsed/supplied material differs from claim category | Warning, 12 | Compare document description and claim category. |
| DOC-CERTIFICATE_INVOICE_MISMATCH | Certificate and invoice fields conflict | Warning, 12 | Compare both source documents and identifiers. |
| DOC-EVIDENCE_CONFLICT | Two evidence records disagree on extracted/supplied fields | Warning, 12 | Compare original files and applicable workflow stages. |
| DUPLICATE_DOCUMENT_IDENTIFIER | A normalized invoice/certificate identifier recurs in accessible evidence | Warning, 28 default | Verify original documents and related claims. |

Document fields may originate from uploader-entered structured metadata or local extraction. Agreement is a consistency check, not proof of authenticity. The current flag payload does not yet preserve a per-field provenance/confidence classification; reviewers should treat these findings as leads and inspect files.

## Scoring formula

1. Start with each active flag's base contribution, or its rule-specific configured weight.
2. Sum contributions within the rule's catalog group, stopping at that group's configured cap. Defaults: mass balance 30, transport 30, document consistency 30, evidence integrity 30, duplicate 35, completeness 0. Uncatalogued rules get their own group and remain visible for catalog review.
3. Sum capped group contributions and clamp the final score to 0–100.
4. Default bands: 0–25 Low, 26–50 Medium, 51–75 High, 76–100 Critical.

Severity remains a per-finding description; configured points and the score band are separate values. Informational absence findings contribute zero. No probabilistic confidence is generated. The score does not itself change claim approval/rejection status.

## Identity, lifecycle, and history

Each detected finding gets a deterministic ID based on claim, rule, code, related claims, evidence IDs, and related operational record IDs. Rerunning unchanged data reuses that ID and original detection time. Findings no longer detected remain in `verification_result.flags` as `RESOLVED` with an automatic resolution timestamp/reason; if the same signature returns, it becomes active again. An authorized officer can dismiss an active finding through `POST /api/v1/claims/{claim_id}/flags/{flag_id}/dismiss`, with a required rationale. The backend enforces the officer's claim jurisdiction, records actor and reason in the append-only audit log, and excludes dismissed findings from the current score. Score snapshots (including finding explanations and observed values) are appended to `explainability.score_history` when the active finding set or score changes. Verification audit events are written only when that state changes, preventing repeated-run audit noise.

The persisted `verification_results` row remains an upsert per claim, so score snapshots are retained in its JSON history rather than a separate immutable table. Older records without IDs are upgraded on the next verification run; their earlier snapshots cannot be reconstructed.

## Scenario coverage

| Scenario family | Existing/new automated coverage | Current limitations |
|---|---|---|
| Normal reconciliation, tolerance, partial workflow | Existing core mass-balance and stage-evidence tests | Facility-specific recovery baselines are unavailable. |
| Mass-balance excess and unexplained difference | Existing mass-balance tests; new group-cap and missing-data tests | Input quantities are recorded at claim/receipt level; batch-specific input allocations are not modeled. |
| Transport speed and invalid ordering | Existing transit-speed test | Cross-claim vehicle overlap scheduling is not implemented. |
| Evidence hashes and document consistency | Existing duplicate hash and evidence extraction tests | No OCR/image verification; uploader metadata is not authenticated. |
| Historical similarity | Existing duplicate-claim checks; comparison now actor-scoped | No sample-size calibrated facility trend/baseline model. Similarity may need local threshold calibration. |
| Repeated verification and correction | New stable-ID, no-audit-noise, resolved finding, score-history, and officer dismissal tests | Score snapshots are stored in the verification row's JSON history, not a separate immutable table. |
| Access control | Existing API security and jurisdiction tests | Historical comparisons only use the records visible to the current evaluator. |

## Calibration guidance

Review scores against adjudicated outcomes and independently verified measurements. Use jurisdiction-specific minimum sample sizes, document source quality, and separately track false positives and missed findings. Do not tune weights against unreviewed flags or treat high-volume facilities as inherently risky. Revisit thresholds after representative verified outcomes are available.
