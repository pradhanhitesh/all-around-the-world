// Small single-series trend chart (inline SVG) with a hover crosshair + tooltip.
// One hue, 2px line, endpoint labels only; the title outside the chart names the series.

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const usdCompact = new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 });

// How values are written on the chart (`label`) and in the tooltip (`tip`).
const FORMATS = {
  years: { label: (v) => v.toFixed(1), tip: (v) => `${v.toFixed(1)} years` },
  usd: { label: (v) => usdCompact.format(v), tip: (v) => usdCompact.format(v) },
};

const W = 320;
const H = 120;
const PAD = { l: 8, r: 8, t: 22, b: 20 };
let gradientId = 0;

/**
 * @param {{year:number, value:number}[]} series  sorted by year
 * @param {{summary:string, format:'years'|'usd', zero?:boolean}} opts
 *   zero: start the value axis at 0 (use for magnitudes like GDP).
 */
export function trendChart(series, { summary, format, zero = false }) {
  if (series.length < 2) return '';
  const fmt = FORMATS[format];
  const first = series[0];
  const last = series[series.length - 1];
  const vals = series.map((p) => p.value);
  const max = Math.max(...vals);
  const lo = zero ? 0 : Math.floor(Math.min(...vals) - 2);
  const hi = zero ? max * 1.08 : Math.ceil(max + 2);
  const x = (year) => PAD.l + ((year - first.year) / (last.year - first.year)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const line = series.map((p, i) => `${i ? 'L' : 'M'}${x(p.year).toFixed(1)},${y(p.value).toFixed(1)}`).join('');
  const area = `${line}L${x(last.year).toFixed(1)},${H - PAD.b}L${x(first.year).toFixed(1)},${H - PAD.b}Z`;
  // Start label goes below its point when the line climbs away from it, so it never sits on the line.
  const climbs = series[Math.min(5, series.length - 1)].value >= first.value;
  const firstLabelY = Math.min(climbs ? y(first.value) + 15 : y(first.value) - 8, H - PAD.b - 4);
  const points = series.map((p) => `${p.year}:${p.value}`).join(',');
  const gid = `trend-fill-${++gradientId}`;

  return `<figure class="trend-chart" data-points="${points}" data-lo="${lo}" data-hi="${hi}" data-format="${format}">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(summary)}">
      <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="var(--accent)" stop-opacity=".22"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/>
      </linearGradient></defs>
      <line class="tc-base" x1="${PAD.l}" x2="${W - PAD.r}" y1="${H - PAD.b}" y2="${H - PAD.b}"/>
      <path d="${area}" fill="url(#${gid})"/>
      <path class="tc-line" d="${line}"/>
      <circle class="tc-end" cx="${x(first.year)}" cy="${y(first.value)}" r="3"/>
      <circle class="tc-end" cx="${x(last.year)}" cy="${y(last.value)}" r="3"/>
      <text class="tc-label" x="${x(first.year) + 6}" y="${firstLabelY}" text-anchor="start">${esc(fmt.label(first.value))}</text>
      <text class="tc-label" x="${x(last.year)}" y="${y(last.value) - 8}" text-anchor="end">${esc(fmt.label(last.value))}</text>
      <text class="tc-axis" x="${PAD.l}" y="${H - 5}" text-anchor="start">${first.year}</text>
      <text class="tc-axis" x="${W - PAD.r}" y="${H - 5}" text-anchor="end">${last.year}</text>
      <g class="tc-hover" visibility="hidden">
        <line class="tc-cross" y1="${PAD.t - 6}" y2="${H - PAD.b}"/>
        <circle class="tc-dot" r="4"/>
      </g>
      <rect class="tc-hit" x="0" y="0" width="${W}" height="${H}" fill="transparent"/>
    </svg>
    <div class="tc-tip" hidden></div>
    <figcaption class="sr-only">${esc(summary)}</figcaption>
  </figure>`;
}

/** Crosshair + tooltip for any trend chart (event delegation from main.js). */
export function handleChartPointer(e) {
  const fig = e.target.closest?.('.trend-chart');
  if (!fig) return;
  const svg = fig.querySelector('svg');
  const hover = fig.querySelector('.tc-hover');
  const tip = fig.querySelector('.tc-tip');
  if (e.type === 'pointerleave') {
    hover.setAttribute('visibility', 'hidden');
    tip.hidden = true;
    fig.classList.remove('hovering');
    return;
  }
  const fmt = FORMATS[fig.dataset.format];
  const pts = fig.dataset.points.split(',').map((s) => s.split(':').map(Number));
  const lo = Number(fig.dataset.lo);
  const hi = Number(fig.dataset.hi);
  const rect = svg.getBoundingClientRect();
  const vx = ((e.clientX - rect.left) / rect.width) * W; // pointer x in viewBox units
  const [y0, y1] = [pts[0][0], pts[pts.length - 1][0]];
  const year = Math.round(y0 + ((vx - PAD.l) / (W - PAD.l - PAD.r)) * (y1 - y0));
  const [yr, val] = pts.reduce((best, p) => (Math.abs(p[0] - year) < Math.abs(best[0] - year) ? p : best));
  const cx = PAD.l + ((yr - y0) / (y1 - y0)) * (W - PAD.l - PAD.r);
  const cy = PAD.t + (1 - (val - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  hover.setAttribute('visibility', 'visible');
  fig.classList.add('hovering'); // fades endpoint labels so the tooltip never sits on them
  hover.querySelector('.tc-cross').setAttribute('x1', cx);
  hover.querySelector('.tc-cross').setAttribute('x2', cx);
  hover.querySelector('.tc-dot').setAttribute('cx', cx);
  hover.querySelector('.tc-dot').setAttribute('cy', cy);
  tip.hidden = false;
  tip.innerHTML = `<b>${esc(fmt.tip(val))}</b><span>${yr}</span>`;
  const px = (cx / W) * rect.width;
  tip.style.left = `${Math.min(Math.max(px, 48), rect.width - 48)}px`;
}
