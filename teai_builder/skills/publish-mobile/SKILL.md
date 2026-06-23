---
name: publish-mobile
description: Ship Expo/React Native apps to the Google Play Store and Apple App Store using EAS Build and EAS Submit, with build verification and a clear stop point for store credentials.
metadata: {"teai_builder": {"emoji": "🛫"}}
---

# Publishing Mobile Apps — Expo EAS (Play Store + App Store)

This skill takes an app built per the `mobile` skill from "runs on my phone via
Expo Go" to "installable from the app stores". It uses **EAS Build** (cloud
builds of signed binaries) and **EAS Submit** (upload to the stores).

## Hard reality: you cannot fully publish without the user's accounts

Store publishing requires paid developer accounts and secrets that only the user
can provide. **Stop and ask the user** for these before attempting submission —
never invent them, never assume them:

- **Google Play:** a Google Play Developer account ($25 one-time) and a **service
  account JSON key** with Play Console access.
- **Apple App Store:** an **Apple Developer Program** membership ($99/yr), the
  Apple ID / Team ID, and either an App Store Connect **API key** (`.p8` + key id
  + issuer id) or app-specific credentials.
- An **Expo (EAS) account** (free tier is fine for getting started).

Building unsigned/internal artifacts (`.apk`, internal `.aab`) does NOT need
store accounts and can be done immediately for testing. Submission does.

## Step 0 — Verify the app first (gate)

Do not build a store binary for a broken app:
- `run_verification(project="<name>")` must return `status: pass`.
- The app must run cleanly in Expo Go (per the `mobile` skill).
- `app.json` has a real `name`, `slug`, unique `ios.bundleIdentifier`
  (e.g. `com.yourco.app`) and `android.package`, an `version`, and valid icon /
  splash assets that actually exist.

## Step 1 — Install and authenticate EAS

```bash
cd projects/<name>
npm install --global eas-cli   # or: npx eas-cli@latest
eas login                      # stop here and ask user to log in if non-interactive
eas whoami                     # confirm authenticated
```

## Step 2 — Configure the project for builds

```bash
eas build:configure            # creates eas.json with build profiles
```

A typical `eas.json`:
```json
{
  "cli": { "version": ">= 5.0.0" },
  "build": {
    "development": { "developmentClient": true, "distribution": "internal" },
    "preview":     { "distribution": "internal", "android": { "buildType": "apk" } },
    "production":  { "autoIncrement": true }
  },
  "submit": { "production": {} }
}
```

## Step 3 — Build signed binaries (cloud)

EAS manages signing keys for you (or you can supply your own).

```bash
# Quick installable test build (no store account needed):
eas build --platform android --profile preview        # → .apk you can sideload

# Production store binaries:
eas build --platform android --profile production      # → .aab for Play Store
eas build --platform ios     --profile production      # → .ipa for App Store (needs Apple acct)

# Or both:
eas build --platform all --profile production
```

Builds run in the cloud; the command prints a build URL and, when finished, a
download link. **Verification:** confirm the build status is `finished` (not
`errored`) and that an artifact URL exists. Surface the build URL/artifact to
the user (and to canvas if useful). A failed EAS build means publishing failed —
read the logs (`eas build:view <id>`), fix, and rebuild.

## Step 4 — Submit to the stores (needs the credentials above)

```bash
# Google Play (requires service account JSON):
eas submit --platform android --profile production \
  --path <downloaded.aab>            # or omit --path to submit the latest build

# Apple App Store (requires Apple Developer credentials / ASC API key):
eas submit --platform ios --profile production
```

Store credentials can be configured non-interactively in `eas.json` under
`submit.production` (e.g. `android.serviceAccountKeyPath`,
`ios.ascApiKeyPath` / `ascApiKeyId` / `ascApiKeyIssuerId`) — ask the user to
provide these and store them securely; never commit them.

## Step 5 — Post-submission

- Play Store: the build lands in the chosen track (internal/closed/production).
  The user finishes the store listing (screenshots, description, content rating)
  in the Play Console and promotes to production.
- App Store: the build appears in App Store Connect after processing; the user
  completes the listing and submits for App Review.
- Record store URLs / build ids in `PROJECT.md`. Use `project_gate(action=
  "advance", phase="deploy")` only after a build (and, when accounts are
  available, a submission) has actually succeeded.

## Stop points to surface to the user (don't guess)

- "I need your Expo (EAS) login."
- "Publishing to Google Play needs a Play Developer account + service account JSON."
- "Publishing to the App Store needs an Apple Developer membership + App Store
  Connect API key."
- "Pick the release track (internal test vs production)."

## Verification checklist (before reporting "published")
- [ ] `run_verification` passed and app runs in Expo Go
- [ ] `app.json` has valid identifiers, version, and existing assets
- [ ] `eas build` finished successfully with a downloadable artifact
- [ ] (If submitting) `eas submit` returned success for each platform
- [ ] Build/store URLs recorded in `PROJECT.md`
- [ ] Any missing accounts/keys were clearly requested from the user
