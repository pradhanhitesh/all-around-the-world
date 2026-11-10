// Air quality card (Health tab): current US AQI for the capital, pollutants, and a 36-hour trend.
// Data: /api/countries/:iso3/air (Open-Meteo, CAMS model). Loaded only when Health is opened.
import { icon } from './icons.js';
import { trendChart } from './chart.js';

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// US EPA AQI bands. Colour is never shown alone: every band has a label and a short note.
const BANDS = [
  { max: 50, label: 'Good', color: '#4ade80', note: 'Air quality is satisfactory.' },
  { max: 100, label: 'Moderate', color: '#facc15', note: 'Acceptable; unusually sensitive people may be affected.' },
  { max: 150, label: 'Unhealthy for sensitive groups', color: '#fb923c', note: 'Children, older adults and people with lung disease should limit long exertion outdoors.' },
  { max: 200, label: 'Unhealthy', color: '#f87171', note: 'Everyone may begin to feel effects; sensitive groups more so.' },
  { max: 300, label: 'Very unhealthy', color: '#c084fc', note: 'Health alert: everyone may experience more serious effects.' },
  { max: Infinity, label: 'Hazardous', color: '#f43f5e', note: 'Health warning of emergency conditions.' },
];
const band = (aqi) => BANDS.find((b) => aqi <= b.max);

const POLLUTANTS = [
  ['pm2_5', 'PM2.5'],
  ['pm10', 'PM10'],
  ['ozone', 'Ozone (O₃)'],
  ['nitrogen_dioxide', 'NO₂'],
  ['sulphur_dioxide', 'SO₂'],
  ['carbon_monoxide', 'CO'],
];

const fmt1 = new Intl.NumberFormat('en', { maximumFractionDigits: 1 });

// Open-Meteo returns local times without an offset ("2026-11-10T21:30"); show them as-is.
const hhmm = (t) => (t ?? '').slice(11, 16);
const dayHour = (t) => {
  const d = new Date(`${t}:00Z`); // parse as a wall-clock time; formatting in UTC keeps it unchanged
  return d.toLocaleString('en', { weekday: 'short', hour: 'numeric', timeZone: 'UTC' });
};

export function airPlaceholder() {
  return `<section class="air-card" id="air-card" aria-live="polite">
    <div class="k">${icon('wind')}Air quality now</div>
    <p class="muted">Loading air quality…</p>
  </section>`;
}

export function renderAirError(message) {
  return `<div class="k">${icon('wind')}Air quality now</div>
    <p class="muted">Air quality isn't available right now (${esc(message)}).</p>
    <button class="wiki-btn" data-action="retry-air">Try again</button>`;
}

export function renderAir(a) {
  const aqi = a.current?.us_aqi;
  if (aqi == null) {
    return `<div class="k">${icon('wind')}Air quality now</div><p class="muted">No air-quality reading for this location.</p>`;
  }
  const b = band(aqi);
  const where = a.location.kind === 'capital' ? `${esc(a.location.name)} (capital)` : `${esc(a.location.name)} (country centre)`;

  // 36-hour US AQI trend (12 h past + 24 h forecast), with a "now" marker.
  const hourly = a.hourly ?? [];
  const nowIdx = hourly.findIndex((h) => h.time >= a.time.slice(0, 13));
  const series = hourly.map((h, i) => ({ year: i, value: h.us_aqi }));
  const peak = hourly.slice(Math.max(nowIdx, 0)).reduce((m, h) => (h.us_aqi > (m?.us_aqi ?? -1) ? h : m), null);
  const chart =
    series.length > 2
      ? trendChart(series, {
          format: 'aqi',
          zero: true,
          labels: hourly.map((h) => dayHour(h.time)),
          marker: nowIdx >= 0 ? nowIdx : undefined,
          summary: `US AQI in ${a.location.name} over the past 12 hours and next 24 hours; now ${aqi}${peak ? `, forecast peak ${peak.us_aqi}` : ''}.`,
        })
      : '';

  const pollutants = POLLUTANTS.filter(([k]) => a.current[k] != null)
    .map(([k, label]) => `<div><dt>${label}</dt><dd>${fmt1.format(a.current[k])} <span>${esc(a.units?.[k] ?? '')}</span></dd></div>`)
    .join('');

  return `
    <div class="k">${icon('wind')}Air quality now · ${where}</div>
    <div class="air-head">
      <div class="air-value">${aqi}<span>US AQI</span></div>
      <div class="air-band">
        <span class="air-chip" style="--band:${b.color}"><i aria-hidden="true"></i>${esc(b.label)}</span>
        <p>${esc(b.note)}</p>
      </div>
    </div>
    ${chart ? `<h3 class="air-sub">Past 12 h and next 24 h${peak ? ` · peak ${peak.us_aqi} around ${esc(dayHour(peak.time))}` : ''}</h3>${chart}` : ''}
    <dl class="air-pollutants">${pollutants}</dl>
    <p class="data-credit">Model estimate for ${hhmm(a.time)} local time, not a ground sensor. European AQI: ${a.current.european_aqi ?? '—'}.
      Source: <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a> /
      <a href="https://atmosphere.copernicus.eu/" target="_blank" rel="noopener">CAMS</a>
      (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).</p>`;
}
