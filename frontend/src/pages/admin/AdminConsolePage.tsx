import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useLocation } from 'react-router-dom';
import { adminApi, type AdminAccount, type AdminActivity, type AdminFacility, type AdminJurisdiction, type AdminLegacy } from '@/lib/api';

const titles: Record<string, string> = {
  facilities: 'Recycler facilities', memberships: 'Employee memberships and accounts',
  jurisdictions: 'Government jurisdictions', legacy: 'Unresolved legacy records', activity: 'Administrative activity',
};
const reasonDefault = 'Reviewed against supporting registry records';
const inputClass = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm';
const cardClass = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm';

export function AdminConsolePage() {
  const location = useLocation();
  const section = location.pathname.split('/').filter(Boolean)[1] ?? 'facilities';
  const [facilities, setFacilities] = useState<AdminFacility[]>([]);
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [jurisdictions, setJurisdictions] = useState<AdminJurisdiction[]>([]);
  const [legacy, setLegacy] = useState<AdminLegacy>({ claims: [], recycler_accounts: [], government_accounts: [] });
  const [activity, setActivity] = useState<AdminActivity[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedFacility, setSelectedFacility] = useState('');
  const [selectedJurisdiction, setSelectedJurisdiction] = useState('');
  const [facilityDraft, setFacilityDraft] = useState({ id: '', name: '', registration_number: '', address: '', authorization_status: 'PENDING', permitted_waste_categories: 'WEEE Category 1', reason: reasonDefault });
  const [jurisdictionDraft, setJurisdictionDraft] = useState({ id: '', name: '', boundary: '[]', reason: reasonDefault });
  const [reason, setReason] = useState(reasonDefault);
  const [memberUser, setMemberUser] = useState('');
  const [officerUser, setOfficerUser] = useState('');
  const [resolutions, setResolutions] = useState<Record<string, { facility: string; jurisdiction: string }>>({});

  async function refresh() {
    try {
      const [f, a, j, l, h] = await Promise.all([adminApi.facilities(), adminApi.accounts(), adminApi.jurisdictions(), adminApi.legacy(), adminApi.activity()]);
      setFacilities(f); setAccounts(a); setJurisdictions(j); setLegacy(l); setActivity(h);
      setSelectedFacility(current => current || f[0]?.id || '');
      setSelectedJurisdiction(current => current || j[0]?.id || '');
      setError('');
    } catch (e) { setError(e instanceof Error ? e.message : 'Administrative data could not be loaded.'); }
  }
  useEffect(() => { void refresh(); }, []);
  const employees = useMemo(() => accounts.filter(a => a.role === 'RECYCLER_EMPLOYEE'), [accounts]);
  const officers = useMemo(() => accounts.filter(a => a.role === 'GOVERNMENT_OFFICER'), [accounts]);

  async function act(work: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setMessage('');
    try { await work(); setMessage(success); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'The administrative change could not be saved.'); }
    finally { setBusy(false); }
  }
  function submitFacility(e: FormEvent) {
    e.preventDefault();
    void act(() => adminApi.saveFacility({ ...facilityDraft,
      permitted_waste_categories: facilityDraft.permitted_waste_categories.split(',').map(x => x.trim()).filter(Boolean),
    }), 'Facility details saved.');
  }
  function editFacility(f: AdminFacility) {
    setFacilityDraft({ id: f.id, name: f.name, registration_number: f.registration_number, address: f.address,
      authorization_status: f.authorization_status, permitted_waste_categories: f.permitted_waste_categories.join(', '), reason: reasonDefault });
  }
  function submitJurisdiction(e: FormEvent) {
    e.preventDefault();
    let boundary: number[][] | null;
    try { boundary = JSON.parse(jurisdictionDraft.boundary) as number[][] | null; }
    catch { setError('Boundary must be valid JSON coordinate pairs, for example [[76,12],[79,12],[78,14]].'); return; }
    if (!jurisdictionDraft.id.trim()) { setError('Enter a jurisdiction ID.'); return; }
    void act(() => adminApi.saveJurisdiction(jurisdictionDraft.id, { name: jurisdictionDraft.name, boundary, reason: jurisdictionDraft.reason }), 'Jurisdiction saved.');
  }
  function editJurisdiction(j: AdminJurisdiction) {
    setJurisdictionDraft({ id: j.id, name: j.name, boundary: JSON.stringify(j.boundary ?? []), reason: reasonDefault });
  }

  return <div className="mx-auto max-w-6xl space-y-6">
    <header><p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">Controlled provisioning</p><h1 className="mt-1 text-2xl font-bold text-slate-900">{titles[section] ?? 'Administration'}</h1><p className="mt-1 text-sm text-slate-500">Changes are recorded with your account, timestamp, reason, and before and after values.</p></header>
    {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
    {message && <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700" role="status">{message}</p>}

    {section === 'facilities' && <div className="grid gap-5 lg:grid-cols-[1.1fr_.9fr]">
      <section className={cardClass}><div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">Registered facilities</h2><button className="text-sm text-indigo-700" onClick={() => setFacilityDraft({ id: '', name: '', registration_number: '', address: '', authorization_status: 'PENDING', permitted_waste_categories: 'WEEE Category 1', reason: reasonDefault })}>New facility</button></div>
        <div className="space-y-3">{facilities.map(f => <div key={f.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 p-3"><div><div className="font-medium">{f.name}</div><div className="text-xs text-slate-500">{f.registration_number} · {f.authorization_status} · {f.memberships.filter(m => m.active && m.verified).length} verified employees</div></div><button className="rounded-md border px-3 py-1.5 text-sm" onClick={() => editFacility(f)}>Edit</button></div>)}{!facilities.length && <p className="text-sm text-slate-500">No facilities registered.</p>}</div>
      </section>
      <form className={`${cardClass} space-y-3`} onSubmit={submitFacility}><h2 className="font-semibold">{facilityDraft.id ? 'Update facility' : 'Register facility'}</h2>
        <input className={inputClass} required placeholder="Facility name" value={facilityDraft.name} onChange={e => setFacilityDraft({ ...facilityDraft, name: e.target.value })} />
        <input className={inputClass} required placeholder="Registration number" value={facilityDraft.registration_number} onChange={e => setFacilityDraft({ ...facilityDraft, registration_number: e.target.value })} />
        <input className={inputClass} placeholder="Address" value={facilityDraft.address} onChange={e => setFacilityDraft({ ...facilityDraft, address: e.target.value })} />
        <label className="block text-xs font-medium text-slate-600">Authorization status<select className={`${inputClass} mt-1`} value={facilityDraft.authorization_status} onChange={e => setFacilityDraft({ ...facilityDraft, authorization_status: e.target.value })}>{['PENDING', 'AUTHORIZED', 'SUSPENDED', 'DEACTIVATED'].map(v => <option key={v}>{v}</option>)}</select></label>
        <input className={inputClass} required placeholder="Permitted categories, comma separated" value={facilityDraft.permitted_waste_categories} onChange={e => setFacilityDraft({ ...facilityDraft, permitted_waste_categories: e.target.value })} />
        <textarea className={inputClass} required minLength={8} value={facilityDraft.reason} onChange={e => setFacilityDraft({ ...facilityDraft, reason: e.target.value })} aria-label="Reason for facility change" />
        <button disabled={busy} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Save facility</button>
      </form>
    </div>}

    {section === 'memberships' && <div className="space-y-5">
      <section className={cardClass}><h2 className="mb-4 font-semibold">Employee to facility membership</h2><div className="grid gap-3 md:grid-cols-3">
        <select className={inputClass} value={selectedFacility} onChange={e => setSelectedFacility(e.target.value)}><option value="">Select facility</option>{facilities.map(f => <option key={f.id} value={f.id}>{f.name} · {f.authorization_status}</option>)}</select>
        <select className={inputClass} value={memberUser} onChange={e => setMemberUser(e.target.value)}><option value="">Select recycler employee</option>{employees.map(a => <option key={a.id} value={a.id}>{a.display_name} · {a.organisation}</option>)}</select>
        <button disabled={busy || !selectedFacility || !memberUser} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" onClick={() => void act(() => adminApi.setMembership(selectedFacility, memberUser, { active: true, verified: true, reason }), 'Verified membership assigned.')}>Verify and assign</button>
      </div><textarea className={`${inputClass} mt-3`} value={reason} onChange={e => setReason(e.target.value)} aria-label="Reason for membership change" />
        <div className="mt-4 space-y-2">{facilities.flatMap(f => f.memberships.map(m => <div key={`${f.id}:${m.user_id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"><span><b>{m.display_name}</b> · {f.name} · {m.verified ? 'verified' : 'unverified'} · {m.active ? 'active' : 'revoked'}</span>{m.active && <button className="rounded-md border border-red-200 px-3 py-1 text-red-700" onClick={() => void act(() => adminApi.revokeMembership(f.id, m.user_id, reason), 'Membership revoked.')}>Revoke</button>}</div>))}</div>
      </section>
      <section className={cardClass}><h2 className="mb-3 font-semibold">Account access</h2><p className="mb-3 text-xs text-slate-500">Accounts are created and assigned roles through trusted server configuration. This panel can activate or suspend existing accounts.</p>{accounts.map(a => <div key={a.id} className="flex flex-wrap items-center justify-between gap-2 border-t py-3 text-sm"><span><b>{a.display_name}</b> · {a.username} · {a.role} · {a.is_active ? 'active' : 'suspended'}</span>{a.id !== '' && <button className="rounded-md border px-3 py-1 text-sm" disabled={busy} onClick={() => void act(() => adminApi.setAccountActive(a.id, !a.is_active, reason), a.is_active ? 'Account suspended.' : 'Account activated.')}>{a.is_active ? 'Suspend' : 'Activate'}</button>}</div>)}</section>
    </div>}

    {section === 'jurisdictions' && <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
      <section className={cardClass}><h2 className="mb-4 font-semibold">Jurisdictions and assignments</h2>{jurisdictions.map(j => <div key={j.id} className="mb-3 rounded-lg border p-3"><div className="flex justify-between"><div><b>{j.name}</b><div className="text-xs text-slate-500">{j.id} · {j.officers.length} assigned officers</div></div><button className="text-sm text-indigo-700" onClick={() => { editJurisdiction(j); setSelectedJurisdiction(j.id); }}>Edit</button></div>{j.officers.map(o => <div key={o.user_id} className="mt-2 flex justify-between text-sm"><span>{o.display_name}</span><button className="text-xs text-red-700" onClick={() => void act(() => adminApi.revokeOfficer(j.id, o.user_id, reason), 'Officer assignment revoked.')}>Revoke</button></div>)}</div>)}</section>
      <div className="space-y-5"><form className={`${cardClass} space-y-3`} onSubmit={submitJurisdiction}><h2 className="font-semibold">Create or update jurisdiction</h2><input className={inputClass} required placeholder="Stable jurisdiction ID" value={jurisdictionDraft.id} onChange={e => setJurisdictionDraft({ ...jurisdictionDraft, id: e.target.value })} /><input className={inputClass} required placeholder="Name" value={jurisdictionDraft.name} onChange={e => setJurisdictionDraft({ ...jurisdictionDraft, name: e.target.value })} /><textarea className={inputClass} rows={3} placeholder="Boundary JSON: [[longitude,latitude], ...]" value={jurisdictionDraft.boundary} onChange={e => setJurisdictionDraft({ ...jurisdictionDraft, boundary: e.target.value })} /><textarea className={inputClass} minLength={8} value={jurisdictionDraft.reason} onChange={e => setJurisdictionDraft({ ...jurisdictionDraft, reason: e.target.value })} aria-label="Reason for jurisdiction change" /><button className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white" disabled={busy}>Save jurisdiction</button></form>
        <section className={`${cardClass} space-y-3`}><h2 className="font-semibold">Assign government officer</h2><select className={inputClass} value={selectedJurisdiction} onChange={e => setSelectedJurisdiction(e.target.value)}><option value="">Select jurisdiction</option>{jurisdictions.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select><select className={inputClass} value={officerUser} onChange={e => setOfficerUser(e.target.value)}><option value="">Select officer</option>{officers.map(a => <option key={a.id} value={a.id}>{a.display_name}</option>)}</select><button disabled={busy || !selectedJurisdiction || !officerUser} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => void act(() => adminApi.assignOfficer(selectedJurisdiction, officerUser, reason), 'Officer assigned.')}>Assign officer</button></section>
      </div>
    </div>}

    {section === 'legacy' && <div className="space-y-5"><p className="text-sm text-slate-600">Mappings require an explicit review checkbox and reason. Original party labels are retained in the audit event before and after snapshot.</p>
      {legacy.claims.map(c => <section className={cardClass} key={c.id}><div className="mb-3"><h2 className="font-semibold">{c.reference_number}</h2><p className="text-sm text-slate-500">{c.recycler_name} · {c.recycler_registration_number} · unresolved: {c.unresolved.join(', ')}</p></div><div className="grid gap-3 md:grid-cols-2"><select className={inputClass} value={resolutions[c.id]?.facility ?? ''} onChange={e => setResolutions({ ...resolutions, [c.id]: { facility: e.target.value, jurisdiction: resolutions[c.id]?.jurisdiction ?? '' } })}><option value="">Leave facility unresolved</option>{facilities.filter(f => f.authorization_status === 'AUTHORIZED').map(f => <option key={f.id} value={f.id}>{f.name} · {f.registration_number}</option>)}</select><select className={inputClass} value={resolutions[c.id]?.jurisdiction ?? ''} onChange={e => setResolutions({ ...resolutions, [c.id]: { facility: resolutions[c.id]?.facility ?? '', jurisdiction: e.target.value } })}><option value="">Leave jurisdiction unresolved</option>{jurisdictions.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select></div><label className="mt-3 flex gap-2 text-sm"><input type="checkbox" data-confirm={c.id} />I reviewed the source records and confirm these mappings.</label><textarea className={`${inputClass} mt-3`} value={reason} onChange={e => setReason(e.target.value)} aria-label={`Reason for ${c.reference_number}`} /><button className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white" disabled={busy} onClick={e => { const checkbox = e.currentTarget.parentElement?.querySelector<HTMLInputElement>(`[data-confirm="${c.id}"]`); void act(() => adminApi.resolveLegacy(c.id, { recycler_facility_id: resolutions[c.id]?.facility || null, jurisdiction_id: resolutions[c.id]?.jurisdiction || null, confirm: checkbox?.checked === true, reason }), 'Legacy mappings resolved.'); }}>Confirm mapping</button></section>)}
      {legacy.recycler_accounts.map(a => <section className={cardClass} key={a.id}><b>{a.display_name}</b> · {a.organisation}<p className="mt-1 text-sm text-slate-500">No verified active facility membership. Use Memberships &amp; accounts to review and assign.</p></section>)}
      {legacy.government_accounts.map(a => <section className={`${cardClass} flex flex-wrap items-center justify-between gap-3`} key={a.id}><span><b>{a.display_name}</b> · {a.organisation}<span className="block text-sm text-slate-500">No jurisdiction assignment</span></span><select className={`${inputClass} max-w-xs`} defaultValue="" onChange={e => { if (e.target.value) void act(() => adminApi.assignOfficer(e.target.value, a.id, reason), 'Officer assigned to jurisdiction.'); }}><option value="">Choose jurisdiction to assign</option>{jurisdictions.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select></section>)}
      {!legacy.claims.length && !legacy.recycler_accounts.length && !legacy.government_accounts.length && <div className={cardClass}><p className="text-sm text-emerald-700">No unresolved claim or account mappings.</p></div>}
    </div>}

    {section === 'activity' && <section className={cardClass}><h2 className="mb-4 font-semibold">Administrative activity history</h2><div className="space-y-3">{activity.map(event => <article key={event.id} className="border-l-2 border-indigo-500 pl-4"><div className="flex flex-wrap justify-between gap-2 text-sm"><b>{event.action_type} · {event.entity_type} {event.entity_id}</b><time className="text-slate-500">{new Date(event.occurred_at).toLocaleString()}</time></div><p className="text-xs text-slate-600">{event.actor_display_name} ({event.actor_role}) · {event.reason}</p><details className="mt-1 text-xs"><summary className="cursor-pointer text-indigo-700">Before and after</summary><pre className="mt-2 overflow-auto rounded bg-slate-50 p-2">{JSON.stringify({ previous: event.previous_values, next: event.new_values }, null, 2)}</pre></details><p className="mt-1 break-all font-mono text-[10px] text-slate-400">SHA-256 {event.event_hash}</p></article>)}</div></section>}
  </div>;
}
