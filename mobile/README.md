# Dalili: the mobile app (Flutter, Android + iOS)

The app is the Dalili website - one UI for the web and the phone - inside a native shell (`lib/shell.dart`):

| Native part | Why |
|---|---|
| The web view | Every feature (chat, trip board, Events, Hajj & Umrah, the landmark camera, travel buddies) is built once, on the site, and is the same in the app. |
| Camera / gallery | The landmark camera's `<input type="file">` opens a choice: take a photo or pick one (`image_picker`; iOS's web view does it by itself). |
| Back button | Goes back in the site; exits on the first page. |
| Links out | A hotel's page, Wikipedia, a ticket office open in the browser, never inside the app. |
| Offline screen | No connection: a clear screen and "Try again". |
| Carry-over | On the first start after the update, the previous app's guest id and sign-in become the site's cookies, and its open trip, language and theme its local storage: nobody loses a trip or has to sign in again. |

The server comes from the build: `--dart-define=DALILI_SERVER=https://...` (the Mobile workflow passes it).

## Releasing this version (a store release, once)

This version adds native plugins (`webview_flutter`, `image_picker`), so it can't be a Shorebird patch:

1. GitHub → Actions → **Mobile** → *Run workflow* on this branch with **release** (Google Play `.aab`) or
   **release-apk** (an `.apk` to install directly).
2. Upload the `.aab` from the run's artifacts to Google Play (or share the `.apk`).
3. Merge the branch into `main`. From then on, Dart changes reach installed apps as Shorebird patches again - and
   since the app shows the website, most changes need no app update at all.

## Run it locally

```powershell
cd mobile
flutter pub get
flutter build apk --debug   # -> build\app\outputs\flutter-apk\app-debug.apk (talks to the live site)
flutter run --dart-define=DALILI_SERVER=http://10.0.2.2:8001   # an emulator against the backend on this computer
```

## Tests

```powershell
flutter analyze    # no issues
flutter test       # links out vs. in the app; the first page's language
```
