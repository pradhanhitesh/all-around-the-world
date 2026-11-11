// Procedural starfield: points scattered on a huge sphere around the globe, so they move with
// the camera like a real sky. Nothing to download. Seeded, so every visit shows the same sky.
import { BufferGeometry, CanvasTexture, Color, Float32BufferAttribute, Group, Points, PointsMaterial } from 'three';

const RADIUS = 20000; // well behind the globe (radius 100), well inside the camera's far plane

// Many faint stars, fewer medium, a handful of bright ones (pixel sizes; no distance scaling).
// Sizes include the soft edge of the round sprite below, so they're a bit larger than the visible core.
const TIERS = [
  { count: 1900, size: 2.2, brightness: [0.3, 0.6] },
  { count: 450, size: 3.2, brightness: [0.55, 0.85] },
  { count: 70, size: 5, brightness: [0.85, 1] },
];

/** Soft round dot (points are square by default): a radial gradient drawn into a small canvas. */
function roundSprite() {
  const size = 32;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.35, 'rgba(255,255,255,0.85)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new CanvasTexture(canvas);
}

// Star colours: mostly white, some blue-white and some warm.
const TINTS = ['#ffffff', '#ffffff', '#ffffff', '#cfdcff', '#bcd0ff', '#fff1d6', '#ffe0b8'];

function mulberry32(seed) {
  return () => {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** pixelRatio: the renderer's pixel ratio (point sizes are in device pixels). */
export function createStarfield(globe, { seed = 1977, pixelRatio = 1 } = {}) {
  const rand = mulberry32(seed);
  const group = new Group();
  const color = new Color();
  const sprite = roundSprite();

  for (const tier of TIERS) {
    const positions = new Float32Array(tier.count * 3);
    const colors = new Float32Array(tier.count * 3);
    for (let i = 0; i < tier.count; i++) {
      // Uniform direction on a sphere.
      const z = rand() * 2 - 1;
      const a = rand() * Math.PI * 2;
      const r = Math.sqrt(1 - z * z);
      positions.set([RADIUS * r * Math.cos(a), RADIUS * r * Math.sin(a), RADIUS * z], i * 3);
      const [lo, hi] = tier.brightness;
      const b = lo + rand() * (hi - lo);
      color.set(TINTS[Math.floor(rand() * TINTS.length)]).multiplyScalar(b);
      colors.set([color.r, color.g, color.b], i * 3);
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
    const material = new PointsMaterial({
      size: tier.size * pixelRatio,
      map: sprite,
      alphaTest: 0.01,
      sizeAttenuation: false,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
    });
    group.add(new Points(geometry, material));
  }

  group.renderOrder = -1; // draw before everything else
  globe.scene().add(group);

  return {
    setVisible(on) {
      group.visible = on;
    },
  };
}
