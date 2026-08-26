const fs = require('fs');
let code = fs.readFileSync('web/js/render.js', 'utf8');

// Add the new layers fetch
code = code.replace(
  "fetchJSON(`data/dong_history.json?t=${Date.now()}`).catch(() => ({}))",
  "fetchJSON(`data/dong_history.json?t=${Date.now()}`).catch(() => ({})),\n      fetchJSON(`https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo_simple.json`).catch(() => null),\n      fetchJSON(`data/mock_pipes.geojson?t=${Date.now()}`).catch(() => null),\n      fetchJSON(`data/mock_complaints.json?t=${Date.now()}`).catch(() => null)"
);

code = code.replace(
  "if (dongGeoJson) DONG_GEOJSON = dongGeoJson;",
  "if (dongGeoJson) DONG_GEOJSON = dongGeoJson;\n    const nationwideGeoJson = arguments[0][8];\n    const pipesGeoJson = arguments[0][9];\n    const complaintsData = arguments[0][10];\n    if (nationwideGeoJson) NATIONWIDE_GEOJSON = nationwideGeoJson;\n    if (pipesGeoJson) PIPES_GEOJSON = pipesGeoJson;\n    if (complaintsData) COMPLAINTS_DATA = complaintsData;"
);
// Wait, the arguments from Promise.all are destructured. Let me just use standard node string replace instead of tricky arguments[0].
