// Current weather at the capital (Open-Meteo) for the Facts tab, and the effect it drives on the globe.
import { icon } from './icons.js';

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/**
 * WMO weather code -> label, icon (day/night) and effect kind.
 * Effect kinds: clear | cloudy | fog | drizzle | rain | snow | storm.
 */
export function describe(code, isDay) {
  const day = isDay !== 0;
  if (code === 0) return { label: day ? 'Clear sky' : 'Clear night', icon: day ? 'sun' : 'moon', kind: 'clear' };
  if (code === 1) return { label: 'Mainly clear', icon: day ? 'cloud-sun' : 'cloud-moon', kind: 'clear' };
  if (code === 2) return { label: 'Partly cloudy', icon: day ? 'cloud-sun' : 'cloud-moon', kind: 'cloudy' };
  if (code === 3) return { label: 'Overcast', icon: 'cloud', kind: 'cloudy' };
  if (code === 45 || code === 48) return { label: 'Fog', icon: 'cloud-fog', kind: 'fog' };
  if (code >= 51 && code <= 57) return { label: code >= 56 ? 'Freezing drizzle' : 'Drizzle', icon: 'cloud-drizzle', kind: 'drizzle' };
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) {
    const heavy = [65, 67, 82].includes(code);
    const label = code >= 80 ? 'Rain showers' : code >= 66 ? 'Freezing rain' : heavy ? 'Heavy rain' : 'Rain';
    return { label, icon: 'cloud-rain', kind: 'rain', heavy };
  }
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) {
    return { label: code >= 85 ? 'Snow showers' : 'Snow', icon: 'cloud-snow', kind: 'snow', heavy: [75, 86].includes(code) };
  }
  if (code >= 95) return { label: code >= 96 ? 'Thunderstorm with hail' : 'Thunderstorm', icon: 'cloud-lightning', kind: 'storm', heavy: true };
  return { label: 'Unknown', icon: 'cloud', kind: 'cloudy' };
}

export function weatherPlaceholder() {
  return `<section class="air-card weather-card" id="weather-card" aria-live="polite">
    <div class="k">${icon('cloud-sun')}Weather now</div>
    <p class="muted">Checking the weather…</p>
  </section>`;
}

export function renderWeatherError(message) {
  return `<div class="k">${icon('cloud')}Weather now</div>
    <p class="muted">Weather isn't available right now (${esc(message)}).</p>
    <button class="wiki-btn" data-action="retry-weather">Try again</button>`;
}

const round = (v) => (v == null ? '—' : Math.round(v));

export function renderWeather(w) {
  const c = w.current ?? {};
  const d = describe(c.weather_code, c.is_day);
  const where = w.location.kind === 'capital' ? esc(w.location.name) : `${esc(w.location.name)} (centre)`;
  const local = (w.time ?? '').slice(11, 16);
  return `
    <div class="k">${icon(d.icon)}Weather now · ${where}</div>
    <div class="weather-head">
      <div class="air-value">${round(c.temperature_2m)}<span>°C</span></div>
      <div class="weather-desc">
        <b>${esc(d.label)}</b>
        <p>Feels like ${round(c.apparent_temperature)}°C · ${local} local time</p>
      </div>
    </div>
    <dl class="air-pollutants weather-stats">
      <div><dt>${icon('droplets')}Humidity</dt><dd>${round(c.relative_humidity_2m)}<span>%</span></dd></div>
      <div><dt>${icon('wind')}Wind</dt><dd>${round(c.wind_speed_10m)}<span> km/h</span></dd></div>
      <div><dt>${icon('cloud')}Cloud</dt><dd>${round(c.cloud_cover)}<span>%</span></dd></div>
    </dl>
    <p class="data-credit">Source: <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>
      (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).</p>`;
}
