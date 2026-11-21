#!/usr/bin/env python3
"""Voice key for the TV remote (offline). Hold the remote's voice key and speak; on release the audio from the
remote's own USB mic is transcribed on this box by whisper.cpp (tv-whisper.service, unix socket, no network
port, no cloud) and the text is posted to tv-remote over loopback (POST /voice {text}); tv-remote runs a
command ("TRT 1 aç", "sesi kıs", "YouTube'da ... ara") or types the text into the focused Android field.
A very short tap (remotes that send press+release at once) records a fixed window instead.
Audio stays in memory; the last 20 clips are kept in /run (RAM, wiped on reboot) for tuning."""
import array, http.client, io, json, re, select, socket, subprocess, threading, time, uuid, wave

import evdev
from evdev import ecodes

REMOTE_MATCH = ("XING WEI 2.4G",)          # remote dongle name prefix (/proc/bus/input/devices)
MIC_MATCH = "alsa_input.usb-XING_WEI"       # its mic as a PipeWire/Pulse source (pactl list short sources)
VOICE_KEYS = {ecodes.KEY_VOICECOMMAND, getattr(ecodes, "KEY_ASSISTANT", -1)}
PULSE = "unix:/run/tv/pulse/native"
WHISPER_SOCK = "/run/tv-whisper/whisper.sock"
PORT = 8090
MAX_SEC, TAP_SEC, TAP_WINDOW = 7, 0.35, 5.0    # whisper runs with audio_ctx 384 (~7.7 s), so cap at 7 s
CHANNELS_FILE = "/etc/tv/turkiye.m3u"


def post(path, obj=None):
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        body = json.dumps(obj).encode() if obj is not None else b""
        c.request("POST", path, body, {"Host": "127.0.0.1", "X-TV": "1", "X-TV-Device": "Kumanda%20(ses)",
                                        "Content-Type": "application/json"})
        r = c.getresponse(); out = r.read(); c.close()
        return out
    except Exception as e:
        print("post:", e, flush=True)


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(WHISPER_SOCK)


def prompt():
    """A natural Turkish command sentence as context. Measured on the reference box: a bare list of channel names
    made whisper answer in CAPITALS and hallucinate channel names (0.914 similarity, 11/25 exact); this sentence
    style gave 0.958, 17/25 exact at the same speed."""
    return ("Televizyon kumandası sesli komutları: YouTube'dan video aç, YouTube'da şarkı ara, Netfly'ı aç, "
            "kanal listesini göster, sesi kıs, TRT 1'i aç, Kanal D'ye geç, Show TV, ATV, Star TV, Now, Habertürk.")


HALLU = re.compile(r"(allah|altyazı m\.?k|izlediğiniz için teşekkür(ler| ederim)|abone ol\w*.*|"
                   r"altyazı\w*.*|teşekkürler|music|müzik)")
CLIPS = "/run/tv-voice/clips"      # RAM only (tmpfs), last KEEP clips, for tuning; gone on reboot
KEEP = 20


def keep_clip(pcm, text):
    try:
        import os
        os.makedirs(CLIPS, mode=0o700, exist_ok=True)
        name = time.strftime("%H%M%S") + "_" + re.sub(r"[^\w]+", "_", text)[:40] + ".wav"
        with wave.open(f"{CLIPS}/{name}", "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm)
        for old in sorted(os.listdir(CLIPS))[:-KEEP]:
            os.remove(f"{CLIPS}/{old}")
    except Exception as e:
        print("keep_clip:", e, flush=True)


def normalize(pcm):
    """Quiet remote mics: scale so the peak sits near 70 % (whisper's log-mel is level sensitive)."""
    a = array.array("h"); a.frombytes(pcm[: len(pcm) // 2 * 2])
    peak = max((abs(x) for x in a), default=0)
    if 0 < peak < 16000:
        g = min(8.0, 23000 / peak)
        a = array.array("h", (max(-32767, min(32767, int(x * g))) for x in a))
    return a.tobytes()


def transcribe(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm)
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("language", "tr"), ("response_format", "json"), ("temperature", "0"), ("prompt", prompt())):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="v.wav"\r\n'
                 f'Content-Type: audio/wav\r\n\r\n'.encode() + buf.getvalue() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    c = UnixHTTP("localhost", timeout=60)
    c.request("POST", "/inference", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"})
    r = c.getresponse(); data = r.read(); c.close()
    return re.sub(r"\s+", " ", json.loads(data).get("text", "")).strip()


def mic_source():
    out = subprocess.run(["pactl", "-s", PULSE, "list", "short", "sources"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) > 1 and f[1].startswith(MIC_MATCH):
            return f[1]
    return None


class Rec:
    def __init__(self):
        self.p = None; self.buf = []

    def start(self):
        src = mic_source()
        if not src:
            print("no mic source", flush=True); return False
        self.buf = []
        self.p = subprocess.Popen(["parecord", f"--server={PULSE}", "-d", src, "--rate=16000", "--channels=1",
                                   "--format=s16le", "--raw", "--latency-msec=40"], stdout=subprocess.PIPE)
        threading.Thread(target=self._read, args=(self.p, self.buf), daemon=True).start()
        return True

    @staticmethod
    def _read(p, buf):
        while True:
            b = p.stdout.read(3200)
            if not b:
                break
            buf.append(b)

    def stop(self):
        p, self.p = self.p, None
        if p:
            p.terminate()
            try:
                p.wait(2)
            except Exception:
                p.kill()
        time.sleep(0.05)
        return b"".join(self.buf)


def endpoint(rec, stop):
    """Tap mode: stop ~0.7 s after the speech ends (energy VAD on 100 ms frames), or on a second key press,
    or after MAX_SEC; give up after 4 s without speech. A fixed 5 s window made every command wait 5 s and
    fed trailing room noise to the recogniser."""
    t0 = time.time(); seen = False; quiet = 0; loud = 0; floor = None; done = 0
    while not stop.wait(0.1):
        pcm = b"".join(rec.buf)
        n = len(pcm) // 3200                       # 100 ms frames at 16 kHz s16
        while done < n:
            a = array.array("h"); a.frombytes(pcm[done * 3200:(done + 1) * 3200])
            rms = (sum(x * x for x in a) / max(1, len(a))) ** 0.5
            done += 1
            if done <= 2:                          # key click lands in the first ~200 ms
                continue
            if done <= 6:
                floor = rms if floor is None else min(floor, rms)
            thr = max(250.0, (floor or 0) * 3.0)
            if rms > thr:
                loud += 1; quiet = 0
                if loud >= 2:
                    seen = True
            else:
                loud = 0
                if seen:
                    quiet += 1
        el = time.time() - t0
        if (seen and quiet >= 8 and el > 1.5) or el > MAX_SEC or (not seen and el > 4.0):
            return


def main():
    rec, devs, last_scan = Rec(), {}, 0
    state = {"down": None, "tap": None, "last": 0}
    work = threading.Lock()

    def finish(pcm):
        with work:
            pcm = pcm[: MAX_SEC * 32000]
            a = array.array("h"); a.frombytes(pcm[: len(pcm) // 2 * 2])
            secs, peak = len(a) / 16000, max((abs(x) for x in a), default=0)
            if secs < 0.4 or peak < 300:
                print(f"too short/quiet {secs:.1f}s peak={peak}", flush=True); post("/voice/fail"); return
            post("/voice/think")
            t = time.time()
            pcm = normalize(pcm)
            try:
                text = transcribe(pcm)
            except Exception as e:
                print("whisper:", e, flush=True); post("/voice/fail"); return
            print(f"{secs:.1f}s audio -> {time.time() - t:.1f}s: {text!r}", flush=True)
            keep_clip(pcm, text)
            if HALLU.fullmatch(text.strip(" .,!…").lower()):          # whisper's stock phrases on silence/noise
                print("hallucination dropped", flush=True); text = ""
            post("/voice", {"text": text}) if text and not text.startswith(("[", "(")) else post("/voice/fail")

    def kb_mic():
        """The on-screen TV Klavye's mic key logs 'KlavyeMic: start' (Android can't reach the host);
        treat it like a tap on the remote's voice key: listen until silence, transcribe, type."""
        while True:
            try:
                subprocess.run(["adb", "connect", "__ANDROID_IP__:5555"], capture_output=True, timeout=10)
                p = subprocess.Popen(["adb", "-s", "__ANDROID_IP__:5555", "logcat", "-T", "1", "-s", "KlavyeMic:I"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="ignore")
                for line in p.stdout:
                    if "start" not in line or "KlavyeMic" not in line:
                        continue
                    if state.get("tap"):
                        state["tap"].set(); continue
                    if work.locked() or state["down"] or time.time() - state.get("last", 0) < 0.8:
                        continue
                    if not rec.start():
                        post("/voice/fail"); continue
                    state["last"] = time.time(); post("/voice/listen")
                    stop = threading.Event(); state["tap"] = stop
                    def tap(stop=stop):
                        endpoint(rec, stop)
                        state["tap"] = None
                        finish(rec.stop())
                    threading.Thread(target=tap, daemon=True).start()
                p.wait()
            except Exception as e:
                print("kb mic:", e, flush=True)
            time.sleep(5)

    threading.Thread(target=kb_mic, daemon=True).start()

    while True:
        if time.time() - last_scan > 5:
            last_scan = time.time()
            for path in evdev.list_devices():
                if path in devs:
                    continue
                try:
                    d = evdev.InputDevice(path)
                except Exception:
                    continue
                if d.name.startswith(REMOTE_MATCH) and VOICE_KEYS & set(d.capabilities().get(ecodes.EV_KEY, [])):
                    devs[path] = d; print("listening on", path, d.name, flush=True)
                else:
                    d.close()
        if state["down"] and time.time() - state["down"] > MAX_SEC:      # safety cap
            state["down"] = None; threading.Thread(target=finish, args=(rec.stop(),), daemon=True).start()
        if not devs:
            time.sleep(5); continue
        r, _, _ = select.select(list(devs.values()), [], [], 0.5)
        for d in r:
            try:
                evs = list(d.read())
            except OSError:
                devs.pop(d.path, None); continue
            for ev in evs:
                if ev.type != ecodes.EV_KEY or ev.code not in VOICE_KEYS:
                    continue
                if ev.value != 1 and ev.value != 0:
                    continue
                if ev.value == 1 and state.get("tap"):          # second press while listening = "done"
                    state["tap"].set(); continue
                if ev.value == 1 and (work.locked() or time.time() - state.get("last", 0) < 0.8):
                    continue                                   # busy / bounce: ignore (no queue of stale requests)
                if ev.value == 1 and not state["down"]:
                    if rec.start():
                        state["down"] = time.time(); post("/voice/listen")
                elif ev.value == 0 and state["down"]:
                    held = time.time() - state["down"]
                    state["down"] = None; state["last"] = time.time()
                    if held < TAP_SEC:            # this remote sends press+release at once: listen until silence
                        stop = threading.Event(); state["tap"] = stop
                        def tap(stop=stop):
                            endpoint(rec, stop)
                            state["tap"] = None
                            finish(rec.stop())
                        threading.Thread(target=tap, daemon=True).start()
                    else:
                        threading.Thread(target=finish, args=(rec.stop(),), daemon=True).start()


if __name__ == "__main__":
    main()
