import { apiBaseUrl, apiKey } from "./config";
import { PillEvent } from "./types";

// Every request carries the shared secret in the (lowercase) x-api-key header,
// which the backend Lambda authorizer validates.
const headers = {
  "Content-Type": "application/json",
  "x-api-key": apiKey,
};

// React Native's fetch often leaves statusText empty, so surface the response body instead.
async function failure(label: string, res: Response): Promise<Error> {
  const body = await res.text().catch(() => "");
  return new Error(`${label} failed: ${res.status} ${body}`.trim());
}

// GET /events -> { events: PillEvent[] } (sorted ascending by date server-side).
export async function getEvents(): Promise<PillEvent[]> {
  const res = await fetch(`${apiBaseUrl}/events`, { headers });
  if (!res.ok) {
    throw await failure("GET /events", res);
  }
  const data = (await res.json()) as { events?: PillEvent[] };
  return data.events ?? [];
}

// POST /token { token } -> registers this device's FCM token with the backend.
export async function registerToken(token: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl}/token`, {
    method: "POST",
    headers,
    body: JSON.stringify({ token }),
  });
  if (!res.ok) {
    throw await failure("POST /token", res);
  }
}
