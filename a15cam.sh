#!/bin/bash
# a15cam: headless photo on the A15 (Camera2 app com.claude.a15cam), file lands in ~/a15-media/
# usage: a15cam [-i ISO] [-e EXPOSURE] [-c CAM] [-s WxH] [-f FOCUS] [-o NAME.jpg] [-l] [-k]
#   -e: 1/30 | 0.033 | 33333us   (omit -i and -e = auto exposure)   -l list camera info   -k keep screen on
DEV="${A15_DEV:?set A15_DEV=PHONE_IP:5555}"
ADB="adb -s $DEV"
D=/sdcard/Android/data/com.claude.a15cam/files
OUT=~/a15-media; mkdir -p "$OUT"
name="a15cam-$(date +%Y%m%d-%H%M%S).jpg"; args=(); list=0; keep=0
while getopts "i:e:c:s:f:o:lk" o; do case $o in
  i) args+=(--ei iso "$OPTARG");;
  e) us=$(awk -v v="$OPTARG" 'BEGIN{ if(v~/us$/){sub(/us$/,"",v);print int(v)} else if(v~/\//){split(v,a,"/");print int(1000000*a[1]/a[2])} else print int(v*1000000)}'); args+=(--el exp_us "$us");;
  c) args+=(--es cam "$OPTARG");;
  s) args+=(--es size "$OPTARG");;
  f) args+=(--ef focus "$OPTARG");;
  o) name="$OPTARG";;
  l) list=1;;
  k) keep=1;;
esac; done
$ADB connect "$DEV" >/dev/null 2>&1
$ADB get-state >/dev/null 2>&1 || { echo "A15 not reachable over ADB"; exit 1; }
$ADB shell input keyevent KEYCODE_WAKEUP
$ADB shell pm grant com.claude.a15cam android.permission.CAMERA 2>/dev/null
$ADB shell "su -c 'rm -f $D/$name $D/$name.txt'"
[ $list = 1 ] && args+=(--ez list true)
$ADB shell am start -n com.claude.a15cam/.ShotActivity --es out "$name" "${args[@]}" >/dev/null
for t in $(seq 1 45); do
  st=$($ADB shell "su -c 'cat $D/$name.txt 2>/dev/null'" | tr -d '\r'); [ -n "$st" ] && break; sleep 1
done
[ $keep = 0 ] && $ADB shell input keyevent KEYCODE_SLEEP
echo "$st"
case "$st" in OK*) $ADB exec-out "su -c 'cat $D/$name'" > "$OUT/$name"; echo "-> $OUT/$name ($(stat -c %s "$OUT/$name") bytes)";; esac
