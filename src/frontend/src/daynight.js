// Day/night shading: a transparent sphere just above the country shapes that darkens the
// hemisphere facing away from the sun. The sun's position is computed from the current UTC time.
import { Mesh, ShaderMaterial, SphereGeometry, Vector3 } from 'three';

const DEG = Math.PI / 180;

/** Sub-solar point (where the sun is overhead) for a date: { lat, lng } in degrees. */
export function subsolarPoint(date = new Date()) {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const day = (date.getTime() - start) / 86400000; // day of year, fractional
  const g = (2 * Math.PI / 365) * (day - 1); // fractional year (radians)
  // NOAA approximations: solar declination and equation of time (minutes).
  const decl =
    0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g) +
    0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const eqTime =
    229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const utcMinutes = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  let lng = -(utcMinutes + eqTime - 720) / 4; // sun is overhead where local solar time is noon
  lng = ((lng + 540) % 360) - 180;
  return { lat: decl / DEG, lng };
}

/**
 * Add the night shade to a globe.gl instance.
 * altitude: radius offset as a fraction of the globe radius (sit above the shapes).
 */
export function createNightShade(globe, { altitude = 0.012, opacity = 0.55 } = {}) {
  const sun = new Vector3();
  const material = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { sunDir: { value: sun }, strength: { value: opacity } },
    vertexShader: `
      varying vec3 vNormal;
      void main() {
        vNormal = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 sunDir;
      uniform float strength;
      varying vec3 vNormal;
      void main() {
        float light = dot(normalize(vNormal), sunDir);
        // Soft terminator (~ twilight band), full shade on the night side.
        float night = smoothstep(0.08, -0.12, light);
        gl_FragColor = vec4(0.0, 0.016, 0.05, night * strength);
      }`,
  });
  const radius = globe.getGlobeRadius() * (1 + altitude);
  const mesh = new Mesh(new SphereGeometry(radius, 96, 64), material);
  mesh.renderOrder = 1;
  globe.scene().add(mesh);

  function update(date = new Date()) {
    const { lat, lng } = subsolarPoint(date);
    const p = globe.getCoords(lat, lng, 0);
    sun.set(p.x, p.y, p.z).normalize();
  }
  update();
  const timer = setInterval(update, 60_000);

  return {
    update,
    setVisible(on) {
      mesh.visible = on;
    },
    dispose() {
      clearInterval(timer);
      globe.scene().remove(mesh);
      mesh.geometry.dispose();
      material.dispose();
    },
  };
}
