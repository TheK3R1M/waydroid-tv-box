#!/bin/sh
# Build the assistant-bar overlay APK on the TV host: javac (openjdk-21-jdk-headless) + d8 + aapt2 + apksigner.
# Usage: sh build.sh <dir>  -> <dir>/asistan.apk   (same signing key as the Kanallar tile, /root/tv-keys)
set -e
D=$(cd "${1:-.}" && pwd); W=$(mktemp -d)
A=/opt/tv-voice/android; P=$A/android.jar
[ -f $P ] || { mkdir -p $A && cd $A && curl -sfLO https://dl.google.com/android/repository/platform-33_r02.zip &&
  unzip -qj platform-33_r02.zip '*/android.jar' && rm platform-33_r02.zip; }
D8=$(ls $A/bt/*/lib/d8.jar 2>/dev/null | head -1)
[ -n "$D8" ] || { cd $A && curl -sfLo bt.zip https://dl.google.com/android/repository/build-tools_r34-linux.zip &&
  unzip -q bt.zip -d bt && rm bt.zip; D8=$(ls $A/bt/*/lib/d8.jar | head -1); }
K=/root/tv-keys/kanallar.jks
[ -f $K ] || { echo "signing key missing: build the Kanallar tile first (android/kanallar/build.sh)"; exit 1; }
mkdir -p $W/obj $W/dex
javac -nowarn -source 8 -target 8 -bootclasspath $P -d $W/obj $(find $D/src -name '*.java') 2>&1 | grep -v -E "^warning|^[0-9]+ warning" || true
java -cp $D8 com.android.tools.r8.D8 --lib $P --min-api 26 --release --output $W/dex $(find $W/obj -name '*.class')
aapt2 link -o $W/u.apk -I $P --manifest $D/AndroidManifest.xml
(cd $W/dex && zip -q $W/u.apk classes.dex)
zipalign -f 4 $W/u.apk $W/a.apk
apksigner sign --ks $K --ks-pass "pass:$(cat /root/tv-keys/kanallar.pass)" --out $D/asistan.apk $W/a.apk
rm -rf $W; apksigner verify $D/asistan.apk && echo "built $D/asistan.apk"
