#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v gradle >/dev/null 2>&1; then echo 'Install Android Studio or Gradle + Android SDK to build APK.'; exit 2; fi
gradle :app:assembleDebug
printf '\nAPK: %s\n' "$(pwd)/app/build/outputs/apk/debug/app-debug.apk"
