# Dalili: the mobile app (Flutter, iOS + Android)

This is the phone version of Dalili. It talks to the same backend as the website (`../travel_agent`, FastAPI).

## Screens

| Tab | What it does |
|---|---|
| **Explore** | Where to next, with one line straight into the chat. The quick form (4 steps). Your personal "Picked for you" suggestions (the from-scratch model). Vibes and popular destinations. |
| **Chat** | Talk to Dalili in Arabic or English. While it plans, you watch each step live (flights, hotels, places, weather…). Tap the finished trip to open it. |
| **My trips** | All your trips, filtered by upcoming, past or drafts. Swipe to delete. |
| **Profile** | Sign up or sign in (a secure token kept in the Keychain on iOS or the Keystore on Android). Your stats and travel taste. Language (AR/EN), theme, home city, currency and interests. Change password, delete account, and the server address. |

The **trip page** shows:
- the photo, total and budget, TripScore and planning modes;
- the day-by-day plan as a timeline;
- flights and hotel cards with booking links;
- the budget with a chart of spending per day;
- the weather.

Every price is marked ✓ (published) or *est.* (estimated), as on the website.

## Run it (Android emulator)

1. Start the backend from the project folder:
   ```powershell
   .\.venv\Scripts\python -m uvicorn travel_agent.api:app --port 8001
   ```
2. Start the emulator, then install the app:
   ```powershell
   $env:JAVA_HOME = "$env:USERPROFILE\dev\jdk17"
   & "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd medium_phone -no-snapshot -gpu host
   cd mobile
   flutter run          # or: flutter build apk --debug  ->  build\app\outputs\flutter-apk\app-debug.apk
   ```
   The emulator reaches the computer at `http://10.0.2.2:8001`, which is the default server address.

## On a real phone

1. Start the backend so the local network can reach it:
   ```powershell
   .\.venv\Scripts\python -m uvicorn travel_agent.api:app --host 0.0.0.0 --port 8001
   ```
2. Put the phone on the same Wi-Fi.
3. In the app, go to **Profile → Server address** and enter `http://<your computer's IP>:8001`.
4. For Android, install the APK with `flutter install`, or copy `app-debug.apk` to the phone.

## iOS

The same code builds for iOS, but Apple only allows building on a **Mac with Xcode**:
```bash
cd mobile && flutter pub get && cd ios && pod install && cd .. && flutter run -d ios
```
Development builds are allowed to reach the local server (`NSAllowsLocalNetworking`). A store build needs an https server.

## Before publishing

Before a store release:
- Point the default server to an **https** domain and remove `usesCleartextTraffic`.
- Sign the Android build with your own key.
- Set the bundle id (`com.dalili.dalili`) and the app name.

## Tests

```powershell
flutter analyze    # no issues
flutter test       # strings in both languages, money formatting, markdown rendering
```
The backend has its own tests (`../tests`), including the mobile token sign-in (`test_mobile_app_uses_a_bearer_token_and_a_guest_header`).
