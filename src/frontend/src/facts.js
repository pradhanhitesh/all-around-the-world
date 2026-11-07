// Renders the facts panel for one country (full record from /api/countries/:iso3).
import { icon, flag } from './icons.js';
import { trendChart } from './chart.js';

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const nf = new Intl.NumberFormat('en');
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
const usdCompact = new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 });
const usd = new Intl.NumberFormat('en', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

export function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

const rankText = (rank, total) => (rank ? `#${rank} of ${total}` : '');

function highlights(c) {
  const total = c.total_countries;
  const out = [];
  const pop = c.population_rank, area = c.area_rank, gdp = c.gdp_rank, dens = c.density_rank;

  if (pop && pop <= 10) out.push(pop === 1 ? 'The most populous country on Earth' : `${ordinal(pop)} most populous country in the world`);
  if (area && area <= 10) out.push(area === 1 ? 'The largest country on Earth by area' : `${ordinal(area)} largest country by area`);
  if (gdp && gdp <= 10) out.push(gdp === 1 ? 'The largest economy in the world' : `${ordinal(gdp)} largest economy in the world`);
  if (dens && dens <= 10) out.push(`One of the most densely populated places (${ordinal(dens)})`);
  if (area && area > total - 15) out.push('One of the smallest countries or territories by area');
  if (!c.population) out.push('No permanent population on record');
  if (area && area > 10 && area <= total - 15) {
    const pct = Math.round(((total - area) / total) * 100);
    out.push(`Bigger than ${pct}% of countries and territories`);
  }
  if (c.median_age_rank && c.median_age_rank <= 10) out.push(`One of the youngest populations (median age ${c.median_age})`);
  if (c.median_age_rank_oldest && c.median_age_rank_oldest <= 10) out.push(`One of the oldest populations (median age ${c.median_age})`);
  if (c.un_member === false) out.push('Not a UN member state');
  const offsets = new Set((c.timezones ?? []).map((z) => z.gmt_offset));
  if (offsets.size > 2) out.push(`Spans ${offsets.size} UTC offsets`);
  if (c.hemisphere) out.push(`Lies in the ${c.hemisphere} hemispheres`);
  return out;
}

function localTime(zone) {
  try {
    return new Intl.DateTimeFormat('en', { timeZone: zone, hour: '2-digit', minute: '2-digit', weekday: 'short' }).format(new Date());
  } catch {
    return '';
  }
}

const stat = (ico, k, v, r = '', wide = false) =>
  v == null || v === ''
    ? ''
    : `<div class="stat${wide ? ' wide' : ''}"><div class="k">${icon(ico)}${esc(k)}</div><div class="v">${v}</div>${r ? `<div class="r">${esc(r)}</div>` : ''}</div>`;

function coords(lat, lng) {
  const f = (x, p, n) => `${Math.abs(x).toFixed(2)}° ${x >= 0 ? p : n}`;
  return `${f(lat, 'N', 'S')}, ${f(lng, 'E', 'W')}`;
}

export function renderFacts(c) {
  const total = c.total_countries;
  const tz = c.timezones ?? [];
  // Show first 3 time zones, fold the rest.
  const tzHtml =
    tz.length > 4
      ? tz.slice(0, 3).map(tzRow).join('') +
        `<details class="more"><summary>Show ${tz.length - 3} more</summary>${tz.slice(3).map(tzRow).join('')}</details>`
      : tz.map(tzRow).join('');

  const pop = c.population;
  const gdp = c.gdp_usd ?? null;

  return `
    <div class="hero">
      ${flag(c.iso2, 'flag-lg')}
      <div>
        <h1>${esc(c.name)}</h1>
        <div class="sub">${esc([c.subregion, c.region].filter(Boolean).join(' · ') || 'Unassigned region')}</div>
        ${c.income_group ? `<div class="badge">${esc(c.income_group)}</div>` : ''}
      </div>
    </div>

    <div class="capital">
      <div class="label">${icon('landmark')}Capital</div>
      <div class="value">${esc(c.capital || '—')}</div>
    </div>

    <ul class="highlights">${highlights(c).map((h) => `<li>${icon('sparkles')}<span>${esc(h)}</span></li>`).join('')}</ul>

    <div class="grid">
      ${stat('users', 'Population', pop != null ? compact.format(pop) : '—', pop != null ? `${nf.format(pop)} · ${rankText(c.population_rank, total)}` : '')}
      ${stat('maximize', 'Area', c.area_sq_km != null ? `${compact.format(c.area_sq_km)} km²` : '—', rankText(c.area_rank, total))}
      ${stat('grid', 'Density', c.population_density != null ? `${nf.format(c.population_density)} /km²` : '—', rankText(c.density_rank, total))}
      ${stat('trending-up', 'GDP', gdp ? usdCompact.format(gdp) : '—', [rankText(c.gdp_rank, total), c.gdp_year].filter(Boolean).join(' · '))}
      ${stat('wallet', 'GDP per capita', c.gdp_per_capita_usd ? usd.format(c.gdp_per_capita_usd) : '—')}
      ${stat('banknote', 'Currency', `${esc(c.currency)}`, c.currency_name)}
      ${stat('phone', 'Calling code', c.phonecode ? `+${esc(c.phonecode)}` : '—')}
      ${stat('globe', 'Internet TLD', esc(c.tld))}
      ${stat('user', 'People', esc(c.nationality))}
      ${stat('languages', 'Language', esc(c.primary_language), c.primary_language ? 'Most spoken' : '')}
      ${stat('hand-heart', 'Religion', esc(c.main_religion), c.main_religion ? 'Largest group' : '')}
      ${stat('hourglass', 'Median age', c.median_age != null ? `${c.median_age} years` : '')}
      ${stat('car', 'Drives on', c.driving_side ? `${esc(c.driving_side[0].toUpperCase() + c.driving_side.slice(1))}` : '')}
      ${stat('hash', 'ISO codes', `${esc(c.iso2)} · ${esc(c.iso3)}`, `Numeric ${c.numeric_code}`)}
      ${stat('map-pin', 'Coordinates', coords(c.latitude, c.longitude), '', true)}
    </div>

    ${gdpChart(c)}

    ${tz.length ? `<h2 class="section">${icon('clock')}Time zones · local time now</h2>${tzHtml}` : ''}

    <div class="footer-links">
      ${safeUrl(c.gov_website) ? `<a href="${esc(c.gov_website)}" target="_blank" rel="noopener noreferrer">Official website${icon('external-link', 'ico-sm')}</a>` : ''}
      ${c.wikidata_id ? `<a href="https://www.wikidata.org/wiki/${encodeURIComponent(c.wikidata_id)}" target="_blank" rel="noopener">Wikidata ${esc(c.wikidata_id)}${icon('external-link', 'ico-sm')}</a>` : ''}
    </div>
    <p class="data-credit">GDP and income group from the
      <a href="https://data.worldbank.org/" target="_blank" rel="noopener">World Bank</a>
      (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).
      Language, religion, median age, driving side and UN status from
      <a href="https://simplemaps.com/data/countries" target="_blank" rel="noopener">SimpleMaps</a>
      (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).</p>
  `;
}

// ---------------------------------------------------------------- Wikipedia reader

const ALLOWED_TAGS = new Set([
  'P', 'B', 'I', 'EM', 'STRONG', 'UL', 'OL', 'LI', 'DL', 'DT', 'DD', 'BR',
  'SUP', 'SUB', 'BLOCKQUOTE', 'H2', 'H3', 'H4', 'H5', 'H6', 'SMALL', 'SPAN',
]);
const DROP_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'IMG', 'SVG', 'MATH', 'FORM']);

/** Allowlist sanitizer for Wikipedia extract HTML: keeps basic text markup, strips all attributes. */
export function sanitize(html) {
  const doc = new DOMParser().parseFromString(`<div>${html ?? ''}</div>`, 'text/html');
  const walk = (node) => {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.COMMENT_NODE) {
        child.remove();
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        if (DROP_TAGS.has(child.tagName)) {
          child.remove();
          continue;
        }
        walk(child);
        if (!ALLOWED_TAGS.has(child.tagName)) {
          child.replaceWith(...child.childNodes); // unwrap, keep text
        } else {
          for (const attr of [...child.attributes]) child.removeAttribute(attr.name);
          if (child.tagName === 'P' && !child.textContent.trim()) child.remove();
        }
      }
    }
  };
  const root = doc.body.firstElementChild;
  walk(root);
  return root.innerHTML;
}

const VIEW_LABEL = { facts: 'facts', health: 'health data', news: 'headlines', wiki: 'Wikipedia article' };

export function renderLoading(c, view) {
  return `<div class="wiki"><h1>${flag(c.iso2)}${esc(c.name)}</h1><p class="muted">Loading ${VIEW_LABEL[view]}…</p></div>`;
}

export function renderError(c, view, message) {
  return `<div class="wiki"><h1>${flag(c.iso2)}${esc(c.name)}</h1>
    <p class="muted">Could not load ${VIEW_LABEL[view]}: ${esc(message)}</p>
    <button class="wiki-btn" data-action="retry">Try again</button></div>`;
}

// ---------------------------------------------------------------- News

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

function timeAgo(iso) {
  if (!iso) return '';
  const secs = (new Date(iso).getTime() - Date.now()) / 1000;
  const units = [['day', 86400], ['hour', 3600], ['minute', 60]];
  for (const [unit, size] of units) if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
  return 'just now';
}

const safeUrl = (u) => (/^https?:\/\//i.test(u ?? '') ? u : null);

export function renderNews(c, data) {
  const items = data.items ?? [];
  const list = items.length
    ? `<ol class="news">${items
        .map((n) => {
          const url = safeUrl(n.url);
          const title = esc(n.title);
          return `<li><a href="${esc(url ?? '#')}" target="_blank" rel="noopener noreferrer">
            <span class="news-title">${title}</span>
            <span class="news-meta">${esc(n.source)}${n.published ? ` · <time datetime="${esc(n.published)}">${esc(timeAgo(n.published))}</time>` : ''}${icon('external-link', 'ico-sm')}</span>
          </a></li>`;
        })
        .join('')}</ol>`
    : `<p class="muted">No headlines about ${esc(c.name)} in the last 7 days.</p>`;
  return `
    <div class="wiki">
      <h1>${flag(c.iso2)}${esc(c.name)}</h1>
      <p class="news-sub">Latest headlines · past 7 days</p>
      ${list}
      <p class="wiki-credit">${esc(data.attribution ?? 'Headlines via Google News')}. Articles open on the publisher's site.</p>
    </div>`;
}

export function renderWiki(c, article) {
  // Group flattened sections: level-1 sections become collapsible blocks,
  // deeper levels render as sub-headings inside them.
  const groups = [];
  for (const s of article.sections) {
    if (s.level <= 1 || !groups.length) groups.push({ title: s.title, parts: [s.html] });
    else groups.at(-1).parts.push(`<h${Math.min(s.level + 2, 6)}>${esc(s.title)}</h${Math.min(s.level + 2, 6)}>${s.html}`);
  }
  const body = groups
    .map((g) => ({ ...g, html: sanitize(g.parts.join('')) }))
    .filter((g) => g.html.trim())
    .map((g) => `<details class="wiki-section" name="wiki-sections"><summary><span>${esc(g.title)}</span>${icon('chevron-down', 'chev')}</summary><div>${g.html}</div></details>`)
    .join('');

  return `
    <article class="wiki">
      <h1>${flag(c.iso2)}${esc(article.title)}</h1>
      <div class="wiki-summary">${sanitize(article.summary_html)}</div>
      ${body}
      <p class="wiki-credit">
        ${esc(article.license)}
        <a href="${esc(article.url)}" target="_blank" rel="noopener">View original article${icon('external-link', 'ico-sm')}</a>
      </p>
    </article>`;
}

function gdpChart(c) {
  const series = c.gdp_series ?? [];
  if (series.length < 2) return '';
  const first = series[0];
  const last = series[series.length - 1];
  return `<h2 class="section">${icon('trending-up')}GDP since ${first.year}</h2>
    ${trendChart(series, {
      format: 'usd',
      zero: true,
      summary: `GDP of ${c.name} went from ${usdCompact.format(first.value)} in ${first.year} to ${usdCompact.format(last.value)} in ${last.year}, in current US dollars.`,
    })}
    <p class="chart-note">Current US$, not adjusted for inflation. Source: World Bank.</p>`;
}

function tzRow(z) {
  return `<div class="tz"><span>${esc(z.zone_name)}<br><small style="color:var(--muted)">${esc(z.tz_name ?? '')}</small></span><span>${esc(z.gmt_offset_name ?? '')}<br>${esc(localTime(z.zone_name))}</span></div>`;
}
