#!/usr/bin/env bash
# build_apk.sh — helper to install Buildozer locally and build debug APK.
# Usage:
#   chmod +x build_apk.sh
#   ./build_apk.sh
set -e
echo "Installing build dependencies (user pip)..."
python3 -m pip install --user --upgrade pip
python3 -m pip install --user buildozer Cython==0.29.* requests kivy
export PATH="$HOME/.local/bin:$PATH"
echo "Starting Buildozer debug build (this may take long on first run)..."
buildozer -v android debug
echo "Build finished. APK will be in bin/"