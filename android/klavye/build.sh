#!/bin/sh
# Build the TV Klavye IME APK on the TV host: javac + d8 + aapt2 + zipalign + apksigner.
# Usage: sh build.sh <dir>  -> <dir>/klavye.apk  (signed with /root/tv-keys/kanallar.jks)
set -e
D=$(cd "${1:-.}" && pwd); W=$(mktemp -d)
A=/opt/tv-voice/android; P=$A/android.jar
[ -f $P ] || { echo "missing $P"; exit 1; }
D8=$(ls $A/bt/*/lib/d8.jar 2>/dev/null | head -1)
[ -n "$D8" ] || { echo "missing d8.jar under $A/bt"; exit 1; }
K=/root/tv-keys/kanallar.jks
[ -f $K ] || { echo "signing key missing: $K"; exit 1; }
mkdir -p $W/obj $W/dex
javac -nowarn -encoding UTF-8 -source 8 -target 8 -bootclasspath $P -d $W/obj $(find $D/src -name '*.java') 2>&1 | grep -v -E "^warning|^[0-9]+ warnings?$" || true
java -cp $D8 com.android.tools.r8.D8 --lib $P --min-api 26 --release --output $W/dex $(find $W/obj -name '*.class')
aapt2 compile --dir $D/res -o $W/res.zip
aapt2 link -o $W/u.apk -I $P --manifest $D/AndroidManifest.xml -A $D/assets $W/res.zip
(cd $W/dex && zip -q $W/u.apk classes.dex)
zipalign -f 4 $W/u.apk $W/a.apk
apksigner sign --ks $K --ks-pass "pass:$(cat /root/tv-keys/kanallar.pass)" --out $D/klavye.apk $W/a.apk
rm -rf $W
apksigner verify $D/klavye.apk && echo "built $D/klavye.apk"
