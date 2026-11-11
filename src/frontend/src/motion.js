// Tilt to explore: on phones/tablets, tilting the device rotates the globe.
// Uses the DeviceOrientation API (HTTPS only; iOS asks for permission on a user tap).
//
// The angle the device is held at when tilt starts becomes "neutral", so it works however the
// user holds it. Finger drags still work: tilt pauses during the drag and re-centres after it.

const DEG_PER_DEG = 1.6; // globe degrees per degree of device tilt
const MAX_TILT = 35; // ignore tilt beyond this (degrees from neutral), so it never spins wildly
const SMOOTHING = 0.12; // 0..1 per frame; lower = smoother/slower
const NO_DATA_MS = 1500; // no readings by then -> no usable sensor

/** Can this device plausibly do it? (touch screen + the API exists) */
export function tiltSupported() {
  return 'DeviceOrientationEvent' in window && matchMedia('(pointer: coarse)').matches;
}

/** Device tilt in screen terms: x = left/right, y = towards/away, for the current orientation. */
function screenTilt(e) {
  const angle = (screen.orientation?.angle ?? window.orientation ?? 0) % 360;
  const { beta, gamma } = e; // beta: front/back (-180..180), gamma: left/right (-90..90)
  switch ((angle + 360) % 360) {
    case 90:
      return { x: beta, y: -gamma };
    case 270:
      return { x: -beta, y: gamma };
    case 180:
      return { x: -gamma, y: -beta };
    default:
      return { x: gamma, y: beta };
  }
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function createTilt(globe, controls) {
  let on = false;
  let latest = null; // last screen tilt reading
  let neutral = null; // tilt reading that maps to the base view
  let base = null; // camera view {lat, lng, altitude} at neutral
  let target = null;
  let holdUntil = 0; // pause tilt (e.g. while the camera flies to a country)
  let dragging = false;
  let frame = 0;
  let noDataTimer = 0;
  let onFail = () => {};

  function recentre() {
    neutral = latest;
    base = globe.pointOfView();
    target = null;
  }

  function onOrientation(e) {
    if (e.beta == null || e.gamma == null) return;
    clearTimeout(noDataTimer);
    latest = screenTilt(e);
    if (!neutral) recentre();
  }

  function tick() {
    frame = requestAnimationFrame(tick);
    if (!on || !latest || !neutral || !base || dragging) return;
    if (performance.now() < holdUntil) {
      recentre(); // follow the flight, then continue from where it lands
      return;
    }
    const dx = clamp(latest.x - neutral.x, -MAX_TILT, MAX_TILT);
    const dy = clamp(latest.y - neutral.y, -MAX_TILT, MAX_TILT);
    target = {
      lat: clamp(base.lat + dy * DEG_PER_DEG, -80, 80),
      lng: base.lng - dx * DEG_PER_DEG,
    };
    const now = globe.pointOfView();
    const lng = now.lng + (((target.lng - now.lng + 540) % 360) - 180) * SMOOTHING; // shortest way round
    const lat = now.lat + (target.lat - now.lat) * SMOOTHING;
    if (Math.abs(lat - now.lat) > 0.01 || Math.abs(lng - now.lng) > 0.01) {
      globe.pointOfView({ lat, lng, altitude: now.altitude }, 0);
    }
  }

  // Finger drags take over; re-centre on release so tilt continues from the new view.
  controls.addEventListener('start', () => (dragging = true));
  controls.addEventListener('end', () => {
    dragging = false;
    if (on) recentre();
  });

  return {
    get enabled() {
      return on;
    },

    /** Must be called from a tap/click handler (iOS permission prompt). Resolves to true if on. */
    async enable(failed = () => {}) {
      onFail = failed;
      const DOE = window.DeviceOrientationEvent;
      if (typeof DOE?.requestPermission === 'function') {
        let state = 'denied';
        try {
          // Some browsers never answer (e.g. inside an embedded frame); don't hang forever.
          state = await Promise.race([
            DOE.requestPermission(),
            new Promise((resolve) => setTimeout(() => resolve('timeout'), 15000)),
          ]);
        } catch {
          /* thrown when not called from a user gesture or over HTTP */
        }
        if (state !== 'granted') {
          onFail('Motion access was not allowed. You can allow it in your browser settings.');
          return false;
        }
      }
      on = true;
      latest = neutral = base = null;
      controls.autoRotate = false;
      window.addEventListener('deviceorientation', onOrientation);
      noDataTimer = setTimeout(() => {
        if (!latest) {
          this.disable();
          onFail(location.protocol === 'https:' ? 'No motion sensor found on this device.' : 'Tilt needs a secure (https) connection.');
        }
      }, NO_DATA_MS);
      if (!frame) frame = requestAnimationFrame(tick);
      return true;
    },

    disable() {
      on = false;
      clearTimeout(noDataTimer);
      window.removeEventListener('deviceorientation', onOrientation);
      cancelAnimationFrame(frame);
      frame = 0;
    },

    /** Let a scripted camera move (country fly-to) play out, then continue tilting from there. */
    holdFor(ms) {
      holdUntil = performance.now() + ms;
    },
  };
}
