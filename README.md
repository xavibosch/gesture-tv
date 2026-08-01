# Gesture TV

**Hands free control for a Sony television: clap to turn it on, hold a hand in a zone to open an app, speak to navigate.**

Built for someone who cannot use a remote. The buttons are small, the presses
are precise, and none of it was designed for their hands. This replaces the
remote entirely — no phone, no app store, and no need to ask anyone for help.

Everything runs locally on a Mac. No video, no audio and no logs are ever
written to disk.

---

## How it works

Three input paths, all landing on the same set of TV commands.

### 1. Clap to power on

OpenCV learns the background from the webcam and looks for motion blobs large
enough to count as a person arriving, checked against a defined polygon zone
(`supervision.PolygonZone`). MediaPipe then tracks both hands: a clap is
registered when they go from apart to together in under a second.

### 2. Hand in a zone

The screen is divided into rectangular zones, each bound to one action. Hold a
hand inside a zone and it fires. Zones cover:

| Kind | Actions |
|---|---|
| Apps | Netflix, YouTube, 3Cat, Spotify, HBO |
| Navigation | Up, Down, Left, Right, OK |
| Volume | Vol+, Vol− |
| Power | On, Off |

Commands go to the television's own IP control API over the local network, as
fixed HTTP requests.

### 3. Voice

Vosk runs entirely offline from a model file in `models/`. Recognised commands:

```
up · down · left · right · ok · more · less
netflix · youtube · 3cat · spotify · hbo
home · open · close
```

Directions and volume take a count: `down two`, `more three`.

No audio leaves the machine and nothing is recorded.

---

## Safety, by design

This drives a device in someone's home, so the threat model was part of the
design rather than an afterthought.

- **The program cannot execute commands.** It never imports `subprocess`,
  `os.system`, `eval` or `exec`. Even with a tampered config there is no path
  to running anything.
- **No ADB.** Android Debug Bridge would open a debug port and hand out shell
  access on the television. The IP control API only accepts a fixed set of
  documented commands instead.
- **The destination is verified to be local.** The target address is checked to
  be a private address. Point it at the internet and it refuses to send.
- **Nothing is stored.** Camera frames are processed in memory and discarded.
  No video, no stills, no logs, no files written.
- **No pickle model weights.** There is no PyTorch `.pt` file, whose format can
  execute code on load. `torch` and `ultralytics` are deliberately not
  dependencies.

It also starts in dry run: without `--live` it prints what it would send and
sends nothing.

---

## Setup

### Television, once

1. **Settings → Network → Home network setup → IP control**
2. Authentication: *Normal and Pre-Shared Key*
3. Set a pre-shared key. It travels in clear text over the local network, so
   use a throwaway value, not a password you care about.
4. Note the television's local IP.

### Machine

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp config.example.py config.py
# then edit TV_IP and TV_PSK
```

### Models

Not committed, they are large. Download separately into `models/`:

- **Hand gestures** — MediaPipe `gesture_recognizer.task`
- **Speech** — a Vosk small model, for example `vosk-model-small-en-us-0.15`

---

## Use

```bash
.venv/bin/python zones_tv.py            # dry run, sends nothing
.venv/bin/python zones_tv.py --live     # actually controls the TV
.venv/bin/python zones_tv.py --test-tv  # power on and exit
```

`q` quits.

---

## Requirements

Python 3.10+, a webcam, and a Sony television with IP control on the same
network as the machine.

OpenCV · MediaPipe · supervision · NumPy · Vosk · sounddevice

---

## License

[MIT](LICENSE)
