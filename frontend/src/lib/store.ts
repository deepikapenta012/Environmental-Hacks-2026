import type { RecyclingClaim } from '@/types';

// Single in-memory store shared across both personas.
// Starts empty — every claim is user-submitted.
let claims: RecyclingClaim[] = [];

export function getClaims(): RecyclingClaim[] {
  return [...claims];
}

export function getClaimById(id: string): RecyclingClaim | undefined {
  return claims.find((c) => c.id === id);
}

export function addClaim(claim: RecyclingClaim): void {
  claims = [claim, ...claims];
}

export function updateClaim(id: string, patch: Partial<RecyclingClaim>): void {
  claims = claims.map((c) => (c.id === id ? { ...c, ...patch } : c));
}

// Only the government official may call these two actions.
export function approveClaim(id: string, officialName: string): void {
  claims = claims.map((c) =>
    c.id === id
      ? {
          ...c,
          status: 'VERIFIED',
          updated_at: new Date().toISOString(),
          notes: `${c.notes ? c.notes + '\n' : ''}Approved by ${officialName} on ${new Date().toLocaleString()}.`,
        }
      : c
  );
}

export function rejectClaim(id: string, officialName: string, reason: string): void {
  claims = claims.map((c) =>
    c.id === id
      ? {
          ...c,
          status: 'REJECTED',
          updated_at: new Date().toISOString(),
          notes: `${c.notes ? c.notes + '\n' : ''}Rejected by ${officialName} on ${new Date().toLocaleString()}. Reason: ${reason}`,
        }
      : c
  );
}

export function clearClaims(): void {
  claims = [];
}
