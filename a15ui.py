#!/usr/bin/env python3
"""a15ui - touch-simulator for the A15 over ADB (uiautomator): find UI elements by text / content-desc / resource-id and tap them.
No fixed coordinates: the element bounds come from `uiautomator dump`, so it survives layout changes.
Runs on the Ubuntu server (adb to $A15_DEV (host:port), root via su).

  a15ui.py dump                      list the visible, tappable / labelled elements
  a15ui.py tap "NIGHT"               tap the element whose text/desc/id equals (case-insensitive) or contains the argument
  a15ui.py wait "Take picture" [s]   wait until such an element appears (default 15 s)
  a15ui.py xy 540 1900               raw tap
  a15ui.py swipe x1 y1 x2 y2 [ms]    swipe
  a15ui.py night [out.jpg]           Samsung camera: PHOTO > MORE > NIGHT > shutter; waits for the new file, pulls it to ~/a15-media/
  a15ui.py photo [out.jpg]           Samsung camera: PHOTO mode, shutter, pull
  a15ui.py pro [--iso 400|auto] [--speed 2|1/4|auto] [--focus 0..1|auto] [--out x.jpg] [--no-shot]
                                     Samsung PRO mode: set ISO / shutter / manual focus on the sliders (closed loop), shoot, pull
  # manual focus scale (measured on the A15): 0.5 = sharp on distant scenery (about infinity); 0.0 / 1.0 are near / macro-side and blurry for far subjects
  a15ui.py map [outdir]              open every camera mode (main bar + MORE grid) and save its UI elements as JSON
"""
import json, os, re, subprocess, sys, time, xml.etree.ElementTree as ET

DEV = os.environ.get("A15_DEV", "PHONE_IP:5555")
OUT = os.path.expanduser("~/a15-media")
CAMDIR = "/sdcard/DCIM/Camera"
CAMPKG = "com.sec.android.app.camera/.Camera"


def adb(*a, **k):
    return subprocess.run(["adb", "-s", DEV, *a], capture_output=True, text=k.get("text", True), timeout=k.get("timeout", 60))


def su(cmd):
    return adb("shell", "su -c '%s'" % cmd).stdout


def dump():
    su("uiautomator dump /sdcard/ui.xml >/dev/null")
    xml = su("cat /sdcard/ui.xml")
    return ET.fromstring(xml[xml.index("<"):]) if "<hierarchy" in xml else None


def nodes():
    root = dump()
    out = []
    if root is None:
        return out
    for n in root.iter("node"):
        b = re.findall(r"\d+", n.get("bounds", ""))
        if len(b) != 4:
            continue
        x1, y1, x2, y2 = map(int, b)
        out.append(dict(text=n.get("text", ""), desc=n.get("content-desc", ""), rid=n.get("resource-id", "").split("/")[-1],
                        click=n.get("clickable") == "true", box=(x1, y1, x2, y2), c=((x1 + x2) // 2, (y1 + y2) // 2)))
    return out


def find(q, ns=None):
    q = q.lower()
    ns = ns if ns is not None else nodes()
    for exact in (True, False):
        for n in ns:
            if n["box"][2] - n["box"][0] <= 12:
                continue  # off-screen sliver
            for f in (n["text"], n["desc"], n["rid"]):
                f = f.lower()
                if f and ((f == q) if exact else (q in f)):
                    return n
    return None


def tap_xy(x, y):
    adb("shell", "input tap %d %d" % (x, y))


def tap(q, wait=0.0):
    n = find(q)
    for _ in range(3):  # uiautomator dump is flaky during animations
        if n:
            break
        time.sleep(1.2)
        n = find(q)
    if not n:
        raise SystemExit("not found: %s" % q)
    tap_xy(*n["c"])
    print("tap %r at %s" % (q, n["c"]))
    time.sleep(wait)
    return n


def wait_for(q, secs=15):
    t = time.time()
    while time.time() - t < secs:
        n = find(q)
        if n:
            return n
        time.sleep(1)
    raise SystemExit("timeout waiting for: %s" % q)


def wake():
    adb("shell", "input keyevent KEYCODE_WAKEUP")
    time.sleep(1)


def files():
    return set(l.strip() for l in su("ls %s" % CAMDIR).splitlines() if l.strip().lower().endswith((".jpg", ".jpeg", ".heic")))


def pull(name, dest):
    data = adb("exec-out", "su -c 'cat %s/%s'" % (CAMDIR, name), text=False, timeout=120).stdout
    os.makedirs(OUT, exist_ok=True)
    open(dest, "wb").write(data)
    print("-> %s (%d bytes)" % (dest, len(data)))


def capture(tag, out, before, maxwait=90):
    tap("Take picture")
    t = time.time()
    new = set()
    while time.time() - t < maxwait:  # night / long exposure: seconds of exposure + processing
        time.sleep(2)
        new = files() - before
        if new:
            time.sleep(3)  # let the file finish
            new = files() - before
            break
    adb("shell", "am force-stop com.sec.android.app.camera")
    adb("shell", "input keyevent KEYCODE_SLEEP")
    if not new:
        raise SystemExit("no new photo appeared")
    name = sorted(new)[-1]
    dest = os.path.join(OUT, out or ("a15-%s-%s.jpg" % (tag, time.strftime("%Y%m%d-%H%M%S"))))
    pull(name, dest)


def camera_flow(mode, out):
    open_camera()
    before = files()
    if mode == "night":
        tap("MORE", 1.5)
        tap("NIGHT", 2.5)
    else:
        tap("PHOTO", 1.5)
    wait_for("Take picture", 10)
    capture(mode, out, before)


# ---- PRO mode sliders (wheel: fling to an end, then D-pad steps; the value is read from activeTextView) ----
def parse_val(t):
    t = t.strip().upper().lstrip("A ").rstrip("S ").strip()
    if "/" in t:
        a, b = t.split("/")
        return float(a) / float(b)
    return float(t)


def slider_text(settle=True):
    """Current value, read from the slider's own content-desc ("A 1/15, Shutter speed"). One screen dump (~1.4 s) per read."""
    for _ in range(3):
        for n in nodes():
            if n["rid"].endswith("_slider") and "," in n["desc"] and n["box"][3] - n["box"][1] > 100:
                return n["desc"].split(",")[0].strip()
        time.sleep(0.5)
    return None


def set_slider(header, target):
    """header: ISO | SPEED. target: number (ISO / seconds) or 'auto'. Swipe right = lower value, left = higher."""
    import math
    tap(header, 2)
    btn = [n for n in nodes() if n["rid"] == "manual_auto_button"]
    is_auto = bool(btn) and btn[0]["desc"].lower().startswith("auto")
    if target == "auto":
        if not is_auto:
            tap_xy(*btn[0]["c"])
        print("%s -> auto" % header)
        return
    if is_auto:
        tap_xy(*btn[0]["c"])
        time.sleep(1.5)
    want = float(target)
    amp, last_sign = 140, 0
    cur = parse_val(slider_text())
    for i in range(14):
        err = math.log2(max(cur, 1e-9) / want)  # >0: too high
        if abs(err) < 0.25:  # within ~1/4 stop
            break
        sign = 1 if err > 0 else -1  # too high -> swipe right (dx>0)
        if last_sign and sign != last_sign:
            amp = max(40, amp // 2)  # overshoot: smaller steps
        last_sign = sign
        dx = int(sign * min(amp, 60 + 40 * abs(err)))
        adb("shell", "input swipe 540 1746 %d 1746 1200" % (540 + dx))
        time.sleep(0.8)
        cur = parse_val(slider_text())
        print("  step %d dx=%d -> %s" % (i, dx, slider_text(False) if False else cur), flush=True)
    print("%s target %s -> %s" % (header, target, cur), flush=True)
    return cur


def set_focus(target):
    """FOCUS: 'auto' or 0.0-1.0 (slider scale; swipe left = higher). Opens the AUTO/MANUAL chooser, picks MANUAL, closed loop on the value."""
    tap("FOCUS", 2)
    if target == "auto":
        tap_xy(*[n for n in nodes() if n["rid"] == "pro_item_button" and n["desc"] == "AUTO"][0]["c"])
        print("FOCUS -> auto")
        return
    m = [n for n in nodes() if n["rid"] == "pro_item_button" and n["desc"] == "MANUAL"]
    if m:
        tap_xy(*m[0]["c"])
        time.sleep(1.5)
    want = float(target)
    cur = parse_val(slider_text() or "0.5")
    for i in range(12):
        err = cur - want  # >0: too high -> swipe right
        if abs(err) < 0.04:
            break
        if abs(err) > 0.4 or want in (0.0, 1.0):  # fling to the end
            x1, x2, ms = (200, 800, 300) if err > 0 else (800, 200, 300)
        else:
            dx = int(max(40, min(300, abs(err) * 700)))
            x1, x2, ms = (540, 540 + dx, 1200) if err > 0 else (540, 540 - dx, 1200)
        adb("shell", "input swipe %d 1746 %d 1746 %d" % (x1, x2, ms))
        time.sleep(0.8)
        cur = parse_val(slider_text() or str(cur))
        print("  focus step %d -> %s" % (i, cur), flush=True)
        if want in (0.0, 1.0) and cur == want:
            break
    print("FOCUS target %s -> %s" % (target, cur), flush=True)
    return cur


def pro_flow(opts):
    open_camera()
    before = files()
    tap("MORE", 1.5)
    tap("PRO", 3)
    for hdr, key in (("ISO", "iso"), ("SPEED", "speed")):
        if key in opts:
            v = opts[key]
            set_slider(hdr, "auto" if v == "auto" else parse_val(v))
    if "focus" in opts:
        v = opts["focus"]
        set_focus("auto" if v == "auto" else float(v))
    if opts.get("shot", True):
        wait_for("Take picture", 10)
        capture("pro", opts.get("out"), before, maxwait=120)
    else:
        adb("shell", "am force-stop com.sec.android.app.camera")


def snapshot():
    return [dict(rid=n["rid"], text=n["text"], desc=n["desc"], click=n["click"], box=list(n["box"])) for n in nodes()
            if (n["text"] or n["desc"] or n["click"]) and n["box"][2] - n["box"][0] > 12]


def open_camera():
    wake()
    adb("shell", "am force-stop com.sec.android.app.camera")
    adb("shell", "am start -n %s" % CAMPKG)
    wait_for("Take picture", 20)


def map_modes(outdir):
    os.makedirs(outdir, exist_ok=True)
    result = {}

    def save(name):
        result[name] = snapshot()
        json.dump(result[name], open(os.path.join(outdir, name + ".json"), "w"), indent=1)
        print("%-12s %d elements" % (name, len(result[name])))

    open_camera()
    time.sleep(1.5)
    bar = [n["text"] for n in nodes() if n["rid"] == "shooting_mode_item_button" and n["text"]]
    print("main bar:", bar)
    for m in bar:
        if m == "MORE":
            continue
        open_camera()
        tap(m, 2)
        save(m.lower().replace(" ", "_"))
    open_camera()
    tap("MORE", 2)
    grid = [n["text"] for n in nodes() if n["rid"] == "more_grid_list_text" and n["text"]]
    print("MORE grid:", grid)
    save("more_menu")
    for g in grid:
        open_camera()
        tap("MORE", 1.5)
        tap(g, 2.5)
        save("more_" + g.lower().replace(" ", "_"))
    adb("shell", "am force-stop com.sec.android.app.camera")
    adb("shell", "input keyevent KEYCODE_SLEEP")
    json.dump(result, open(os.path.join(outdir, "all.json"), "w"), indent=1)


def main(a):
    if not a:
        print(__doc__)
        return
    c = a[0]
    if c == "dump":
        for n in nodes():
            if n["text"] or n["desc"] or n["click"]:
                print("%-28s %-24r %-32r %s%s" % (n["rid"][:28], n["text"][:24], n["desc"][:32], n["box"], " C" if n["click"] else ""))
    elif c == "tap":
        tap(a[1])
    elif c == "wait":
        print(wait_for(a[1], int(a[2]) if len(a) > 2 else 15)["c"])
    elif c == "xy":
        tap_xy(int(a[1]), int(a[2]))
    elif c == "swipe":
        adb("shell", "input swipe %s %s %s %s %s" % (a[1], a[2], a[3], a[4], a[5] if len(a) > 5 else 300))
    elif c == "pro":
        o, i = {"shot": True}, 1
        while i < len(a):
            if a[i] == "--no-shot":
                o["shot"] = False
            elif a[i].startswith("--") and i + 1 < len(a):
                o[a[i][2:]] = a[i + 1]
                i += 1
            i += 1
        pro_flow(o)
    elif c == "map":
        map_modes(a[1] if len(a) > 1 else os.path.expanduser("~/a15-media/map"))
    elif c in ("night", "photo"):
        camera_flow(c, a[1] if len(a) > 1 else None)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
