// DynamoDB helpers over the single generic pk/sk table.
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import {
  DynamoDBDocumentClient,
  PutCommand,
  QueryCommand,
} from '@aws-sdk/lib-dynamodb';
import { nowIso } from './time.mjs';

const TABLE_NAME = process.env.TABLE_NAME;

const doc = DynamoDBDocumentClient.from(new DynamoDBClient({}));

// Record one EVENTS item for the day. The condition ensures only the FIRST lid opening of the
// day is stored. Returns true if inserted, false if today's item already existed.
export async function putEventIfFirstToday(date, takenAt, device) {
  try {
    await doc.send(new PutCommand({
      TableName: TABLE_NAME,
      Item: {
        pk: 'EVENTS',
        sk: date,
        takenAt,
        device,
        createdAt: nowIso(),
      },
      ConditionExpression: 'attribute_not_exists(pk)',
    }));
    return true;
  } catch (err) {
    if (err.name === 'ConditionalCheckFailedException') {
      return false;
    }
    throw err;
  }
}

// All recorded events, mapped to { date, takenAt } and sorted ascending by date.
export async function queryEvents() {
  const res = await doc.send(new QueryCommand({
    TableName: TABLE_NAME,
    KeyConditionExpression: 'pk = :pk',
    ExpressionAttributeValues: { ':pk': 'EVENTS' },
  }));
  const items = res.Items ?? [];
  return items
    .map((it) => ({ date: it.sk, takenAt: it.takenAt }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// Upsert an FCM device token.
export async function upsertToken(token) {
  await doc.send(new PutCommand({
    TableName: TABLE_NAME,
    Item: {
      pk: 'TOKENS',
      sk: token,
      updatedAt: nowIso(),
    },
  }));
}

// All registered FCM device tokens (the sk of each TOKENS item).
export async function queryTokens() {
  const res = await doc.send(new QueryCommand({
    TableName: TABLE_NAME,
    KeyConditionExpression: 'pk = :pk',
    ExpressionAttributeValues: { ':pk': 'TOKENS' },
  }));
  return (res.Items ?? []).map((it) => it.sk);
}
