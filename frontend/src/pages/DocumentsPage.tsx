import { useState, useEffect } from 'react';
import {
  Globe,
  FileText,
  Download,
  ExternalLink,
  Search,
  Clock,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,

  FileSearch,
  Newspaper,
  Scale,
  Building2,
  Link as LinkIcon,
  Eye,
} from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';

/* ─── Simulated scraped web data ─── */
interface ScrapedSource {
  id: string;
  title: string;
  url: string;
  source: string;
  category: 'REGULATION' | 'NEWS' | 'REGISTRY' | 'ENFORCEMENT';
  snippet: string;
  scraped_at: string;
  relevance_score: number;
  status: 'FRESH' | 'STALE' | 'ERROR';
}

interface ClaimDocument {
  id: string;
  claim_ref: string;
  filename: string;
  type: 'CERTIFICATE' | 'MANIFEST' | 'WEIGHT_SLIP' | 'INVOICE' | 'PHOTO' | 'AUDIT_REPORT';
  uploaded_at: string;
  size_kb: number;
  extracted_text: string;
  verified: boolean;
  flagged: boolean;
}

const SCRAPED_SOURCES: ScrapedSource[] = [
  {
    id: 'src_001',
    title: 'EU WEEE Directive 2012/19/EU — Latest Amendments (Oct 2026)',
    url: 'https://eur-lex.europa.eu/weee-directive-2012-19',
    source: 'EUR-Lex',
    category: 'REGULATION',
    snippet: 'Member States shall ensure that producers of EEE provide adequate financial guarantees for the collection, treatment, recovery and disposal of WEEE. Updated thresholds for Category 4 now require minimum 65% recovery rate by weight.',
    scraped_at: '2026-10-08T09:00:00Z',
    relevance_score: 96,
    status: 'FRESH',
  },
  {
    id: 'src_002',
    title: 'Stiftung EAR — Registered Collection & Recycling Facilities',
    url: 'https://www.stiftung-ear.de/en/registered-facilities',
    source: 'Stiftung EAR',
    category: 'REGISTRY',
    snippet: 'As of Q3 2026, there are 1,847 registered recycling facilities across EU member states. NovaCycle Processing S.A. (PL-WIOL-2021-0187) shows an active registration with last audit on 2026-06-14.',
    scraped_at: '2026-10-07T14:30:00Z',
    relevance_score: 91,
    status: 'FRESH',
  },
  {
    id: 'src_003',
    title: 'Cross-Border E-Waste Fraud Ring Detected — INTERPOL Operation',
    url: 'https://www.interpol.int/news/2026/e-waste-fraud-ring',
    source: 'INTERPOL',
    category: 'ENFORCEMENT',
    snippet: 'Operation "Circuit Breaker" uncovered a network of 23 shell companies filing fraudulent recycling certificates across 7 EU member states. Total declared but unprocessed waste estimated at 14,000 tonnes.',
    scraped_at: '2026-10-06T08:15:00Z',
    relevance_score: 88,
    status: 'FRESH',
  },
  {
    id: 'src_004',
    title: 'German Federal Environment Agency — New Compliance Requirements 2027',
    url: 'https://www.umweltbundesamt.de/en/topics/waste/e-waste-2027',
    source: 'UBA Germany',
    category: 'REGULATION',
    snippet: 'Starting January 2027, all WEEE recyclers must implement real-time mass balance tracking with GPS-verified transport chains. Non-compliance penalties increase to €250,000 per violation.',
    scraped_at: '2026-10-05T11:45:00Z',
    relevance_score: 85,
    status: 'FRESH',
  },
  {
    id: 'src_005',
    title: 'E-Waste Recovery Rates Fall Short of EU Targets in Eastern Europe',
    url: 'https://www.euractiv.com/e-waste-recovery-eastern-europe',
    source: 'Euractiv',
    category: 'NEWS',
    snippet: 'A new report reveals that Poland, Romania, and Bulgaria consistently miss EU-mandated WEEE recovery targets. Critics point to insufficient enforcement and monitoring infrastructure.',
    scraped_at: '2026-10-04T16:20:00Z',
    relevance_score: 72,
    status: 'STALE',
  },
  {
    id: 'src_006',
    title: 'ISO 14001 Certification Database — Environmental Management',
    url: 'https://www.iso.org/iso-14001-database',
    source: 'ISO',
    category: 'REGISTRY',
    snippet: 'Cross-referencing ISO 14001 certification with WEEE registration numbers. 94% of registered recyclers maintain valid ISO 14001 certification. 127 facilities flagged for expired certificates.',
    scraped_at: '2026-10-03T09:10:00Z',
    relevance_score: 79,
    status: 'STALE',
  },
];

const CLAIM_DOCUMENTS: ClaimDocument[] = [
  {
    id: 'doc_001',
    claim_ref: 'EWC-2026-08441',
    filename: 'weee_certificate_aug2026.pdf',
    type: 'CERTIFICATE',
    uploaded_at: '2026-08-13T10:22:00Z',
    size_kb: 412,
    extracted_text: 'CERTIFICATE OF RECYCLING — Certificate No: WEEE-DE-2026-08441 — Issued by: Stiftung EAR — Producer: Meridian Electronics GmbH (DE-EEG-2019-0034) — Recycler: NovaCycle Processing S.A. — Declared Weight: 1,000 kg — Waste Category: WEEE Cat. 4 — Date of Issue: 13 Aug 2026',
    verified: false,
    flagged: true,
  },
  {
    id: 'doc_002',
    claim_ref: 'EWC-2026-08441',
    filename: 'weighbridge_slip_WRC44821.pdf',
    type: 'WEIGHT_SLIP',
    uploaded_at: '2026-08-13T10:26:00Z',
    size_kb: 87,
    extracted_text: 'WEIGHBRIDGE CERTIFICATE — Facility: NovaCycle Wrocław — Vehicle: WRC-44821 — Driver: Tomasz Krawczyk — Gross Weight: 26,720 kg — Tare Weight: 26,000 kg — Net Weight: 720 kg — Date: 12 Aug 2026 — Discrepancy: Net weight 720 kg vs. declared 1,000 kg (-28%)',
    verified: false,
    flagged: true,
  },
  {
    id: 'doc_003',
    claim_ref: 'EWC-2026-08310',
    filename: 'recycling_cert_jul2026.pdf',
    type: 'CERTIFICATE',
    uploaded_at: '2026-07-29T09:00:00Z',
    size_kb: 311,
    extracted_text: 'RECYCLING CERTIFICATE — Certificate No: WEEE-NL-2026-08310 — Issued by: Rijkswaterstaat — Producer: Helix Consumer Electronics NV (NL-WEELAB-2018-0091) — Recycler: Umicore Battery Recycling SA — Declared Weight: 340 kg — Category: WEEE Cat. 8 — Date: 28 Jul 2026',
    verified: true,
    flagged: false,
  },
  {
    id: 'doc_004',
    claim_ref: 'EWC-2026-08519',
    filename: 'transport_manifest_SE3371.pdf',
    type: 'MANIFEST',
    uploaded_at: '2026-09-02T16:00:00Z',
    size_kb: 197,
    extracted_text: 'TRANSPORT MANIFEST — Route: Zurich, CH → Gothenburg, SE — Vehicle: SE-GBG-3371 — Driver: Erik Lindström — Cargo: IT & Telecommunications Equipment (Servers, Network Equipment) — Declared Weight: 2,800 kg — Departure: 01 Sep 2026 05:00 — Arrival: 02 Sep 2026 14:30',
    verified: false,
    flagged: false,
  },
  {
    id: 'doc_005',
    claim_ref: 'EWC-2026-08441',
    filename: 'processing_floor_photo_1.jpg',
    type: 'PHOTO',
    uploaded_at: '2026-08-13T10:24:00Z',
    size_kb: 3750,
    extracted_text: '[IMAGE ANALYSIS] — Processing floor photograph — pHash: a1b2c3d4e5f60718 — DUPLICATE MATCH with claim EWC-2026-07293 (NovaCycle, July 2026) — Similarity: 97% — Classification: Suspicious reuse of evidence photo',
    verified: false,
    flagged: true,
  },
  {
    id: 'doc_006',
    claim_ref: 'EWC-2026-08310',
    filename: 'battery_audit_report_q3.pdf',
    type: 'AUDIT_REPORT',
    uploaded_at: '2026-07-30T14:00:00Z',
    size_kb: 1240,
    extracted_text: 'QUARTERLY AUDIT REPORT — Facility: Umicore Battery Recycling SA, Hoboken — Period: Q3 2026 — Total intake: 8,440 kg — Recovery rate: 96.8% — Cobalt recovered: 462 kg — Lithium recovered: 1,128 kg — Compliance Status: FULLY COMPLIANT — Auditor: Bureau Veritas',
    verified: true,
    flagged: false,
  },
];

const CATEGORY_CONFIG = {
  REGULATION: { label: 'Regulation', icon: Scale, color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/20' },
  NEWS: { label: 'News', icon: Newspaper, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  REGISTRY: { label: 'Registry', icon: Building2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' },
  ENFORCEMENT: { label: 'Enforcement', icon: AlertTriangle, color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20' },
};

const DOC_TYPE_CONFIG = {
  CERTIFICATE: { label: 'Certificate', color: 'bg-blue-50 text-blue-700' },
  MANIFEST: { label: 'Manifest', color: 'bg-purple-50 text-purple-700' },
  WEIGHT_SLIP: { label: 'Weight Slip', color: 'bg-amber-50 text-amber-700' },
  INVOICE: { label: 'Invoice', color: 'bg-slate-100 text-slate-700' },
  PHOTO: { label: 'Photo', color: 'bg-pink-50 text-pink-700' },
  AUDIT_REPORT: { label: 'Audit Report', color: 'bg-emerald-50 text-emerald-700' },
};

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso));
}

type Tab = 'scraped' | 'documents';

export function DocumentsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('scraped');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);
  const [scraping, setScraping] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setLoading(false), 600);
    return () => clearTimeout(timer);
  }, []);

  const handleRescrape = () => {
    setScraping(true);
    setTimeout(() => setScraping(false), 2000);
  };

  const filteredSources = SCRAPED_SOURCES.filter(
    (s) =>
      s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.source.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.snippet.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const filteredDocs = CLAIM_DOCUMENTS.filter(
    (d) =>
      d.claim_ref.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.filename.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.extracted_text.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex flex-col min-h-full">
      <TopBar
        title="Documents & Intelligence"
        subtitle="Scraped regulatory data and uploaded claim documents"
      />

      <div className="flex-1 p-6 space-y-5 animate-fade-in">
        {/* Tab navigation + Actions */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <nav
            className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1"
            aria-label="Document sections"
          >
            <button
              onClick={() => setActiveTab('scraped')}
              className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium transition-colors ${
                activeTab === 'scraped'
                  ? 'bg-teal-600 text-white'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Globe className="h-3.5 w-3.5" />
              Web Scraped Data
              <span className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                activeTab === 'scraped' ? 'bg-white/20' : 'bg-slate-100'
              }`}>
                {SCRAPED_SOURCES.length}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('documents')}
              className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium transition-colors ${
                activeTab === 'documents'
                  ? 'bg-teal-600 text-white'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              Claim Documents
              <span className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                activeTab === 'documents' ? 'bg-white/20' : 'bg-slate-100'
              }`}>
                {CLAIM_DOCUMENTS.length}
              </span>
            </button>
          </nav>

          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search documents…"
                className="h-8 w-56 rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-600 focus:border-transparent transition"
              />
            </div>
            {activeTab === 'scraped' && (
              <Button
                variant="secondary"
                size="sm"
                onClick={handleRescrape}
                loading={scraping}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Re-scrape
              </Button>
            )}
          </div>
        </div>

        {/* Content area */}
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-32 rounded-xl" />
            ))}
          </div>
        ) : activeTab === 'scraped' ? (
          /* ─── Scraped Data Tab ─── */
          <div className="space-y-4">
            {/* Summary cards */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {Object.entries(CATEGORY_CONFIG).map(([key, cfg]) => {
                const count = SCRAPED_SOURCES.filter((s) => s.category === key).length;
                const Icon = cfg.icon;
                return (
                  <div
                    key={key}
                    className={`flex items-center gap-3 rounded-xl border ${cfg.border} ${cfg.bg} p-3.5`}
                  >
                    <Icon className={`h-4 w-4 ${cfg.color}`} />
                    <div>
                      <p className="text-xs font-semibold text-slate-700">{cfg.label}</p>
                      <p className="text-lg font-bold text-slate-900">{count}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Source list */}
            <div className="space-y-3">
              {filteredSources.length === 0 ? (
                <Card>
                  <div className="py-12 text-center">
                    <FileSearch className="h-8 w-8 text-slate-300 mx-auto mb-3" />
                    <p className="text-sm text-slate-500">No sources match your search.</p>
                  </div>
                </Card>
              ) : (
                filteredSources.map((source) => {
                  const catCfg = CATEGORY_CONFIG[source.category];
                  const CatIcon = catCfg.icon;
                  return (
                    <Card key={source.id} padding="none">
                      <div className="p-5">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-3 min-w-0">
                            <div
                              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${catCfg.bg} border ${catCfg.border}`}
                            >
                              <CatIcon className={`h-4 w-4 ${catCfg.color}`} />
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-slate-800 leading-snug">
                                {source.title}
                              </p>
                              <div className="mt-1 flex items-center gap-2 flex-wrap">
                                <Badge className={`${catCfg.bg} ${catCfg.color} text-[10px]`}>
                                  {catCfg.label}
                                </Badge>
                                <span className="flex items-center gap-1 text-[10px] text-slate-400">
                                  <LinkIcon className="h-2.5 w-2.5" />
                                  {source.source}
                                </span>
                                <span className="flex items-center gap-1 text-[10px] text-slate-400">
                                  <Clock className="h-2.5 w-2.5" />
                                  {formatDate(source.scraped_at)}
                                </span>
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <div className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                              source.status === 'FRESH'
                                ? 'bg-emerald-50 text-emerald-600'
                                : source.status === 'STALE'
                                ? 'bg-amber-50 text-amber-600'
                                : 'bg-red-50 text-red-600'
                            }`}>
                              {source.status === 'FRESH' ? (
                                <CheckCircle2 className="h-2.5 w-2.5" />
                              ) : (
                                <Clock className="h-2.5 w-2.5" />
                              )}
                              {source.status}
                            </div>
                            <div className="text-right">
                              <p className="text-[10px] text-slate-400">Relevance</p>
                              <p className={`text-sm font-bold ${
                                source.relevance_score >= 90
                                  ? 'text-emerald-600'
                                  : source.relevance_score >= 80
                                  ? 'text-amber-600'
                                  : 'text-slate-600'
                              }`}>
                                {source.relevance_score}%
                              </p>
                            </div>
                          </div>
                        </div>

                        <p className="mt-3 text-xs text-slate-600 leading-relaxed border-l-2 border-slate-200 pl-3">
                          {source.snippet}
                        </p>

                        <div className="mt-3 flex items-center gap-2">
                          <a
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[11px] font-medium text-teal-700 hover:text-teal-800 transition-colors"
                          >
                            <ExternalLink className="h-3 w-3" />
                            View source
                          </a>
                        </div>
                      </div>
                    </Card>
                  );
                })
              )}
            </div>
          </div>
        ) : (
          /* ─── Documents Tab ─── */
          <div className="space-y-3">
            {/* Quick stats */}
            <div className="grid grid-cols-3 gap-3">
              <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <div>
                  <p className="text-xs text-emerald-700 font-medium">Verified</p>
                  <p className="text-lg font-bold text-emerald-800">
                    {CLAIM_DOCUMENTS.filter((d) => d.verified).length}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-3.5">
                <AlertTriangle className="h-4 w-4 text-red-600" />
                <div>
                  <p className="text-xs text-red-700 font-medium">Flagged</p>
                  <p className="text-lg font-bold text-red-800">
                    {CLAIM_DOCUMENTS.filter((d) => d.flagged).length}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3.5">
                <FileText className="h-4 w-4 text-slate-600" />
                <div>
                  <p className="text-xs text-slate-600 font-medium">Total</p>
                  <p className="text-lg font-bold text-slate-800">{CLAIM_DOCUMENTS.length}</p>
                </div>
              </div>
            </div>

            {/* Documents list */}
            {filteredDocs.length === 0 ? (
              <Card>
                <div className="py-12 text-center">
                  <FileSearch className="h-8 w-8 text-slate-300 mx-auto mb-3" />
                  <p className="text-sm text-slate-500">No documents match your search.</p>
                </div>
              </Card>
            ) : (
              filteredDocs.map((doc) => {
                const typeCfg = DOC_TYPE_CONFIG[doc.type];
                const isExpanded = expandedDoc === doc.id;
                return (
                  <Card key={doc.id} padding="none">
                    <div className="p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3 min-w-0">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 border border-slate-200">
                            <FileText className="h-4 w-4 text-slate-500" />
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-slate-800">{doc.filename}</p>
                            <div className="mt-1 flex items-center gap-2 flex-wrap">
                              <Badge className={typeCfg.color}>{typeCfg.label}</Badge>
                              <span className="font-mono text-[10px] text-slate-500">
                                {doc.claim_ref}
                              </span>
                              <span className="text-[10px] text-slate-400">
                                {doc.size_kb} KB
                              </span>
                              <span className="text-[10px] text-slate-400">
                                {formatDate(doc.uploaded_at)}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {doc.flagged && (
                            <span className="flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-600 border border-red-200">
                              <AlertTriangle className="h-2.5 w-2.5" />
                              Flagged
                            </span>
                          )}
                          {doc.verified && (
                            <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 border border-emerald-200">
                              <CheckCircle2 className="h-2.5 w-2.5" />
                              Verified
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Extracted text preview / expansion */}
                      <div className="mt-3">
                        <button
                          onClick={() => setExpandedDoc(isExpanded ? null : doc.id)}
                          className="flex items-center gap-1.5 text-[11px] font-medium text-teal-700 hover:text-teal-800 transition-colors"
                        >
                          <Eye className="h-3 w-3" />
                          {isExpanded ? 'Hide' : 'View'} extracted content
                        </button>
                        {isExpanded && (
                          <div className="mt-2 rounded-lg bg-slate-50 border border-slate-200 p-3 animate-fade-in">
                            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-1.5">
                              Extracted Text / Analysis
                            </p>
                            <p className="text-xs text-slate-700 leading-relaxed font-mono whitespace-pre-wrap">
                              {doc.extracted_text}
                            </p>
                          </div>
                        )}
                      </div>

                      <div className="mt-3 flex items-center gap-2">
                        <button className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 hover:text-slate-700 transition-colors">
                          <Download className="h-3 w-3" />
                          Download
                        </button>
                      </div>
                    </div>
                  </Card>
                );
              })
            )}
          </div>
        )}
      </div>

      <Footer />
    </div>
  );
}
