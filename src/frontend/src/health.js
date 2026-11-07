// Health tab: World Bank WDI indicators (latest value, year, world position) and a
// life-expectancy trend chart. Data comes with the facts record, so no extra request.
import { icon, flag } from './icons.js';
import { trendChart } from './chart.js';

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const num = (digits) => new Intl.NumberFormat('en', { maximumFractionDigits: digits, minimumFractionDigits: digits });
const usd = new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

// Display metadata per World Bank indicator code (the build decides which codes exist).
const INDICATORS = {
  'SP.DYN.IMRT.IN': { label: 'Infant mortality', fmt: (v) => num(1).format(v), unit: 'per 1,000 births', icon: 'baby' },
  'SH.STA.MMRT': { label: 'Maternal mortality', fmt: (v) => num(0).format(v), unit: 'per 100,000 births', icon: 'heart-pulse' },
  'SP.DYN.TFRT.IN': { label: 'Fertility rate', fmt: (v) => num(2).format(v), unit: 'births per woman', icon: 'users' },
  'SP.POP.65UP.TO.ZS': { label: 'Aged 65 and over', fmt: (v) => `${num(1).format(v)}%`, unit: 'of population', icon: 'hourglass' },
  'SH.MED.PHYS.ZS': { label: 'Doctors', fmt: (v) => num(2).format(v), unit: 'per 1,000 people', icon: 'stethoscope' },
  'SH.MED.NUMW.P3': { label: 'Nurses & midwives', fmt: (v) => num(2).format(v), unit: 'per 1,000 people', icon: 'user' },
  'SH.MED.BEDS.ZS': { label: 'Hospital beds', fmt: (v) => num(1).format(v), unit: 'per 1,000 people', icon: 'bed' },
  'SH.XPD.CHEX.GD.ZS': { label: 'Health spending', fmt: (v) => `${num(1).format(v)}%`, unit: 'of GDP', icon: 'trending-up' },
  'SH.XPD.CHEX.PC.CD': { label: 'Spending per person', fmt: (v) => usd.format(v), unit: 'per year', icon: 'wallet' },
  'SH.IMM.MEAS': { label: 'Measles vaccination', fmt: (v) => `${num(0).format(v)}%`, unit: 'of children 12–23 months', icon: 'syringe' },
  'SH.H2O.BASW.ZS': { label: 'Drinking water', fmt: (v) => `${num(0).format(v)}%`, unit: 'with basic access', icon: 'droplet' },
  'SH.STA.BASS.ZS': { label: 'Sanitation', fmt: (v) => `${num(0).format(v)}%`, unit: 'with basic access', icon: 'droplet' },
  'SH.PRV.SMOK': { label: 'Tobacco use', fmt: (v) => `${num(0).format(v)}%`, unit: 'of adults', icon: 'cigarette' },
};

const GROUPS = [
  { title: 'Population', codes: ['SP.DYN.IMRT.IN', 'SH.STA.MMRT', 'SP.DYN.TFRT.IN', 'SP.POP.65UP.TO.ZS'] },
  { title: 'Healthcare', codes: ['SH.MED.PHYS.ZS', 'SH.MED.NUMW.P3', 'SH.MED.BEDS.ZS', 'SH.IMM.MEAS', 'SH.XPD.CHEX.GD.ZS', 'SH.XPD.CHEX.PC.CD'] },
  { title: 'Living conditions', codes: ['SH.H2O.BASW.ZS', 'SH.STA.BASS.ZS', 'SH.PRV.SMOK'] },
];

/** Neutral world position: share of reporting countries with a lower value. */
function position(h) {
  if (!h.count || h.count < 2) return '';
  const pct = Math.round(((h.count - h.rank) / h.count) * 100);
  return `Higher than ${pct}% of ${h.count} countries`;
}

function tile(h) {
  const meta = INDICATORS[h.code];
  if (!meta) return '';
  return `<div class="stat">
    <div class="k">${icon(meta.icon)}${esc(meta.label)}</div>
    <div class="v">${esc(meta.fmt(h.value))} <span class="unit">${esc(meta.unit)}</span></div>
    <div class="r">${esc(position(h))}${position(h) ? ' · ' : ''}${h.year}</div>
  </div>`;
}

// ---------------------------------------------------------------- tab

function lifeChart(c) {
  const series = c.life_expectancy_series ?? [];
  if (series.length < 2) return '';
  const first = series[0];
  const last = series[series.length - 1];
  return trendChart(series, {
    format: 'years',
    summary: `Life expectancy in ${c.name} went from ${first.value.toFixed(1)} years in ${first.year} to ${last.value.toFixed(1)} in ${last.year}.`,
  });
}

export function renderHealth(summary, c) {
  const byCode = Object.fromEntries((c.health ?? []).map((h) => [h.code, h]));
  const head = `<h1>${flag(c.iso2)}${esc(c.name)}</h1>`;
  if (!c.health?.length) {
    return `<div class="wiki">${head}<p class="muted">The World Bank doesn't publish health indicators for ${esc(c.name)}.</p></div>`;
  }

  const le = byCode['SP.DYN.LE00.IN'];
  const fe = byCode['SP.DYN.LE00.FE.IN'];
  const ma = byCode['SP.DYN.LE00.MA.IN'];
  const hero = le
    ? `<section class="le-hero">
        <div class="le-head">
          <div>
            <div class="k">${icon('heart-pulse')}Life expectancy at birth</div>
            <div class="le-value">${num(1).format(le.value)} <span>years</span></div>
            <div class="r">${esc(position(le))} · ${le.year}</div>
          </div>
          ${fe && ma ? `<dl class="le-split"><div><dt>Women</dt><dd>${num(1).format(fe.value)}</dd></div><div><dt>Men</dt><dd>${num(1).format(ma.value)}</dd></div></dl>` : ''}
        </div>
        ${lifeChart(c)}
      </section>`
    : '';

  const groups = GROUPS.map((g) => {
    const tiles = g.codes.map((code) => byCode[code]).filter(Boolean).map(tile).join('');
    return tiles ? `<h2 class="section">${esc(g.title)}</h2><div class="grid health-grid">${tiles}</div>` : '';
  }).join('');

  return `<div class="wiki">
    ${head}
    <p class="news-sub">${c.income_group ? `${esc(c.income_group)} economy · ` : ''}latest available year for each figure</p>
    ${hero}
    ${groups}
    <p class="data-credit">Source: <a href="https://data.worldbank.org/" target="_blank" rel="noopener">World Bank, World Development Indicators</a>
      (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).
      "Higher than X%" compares with the countries that report each figure.</p>
  </div>`;
}
