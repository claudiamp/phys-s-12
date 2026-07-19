// IoT rule target: records "pill taken today" and starts the 1-hour reminder.
import { SFNClient, StartExecutionCommand } from '@aws-sdk/client-sfn';
import { putEventIfFirstToday } from './lib/dynamo.mjs';
import { dateFromTimestamp, nowLima } from './lib/time.mjs';

const sfn = new SFNClient({});

export const handler = async (event) => {
  // The IoT rule (SELECT *) delivers the raw MQTT message object as the Lambda event.
  const date = dateFromTimestamp(event.timestamp);
  const takenAt = event.timestamp || nowLima();
  const device = event.device || process.env.DEVICE_ID;

  const inserted = await putEventIfFirstToday(date, takenAt, device);

  if (!inserted) {
    console.log(`already recorded today (${date}), skipping`);
    return { recorded: false, date };
  }

  // First opening today: start the "okay to eat" reminder. A stable per-day execution name
  // keeps later openings from launching more than one reminder for the same day.
  try {
    await sfn.send(new StartExecutionCommand({
      stateMachineArn: process.env.STATE_MACHINE_ARN,
      name: `pill-${date}`,
      input: JSON.stringify({ date, takenAt, trigger: 'pill' }),
    }));
    console.log(`recorded ${date}, reminder started`);
  } catch (err) {
    if (err.name === 'ExecutionAlreadyExists') {
      console.log(`reminder for ${date} already running`);
    } else {
      throw err;
    }
  }

  return { recorded: true, date };
};
