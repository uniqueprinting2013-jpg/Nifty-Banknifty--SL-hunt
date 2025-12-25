# SLHunt — Build & Install (Debug APK)

This repo contains a Kivy-based Python app (main.py) and Buildozer config to produce an Android debug APK.

Two ways to build a debug APK:

1) Local build (recommended if you have Linux / WSL2 / VM)
2) Cloud build using GitHub Actions (automated, recommended if you don't want to set up local toolchain)

---

## Option A — Local build (Linux / WSL2 / VM)

Prereqs (Ubuntu example):
```bash
sudo apt update
sudo apt install -y python3-pip python3-dev build-essential git zip unzip openjdk-8-jdk zlib1g-dev libncurses5 libstdc++6 android-sdk-platform-tools
```

Install Buildozer and deps:
```bash
python3 -m pip install --user --upgrade pip
python3 -m pip install --user buildozer Cython==0.29.* requests kivy
export PATH="$HOME/.local/bin:$PATH"
```

Build:
```bash
# from repository root
chmod +x build_apk.sh
./build_apk.sh
# or run manually:
# buildozer -v android debug
```

APK will be in `bin/` (e.g. `bin/slhunt-1.0-debug.apk`).

Install to device:
- Enable Developer Options → USB Debugging on Android.
- Connect device via USB.
- Use adb:
  ```bash
  adb devices
  adb install -r bin/slhunt-1.0-debug.apk
  ```
- Or copy APK to device and install via file manager (enable "Install unknown apps").

Notes:
- First build downloads Android SDK/NDK etc. — can take long and use several GB.
- Use OpenJDK 8 for best compatibility with python-for-android.

---

## Option B — GitHub Actions (cloud build)

1. Initialize Git repository, commit all project files (including `main.py`, `buildozer.spec`, `build_apk.sh`, and the `.github/workflows/build.yml` added here), and push to GitHub.

2. The workflow triggers on push and will run Buildozer in the cloud. When complete it uploads the debug APK as an artifact.

3. Download the APK from the workflow run page → Artifacts → `slhunt-debug-apks`.

Notes:
- Cloud builds will also download SDK/NDK and can take a while (~20–60+ minutes).
- If the build fails on Actions, open the workflow run and paste the build log here — I’ll help debug.

---

## Troubleshooting & tips

- If Buildozer isn't found locally, ensure `~/.local/bin` is in your PATH.
- If you get JDK errors, install `openjdk-8-jdk`.
- If NSE live fetch fails on the phone due to network/CORS/etc., the app will fall back to cached JSON files (if present).
- If the APK doesn't install, uninstall any older debug installs first: `adb uninstall org.example.slhunt` (package name from `buildozer.spec`).

---

If you want, I can:
- Add GitHub Action secrets & release signing steps (for a signed release build),
- Tweak buildozer.spec (icons, package name/domain, permissions),
- Or help debug any build errors from a run.

Push the repo now and I’ll guide you through grabbing the artifact once the workflow finishes.