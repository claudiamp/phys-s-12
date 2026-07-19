// Time helpers.
// The ESP32 sends LOCAL Peru time (GMT-5, no DST) with no timezone suffix, so incoming
// timestamps are used as-is. We only compute Lima time for fallbacks when it is missing.

// Current wall-clock time as an ISO 8601 UTC string.
export function nowIso() {
  return new Date().toISOString();
}

// "YYYY-MM-DDTHH:MM:SS" in America/Lima. The sv-SE locale formats as "YYYY-MM-DD HH:MM:SS";
// swap the space for a "T" to match the device timestamp shape.
export function nowLima() {
  const s = new Date().toLocaleString('sv-SE', { timeZone: 'America/Lima' });
  return s.replace(' ', 'T');
}

// Local date "YYYY-MM-DD" from a device timestamp; falls back to today in Lima.
export function dateFromTimestamp(ts) {
  if (typeof ts === 'string' && ts.length > 0) {
    return ts.slice(0, 10);
  }
  return nowLima().slice(0, 10);
}
