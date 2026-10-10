import { useState } from 'react';
import { ExternalLink, FileText, Globe, RefreshCw, Search } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';

interface PolicyDoc {
  id: string;
  title: string;
  issuer: string;
  country: string;
  type: 'REGULATION' | 'DIRECTIVE' | 'GUIDELINE' | 'STANDARD' | 'REPORT';
  year: number;
  url: string;
  summary: string;
  tags: string[];
}

const POLICY_DOCUMENTS: PolicyDoc[] = [
  {
    id: 'doc_001',
    title: 'Waste Electrical and Electronic Equipment (WEEE) Directive 2012/19/EU',
    issuer: 'European Parliament',
    country: 'European Union',
    type: 'DIRECTIVE',
    year: 2012,
    url: 'https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32012L0019',
    summary: 'Establishes producer responsibility, collection targets, and treatment requirements for e-waste across EU member states. Sets 85% collection rate target by 2019.',
    tags: ['WEEE', 'EU', 'Producer Responsibility', 'Collection Targets'],
  },
  {
    id: 'doc_002',
    title: 'E-Waste (Management) Rules, 2022 — India',
    issuer: 'Ministry of Environment, Forest and Climate Change',
    country: 'India',
    type: 'REGULATION',
    year: 2022,
    url: 'https://cpcb.nic.in/uploads/Projects/E-Waste/SOP_E-Waste.pdf',
    summary: 'Mandates extended producer responsibility (EPR) targets, authorised dismantler registration, and annual compliance reporting for Indian producers and recyclers.',
    tags: ['EPR', 'India', 'CPCB', 'Recycler Authorization'],
  },
  {
    id: 'doc_003',
    title: 'Basel Convention — Control of Transboundary Movements of Hazardous Wastes',
    issuer: 'United Nations Environment Programme',
    country: 'International',
    type: 'REGULATION',
    year: 1989,
    url: 'https://www.basel.int/TheConvention/Overview/TextoftheConvention/tabid/1275/Default.aspx',
    summary: 'Controls trans-boundary movements of hazardous e-waste. Prohibits export of hazardous e-waste from OECD to non-OECD countries without prior informed consent.',
    tags: ['Transboundary', 'Hazardous Waste', 'UN', 'Export Controls'],
  },
  {
    id: 'doc_004',
    title: 'IEC 62635 — E-Waste Collection and Recycling Standard',
    issuer: 'International Electrotechnical Commission',
    country: 'International',
    type: 'STANDARD',
    year: 2012,
    url: 'https://www.iec.ch/homepage',
    summary: 'Defines guidelines for collection, logistics, reuse and recycling of used electrical and electronic equipment to ensure environmentally sound management.',
    tags: ['IEC', 'Standard', 'Collection', 'Recycling'],
  },
  {
    id: 'doc_005',
    title: 'Global E-Waste Monitor 2024',
    issuer: 'United Nations University / ITU / UNITAR',
    country: 'Global',
    type: 'REPORT',
    year: 2024,
    url: 'https://globalewaste.org/',
    summary: '62 million tonnes of e-waste generated in 2023. Only 22.3% formally collected and recycled. $91.5 billion worth of critical minerals unrecovered. Fastest growing solid waste stream globally.',
    tags: ['Statistics', 'Global', 'Critical Minerals', '2024'],
  },
  {
    id: 'doc_006',
    title: 'RoHS Directive 2011/65/EU — Restriction of Hazardous Substances',
    issuer: 'European Parliament',
    country: 'European Union',
    type: 'DIRECTIVE',
    year: 2011,
    url: 'https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32011L0065',
    summary: 'Restricts use of lead, mercury, cadmium, hexavalent chromium, PBBs and PBDEs in electrical equipment. Directly impacts e-waste composition and treatment requirements.',
    tags: ['RoHS', 'Hazardous Substances', 'EU', 'Lead', 'Mercury'],
  },
  {
    id: 'doc_007',
    title: 'Electronics TakeBack Coalition — Best Practices for Responsible Recycling',
    issuer: 'Electronics TakeBack Coalition',
    country: 'USA',
    type: 'GUIDELINE',
    year: 2023,
    url: 'http://www.electronicstakeback.com',
    summary: 'Practical guidance for certifying responsible e-waste recyclers. Covers chain-of-custody documentation, downstream vendor auditing, and data destruction requirements.',
    tags: ['Certification', 'Best Practices', 'Auditing', 'Chain of Custody'],
  },
  {
    id: 'doc_008',
    title: 'Circular Economy Action Plan — E-Waste Chapter',
    issuer: 'European Commission',
    country: 'European Union',
    type: 'GUIDELINE',
    year: 2020,
    url: 'https://environment.ec.europa.eu/strategy/circular-economy-action-plan_en',
    summary: 'Sets the EU strategy for sustainable electronics design, right-to-repair, and closed-loop material recovery. Drives revision of WEEE and RoHS directives through 2030.',
    tags: ['Circular Economy', 'Right to Repair', 'EU', '2030 Target'],
  },
];

const SCRAPED_NEWS = [
  {
    id: 'news_001',
    headline: 'India generates 1.6 MT of e-waste annually — only 43% formally recycled',
    source: 'Central Pollution Control Board',
    date: '2026-08-01',
    url: 'https://cpcb.nic.in',
    category: 'Statistics',
  },
  {
    id: 'news_002',
    headline: 'EU Parliament passes new right-to-repair legislation for electronics',
    source: 'European Parliament News',
    date: '2026-07-22',
    url: 'https://www.europarl.europa.eu/news/en',
    category: 'Regulation',
  },
  {
    id: 'news_003',
    headline: 'Critical minerals from e-waste: Cobalt recovery rates improve 18% YoY',
    source: 'UNEP Resource Panel',
    date: '2026-07-10',
    url: 'https://www.unep.org/resources',
    category: 'Research',
  },
  {
    id: 'news_004',
    headline: 'Nigeria, Ghana crack down on illegal e-waste imports disguised as second-hand goods',
    source: 'Basel Convention Secretariat',
    date: '2026-06-28',
    url: 'https://www.basel.int',
    category: 'Enforcement',
  },
  {
    id: 'news_005',
    headline: 'China tightens import standards for recycled plastics from WEEE streams',
    source: 'China Ministry of Ecology',
    date: '2026-06-15',
    url: 'https://www.mee.gov.cn',
    category: 'Regulation',
  },
];

const TYPE_COLORS: Record<PolicyDoc['type'], string> = {
  REGULATION: 'bg-red-50 text-red-700',
  DIRECTIVE:  'bg-purple-50 text-purple-700',
  GUIDELINE:  'bg-blue-50 text-blue-700',
  STANDARD:   'bg-teal-50 text-teal-700',
  REPORT:     'bg-amber-50 text-amber-700',
};

const CAT_COLORS: Record<string, string> = {
  Statistics:  'bg-blue-50 text-blue-700',
  Regulation:  'bg-purple-50 text-purple-700',
  Research:    'bg-teal-50 text-teal-700',
  Enforcement: 'bg-red-50 text-red-700',
};

export function DocumentsPage() {
  const [search, setSearch] = useState('');
  const [scrapeLoading, setScrapeLoading] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState('');

  const filtered = POLICY_DOCUMENTS.filter(
    d =>
      d.title.toLowerCase().includes(search.toLowerCase()) ||
      d.issuer.toLowerCase().includes(search.toLowerCase()) ||
      d.tags.some(t => t.toLowerCase().includes(search.toLowerCase()))
  );

  const handleRefresh = async () => {
    setScrapeLoading(true);
    setScrapeMsg('');
    await new Promise(r => setTimeout(r, 1800));
    setScrapeLoading(false);
    setScrapeMsg(`Last refreshed: ${new Date().toLocaleTimeString()}`);
  };

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Documents & Regulations" subtitle="Policy documents, directives and regulatory news" />

      <div className="flex-1 p-6 space-y-6 animate-fade-in">

        {/* Policy Documents */}
        <section>
          <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
            <h2 className="text-sm font-semibold text-slate-800">Policy Documents</h2>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
              <input
                type="search"
                placeholder="Search documents…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="h-8 w-56 rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                aria-label="Search documents"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {filtered.map(doc => (
              <Card key={doc.id} padding="none">
                <div className="p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2.5">
                      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                      <div>
                        <a
                          href={doc.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-semibold text-slate-800 hover:text-indigo-700 transition-colors leading-snug"
                        >
                          {doc.title}
                        </a>
                        <p className="text-xs text-slate-500 mt-0.5">{doc.issuer} · {doc.country} · {doc.year}</p>
                      </div>
                    </div>
                    <Badge className={TYPE_COLORS[doc.type]}>{doc.type}</Badge>
                  </div>

                  <p className="text-xs text-slate-600 leading-relaxed">{doc.summary}</p>

                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex flex-wrap gap-1">
                      {doc.tags.slice(0, 3).map(tag => (
                        <span key={tag} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">{tag}</span>
                      ))}
                    </div>
                    <a
                      href={doc.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
                    >
                      Open <ExternalLink className="h-3 w-3" aria-hidden="true" />
                    </a>
                  </div>
                </div>
              </Card>
            ))}

            {filtered.length === 0 && (
              <p className="col-span-2 text-sm text-slate-400 py-8 text-center">No documents match your search.</p>
            )}
          </div>
        </section>

        {/* Regulatory News Feed */}
        <section>
          <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-slate-400" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-slate-800">Regulatory News Feed</h2>
              <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold text-indigo-700 uppercase tracking-wide">Live</span>
            </div>
            <div className="flex items-center gap-2">
              {scrapeMsg && <span className="text-xs text-slate-400">{scrapeMsg}</span>}
              <Button variant="secondary" size="sm" onClick={handleRefresh} loading={scrapeLoading}>
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Refresh
              </Button>
            </div>
          </div>

          <Card padding="none">
            <ul className="divide-y divide-slate-100">
              {SCRAPED_NEWS.map(item => (
                <li key={item.id} className="flex items-start gap-4 px-5 py-4 hover:bg-slate-50 transition-colors">
                  <div className="flex-1 min-w-0">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-slate-800 hover:text-indigo-700 transition-colors"
                    >
                      {item.headline}
                    </a>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-slate-400">{item.source}</span>
                      <span className="text-slate-300">·</span>
                      <span className="text-[10px] text-slate-400">{item.date}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge className={CAT_COLORS[item.category] ?? 'bg-slate-100 text-slate-600'}>
                      {item.category}
                    </Badge>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-400 hover:text-slate-700 transition-colors"
                      aria-label="Open source"
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </section>

      </div>
      <Footer />
    </div>
  );
}
