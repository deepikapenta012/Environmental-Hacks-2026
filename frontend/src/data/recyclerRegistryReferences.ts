/**
 * Public e-waste recycler references for administrator review.
 * These are not active local facility records and must not be used to assign claims
 * until an administrator verifies current authorization and permitted categories.
 *
 * Sources:
 * - Odisha SPCB, CPCB-registered recycler list (Nov 2025):
 *   https://ospcboard.odisha.gov.in/wp-content/uploads/2025/11/empanelled-list-of-e-waste-recyclers-registered-with-CPCB.pdf
 * - West Bengal PCB, CPCB-approved recyclers and authorization validity:
 *   https://www.wbpcb.gov.in/files/Fr-04-2024-04-11-44list%20of%20E%20Waste%20recyclers.pdf
 */
export const RECYCLER_REGISTRY_REFERENCES = [
  { recyclerId: '7632', name: 'WB E-Waste Control Management Pvt. Ltd.', address: 'Maheshrekha, Kulgachia, Howrah, West Bengal', authorizationValidThrough: '2028-01-31' },
  { recyclerId: '5736', name: 'J. S. Pigments Pvt. Ltd.', address: 'Jarura, Polba, Hooghly, West Bengal', authorizationValidThrough: '2028-04-30' },
  { recyclerId: '258', name: 'Hindusthan Recycling', address: 'Madhuban, Purulia, West Bengal', authorizationValidThrough: '2027-05-31' },
] as const;
