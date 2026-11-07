// Stand-in for h3-js (~540 KB). three-globe imports it only for the hexBin and
// hexPolygons layers, which this app doesn't use. If you enable those layers,
// remove the alias in vite.config.js.
const unavailable = (name) => () => {
  throw new Error(`h3-js.${name} is stubbed out (see src/stubs/h3-js.js)`);
};
export const latLngToCell = unavailable('latLngToCell');
export const cellToLatLng = unavailable('cellToLatLng');
export const cellToBoundary = unavailable('cellToBoundary');
export const polygonToCells = unavailable('polygonToCells');
