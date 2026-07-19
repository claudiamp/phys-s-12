# Smart Pillbox — Mobile App (Expo / React Native)

A minimal Android app for the Smart Pillbox. It has two views:

- **Calendar** — a month calendar with a green check `✓` under each day a pill was taken.
- **History** — a list of days and the time the pill was taken, most recent first.

On launch it requests notification permission and registers this device's **FCM token** with the
backend, so it receives the "okay to eat" push one hour after the pillbox is opened. Data comes from
the backend REST API.

Built with Expo (SDK 52, managed) and TypeScript. It is prebuilt to native Android and compiled into
a standalone APK you sideload onto your phone.

## Files

```
app/
  app.config.js                 # reads env, sets extra.{apiBaseUrl,apiKey}, android package, expo-notifications plugin
  App.tsx                       # root: registers for push, switches Calendar | History
  index.ts                      # Expo entry (registerRootComponent)
  package.json
  tsconfig.json
  babel.config.js
  .env.example                  # EXPO_PUBLIC_API_BASE_URL / EXPO_PUBLIC_API_KEY
  google-services.json.example  # placeholder showing where the real Firebase file goes
  .gitignore
  src/
    config.ts                   # reads Constants.expoConfig.extra -> { apiBaseUrl, apiKey }
    api.ts                      # getEvents(), registerToken(); adds the x-api-key header
    types.ts                    # PillEvent { date, takenAt }
    notifications.ts            # permission + getDevicePushTokenAsync -> registerToken
    screens/CalendarView.tsx
    screens/HistoryView.tsx
```

There is no `app.json` (config lives only in `app.config.js`) and no `assets/` folder — the app uses
Expo's built-in default icon and splash. See "App icon" below to replace it later.

## Prerequisites

- **Node.js 24** (Node 18+ works for the Expo tooling)
- **JDK 17** — the version React Native 0.76 / Expo SDK 52 and their Gradle + Android Gradle Plugin
  are tested against. Do **not** use a newer JDK: Gradle refuses to run on a JDK it doesn't support,
  so a too-new one (21 sometimes works; 25 is too new) breaks the build rather than improving it.
- **Android SDK / Android Studio** (with `adb` and platform tools on your `PATH`)
- An **Android device** with USB debugging enabled (a physical device is required — push tokens are
  not available on emulators)
- The **backend deployed** (see `../backend/README.md`); you need its `ApiBaseUrl` output and the
  `ApiKey` you chose.

## One-time environment setup (macOS)

Do this once before your first build.

**1. Install the Android SDK.** Install **Android Studio** and run its **Setup Wizard** — that
downloads the Android SDK (platform-tools, build-tools, and an SDK platform; API 35 matches Expo 52)
to `~/Library/Android/sdk`. Installing the Android Studio app alone is not enough; the wizard is what
fetches the SDK.

**2. Point your shell at the SDK and JDK 17.** Append the exports to `~/.zshrc` and reload:

```bash
cat >> ~/.zshrc <<'EOF'

# Android SDK + JDK 17 (React Native / Expo builds)
export ANDROID_HOME=$HOME/Library/Android/sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
EOF
source ~/.zshrc
```

Gradle needs `ANDROID_HOME` to locate the SDK, and `adb` on `PATH` is used to install the APK.

**3. Verify the toolchain.** All three should print a value:

```bash
java -version         # -> 17.x
echo "$ANDROID_HOME"  # -> /Users/<you>/Library/Android/sdk
adb version           # -> Android Debug Bridge version 1.0.41
```

**4. Enable USB debugging** on the phone (**Settings → About phone → tap Build number 7×**, then
**Developer options → USB debugging**), plug it in over USB, and tap **Allow** on the authorization
prompt. `adb devices` should then list it as `device` (not `unauthorized`).

## Setup

Run everything below from this `app/` directory.

### 1. Install dependencies

```bash
npm install
```

### 2. Add the Firebase Android config

In the [Firebase console](https://console.firebase.google.com/), add an **Android app** to your
project with package name **`com.pillbox.app`**, then download its **`google-services.json`**. Place
it here:

```
app/google-services.json
```

This file is gitignored. See `google-services.json.example` for the exact location and package name
(the example is a placeholder and is not used by the build).

### 3. Create your `.env`

Copy the example and fill in both values:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
# The backend stack's ApiBaseUrl output
EXPO_PUBLIC_API_BASE_URL=https://abc123.execute-api.us-east-1.amazonaws.com/Prod
# The same value you passed to the backend ApiKey SAM parameter
EXPO_PUBLIC_API_KEY=your-api-key-here
```

`app.config.js` reads these at build time and surfaces them to JS via `expo-constants` `extra`
(read in `src/config.ts`). **The API key is injected from `.env`, never hardcoded in source.** Every
API request sends it in the `x-api-key` header.

### 4. Generate the native Android project

```bash
npx expo prebuild --platform android --clean
```

This creates the `android/` folder from `app.config.js` (wiring in the package name, the
`expo-notifications` plugin, and your `google-services.json`).

### 5. Build the APK

```bash
cd android && ./gradlew assembleRelease
```

Use `./gradlew assembleDebug` instead for a quicker dev build. The APK is written under:

```
android/app/build/outputs/apk/release/app-release.apk     # assembleRelease
android/app/build/outputs/apk/debug/app-debug.apk         # assembleDebug
```

By default the release APK is signed with the debug keystore, which is fine for personal
sideloading. Generating your own release keystore is optional and only needed for Play Store
distribution.

### 6. Install on your phone

With the device connected over USB:

```bash
adb install -r android/app/build/outputs/apk/release/app-release.apk
```

(or copy the APK to the phone and open it). Launch the app, grant the notification permission when
prompted, and it registers its push token with the backend.

## Push notifications

The "okay to eat" push depends on two things being in place:

1. This app registered its FCM token (happens automatically on first launch, after you grant the
   notification permission).
2. The backend has the Firebase **FCM v1 service-account** JSON stored in SSM (backend setup step;
   see `../backend/README.md`).

Both use the **same Firebase project** — `google-services.json` here and the service-account key on
the backend.

## App icon

The app currently uses Expo's default icon and splash so prebuilds never fail on a missing image.
To use your own, add an `assets/` folder and set `icon` / `android.adaptiveIcon` / `splash` in
`app.config.js`, then re-run the prebuild.
