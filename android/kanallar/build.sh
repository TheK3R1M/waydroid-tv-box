#!/bin/sh
# Build the code-less "Kanallar" tile APK on the TV host (needs aapt2, zipalign, apksigner, java).
# Usage: sh build.sh <dir with AndroidManifest.xml + res/>   -> <dir>/kanallar.apk
# The signing key is created once in /root/tv-keys (never commit it). Same key = in-place updates.
set -e
D=${1:-.}; W=$(mktemp -d)
P=/opt/tv-voice/android/android.jar
if [ ! -f $P ]; then
  mkdir -p /opt/tv-voice/android && cd /opt/tv-voice/android
  curl -sfLO https://dl.google.com/android/repository/platform-33_r02.zip
  unzip -qj platform-33_r02.zip '*/android.jar' && rm platform-33_r02.zip
fi
K=/root/tv-keys/kanallar.jks
if [ ! -f $K ]; then
  mkdir -p /root/tv-keys && chmod 700 /root/tv-keys
  head -c 18 /dev/urandom | base64 > /root/tv-keys/kanallar.pass && chmod 600 /root/tv-keys/kanallar.pass
  keytool -genkeypair -keystore $K -alias k -keyalg RSA -keysize 2048 -validity 20000 \
    -storepass:file /root/tv-keys/kanallar.pass -keypass:file /root/tv-keys/kanallar.pass -dname "CN=TV box tile" >/dev/null
fi
aapt2 compile --dir $D/res -o $W/res.zip
aapt2 link -o $W/u.apk -I $P --manifest $D/AndroidManifest.xml $W/res.zip
zipalign -f 4 $W/u.apk $W/a.apk
apksigner sign --ks $K --ks-pass "pass:$(cat /root/tv-keys/kanallar.pass)" --out $D/kanallar.apk $W/a.apk
rm -rf $W; apksigner verify $D/kanallar.apk && echo "built $D/kanallar.apk"
