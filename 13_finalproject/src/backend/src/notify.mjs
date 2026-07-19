// Step Functions target: sends the "okay to eat" FCM push to every registered device token.
import admin from 'firebase-admin';
import { SSMClient, GetParameterCommand } from '@aws-sdk/client-ssm';
import { queryTokens } from './lib/dynamo.mjs';

const ssm = new SSMClient({});

// Lazily initialize the Firebase Admin SDK once, then reuse it across warm invocations.
let app;
async function getApp() {
  if (app) return app;

  const res = await ssm.send(new GetParameterCommand({
    Name: process.env.FCM_SA_PARAM,
    WithDecryption: true,
  }));
  const sa = JSON.parse(res.Parameter.Value);

  // Guard against re-initializing on a warm start.
  app = admin.apps.length
    ? admin.app()
    : admin.initializeApp({ credential: admin.credential.cert(sa) });
  return app;
}

export const handler = async () => {
  await getApp();

  const tokens = await queryTokens();
  if (tokens.length === 0) {
    console.log('no FCM tokens registered, nothing to send');
    return { sent: 0 };
  }

  const message = {
    tokens,
    notification: {
      title: 'Okay to eat 🍽️',
      body: "It's been 1 hour since your levothyroxine — you can eat now.",
    },
    android: { priority: 'high' },
  };

  const res = await admin.messaging().sendEachForMulticast(message);

  // Log per-token outcome; never throw on individual failures.
  res.responses.forEach((r, i) => {
    if (r.success) {
      console.log(`token[${i}] ok`);
    } else {
      console.warn(`token[${i}] failed: ${r.error?.message}`);
    }
  });

  return { sent: res.successCount, failed: res.failureCount };
};
