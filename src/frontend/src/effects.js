// Weather effects over the globe: falling rain/drizzle/snow (and lightning in storms) on a transparent
// canvas. Precipitation only: clear, cloudy and fog show nothing. Light on purpose: particle count scales with screen area,
// the canvas is capped at 1.5x resolution, and animation pauses when the tab is hidden.
// With reduced motion nothing is animated.

const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

const PRESETS = {
  drizzle: { per: 6500, len: [8, 13], speed: [450, 600], width: 1.1, color: 'rgba(190, 212, 255, 0.5)' },
  rain: { per: 4200, len: [12, 20], speed: [900, 1250], width: 1.1, color: 'rgba(175, 200, 255, 0.42)' },
  heavyRain: { per: 2400, len: [16, 26], speed: [1100, 1450], width: 1.3, color: 'rgba(170, 195, 255, 0.5)' },
  snow: { per: 6500, size: [1, 2.6], speed: [28, 70], color: 'rgba(240, 246, 255, 0.85)' },
  heavySnow: { per: 3500, size: [1.2, 3], speed: [40, 90], color: 'rgba(240, 246, 255, 0.9)' },
};
const SLANT = 0.18; // rain falls slightly sideways

const rand = (lo, hi) => lo + Math.random() * (hi - lo);

export function createWeatherFx(canvas) {
  const ctx = canvas.getContext('2d');
  let kind = null; // current effect kind (null = none)
  let preset = null;
  let particles = [];
  let frame = 0;
  let last = 0;
  let enabled = true;
  let nextFlash = 0;
  let flash = 0; // remaining lightning brightness 0..1
  let w = 0;
  let h = 0;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (preset) spawn();
  }

  function spawn() {
    const count = Math.round((w * h) / preset.per);
    particles = Array.from({ length: count }, () => newParticle(true));
  }

  function newParticle(anywhere) {
    const p = preset;
    if (p.size) {
      return { x: rand(0, w), y: anywhere ? rand(0, h) : rand(-20, 0), r: rand(...p.size), v: rand(...p.speed), phase: rand(0, 6.28) };
    }
    return { x: rand(-h * SLANT, w), y: anywhere ? rand(0, h) : rand(-40, 0), len: rand(...p.len), v: rand(...p.speed) };
  }

  function draw(now) {
    frame = requestAnimationFrame(draw);
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    ctx.clearRect(0, 0, w, h);
    if (!preset) return;

    if (preset.size) {
      ctx.fillStyle = preset.color;
      for (const p of particles) {
        p.y += p.v * dt;
        p.x += Math.sin(now / 900 + p.phase) * 18 * dt; // gentle sway
        if (p.y > h + 5) Object.assign(p, newParticle(false));
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
    } else {
      ctx.strokeStyle = preset.color;
      ctx.lineWidth = preset.width;
      ctx.beginPath();
      for (const p of particles) {
        p.y += p.v * dt;
        p.x += p.v * SLANT * dt;
        if (p.y > h + 30) Object.assign(p, newParticle(false));
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x - p.len * SLANT, p.y - p.len);
      }
      ctx.stroke();
    }

    if (kind === 'storm') {
      if (now > nextFlash) {
        flash = rand(0.18, 0.32);
        nextFlash = now + rand(3500, 9000);
      }
      if (flash > 0) {
        ctx.fillStyle = `rgba(220, 230, 255, ${flash})`;
        ctx.fillRect(0, 0, w, h);
        flash = Math.max(0, flash - dt * 1.6);
      }
    }
  }

  function start() {
    if (frame || !preset || document.hidden) return;
    last = performance.now();
    frame = requestAnimationFrame(draw);
  }

  function stop() {
    cancelAnimationFrame(frame);
    frame = 0;
    ctx.clearRect(0, 0, w, h);
  }

  document.addEventListener('visibilitychange', () => (document.hidden ? stop() : start()));
  window.addEventListener('resize', resize);
  resize();

  function apply() {
    const active = enabled && kind;
    preset = null;
    if (active && !reduceMotion()) {
      if (kind === 'drizzle') preset = PRESETS.drizzle;
      else if (kind === 'rain' || kind === 'storm') preset = kind === 'storm' || heavy ? PRESETS.heavyRain : PRESETS.rain;
      else if (kind === 'snow') preset = heavy ? PRESETS.heavySnow : PRESETS.snow;
    }
    stop();
    if (preset) {
      spawn();
      nextFlash = performance.now() + 1500;
      start();
    }
  }

  let heavy = false;
  return {
    /** Animate rain/drizzle/snow/storm (see weather.js describe()); other kinds and null show nothing. */
    set(nextKind, { heavy: isHeavy = false } = {}) {
      kind = nextKind;
      heavy = isHeavy;
      apply();
    },
    clear() {
      kind = null;
      apply();
    },
    setEnabled(on) {
      enabled = on;
      apply();
    },
  };
}

