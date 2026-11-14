// Ocean currents layer: flow lines from /data/currents.json (built nightly by a GitHub Action from
// Open-Meteo surface-current data), drawn as animated dashes moving with the flow.

// One hue, dim (slow) to bright (fast): reads on navy, satellite and dark themes alike.
export const CURRENT_RAMP = ['#1f6f8b', '#2f97b3', '#58bdd3', '#9ad9e6', '#e3f7fb'];

let data = null;
let loading = null;

/** Fetch the layer once (only when first switched on). */
export function loadCurrents() {
  if (data) return Promise.resolve(data);
  if (!loading) {
    loading = fetch('/data/currents.json', { cache: 'no-cache' })
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json();
      })
      .then((json) => (data = json))
      .finally(() => (loading = null));
  }
  return loading;
}

/** Colour for a line's mean speed, relative to the 90th-percentile speed in the data. */
export function currentColor(speed, p90) {
  const t = Math.min(1, speed / (p90 || 1));
  return CURRENT_RAMP[Math.min(CURRENT_RAMP.length - 1, Math.floor(t * CURRENT_RAMP.length))];
}

/** Configure globe.gl's paths layer for currents (call once). */
export function setupCurrentsLayer(globe) {
  globe
    .pathPoints('p')
    .pathPointLat((pt) => pt[1])
    .pathPointLng((pt) => pt[0])
    .pathPointAlt(0.004) // above the ocean, below country shapes (0.008)
    .pathStroke(null) // thin GL lines: cheap enough for ~1,000 animated lines on phones
    .pathDashLength(0.12)
    .pathDashGap(0.06)
    // Faster currents animate faster (ms for a dash to travel the whole line).
    .pathDashAnimateTime((d) => Math.max(5000, Math.min(40000, 26000 / (d.s + 0.4))))
    .pathTransitionDuration(0);
}

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

export function currentsLegend(d) {
  const p90 = d.speed_p90 ?? 1;
  return `
    <div class="legend-title">Ocean currents <span>surface speed, km/h</span></div>
    <div class="legend-ramp legend-ramp-5" aria-hidden="true">${CURRENT_RAMP.map((c) => `<i style="background:${c}"></i>`).join('')}</div>
    <div class="legend-foot"><span>Slow</span><span>${esc((p90 * 0.5).toFixed(1))}</span><span>${esc(p90.toFixed(1))}+ fast</span></div>
    <p class="legend-note">Moving dashes follow the flow. Updated ${esc((d.generated ?? '').slice(0, 10))} · 3° grid, so narrow coastal currents are smoothed · Open-Meteo / Météo-France</p>`;
}
