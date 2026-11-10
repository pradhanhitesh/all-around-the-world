// Globe themes. Each one sets the globe surface, atmosphere and how country shapes are drawn.
// The UI (panel, tooltips) stays the same across themes.

const SELECTED = '#ffd166';

const REGION_COLORS = {
  Africa: '#e4a35a',
  Americas: '#6cc28b',
  Asia: '#e2725b',
  Europe: '#6fa8dc',
  Oceania: '#b48ad6',
  Polar: '#cfd8e3',
};
const OTHER_REGION = '#9aa5b5';

function lighten(hex, amount = 0.35) {
  const n = parseInt(hex.slice(1), 16);
  const mix = (c) => Math.round(c + (255 - c) * amount);
  return `rgb(${mix(n >> 16)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
}

/**
 * cap(region, { hovered, selected, known }) -> fill colour for a country shape.
 * image: optional texture URL for the globe surface (served from /public, loaded only when used).
 */
export const THEMES = {
  regions: {
    label: 'Regions',
    swatch: ['#e2725b', '#6fa8dc', '#0d2240'],
    background: '#070b14',
    atmosphere: '#4f8fff',
    ocean: { color: '#0d2240', emissive: '#06101f' },
    image: null,
    stroke: 'rgba(7, 11, 20, 0.6)',
    side: () => 'rgba(0, 0, 0, 0.25)',
    cap(region, s) {
      if (!s.known) return 'rgba(120, 130, 145, 0.35)';
      if (s.selected) return SELECTED;
      const base = REGION_COLORS[region] ?? OTHER_REGION;
      return s.hovered ? lighten(base) : base;
    },
    point: (region, s) => (s.selected ? SELECTED : REGION_COLORS[region] ?? OTHER_REGION),
  },

  realistic: {
    label: 'Satellite',
    swatch: ['#2f6b3a', '#1f4f8a', '#c9b48a'],
    background: '#05070d',
    atmosphere: '#8ec5ff',
    // The texture is multiplied by the surface colour, so keep it white to show true colours.
    ocean: { color: '#ffffff', emissive: '#000000' },
    image: '/textures/earth-blue-marble.jpg',
    stroke: 'rgba(255, 255, 255, 0.35)',
    side: (s) => (s.selected ? 'rgba(255, 209, 102, 0.35)' : 'rgba(0, 0, 0, 0)'),
    cap(region, s) {
      if (s.selected) return 'rgba(255, 209, 102, 0.55)';
      if (s.hovered && s.known) return 'rgba(255, 255, 255, 0.22)';
      return 'rgba(0, 0, 0, 0)'; // imagery shows through
    },
    point: (region, s) => (s.selected ? SELECTED : 'rgba(255, 255, 255, 0.85)'),
  },

  mono: {
    label: 'Monochrome',
    swatch: ['#4a566b', '#2c3445', '#0b1220'],
    background: '#070b14',
    atmosphere: '#5b6b85',
    ocean: { color: '#0b1220', emissive: '#05080f' },
    image: null,
    stroke: 'rgba(7, 11, 20, 0.85)',
    side: () => 'rgba(0, 0, 0, 0.3)',
    cap(region, s) {
      if (!s.known) return 'rgba(74, 86, 107, 0.45)';
      if (s.selected) return SELECTED;
      return s.hovered ? '#6b7a94' : '#3d4859';
    },
    point: (region, s) => (s.selected ? SELECTED : '#8a96ab'),
  },

  night: {
    label: 'Night lights',
    swatch: ['#ffcf70', '#1a2440', '#03050a'],
    background: '#020308',
    atmosphere: '#3557c4',
    ocean: { color: '#ffffff', emissive: '#000000' },
    image: '/textures/earth-night.jpg',
    glow: 0.9, // city lights shine on their own (texture also drives the emissive channel)
    stroke: 'rgba(255, 209, 102, 0.22)',
    side: (s) => (s.selected ? 'rgba(255, 209, 102, 0.3)' : 'rgba(0, 0, 0, 0)'),
    cap(region, s) {
      if (s.selected) return 'rgba(255, 209, 102, 0.45)';
      if (s.hovered && s.known) return 'rgba(255, 209, 102, 0.14)';
      return 'rgba(0, 0, 0, 0)';
    },
    point: (region, s) => (s.selected ? SELECTED : 'rgba(255, 209, 102, 0.75)'),
  },
};

export const DEFAULT_THEME = 'regions';
const STORAGE_KEY = 'aatw-globe-theme';

export function savedTheme() {
  try {
    const id = localStorage.getItem(STORAGE_KEY);
    return id in THEMES ? id : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME; // private mode / blocked storage
  }
}

export function saveTheme(id) {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* not critical */
  }
}
