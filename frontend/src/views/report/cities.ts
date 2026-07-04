// A small city → lat/lon lookup so the geomap can plot nodes from the enriched
// hop city names (enrichment stores city names, not coordinates). Unknown cities
// fall back to the route-strip renderer. Kept intentionally small — extend as
// needed; not authoritative geography.
const CITIES: Record<string, [number, number]> = {
  berlin: [52.52, 13.405],
  frankfurt: [50.11, 8.68],
  "frankfurt am main": [50.11, 8.68],
  amsterdam: [52.37, 4.9],
  london: [51.51, -0.13],
  paris: [48.86, 2.35],
  madrid: [40.42, -3.7],
  milan: [45.46, 9.19],
  munich: [48.14, 11.58],
  hamburg: [53.55, 9.99],
  vienna: [48.21, 16.37],
  zurich: [47.37, 8.54],
  stockholm: [59.33, 18.07],
  dublin: [53.35, -6.26],
  warsaw: [52.23, 21.01],
  ashburn: [39.04, -77.49],
  "new york": [40.71, -74.01],
  newark: [40.74, -74.17],
  chicago: [41.88, -87.63],
  dallas: [32.78, -96.8],
  "los angeles": [34.05, -118.24],
  "san jose": [37.34, -121.89],
  "san francisco": [37.77, -122.42],
  seattle: [47.61, -122.33],
  atlanta: [33.75, -84.39],
  miami: [25.76, -80.19],
  singapore: [1.35, 103.82],
  tokyo: [35.68, 139.69],
  "hong kong": [22.32, 114.17],
  sydney: [-33.87, 151.21],
};

export function cityLatLon(city: string | null | undefined): [number, number] | null {
  if (!city) return null;
  const key = city.split(",")[0].trim().toLowerCase();
  return CITIES[key] ?? null;
}
