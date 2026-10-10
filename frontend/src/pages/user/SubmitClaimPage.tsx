import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, AlertCircle, MapPin } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { RiskScore } from '@/components/ui/RiskScore';
import { EvidencePanel } from '@/components/claims/EvidencePanel';
import {
  fetchRecyclerAccounts,
  findLocations,
  submitClaim,
  uploadClaimEvidence,
  type GeocodingResult,
  type RecyclerAccount,
} from '@/lib/api';
import type { RecyclingClaim } from '@/types';
import { useAuth } from '@/lib/auth';
import { RECYCLER_REGISTRY_REFERENCES } from '@/data/recyclerRegistryReferences';

interface Form {
  producer_name: string;
  producer_registration_number: string;
  recycler_name: string;
  recycler_registration_number: string;
  recycler_facility_id: string;
  waste_category: string;
  declared_weight_kg: string;
  collection_date: string;
  vehicle_registration: string;
  driver_name: string;
  origin_address: string;
  origin_lat: string;
  origin_lng: string;
  destination_address: string;
  destination_lat: string;
  destination_lng: string;
  departed_at: string;
  arrived_at: string;
  notes: string;
}

const EMPTY: Form = {
  producer_name: '', producer_registration_number: '',
  recycler_name: '', recycler_registration_number: '', recycler_facility_id: '',
  waste_category: '', declared_weight_kg: '', collection_date: '',
  vehicle_registration: '', driver_name: '',
  origin_address: '', origin_lat: '', origin_lng: '',
  destination_address: '', destination_lat: '', destination_lng: '',
  departed_at: '', arrived_at: '', notes: '',
};

const WASTE_CATEGORIES = [
  'WEEE Cat. 1 — Large Household Appliances',
  'WEEE Cat. 2 — Small Household Appliances',
  'WEEE Cat. 3 — IT Equipment (Large)',
  'WEEE Cat. 4 — Consumer Equipment',
  'WEEE Cat. 5 — Lighting Equipment',
  'WEEE Cat. 6 — IT and Telecommunications',
  'WEEE Cat. 7 — Toys, Leisure & Sports',
  'WEEE Cat. 8 — Medical Devices',
  'WEEE Cat. 9 — Monitoring Equipment',
  'WEEE Cat. 10 — Automatic Dispensers',
  'WEEE Cat. 11 — Photovoltaic Panels',
];

function transportDistanceKm(originLat: string, originLng: string, destinationLat: string, destinationLng: string) {
  const values = [originLat, originLng, destinationLat, destinationLng].map(Number);
  if (values.some(value => !Number.isFinite(value)) || [originLat, originLng, destinationLat, destinationLng].some(value => value === '')) return null;
  const [lat1, lng1, lat2, lng2] = values.map(value => value * Math.PI / 180);
  const deltaLat = lat2 - lat1;
  const deltaLng = lng2 - lng1;
  const a = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function estimatedArrivalLocal(departedAt: string, straightLineKm: number | null) {
  if (!departedAt || straightLineKm === null || !Number.isFinite(straightLineKm)) return '';
  const departure = new Date(departedAt);
  if (!Number.isFinite(departure.getTime())) return '';
  // Approximate road travel as 1.3× straight-line distance at 40 km/h, with a
  // 30-minute minimum. This is a planning estimate; the recycler confirms actual arrival.
  const minutes = Math.max(30, (straightLineKm * 1.3 / 40) * 60);
  const arrival = new Date(departure.getTime() + minutes * 60_000);
  return new Date(arrival.getTime() - arrival.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function validate(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {};
  if (!f.producer_name.trim()) e.producer_name = 'Required';
  if (!f.producer_registration_number.trim()) e.producer_registration_number = 'Required';
  if (!f.recycler_name.trim()) e.recycler_name = 'Required';
  if (!f.recycler_facility_id) e.recycler_facility_id = 'Select a registered recycler';
  if (!f.waste_category) e.waste_category = 'Select a category';
  if (!f.declared_weight_kg || Number(f.declared_weight_kg) <= 0) e.declared_weight_kg = 'Enter a positive value';
  if (!f.collection_date) e.collection_date = 'Required';
  if (!f.vehicle_registration.trim()) e.vehicle_registration = 'Required';
  if (!f.driver_name.trim()) e.driver_name = 'Required';
  if (!f.origin_address.trim()) e.origin_address = 'Required';
  if (!f.destination_address.trim()) e.destination_address = 'Required';
  if (!f.departed_at) e.departed_at = 'Required';
  if (!f.arrived_at) e.arrived_at = 'Required';
  const latOk = (v: string) => v !== '' && !isNaN(+v) && Math.abs(+v) <= 90;
  const lngOk = (v: string) => v !== '' && !isNaN(+v) && Math.abs(+v) <= 180;
  if (!latOk(f.origin_lat)) e.origin_lat = 'Valid latitude (−90 to 90)';
  if (!lngOk(f.origin_lng)) e.origin_lng = 'Valid longitude (−180 to 180)';
  if (!latOk(f.destination_lat)) e.destination_lat = 'Valid latitude';
  if (!lngOk(f.destination_lng)) e.destination_lng = 'Valid longitude';
  return e;
}

const inp = (hasErr: boolean) =>
  `w-full rounded-lg border ${hasErr ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'} px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-600 focus:border-transparent transition`;

function Field({ label, error, required, hint, children }: {
  label: string; error?: string; required?: boolean; hint?: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-semibold text-slate-700">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
      {hint && !error && <p className="text-[10px] text-slate-400">{hint}</p>}
      {error && (
        <p className="flex items-center gap-1 text-[11px] text-red-600" role="alert">
          <AlertCircle className="h-3 w-3" aria-hidden="true" />{error}
        </p>
      )}
    </div>
  );
}

export function SubmitClaimPage() {
  const { user } = useAuth();
  const [form, setForm] = useState<Form>({ ...EMPTY, producer_name: user?.organisation ?? '' });
  const [errors, setErrors] = useState<Partial<Record<keyof Form, string>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [result, setResult] = useState<RecyclingClaim | null>(null);
  const [recyclerAccounts, setRecyclerAccounts] = useState<RecyclerAccount[]>([]);
  const [loadingRecyclers, setLoadingRecyclers] = useState(true);
  const [recyclerAccountsError, setRecyclerAccountsError] = useState('');
  const [producerEvidence, setProducerEvidence] = useState<{
    collectionWeightSlip: File | null;
    transportChallan: File | null;
    otherSupporting: File | null;
  }>({ collectionWeightSlip: null, transportChallan: null, otherSupporting: null });
  const [lookingUp, setLookingUp] = useState<'origin' | 'destination' | null>(null);
  const [locationMatches, setLocationMatches] = useState<Record<'origin' | 'destination', GeocodingResult[]>>({
    origin: [], destination: [],
  });
  const [selectedLocation, setSelectedLocation] = useState<Record<'origin' | 'destination', string>>({
    origin: '', destination: '',
  });
  const [locationMessages, setLocationMessages] = useState<Record<'origin' | 'destination', string>>({
    origin: '', destination: '',
  });
  const navigate = useNavigate();
  const estimatedDistanceKm = transportDistanceKm(form.origin_lat, form.origin_lng, form.destination_lat, form.destination_lng);

  useEffect(() => {
    const arrival = estimatedArrivalLocal(form.departed_at, estimatedDistanceKm);
    setForm(current => current.arrived_at === arrival ? current : { ...current, arrived_at: arrival });
    if (arrival) setErrors(current => current.arrived_at ? { ...current, arrived_at: undefined } : current);
  }, [form.departed_at, form.origin_lat, form.origin_lng, form.destination_lat, form.destination_lng]);

  useEffect(() => {
    fetchRecyclerAccounts()
      .then(setRecyclerAccounts)
      .catch(() => setRecyclerAccountsError('Registered recyclers could not be loaded. Refresh the page or contact an administrator.'))
      .finally(() => setLoadingRecyclers(false));
  }, []);

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    setForm(p => ({ ...p, [k]: e.target.value }));
    if (errors[k]) setErrors(p => ({ ...p, [k]: undefined }));
  };

  const setAddress = (point: 'origin' | 'destination') =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const addressKey = `${point}_address` as const;
      const latitudeKey = `${point}_lat` as const;
      const longitudeKey = `${point}_lng` as const;
      setForm(current => ({
        ...current,
        [addressKey]: e.target.value,
        [latitudeKey]: '',
        [longitudeKey]: '',
      }));
      setLocationMatches(current => ({ ...current, [point]: [] }));
      setSelectedLocation(current => ({ ...current, [point]: '' }));
      setLocationMessages(current => ({ ...current, [point]: '' }));
      setErrors(current => ({ ...current, [addressKey]: undefined, [latitudeKey]: undefined, [longitudeKey]: undefined }));
    };

  const applyLocation = (point: 'origin' | 'destination', index: number, matches = locationMatches[point]) => {
    const match = matches[index];
    if (!match) return;
    const latitudeKey = `${point}_lat` as const;
    const longitudeKey = `${point}_lng` as const;
    setForm(current => ({
      ...current,
      [latitudeKey]: String(match.latitude),
      [longitudeKey]: String(match.longitude),
    }));
    setSelectedLocation(current => ({ ...current, [point]: String(index) }));
    setErrors(current => ({ ...current, [latitudeKey]: undefined, [longitudeKey]: undefined }));
  };

  const lookupAddress = async (point: 'origin' | 'destination') => {
    setLookingUp(point);
    setLocationMessages(current => ({ ...current, [point]: '' }));
    setLocationMatches(current => ({ ...current, [point]: [] }));
    setSelectedLocation(current => ({ ...current, [point]: '' }));
    try {
      const matches = await findLocations(form[`${point}_address`]);
      setLocationMatches(current => ({ ...current, [point]: matches }));
      if (matches.length === 0) {
        setLocationMessages(current => ({ ...current, [point]: 'No matching location found. Try adding the city or region.' }));
      } else if (matches.length === 1) {
        applyLocation(point, 0, matches);
        setLocationMessages(current => ({ ...current, [point]: `Coordinates filled for ${matches[0].label}.` }));
      } else {
        setLocationMessages(current => ({ ...current, [point]: 'Choose the matching place below to fill its coordinates.' }));
      }
    } catch (error) {
      setLocationMessages(current => ({
        ...current,
        [point]: error instanceof Error ? error.message : 'Could not find this location. Try again.',
      }));
    } finally {
      setLookingUp(null);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError('');
    const errs = validate(form);
    if (Object.keys(errs).length) { setErrors(errs); return; }
    setSubmitting(true);
    try {
      let claim = await submitClaim({
        producer_name: form.producer_name,
        producer_registration_number: form.producer_registration_number,
        recycler_name: form.recycler_name,
        recycler_registration_number: form.recycler_registration_number,
        recycler_facility_id: form.recycler_facility_id,
        waste_category: form.waste_category,
        waste_subcategories: [],
        declared_weight_kg: Number(form.declared_weight_kg),
        collection_date: form.collection_date,
        vehicle_registration: form.vehicle_registration,
        driver_name: form.driver_name,
        origin_lat: Number(form.origin_lat),
        origin_lng: Number(form.origin_lng),
        origin_address: form.origin_address,
        destination_lat: Number(form.destination_lat),
        destination_lng: Number(form.destination_lng),
        destination_address: form.destination_address,
        departed_at: form.departed_at,
        arrived_at: form.arrived_at,
        notes: form.notes || undefined,
      });
      const initialEvidence = [
        [producerEvidence.collectionWeightSlip, 'COLLECTION_WEIGHT_SLIP'],
        [producerEvidence.transportChallan, 'TRANSPORT_CHALLAN'],
        [producerEvidence.otherSupporting, 'OTHER_SUPPORTING'],
      ] as const;
      const evidenceErrors: string[] = [];
      for (const [file, category] of initialEvidence) {
        if (!file) continue;
        try {
          claim = await uploadClaimEvidence(claim.id, file, category);
        } catch (error) {
          const label = category === 'COLLECTION_WEIGHT_SLIP'
            ? 'Origin weight slip'
            : category === 'TRANSPORT_CHALLAN'
              ? 'Transport challan'
              : 'Other supporting evidence';
          evidenceErrors.push(`${label}: ${error instanceof Error ? error.message : 'upload failed'}`);
        }
      }
      if (evidenceErrors.length) {
        setResult(claim);
        setSubmitError(`Claim was submitted, but ${evidenceErrors.join('; ')}. You can retry from the evidence checklist.`);
        return;
      }
      setResult(claim);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Claim submission failed.';
      if (message.includes('Failed to fetch')) {
        setSubmitError('Could not reach the ChainGuard API. Make sure the backend is running, then try again.');
      } else if (message.includes('API 401')) {
        setSubmitError('Your sign-in has expired. Sign out and sign in again before submitting.');
      } else {
        setSubmitError(message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (result) {
    const vr = result.verification_result;
    return (
      <div className="flex flex-col min-h-full">
        <TopBar title="Claim Submitted" />
        <div className="flex-1 flex items-center justify-center p-6">
          <Card className="max-w-md w-full text-center space-y-5 py-8">
            <div className="flex justify-center">
              <div className="h-14 w-14 rounded-full bg-emerald-50 flex items-center justify-center">
                <CheckCircle2 className="h-7 w-7 text-emerald-600" aria-hidden="true" />
              </div>
            </div>
            <div>
              <p className="text-base font-semibold text-slate-900">Claim submitted</p>
              <p className="text-sm text-slate-500 mt-1">
                Ref: <span className="font-mono font-semibold text-slate-800">{result.reference_number}</span>
              </p>
            </div>
            {vr && (
              <div className="flex flex-col items-center gap-1">
                <p className="text-xs text-slate-500">Risk analysis complete</p>
                <RiskScore score={vr.risk_score} level={vr.risk_level} size="md" />
                {vr.flags.length > 0 && (
                  <p className="text-xs text-orange-600 mt-1">{vr.flags.length} flag(s) detected — a government official will review before approving.</p>
                )}
                {vr.flags.length === 0 && (
                  <p className="text-xs text-slate-500 mt-1">No issues detected. Awaiting government official approval.</p>
                )}
              </div>
            )}
            <EvidencePanel
              claimId={result.id}
              evidence={result.evidence}
              status={result.status}
              receivedAt={result.received_at}
              processingCompletedAt={result.processing_completed_at}
              party="PRODUCER"
              onClaimUpdated={setResult}
            />
            {submitError && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" role="alert">{submitError}</div>}
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700 text-center">
              Your claim is <strong>awaiting recycler confirmation</strong>. You will see status updates in My Claims.
            </div>
            <div className="flex gap-2 justify-center">
              <Button variant="secondary" onClick={() => { setResult(null); setSubmitError(''); setProducerEvidence({ collectionWeightSlip: null, transportChallan: null, otherSupporting: null }); setForm({ ...EMPTY, producer_name: user?.organisation ?? '' }); }}>
                Submit Another
              </Button>
              <Button onClick={() => navigate('/user/claims')}>
                View My Claims
              </Button>
            </div>
          </Card>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Submit Recycling Claim" subtitle="All fields marked * are required" />
      <div className="flex-1 p-6 animate-fade-in">
        <form onSubmit={handleSubmit} noValidate className="max-w-3xl mx-auto space-y-5">

          {/* Parties */}
          <Card>
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-4">Parties</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Producer / Your Organisation" error={errors.producer_name} required>
                <input type="text" value={form.producer_name} onChange={set('producer_name')} placeholder="e.g. Acme Electronics Ltd" className={inp(!!errors.producer_name)} />
              </Field>
              <Field label="Producer Registration No." error={errors.producer_registration_number} required hint="National WEEE registration number">
                <input type="text" value={form.producer_registration_number} onChange={set('producer_registration_number')} placeholder="e.g. IN-CPCB-2024-0012" className={inp(!!errors.producer_registration_number)} />
              </Field>
              <Field label="Registered Recycler" error={errors.recycler_facility_id || errors.recycler_name} required hint="Choose an authorized company. The claim is routed to its active recycler account and appears in that company's dashboard.">
                <select value={form.recycler_facility_id} onChange={event => {
                  const account = recyclerAccounts.find(item => item.id === event.target.value);
                  setForm(current => ({
                    ...current,
                    recycler_facility_id: account?.id ?? '',
                    recycler_name: account?.organisation ?? '',
                    recycler_registration_number: account?.registration_number ?? '',
                  }));
                  setErrors(current => ({ ...current, recycler_facility_id: undefined, recycler_name: undefined }));
                }} disabled={loadingRecyclers || recyclerAccounts.length === 0 || !!recyclerAccountsError} className={`${inp(!!errors.recycler_facility_id || !!recyclerAccountsError)} disabled:cursor-not-allowed disabled:bg-slate-100`}>
                  <option value="">{loadingRecyclers ? 'Loading registered recyclers…' : 'Choose a registered recycler…'}</option>
                  {recyclerAccounts.map(account => <option key={account.id} value={account.id}>{account.organisation}</option>)}
                </select>
                {recyclerAccountsError && <p className="text-[11px] text-red-600" role="alert">{recyclerAccountsError}</p>}
                {!loadingRecyclers && !recyclerAccountsError && recyclerAccounts.length === 0 && (
                  <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800" role="status">
                    No authorized recycler facilities are configured in this workspace. An administrator must verify and register a facility before it can be selected for a claim.
                  </p>
                )}
                {!recyclerAccountsError && recyclerAccounts.length > 0 && (
                  <ul aria-label="Registered recyclers" className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-slate-50">
                    {recyclerAccounts.map(account => (
                      <li key={account.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs">
                        <span className="font-medium text-slate-700">{account.organisation}</span>
                        <span className="text-slate-500">Registration: {account.registration_number || 'Not listed'}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Field>
            </div>
            {!loadingRecyclers && !recyclerAccountsError && recyclerAccounts.length === 0 && (
              <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3" aria-label="Public recycler registry references">
                <h3 className="text-xs font-semibold text-slate-700">Public registry references · administrator review needed</h3>
                <p className="mt-1 text-[10px] text-slate-500">These government-published records are references only. Verify current authorization and permitted waste categories before registering them in ChainGuard.</p>
                <ul className="mt-2 divide-y divide-slate-100">
                  {RECYCLER_REGISTRY_REFERENCES.map(facility => (
                    <li key={facility.recyclerId} className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2 text-xs">
                      <span className="font-medium text-slate-700">{facility.name}<span className="ml-2 font-normal text-slate-500">{facility.address}</span></span>
                      <span className="shrink-0 text-slate-500">CPCB Recycler ID {facility.recyclerId} · listed validity through {facility.authorizationValidThrough}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[10px] text-slate-400">Sources: <a className="underline" href="https://ospcboard.odisha.gov.in/wp-content/uploads/2025/11/empanelled-list-of-e-waste-recyclers-registered-with-CPCB.pdf" target="_blank" rel="noreferrer">Odisha SPCB / CPCB recycler list</a> and <a className="underline" href="https://www.wbpcb.gov.in/files/Fr-04-2024-04-11-44list%20of%20E%20Waste%20recyclers.pdf" target="_blank" rel="noreferrer">West Bengal PCB authorization list</a>.</p>
              </div>
            )}
          </Card>

          {/* Waste */}
          <Card>
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-4">Waste Details</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Waste Category" error={errors.waste_category} required>
                <select value={form.waste_category} onChange={set('waste_category')} className={inp(!!errors.waste_category)}>
                  <option value="">Select category…</option>
                  {WASTE_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
              <Field label="Collection Date" error={errors.collection_date} required>
                <input type="date" value={form.collection_date} onChange={set('collection_date')} className={inp(!!errors.collection_date)} />
              </Field>
              <Field label="Declared Weight (kg)" error={errors.declared_weight_kg} required hint="Weight at origin">
                <input type="number" min="0.1" step="0.1" value={form.declared_weight_kg} onChange={set('declared_weight_kg')} placeholder="e.g. 500" className={inp(!!errors.declared_weight_kg)} />
              </Field>
            </div>
          </Card>

          {/* Transport */}
          <Card>
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-4">Transport</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Vehicle Registration" error={errors.vehicle_registration} required>
                <input type="text" value={form.vehicle_registration} onChange={set('vehicle_registration')} placeholder="e.g. KA-01-AB-1234" className={inp(!!errors.vehicle_registration)} />
              </Field>
              <Field label="Driver Name" error={errors.driver_name} required>
                <input type="text" value={form.driver_name} onChange={set('driver_name')} placeholder="e.g. Rajesh Kumar" className={inp(!!errors.driver_name)} />
              </Field>
              <Field label="Origin Address" error={errors.origin_address} required>
                <div className="flex gap-2">
                  <input type="text" value={form.origin_address} onChange={setAddress('origin')} placeholder="e.g. Electronic City, Bengaluru" className={`${inp(!!errors.origin_address)} min-w-0 flex-1`} />
                  <Button type="button" variant="secondary" size="sm" loading={lookingUp === 'origin'} disabled={!form.origin_address.trim() || lookingUp !== null} onClick={() => lookupAddress('origin')}>
                    <MapPin className="h-4 w-4" aria-hidden="true" /> Find
                  </Button>
                </div>
                {locationMatches.origin.length > 1 && (
                  <select aria-label="Matching origin locations" value={selectedLocation.origin} onChange={event => applyLocation('origin', Number(event.target.value))} className={inp(false)}>
                    <option value="">Choose the correct place…</option>
                    {locationMatches.origin.map((match, index) => <option key={`${match.latitude},${match.longitude}`} value={index}>{match.label}</option>)}
                  </select>
                )}
                {locationMessages.origin && <p className="text-[10px] text-slate-500" role="status">{locationMessages.origin}</p>}
              </Field>
              <Field label="Destination Address" error={errors.destination_address} required>
                <div className="flex gap-2">
                  <input type="text" value={form.destination_address} onChange={setAddress('destination')} placeholder="e.g. Peenya Industrial Area, Bengaluru" className={`${inp(!!errors.destination_address)} min-w-0 flex-1`} />
                  <Button type="button" variant="secondary" size="sm" loading={lookingUp === 'destination'} disabled={!form.destination_address.trim() || lookingUp !== null} onClick={() => lookupAddress('destination')}>
                    <MapPin className="h-4 w-4" aria-hidden="true" /> Find
                  </Button>
                </div>
                {locationMatches.destination.length > 1 && (
                  <select aria-label="Matching destination locations" value={selectedLocation.destination} onChange={event => applyLocation('destination', Number(event.target.value))} className={inp(false)}>
                    <option value="">Choose the correct place…</option>
                    {locationMatches.destination.map((match, index) => <option key={`${match.latitude},${match.longitude}`} value={index}>{match.label}</option>)}
                  </select>
                )}
                {locationMessages.destination && <p className="text-[10px] text-slate-500" role="status">{locationMessages.destination}</p>}
              </Field>
              <Field label="Origin Latitude" error={errors.origin_lat} required hint="Filled from the selected address; you can adjust it if needed">
                <input type="number" step="any" value={form.origin_lat} onChange={set('origin_lat')} placeholder="12.8449" className={inp(!!errors.origin_lat)} />
              </Field>
              <Field label="Origin Longitude" error={errors.origin_lng} required hint="Filled from the selected address; you can adjust it if needed">
                <input type="number" step="any" value={form.origin_lng} onChange={set('origin_lng')} placeholder="77.6710" className={inp(!!errors.origin_lng)} />
              </Field>
              <Field label="Destination Latitude" error={errors.destination_lat} required hint="Filled from the selected address; you can adjust it if needed">
                <input type="number" step="any" value={form.destination_lat} onChange={set('destination_lat')} placeholder="13.0358" className={inp(!!errors.destination_lat)} />
              </Field>
              <Field label="Destination Longitude" error={errors.destination_lng} required hint="Filled from the selected address; you can adjust it if needed">
                <input type="number" step="any" value={form.destination_lng} onChange={set('destination_lng')} placeholder="77.5620" className={inp(!!errors.destination_lng)} />
              </Field>
              <Field label="Departure Time" error={errors.departed_at} required>
                <input type="datetime-local" value={form.departed_at} onChange={set('departed_at')} className={inp(!!errors.departed_at)} />
              </Field>
              <Field label="Expected Arrival Time" error={errors.arrived_at} required hint={estimatedDistanceKm === null
                ? 'Set both locations to calculate an estimate. The recycler confirms actual arrival when receiving the shipment.'
                : `Auto-estimated from ${estimatedDistanceKm.toFixed(1)} km straight-line distance (road factor 1.3, average 40 km/h). Recycler confirms actual arrival on receipt.`}>
                <input type="datetime-local" value={form.arrived_at} readOnly aria-readonly="true" className={`${inp(!!errors.arrived_at)} bg-slate-50`} />
              </Field>
            </div>
          </Card>

          {/* Producer evidence */}
          <Card>
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-1">Producer / Collector Evidence</h2>
            <p className="mb-4 text-xs text-slate-500">Each file uploads to its own checklist category. Recycler-only records are added later by the assigned recycler.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Collection / Origin Weight Slip · Required" hint="Producer / Collector · Supports the declared weight at origin · PDF or image, up to 10 MB.">
                <input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
                  onChange={event => setProducerEvidence(current => ({ ...current, collectionWeightSlip: event.target.files?.[0] ?? null }))}
                  className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-teal-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-teal-700 hover:file:bg-teal-100"
                />
                {producerEvidence.collectionWeightSlip && <p className="mt-1 text-xs text-slate-500">Selected: {producerEvidence.collectionWeightSlip.name}</p>}
              </Field>
              <Field label="Transport Challan / Delivery Note · Required" hint="Producer / Collector · Supports shipment and delivery handover · PDF or image, up to 10 MB.">
                <input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
                  onChange={event => setProducerEvidence(current => ({ ...current, transportChallan: event.target.files?.[0] ?? null }))}
                  className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-teal-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-teal-700 hover:file:bg-teal-100"
                />
                {producerEvidence.transportChallan && <p className="mt-1 text-xs text-slate-500">Selected: {producerEvidence.transportChallan.name}</p>}
              </Field>
              <Field label="Other Supporting Evidence" hint="Optional additional producer/collector document · PDF or image, up to 10 MB.">
                <input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
                  onChange={event => setProducerEvidence(current => ({ ...current, otherSupporting: event.target.files?.[0] ?? null }))}
                  className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-teal-50 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-teal-700 hover:file:bg-teal-100"
                />
                {producerEvidence.otherSupporting && <p className="mt-1 text-xs text-slate-500">Selected: {producerEvidence.otherSupporting.name}</p>}
              </Field>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
                <p className="text-xs font-semibold text-slate-700">Recycler Receipt / Destination Weight Slip</p>
                <p className="mt-1 text-[11px] text-slate-500">Assigned Recycler · Collected after receipt is confirmed · PDF or image</p>
                <p className="mt-2 text-[10px] text-amber-700">Upload area appears in Recycler Work after receipt confirmation.</p>
              </div>
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
                <p className="text-xs font-semibold text-slate-700">Processing &amp; Recovery Record</p>
                <p className="mt-1 text-[11px] text-slate-500">Assigned Recycler · Collected after processing is recorded · PDF or image</p>
                <p className="mt-2 text-[10px] text-amber-700">Upload area appears in Recycler Work after processing is complete.</p>
              </div>
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3 sm:col-span-2">
                <p className="text-xs font-semibold text-slate-700">Recycling Certificate</p>
                <p className="mt-1 text-[11px] text-slate-500">Assigned Recycler · Conditional evidence collected after processing, when applicable · PDF or image</p>
                <p className="mt-2 text-[10px] text-amber-700">Upload area appears in Recycler Work after processing is complete.</p>
              </div>
            </div>
          </Card>

          <p className="text-center text-[10px] text-slate-400">
            Address lookup uses OpenStreetMap data. © <a className="underline" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>.
          </p>

          {/* Notes */}
          <Card>
            <Field label="Additional Notes" hint="Optional — any context for the auditor">
              <textarea rows={3} value={form.notes} onChange={set('notes')} placeholder="Any deviations from standard procedure, special handling requirements…" className={`${inp(false)} resize-none`} />
            </Field>
          </Card>

          {submitError && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>{submitError}</p>
            </div>
          )}

          <div className="flex justify-end gap-3 pb-2">
            <Button type="button" variant="secondary" onClick={() => { setForm({ ...EMPTY, producer_name: user?.organisation ?? '' }); setErrors({}); setSubmitError(''); }}>
              Clear
            </Button>
            <Button type="submit" loading={submitting} size="lg">
              Submit Claim
            </Button>
          </div>
        </form>
      </div>
      <Footer />
    </div>
  );
}
