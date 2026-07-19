import Constants from "expo-constants";

// Values injected at build time by app.config.js (from EXPO_PUBLIC_* env vars),
// surfaced here via expo-constants `extra`. Never hardcode secrets in source.
const extra = (Constants.expoConfig?.extra ?? {}) as {
  apiBaseUrl?: string;
  apiKey?: string;
};

export const apiBaseUrl: string = extra.apiBaseUrl ?? "";
export const apiKey: string = extra.apiKey ?? "";

if (!apiBaseUrl || !apiKey) {
  console.warn(
    "Missing API config. Set EXPO_PUBLIC_API_BASE_URL and EXPO_PUBLIC_API_KEY " +
      "in app/.env (see app/.env.example). They are read by app.config.js -> extra."
  );
}
