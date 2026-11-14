// "Colour by" metrics: shade every country on the globe by one value (a choropleth).
// One blue hue, 6 equal-count classes (each colour ~ one sixth of countries with data),
// dark = low, light = high (the dark-surface direction of a sequential ramp).

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const nf = (digits) => new Intl.NumberFormat('en', { maximumFractionDigits: digits });
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
const usdCompact = new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 });

export const METRICS = {
  life_expectancy: { label: 'Life expectancy', unit: 'years', fmt: (v) => nf(1).format(v), source: 'World Bank' },
  gdp_per_capita_usd: { label: 'GDP per person', unit: 'US$', fmt: (v) => usdCompact.format(v), source: 'World Bank' },
  median_age: { label: 'Median age', unit: 'years', fmt: (v) => nf(1).format(v), source: 'SimpleMaps' },
  population_density: { label: 'Population density', unit: 'people per km²', fmt: (v) => compact.format(v), source: 'countries dataset' },
  population: { label: 'Population', unit: 'people', fmt: (v) => compact.format(v), source: 'countries dataset' },
  fertility_rate: { label: 'Fertility rate', unit: 'births per woman', fmt: (v) => nf(2).format(v), source: 'World Bank' },
  happiness_score: { label: 'Happiness', unit: 'life evaluation, 0–10', fmt: (v) => nf(2).format(v), source: 'World Happiness Report 2026' },
};

// Sequential blue (reference palette steps 600 -> 100): dark/low to light/high on a dark surface.
export const RAMP = ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#9ec5f4', '#cde2fb'];
export const NO_DATA = 'rgba(120, 130, 145, 0.28)';
// While a metric is shown the ocean turns neutral so the darkest blue doesn't sink into it.
export const METRIC_SURFACE = { color: '#15181e', emissive: '#08090c', background: '#07080b', stroke: 'rgba(7, 8, 11, 0.85)' };

/** Equal-count breaks: returns the 5 inner thresholds splitting the values into 6 classes. */
export function quantileBreaks(values, classes = RAMP.length) {
  const v = values.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return [];
  return Array.from({ length: classes - 1 }, (_, i) => v[Math.floor(((i + 1) * v.length) / classes)]);
}

export function colorFor(value, breaks) {
  if (value == null || !Number.isFinite(value)) return NO_DATA;
  let i = 0;
  while (i < breaks.length && value >= breaks[i]) i++;
  return RAMP[i];
}

export function legend(metricId, breaks, count) {
  const m = METRICS[metricId];
  const ticks = breaks.map((b) => `<span>${esc(m.fmt(b))}</span>`).join('');
  return `
    <div class="legend-title">${esc(m.label)} <span>${esc(m.unit)}</span></div>
    <div class="legend-ramp" aria-hidden="true">${RAMP.map((c) => `<i style="background:${c}"></i>`).join('')}</div>
    <div class="legend-ticks">${ticks}</div>
    <div class="legend-foot"><span>Lower</span><span class="legend-nodata"><i aria-hidden="true"></i>No data</span><span>Higher</span></div>
    <p class="legend-note">Each shade is about a sixth of the ${count} countries with data · ${esc(m.source)}</p>`;
}

const STORAGE_KEY = 'aatw-globe-metric';
export function savedMetric() {
  try {
    const id = localStorage.getItem(STORAGE_KEY);
    return id in METRICS ? id : null;
  } catch {
    return null;
  }
}
export function saveMetric(id) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* not critical */
  }
}
