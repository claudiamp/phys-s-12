// A single "pill taken" event returned by GET /events.
export interface PillEvent {
  date: string; // "YYYY-MM-DD"
  takenAt: string; // "YYYY-MM-DDTHH:MM:SS" (local Lima time, no timezone suffix)
}
