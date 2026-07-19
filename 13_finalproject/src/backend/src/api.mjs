// REST API Lambda: GET /events and POST /token.
import { queryEvents, upsertToken } from './lib/dynamo.mjs';

const json = (statusCode, payload) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

export const handler = async (event) => {
  try {
    const method = event.httpMethod;
    const resource = event.resource ?? event.path;

    if (method === 'GET' && resource === '/events') {
      const events = await queryEvents();
      return json(200, { events });
    }

    if (method === 'POST' && resource === '/token') {
      const body = event.body ? JSON.parse(event.body) : {};
      const token = body.token;
      if (!token) {
        return json(400, { error: 'token is required' });
      }
      await upsertToken(token);
      return json(200, { ok: true });
    }

    return json(404, { error: 'Not found' });
  } catch (err) {
    return json(500, { error: err.message });
  }
};
