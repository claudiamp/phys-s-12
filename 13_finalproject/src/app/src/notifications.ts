import * as Notifications from "expo-notifications";
import * as Device from "expo-device";

import { registerToken } from "./api";

// Show the "okay to eat" push even while the app is foregrounded.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

// Ask for notification permission, grab the raw FCM device token, and register
// it with the backend so the Notify Lambda can push to this device.
// Fire-and-forget friendly: never throws, returns the token or null.
export async function registerForPush(): Promise<string | null> {
  try {
    if (!Device.isDevice) {
      console.warn("Push notifications require a physical device.");
      return null;
    }

    const existing = await Notifications.getPermissionsAsync();
    let status = existing.status;
    if (status !== "granted") {
      status = (await Notifications.requestPermissionsAsync()).status;
    }
    if (status !== "granted") {
      console.warn("Notification permission not granted.");
      return null;
    }

    // On Android this returns the raw FCM device token.
    const token = (await Notifications.getDevicePushTokenAsync()).data;
    await registerToken(token);
    return token;
  } catch (err) {
    console.warn("Failed to register for push notifications:", err);
    return null;
  }
}
