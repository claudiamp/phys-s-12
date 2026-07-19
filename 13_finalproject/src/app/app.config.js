// Expo app config (JS so we can read env vars at build time).
// - API base URL + API key are read from env and surfaced to JS via `extra`
//   (never hardcoded in source).
// - No icon/splash/adaptiveIcon and no assets/ folder on purpose: Expo uses its
//   built-in defaults so `expo prebuild` never fails on a missing image file.
export default {
  name: "Pillbox",
  slug: "pillbox",
  version: "1.0.0",
  orientation: "portrait",
  android: {
    package: "com.pillbox.app",
    googleServicesFile:
      process.env.GOOGLE_SERVICES_JSON ?? "./google-services.json",
  },
  plugins: [
    "expo-notifications",
    // Pin Kotlin to React Native 0.76's version. Otherwise the Android build's
    // kotlinVersion ext defaults to 1.9.25 while the actual Kotlin Gradle plugin
    // (pulled by react-native-gradle-plugin) is 1.9.24, so expo-modules-core selects
    // the wrong Compose Compiler (1.5.15) and the native compile fails. 1.9.24 -> 1.5.14.
    ["expo-build-properties", { android: { kotlinVersion: "1.9.24" } }],
  ],
  extra: {
    apiBaseUrl: process.env.EXPO_PUBLIC_API_BASE_URL,
    apiKey: process.env.EXPO_PUBLIC_API_KEY,
  },
};
