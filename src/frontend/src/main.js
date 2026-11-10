import Globe from 'globe.gl';
import { Color } from 'three';
import { inject as injectAnalytics } from '@vercel/analytics';
import { feature } from 'topojson-client';
import worldTopo from 'world-atlas/countries-110m.json';
import { renderFacts, renderWiki, renderNews, renderLoading, renderError } from './facts.js';
import { flag, icon } from './icons.js';
import { renderHealth } from './health.js';
import { handleChartPointer } from './chart.js';
import { THEMES, savedTheme, saveTheme } from './themes.js';

// Atlas features without an ISO numeric id -> country they belong to (by UN recognition).
const NAMELESS_FEATURE_MAP = { Kosovo: 'XKX', 'N. Cyprus': 'CYP', Somaliland: 'SOM' };

// Active globe theme (see themes.js); remembered per visitor.
let theme = THEMES[savedTheme()];

const $ = (sel) => document.querySelector(sel);

// Vercel Web Analytics (page views). The script and beacon are served same-origin under
// /_vercel/insights, so the CSP needs no changes. Skipped locally, where /_vercel doesn't exist.
if (import.meta.env.PROD && !['localhost', '127.0.0.1'].includes(location.hostname)) {
  injectAnalytics({ mode: 'production' });
}
// Must match the breakpoints in style.css.
const desktopMQ = matchMedia('(min-width: 1024px)');
const phoneMQ = matchMedia('(max-width: 639.98px)');
const isDesktop = () => desktopMQ.matches;
const isPhone = () => phoneMQ.matches;

const state = {
  countries: [], // summary list
  byIso3: new Map(),
  cache: new Map(), // `${view}:${iso3}` -> { data, at } (resolved)
  pending: new Map(), // `${view}:${iso3}` -> in-flight promise (dedupes prefetch + open)
  view: 'facts', // 'facts' | 'news' | 'wiki'
  polygons: [],
  selected: null, // iso3
  hovered: null, // polygon feature
};

// ---------------------------------------------------------------- data
const HTTP_MESSAGES = {
  429: "you're going a bit fast — wait a few seconds and try again",
  502: 'the source is unavailable right now',
  503: 'the server is busy — try again shortly',
};

async function api(path, init) {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(HTTP_MESSAGES[res.status] ?? `${res.status} ${res.statusText}`);
  return res.json();
}

// Each sheet tab is one view: where its data lives, how to render it, how long it stays fresh.
const VIEWS = {
  facts: {
    label: 'Facts',
    icon: 'info',
    url: (iso3) => `/api/countries/${iso3}`,
    render: (c, d) => renderFacts(d),
    // Always revalidate: facts change only on deploy, and an older build told browsers to
    // keep them for an hour. 'no-cache' ignores any such stale copy (the CDN still answers fast).
    fetch: { cache: 'no-cache' },
  },
  // Health uses the facts record (World Bank data is part of it), so no extra request.
  health: { label: 'Health', icon: 'heart-pulse', source: 'facts', render: renderHealth },
  news: {
    label: 'News',
    icon: 'newspaper',
    url: (iso3) => `/api/countries/${iso3}/news`,
    render: renderNews,
    ttl: 15 * 60 * 1000, // matches the server-side cache
  },
  wiki: { label: 'Wikipedia', icon: 'book-open', url: (iso3) => `/api/countries/${iso3}/wiki`, render: renderWiki },
};

// Views can share another view's data (health -> facts); cache and fetch by the source view.
const sourceOf = (view) => VIEWS[view].source ?? view;

function cached(view, iso3) {
  view = sourceOf(view);
  const hit = state.cache.get(`${view}:${iso3}`);
  const ttl = VIEWS[view].ttl;
  return hit && (!ttl || Date.now() - hit.at < ttl) ? hit.data : undefined;
}

function load(view, iso3) {
  view = sourceOf(view);
  const key = `${view}:${iso3}`;
  const hit = cached(view, iso3);
  if (hit) return Promise.resolve(hit);
  if (!state.pending.has(key)) {
    const p = api(VIEWS[view].url(iso3), VIEWS[view].fetch)
      .then((data) => {
        state.cache.set(key, { data, at: Date.now() });
        return data;
      })
      .finally(() => state.pending.delete(key)); // failed fetches can be retried
    state.pending.set(key, p);
  }
  return state.pending.get(key);
}

/** Warm the other tabs in the background so switching is instant. Errors surface only when opened. */
function prefetchOthers(iso3, current) {
  const sources = new Set(Object.keys(VIEWS).map(sourceOf));
  sources.delete(sourceOf(current));
  for (const view of sources) load(view, iso3).catch(() => {});
}

// ---------------------------------------------------------------- globe
const globe = new Globe($('#globe'), { animateIn: true })
  .showAtmosphere(true)
  .atmosphereAltitude(0.18)
  .polygonAltitude((d) => (d.iso3 === state.selected ? 0.05 : d === state.hovered ? 0.02 : 0.008))
  .polygonCapColor((d) => theme.cap(d.country?.region, shapeState(d)))
  .polygonSideColor((d) => theme.side(shapeState(d)))
  .polygonStrokeColor(() => theme.stroke)
  .polygonLabel((d) => tooltip(d.country))
  .polygonsTransitionDuration(250)
  .onPolygonHover((d) => {
    state.hovered = d && d.country ? d : null;
    globe.polygonAltitude(globe.polygonAltitude()).polygonCapColor(globe.polygonCapColor()); // re-evaluate accessors
    $('#globe').style.cursor = state.hovered ? 'pointer' : 'grab';
  })
  .onPolygonClick((d) => d.country && select(d.iso3))
  // Small countries & islands not in the 110m atlas are drawn as dots.
  .pointLat('latitude')
  .pointLng('longitude')
  .pointAltitude((d) => (d.iso3 === state.selected ? 0.06 : 0.012))
  .pointRadius((d) => (d.iso3 === state.selected ? 0.9 : 0.55))
  .pointColor((d) => theme.point(d.region, { selected: d.iso3 === state.selected }))
  .pointLabel((d) => tooltip(d))
  .pointsMerge(false)
  .onPointClick((d) => select(d.iso3))
  .onPointHover((d) => ($('#globe').style.cursor = d ? 'pointer' : 'grab'))
  // Pulsing ring around the selection.
  .ringLat('latitude')
  .ringLng('longitude')
  .ringColor(() => (t) => `rgba(255, 209, 102, ${1 - t})`)
  .ringMaxRadius(4)
  .ringPropagationSpeed(2.5)
  .ringRepeatPeriod(1100)
  .onGlobeClick(() => {}); // keep panel open on ocean taps

globe.renderer().setPixelRatio(Math.min(window.devicePixelRatio, 2));

// ---------------------------------------------------------------- theme menu
const themeBtn = $('#theme-btn');
const themeMenu = $('#theme-menu');
themeMenu.innerHTML = Object.entries(THEMES)
  .map(
    ([id, t]) => `<button role="menuitemradio" data-theme="${id}" aria-checked="false">
      <span class="swatch" aria-hidden="true">${t.swatch.map((c) => `<i style="background:${c}"></i>`).join('')}</span>
      <span>${t.label}</span></button>`,
  )
  .join('');

function setThemeMenu(open) {
  themeMenu.hidden = !open;
  themeBtn.setAttribute('aria-expanded', String(open));
  if (open) themeMenu.querySelector('[aria-checked="true"]')?.focus();
}
themeBtn.addEventListener('click', () => setThemeMenu(themeMenu.hidden));
themeMenu.addEventListener('click', (e) => {
  const id = e.target.closest('[data-theme]')?.dataset.theme;
  if (!id) return;
  applyTheme(id);
  saveTheme(id);
  setThemeMenu(false);
  themeBtn.focus();
});
themeMenu.addEventListener('keydown', (e) => {
  const items = [...themeMenu.querySelectorAll('[data-theme]')];
  const i = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
  } else if (e.key === 'Escape') {
    e.stopPropagation(); // don't also close the country panel
    setThemeMenu(false);
    themeBtn.focus();
  }
});
document.addEventListener('pointerdown', (e) => {
  if (!themeMenu.hidden && !e.target.closest('.theme-wrap')) setThemeMenu(false);
});

const controls = globe.controls();
controls.autoRotate = true;
controls.autoRotateSpeed = 0.35;
controls.enableDamping = true;
controls.minDistance = 130;
controls.maxDistance = 600;

function shapeState(d) {
  return { known: Boolean(d.country), selected: d.iso3 === state.selected, hovered: d === state.hovered };
}

/** Make the surface texture self-lit (night lights). The texture loads asynchronously, so wait for it. */
let glowToken = 0;
function setGlow(intensity) {
  const material = globe.globeMaterial();
  const token = ++glowToken;
  if (!intensity) {
    material.emissiveMap = null;
    material.emissiveIntensity = 1;
    material.needsUpdate = true;
    return;
  }
  const url = theme.image;
  const started = performance.now();
  (function wait() {
    if (token !== glowToken) return; // theme changed meanwhile
    const tex = material.map;
    if (tex?.image && (tex.image.currentSrc || tex.image.src || '').includes(url)) {
      material.emissiveMap = tex;
      material.emissive.set('#ffffff');
      material.emissiveIntensity = intensity;
      material.needsUpdate = true;
    } else if (performance.now() - started < 15000) {
      requestAnimationFrame(wait);
    }
  })();
}

/** Apply a globe theme: surface, imagery, atmosphere and country styling. */
function applyTheme(id) {
  theme = THEMES[id];
  const material = globe.globeMaterial();
  // three-globe sets material.color to null once a texture loads; recreate it when needed.
  if (material.color) material.color.set(theme.ocean.color);
  else material.color = new Color(theme.ocean.color);
  material.emissive.set(theme.ocean.emissive);
  if (!theme.image && material.map) {
    // three-globe doesn't remove the old texture when the image is cleared; do it here.
    material.map.dispose();
    material.map = null;
  }
  material.needsUpdate = true;
  globe
    .backgroundColor(theme.background)
    .atmosphereColor(theme.atmosphere)
    .globeImageUrl(theme.image) // textures load only when a theme that uses one is picked
    .polygonStrokeColor(globe.polygonStrokeColor())
    .polygonSideColor(globe.polygonSideColor());
  setGlow(theme.glow ?? 0);
  refreshLayers();
  document.documentElement.dataset.globeTheme = id;
  for (const item of document.querySelectorAll('#theme-menu [data-theme]')) {
    item.setAttribute('aria-checked', String(item.dataset.theme === id));
  }
}

function tooltip(c) {
  if (!c) return '';
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
  return `<div class="globe-tip">${flag(c.iso2)}<span class="globe-tip-text"><b>${esc(c.name)}</b>${
    c.capital ? `<small>${esc(c.capital)}</small>` : ''
  }</span></div>`;
}

// Size the canvas to #globe's box (window resizes). Opening the laptop side panel doesn't
// resize it: CSS slides the whole canvas with a transform instead, which stays smooth.
const globeEl = $('#globe');
new ResizeObserver(([entry]) => {
  const { width, height } = entry.contentRect;
  if (width && height) globe.width(width).height(height);
}).observe(globeEl);

// Stop spinning once the user grabs the globe.
$('#globe').addEventListener('pointerdown', () => (controls.autoRotate = false), { passive: true });

// ---------------------------------------------------------------- selection
async function select(iso3, { fly = true, view = 'facts' } = {}) {
  const summary = state.byIso3.get(iso3);
  if (!summary) return;
  const changed = state.selected !== iso3;
  state.selected = iso3;
  controls.autoRotate = false;

  if (changed) {
    refreshLayers();
    globe.ringsData([summary]);
    if (fly) flyTo(summary);
  }
  return showView(iso3, view in VIEWS ? view : 'facts');
}

function setHash(iso3, view) {
  const hash = `#/${iso3}${view === 'facts' ? '' : `/${view}`}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

async function showView(iso3, view) {
  const summary = state.byIso3.get(iso3);
  const sameScreen = state.view === view && !sheet.hidden && $('#sheet-body').dataset.key === `${view}:${iso3}`;
  state.view = view;
  setHash(iso3, view);
  updateTabs(view);
  prefetchOthers(iso3, view);

  const hit = cached(view, iso3);
  if (!sameScreen) openSheet(hit ? VIEWS[view].render(summary, hit) : renderLoading(summary, view), `${view}:${iso3}`);
  if (hit) return;
  const stillHere = () => state.selected === iso3 && state.view === view;
  try {
    const data = await load(view, iso3);
    if (stillHere()) $('#sheet-body').innerHTML = VIEWS[view].render(summary, data);
  } catch (err) {
    if (stillHere()) $('#sheet-body').innerHTML = renderError(summary, view, err.message);
  }
}

function deselect() {
  state.selected = null;
  globe.ringsData([]);
  refreshLayers();
  closeSheet();
  history.replaceState(null, '', location.pathname);
}

function refreshLayers() {
  // Re-trigger accessors so colours/altitudes update.
  globe
    .polygonCapColor(globe.polygonCapColor())
    .polygonSideColor(globe.polygonSideColor())
    .polygonAltitude(globe.polygonAltitude());
  globe.pointColor(globe.pointColor()).pointAltitude(globe.pointAltitude()).pointRadius(globe.pointRadius());
}

function flyTo(c) {
  const area = c.area_sq_km ?? 1000;
  const altitude = Math.min(2.2, Math.max(0.9, 0.75 + Math.sqrt(area) / 2500));
  let { latitude: lat, longitude: lng } = c;
  // Phone/tablet: the bottom sheet covers the lower part of the screen, so aim the camera
  // lower to place the country in the visible strip above it. Laptop: the globe already
  // shrinks beside the panel, so no nudge is needed.
  if (!isDesktop()) lat -= altitude * (isPhone() ? 13 : 11);
  globe.pointOfView({ lat, lng, altitude }, 1200);
}

// ---------------------------------------------------------------- sheet
const sheet = $('#sheet');

function openSheet(html, key) {
  const body = $('#sheet-body');
  body.innerHTML = html;
  body.dataset.key = key;
  body.scrollTop = 0;
  sheet.hidden = false;
  document.body.classList.add('panel-open');
}

// Tab bar: Facts · News · Wikipedia
const tabs = $('#tabs');
tabs.innerHTML = Object.entries(VIEWS)
  .map(([view, v]) => `<button role="tab" data-view="${view}" aria-selected="false">${icon(v.icon)}<span>${v.label}</span></button>`)
  .join('');

function updateTabs(view) {
  for (const b of tabs.children) {
    const on = b.dataset.view === view;
    b.setAttribute('aria-selected', on);
    b.tabIndex = on ? 0 : -1;
  }
}

tabs.addEventListener('click', (e) => {
  const view = e.target.closest('[data-view]')?.dataset.view;
  if (view && state.selected && view !== state.view) showView(state.selected, view);
});
tabs.addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  const order = Object.keys(VIEWS);
  const next = order[(order.indexOf(state.view) + (e.key === 'ArrowRight' ? 1 : -1) + order.length) % order.length];
  showView(state.selected, next);
  tabs.querySelector(`[data-view="${next}"]`).focus();
});

function closeSheet() {
  sheet.hidden = true;
  document.body.classList.remove('panel-open');
}

// Wikipedia reader: one section open at a time, and scroll the opened one to the top.
// <details name="..."> gives native exclusivity in modern browsers; the loop is a fallback.
$('#sheet-body').addEventListener(
  'toggle',
  (e) => {
    const opened = e.target;
    if (!opened.matches?.('details.wiki-section') || !opened.open) return;
    for (const d of $('#sheet-body').querySelectorAll('details.wiki-section[open]')) if (d !== opened) d.open = false;
    // Reading the rects forces layout after the other sections collapsed.
    const body = $('#sheet-body');
    const top = opened.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
    body.scrollTo({ top, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  },
  true, // 'toggle' doesn't bubble; listen in the capture phase
);

// Trend chart hover (crosshair + tooltip): GDP in Facts, life expectancy in Health.
for (const type of ['pointermove', 'pointerdown']) $('#sheet-body').addEventListener(type, handleChartPointer);
// pointerleave doesn't bubble; capture it, but only act when the chart itself is left.
$('#sheet-body').addEventListener('pointerleave', (e) => e.target.classList?.contains('trend-chart') && handleChartPointer(e), true);

// "Try again" after a failed load.
$('#sheet-body').addEventListener('click', (e) => {
  if (e.target.closest('[data-action="retry"]') && state.selected) {
    $('#sheet-body').dataset.key = '';
    showView(state.selected, state.view);
  }
});

$('#close').addEventListener('click', deselect);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !sheet.hidden) deselect();
});

// Drag the handle down to dismiss (mobile).
{
  let startY = null;
  let dy = 0;
  const handle = $('#handle');
  handle.addEventListener('pointerdown', (e) => {
    if (isDesktop()) return;
    startY = e.clientY;
    dy = 0;
    sheet.classList.add('dragging');
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', (e) => {
    if (startY == null) return;
    dy = Math.max(0, e.clientY - startY);
    sheet.style.transform = `translateY(${dy}px)`;
  });
  const end = () => {
    if (startY == null) return;
    startY = null;
    sheet.classList.remove('dragging');
    sheet.style.transform = '';
    if (dy > 80) deselect();
  };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
}

// ---------------------------------------------------------------- search
const input = $('#search');
const results = $('#results');
const searchBox = $('.search');
const searchToggle = $('#search-toggle');

function openSearch() {
  searchBox.classList.add('open');
  searchToggle.setAttribute('aria-expanded', 'true');
  input.tabIndex = 0;
  input.focus(); // synchronous inside the tap handler so mobile keyboards open
}

function closeSearch() {
  input.value = '';
  results.hidden = true;
  searchBox.classList.remove('open');
  searchToggle.setAttribute('aria-expanded', 'false');
  input.tabIndex = -1;
  input.blur();
}

searchToggle.addEventListener('click', openSearch);
input.addEventListener('blur', () => {
  // Collapse when focus leaves an empty field.
  if (!input.value.trim()) setTimeout(() => document.activeElement !== input && closeSearch(), 150);
});
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && document.activeElement !== input) {
    e.preventDefault();
    openSearch();
  }
});
let matches = [];
let active = 0;

function normalize(s) {
  return (s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function runSearch() {
  const q = normalize(input.value.trim());
  if (!q) {
    results.hidden = true;
    return;
  }
  const score = (c) => {
    const n = normalize(c.name), cap = normalize(c.capital);
    if (n.startsWith(q) || c.iso3.toLowerCase() === q || c.iso2.toLowerCase() === q) return 0;
    if (cap.startsWith(q)) return 1;
    if (n.includes(q)) return 2;
    if (cap.includes(q)) return 3;
    return -1;
  };
  matches = state.countries
    .map((c) => [score(c), c])
    .filter(([s]) => s >= 0)
    .sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name))
    .slice(0, 8)
    .map(([, c]) => c);
  active = 0;
  results.innerHTML = matches.length
    ? matches
        .map(
          (c, i) =>
            `<li role="option" data-iso3="${c.iso3}" aria-selected="${i === active}">${flag(c.iso2)}<span>${c.name}<small>${c.capital ?? '—'} · ${c.region ?? ''}</small></span></li>`,
        )
        .join('')
    : '<li>No matches</li>';
  results.hidden = false;
}

function pick(iso3) {
  closeSearch(); // also dismisses the mobile keyboard
  select(iso3);
}

input.addEventListener('input', runSearch);
input.addEventListener('focus', runSearch);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    e.stopPropagation(); // don't also close the facts sheet
    closeSearch();
    return;
  }
  if (results.hidden || !matches.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    active = (active + (e.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
    [...results.children].forEach((li, i) => li.setAttribute('aria-selected', i === active));
  } else if (e.key === 'Enter') {
    pick(matches[active].iso3);
  }
});
results.addEventListener('pointerdown', (e) => {
  const li = e.target.closest('li[data-iso3]');
  if (li) {
    e.preventDefault();
    pick(li.dataset.iso3);
  }
});
document.addEventListener('pointerdown', (e) => {
  if (!e.target.closest('.search')) results.hidden = true;
});

$('#random').addEventListener('click', () => {
  const pool = state.countries.filter((c) => c.iso3 !== state.selected);
  select(pool[Math.floor(Math.random() * pool.length)].iso3);
});

// ---------------------------------------------------------------- routing
function fromHash() {
  const m = location.hash.match(/^#\/([A-Za-z]{3})(?:\/(health|news|wiki))?$/);
  if (!m) return;
  const iso3 = m[1].toUpperCase();
  const view = m[2] ?? 'facts';
  if (iso3 !== state.selected || view !== state.view) select(iso3, { view });
}
window.addEventListener('hashchange', fromHash);

// ---------------------------------------------------------------- boot
async function boot() {
  const { countries } = await api('/api/countries', { cache: 'no-cache' });
  state.countries = countries;
  for (const c of countries) state.byIso3.set(c.iso3, c);
  const byNumeric = new Map(countries.map((c) => [String(c.numeric_code).padStart(3, '0'), c]));

  const features = feature(worldTopo, worldTopo.objects.countries).features;
  const drawn = new Set();
  state.polygons = features
    .filter((f) => f.properties.name !== 'Antarctica' || byNumeric.has('010'))
    .map((f) => {
      const country = f.id ? byNumeric.get(f.id) : state.byIso3.get(NAMELESS_FEATURE_MAP[f.properties.name]);
      if (country) drawn.add(country.iso3);
      return Object.assign(f, { country, iso3: country?.iso3 });
    });

  const dots = countries.filter((c) => !drawn.has(c.iso3) && c.latitude != null);
  globe.polygonsData(state.polygons).pointsData(dots);

  $('#loading').remove();
  globe.pointOfView({ lat: 20, lng: 78, altitude: isPhone() ? 3.2 : 2.4 });
  fromHash();
}

// Apply the visitor's saved globe theme (after every helper above is defined).
applyTheme(savedTheme());

boot().catch((err) => {
  $('#loading').textContent = `Failed to load data: ${err.message}. Is the API running on :8000?`;
  console.error(err);
});
