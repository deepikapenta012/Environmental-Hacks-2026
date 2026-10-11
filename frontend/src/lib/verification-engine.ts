import type { RecyclingClaim, VerificationResult, VerificationFlag } from '@/types';

const MAX_HGV_SPEED_KMH = 90;
const MASS_BALANCE_TOLERANCE_PCT = 5;

function haversine(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) *
      Math.sin(dLng / 2);
  return 2 * R * Math.asin(Math.sqrt(a));
}

export function runVerification(claim: RecyclingClaim): VerificationResult {
  const flags: VerificationFlag[] = [];
  const { mass_balance, transport } = claim;
  const startTime = Date.now();

  // Rule MB-001: Output exceeds input
  if (
    mass_balance.processed_output_kg !== null &&
    mass_balance.received_input_kg !== null &&
    mass_balance.processed_output_kg > 0 &&
    mass_balance.processed_output_kg > mass_balance.received_input_kg
  ) {
    const excess =
      ((mass_balance.processed_output_kg - mass_balance.received_input_kg) /
        mass_balance.received_input_kg) *
      100;
    flags.push({
      code: 'MB_OUTPUT_EXCEEDS_INPUT',
      layer: 'MASS_BALANCE',
      severity: 'CRITICAL',
      description: `Output (${mass_balance.processed_output_kg.toFixed(0)} kg) exceeds recycler received input (${mass_balance.received_input_kg.toFixed(0)} kg) by ${excess.toFixed(1)}%. Physical matter cannot increase.`,
      evidence_ids: [],
      rule_reference: 'MB-001',
    });
  }

  // Rule MB-002: Transport shortfall
  if (mass_balance.received_input_kg !== null && mass_balance.received_input_kg > 0) {
    const shortfall =
      ((mass_balance.declared_input_kg - mass_balance.received_input_kg) /
        mass_balance.declared_input_kg) *
      100;
    if (shortfall > MASS_BALANCE_TOLERANCE_PCT) {
      flags.push({
        code: 'MB_TRANSPORT_SHORTFALL',
        layer: 'MASS_BALANCE',
        severity: shortfall > 20 ? 'CRITICAL' : 'WARNING',
        description: `Declared ${mass_balance.declared_input_kg.toFixed(0)} kg but received ${mass_balance.received_input_kg.toFixed(0)} kg. ${shortfall.toFixed(1)}% unaccounted.`,
        evidence_ids: [],
        rule_reference: 'MB-002',
      });
    }
  }

  // Rule GEO-003: Impossible transit speed
  if (transport.length > 0) {
    const leg = transport[0];
    const distance = haversine(
      leg.origin.lat,
      leg.origin.lng,
      leg.destination.lat,
      leg.destination.lng
    );
    const departed = new Date(leg.departed_at).getTime();
    const arrived = new Date(leg.arrived_at).getTime();
    const durationHours = (arrived - departed) / (1000 * 60 * 60);

    if (durationHours > 0) {
      const avgSpeed = distance / durationHours;
      if (avgSpeed > MAX_HGV_SPEED_KMH) {
        const multiplier = avgSpeed / MAX_HGV_SPEED_KMH;
        flags.push({
          code: 'GEO_IMPOSSIBLE_TRANSIT',
          layer: 'GEOSPATIAL',
          severity: 'CRITICAL',
          description: `Vehicle ${leg.vehicle_registration}: ${distance.toFixed(0)} km in ${durationHours.toFixed(1)}h (avg ${avgSpeed.toFixed(0)} km/h). Exceeds HGV limit by ${multiplier.toFixed(1)}×.`,
          evidence_ids: [],
          rule_reference: 'GEO-003',
        });
      }
    }
  }

  const scoreDeltas = {
    MB_OUTPUT_EXCEEDS_INPUT: 18,
    MB_TRANSPORT_SHORTFALL: 12,
    GEO_IMPOSSIBLE_TRANSIT: 22,
  };

  let totalScore = 0;
  const ruleContributions = flags.map((f) => {
    const delta = scoreDeltas[f.code as keyof typeof scoreDeltas] || 0;
    totalScore += delta;
    return {
      rule_id: f.rule_reference || f.code,
      label: f.code.replace(/_/g, ' ').toLowerCase(),
      score_delta: delta,
      triggered: true,
      details: f.description,
    };
  });

  const risk_score = Math.min(100, Math.max(0, totalScore));
  const discrepancies = flags.filter((flag) => flag.severity !== 'INFO');
  const criticalCount = discrepancies.filter((flag) => flag.severity === 'CRITICAL').length;
  let risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  if (criticalCount > 0) risk_level = 'CRITICAL';
  else if (discrepancies.length === 0) risk_level = 'LOW';
  else if (discrepancies.length <= 2) risk_level = 'MEDIUM';
  else risk_level = 'HIGH';

  return {
    claim_id: claim.id,
    risk_score,
    risk_level,
    flags,
    processing_duration_ms: Date.now() - startTime,
    verified_at: new Date().toISOString(),
    model_version: 'frontend-mvp-v1.0.0',
    explainability: {
      document_score: 0,
      image_score: 0,
      geospatial_score: flags.some((f) => f.layer === 'GEOSPATIAL') ? 22 : 0,
      mass_balance_score: flags.some((f) => f.layer === 'MASS_BALANCE') ? 18 : 0,
      duplicate_score: 0,
      graph_score: 0,
      ml_anomaly_score: 0,
      rule_contributions: ruleContributions,
    },
  };
}
