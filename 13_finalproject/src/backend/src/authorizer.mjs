// REQUEST Lambda authorizer.
// Allows the request only when the x-api-key header matches the API_KEY secret.

function generatePolicy(effect, resource) {
  return {
    principalId: 'user',
    policyDocument: {
      Version: '2012-10-17',
      Statement: [
        {
          Action: 'execute-api:Invoke',
          Effect: effect,
          Resource: resource,
        },
      ],
    },
  };
}

// API Gateway caches this authorizer's result (keyed on the api-key value) for a few
// minutes. With a single shared key, GET /events and POST /token hit the SAME cache entry,
// so the Allow policy must cover the WHOLE stage — not just the one method that happened to
// populate the cache — otherwise the other endpoint gets a cached, mismatched policy -> 403.
// methodArn looks like: arn:aws:execute-api:REGION:ACCT:APIID/STAGE/VERB/resource/path
function stageWildcard(methodArn) {
  const parts = methodArn.split(':');
  const [apiId, stage] = parts[5].split('/');
  return `${parts.slice(0, 5).join(':')}:${apiId}/${stage}/*`;
}

export const handler = async (event) => {
  const headers = event.headers ?? {};
  const provided =
    headers['x-api-key'] ??
    headers['X-Api-Key'] ??
    (Array.isArray(event.identitySource) ? event.identitySource[0] : undefined);

  if (provided && provided === process.env.API_KEY) {
    return generatePolicy('Allow', stageWildcard(event.methodArn));
  }

  // Throwing "Unauthorized" makes API Gateway return a 401 — simplest.
  throw new Error('Unauthorized');
};
