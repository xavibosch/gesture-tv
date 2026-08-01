"""Control de la TV Sony amb la mà: posa-la en una zona i s'obre l'app.

Ús:
    .venv/bin/python zones_tv.py           # mode prova: no envia res a la TV
    .venv/bin/python zones_tv.py --live    # actua de veritat
    .venv/bin/python zones_tv.py --test-tv # només encén la TV i surt

Tecla q per sortir.

Seguretat, per disseny:
  - El programa no executa CAP ordre del sistema (no importa `subprocess`).
  - L'única sortida a la xarxa són peticions HTTP a l'API de control de la
    pròpia TV, amb ordres fixes: encendre i obrir una app concreta. No
    descarrega res, no executa res, no pot instal·lar res enlloc.
  - L'adreça de destí es comprova que sigui privada (xarxa local). Si algú hi
    posés una adreça d'Internet, el programa es nega a enviar res.
  - La imatge de la càmera no es desa ni s'envia enlloc. Tot es processa en
    memòria i es descarta.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import BaseOptions, vision

import config

MODEL_PATH = Path(__file__).parent / "models" / "gesture_recognizer.task"
# En espera profunda el servidor HTTP de la TV triga a respondre: cal marge.
TV_TIMEOUT_S = 15.0
TV_RETRIES = 2
# Punts del palmell segons MediaPipe: canell, base de l'índex, base del menovell.
PALM_POINTS = (0, 5, 17)


# --- Control de la TV (API IP de Sony) ---

def _check_local_ip(ip: str) -> str:
    """Només es permeten adreces de xarxa privada. Res que surti a Internet."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"TV_IP no és una adreça IP vàlida: {ip!r}")
    if not address.is_private:
        raise ValueError(
            f"TV_IP ({ip}) no és una adreça de xarxa local. Per seguretat, "
            "aquest programa només parla amb dispositius de casa teva."
        )
    return ip


def _post(path: str, body: bytes, headers: dict) -> bytes:
    ip = _check_local_ip(config.TV_IP)
    if config.TV_PSK:
        headers = {**headers, "X-Auth-PSK": config.TV_PSK}
    request = urllib.request.Request(
        f"http://{ip}{path}", data=body, headers=headers, method="POST"
    )
    last_error: Exception | None = None
    for attempt in range(TV_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TV_TIMEOUT_S) as response:
                return response.read()
        except urllib.error.HTTPError as err:
            if err.code == 403:
                raise ValueError(
                    "La TV rebutja la clau (403). Comprova que TV_PSK i la clau "
                    "precompartida de la TV siguin idèntiques."
                ) from err
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            # Sortint d'espera profunda, la primera petició sol caducar.
            last_error = err
            if attempt < TV_RETRIES:
                time.sleep(1.5)
    raise OSError(f"la TV no respon després de {TV_RETRIES + 1} intents: {last_error}")


def _sony_json(service: str, method: str, params: list) -> dict:
    body = json.dumps(
        {"method": method, "id": 1, "params": params, "version": "1.0"}
    ).encode()
    raw = _post(f"/sony/{service}", body, {"Content-Type": "application/json"})
    return json.loads(raw)


def tv_power_status() -> str:
    """Consulta si la TV està encesa o en espera. No canvia res."""
    reply = _sony_json("system", "getPowerStatus", [])
    if "result" in reply:
        return reply["result"][0].get("status", "?")
    return f"error: {reply.get('error')}"


IRCC_ENVELOPE = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
    ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
    '<u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">'
    "<IRCCCode>{code}</IRCCCode></u:X_SendIRCC></s:Body></s:Envelope>"
)


def _require_psk() -> None:
    if not config.TV_PSK:
        raise ValueError(
            "Falta la clau: posa TV_PSK a config.py i la mateixa clau a la TV "
            "(Configuració > Xarxa > Control per IP > Clau precompartida)."
        )


def send_key(key: str) -> str:
    """Envia una tecla del comandament per xarxa.

    No es fa servir `setPowerStatus` per encendre: aquest model el suporta,
    però en espera respon "Illegal State". Les tecles IRCC sí que funcionen.
    """
    _require_psk()
    code = config.KEYS.get(key)
    if code is None:
        raise ValueError(f"tecla desconeguda: {key}")
    _post(
        "/sony/IRCC",
        IRCC_ENVELOPE.format(code=code).encode(),
        {
            "Content-Type": "text/xml; charset=UTF-8",
            "SOAPACTION": '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"',
        },
    )
    return key


def turn_tv_on() -> str:
    """Encén la TV, si no ho està ja."""
    if tv_power_status() == "active":
        return "la TV ja estava encesa"
    send_key("WakeUp")
    return "TV encesa"


def toggle_power() -> str:
    """Encén o apaga, segons com estigui ara la TV.

    Si no es pot consultar l'estat (la TV triga a despertar-se), s'assumeix que
    està apagada i s'intenta encendre igualment: és el cas que interessa.
    """
    _require_psk()
    try:
        active = tv_power_status() == "active"
    except (ValueError, OSError, urllib.error.URLError):
        active = False
    if active:
        send_key("PowerOff")
        return "TV apagada"
    send_key("WakeUp")
    return "TV encesa"


def launch_app(uri: str, name: str) -> str:
    """Obre una app a la TV. Si està en espera, primer l'encén."""
    _require_psk()
    if tv_power_status() != "active":
        turn_tv_on()
        # La TV triga uns segons a acceptar ordres després d'encendre's.
        for _ in range(12):
            time.sleep(1.0)
            if tv_power_status() == "active":
                break

    reply = _sony_json("appControl", "setActiveApp", [{"uri": uri}])
    if reply.get("error"):
        raise ValueError(f"{name}: la TV respon {reply['error']}")
    return f"{name} obert a la TV"


# --- Mans ---

class HandTracker:
    """Dona la posició de les mans que es veuen a la imatge."""

    def __init__(self):
        if not MODEL_PATH.exists():
            raise SystemExit(f"Falta el model de mans: {MODEL_PATH}")
        options = vision.GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
        )
        # Es fa servir només per les posicions de les mans; la classificació de
        # gestos que porta el model s'ignora.
        self._recognizer = vision.GestureRecognizer.create_from_options(options)
        self.hands: list[tuple[float, float]] = []

    @staticmethod
    def _palm_center(landmarks) -> tuple[float, float]:
        xs = [landmarks[i].x for i in PALM_POINTS]
        ys = [landmarks[i].y for i in PALM_POINTS]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    def update(self, frame_rgb: np.ndarray, now: float) -> list:
        result = self._recognizer.recognize_for_video(
            Image(image_format=ImageFormat.SRGB, data=frame_rgb), int(now * 1000)
        )
        self.hands = [self._palm_center(lm) for lm in result.hand_landmarks]
        return self.hands

    def close(self) -> None:
        self._recognizer.close()


# --- Zones ---

class HotspotTracker:
    """Zones on posar la mà, amb temps de retenció abans d'actuar."""

    def __init__(self, hotspots, width: int, height: int):
        self.hotspots = hotspots
        self.width, self.height = width, height
        self.active: str | None = None   # zona on hi ha la mà ara
        self.progress = 0.0              # 0..1 de la retenció
        self._since: float | None = None
        self._last_key: float | None = None

    def _hit(self, hands) -> dict | None:
        for hand in hands:
            for spot in self.hotspots:
                x0, y0, x1, y1 = spot["rect"]
                if x0 <= hand[0] <= x1 and y0 <= hand[1] <= y1:
                    return spot
        return None

    def update(self, hands, now: float) -> dict | None:
        """Retorna la zona a activar.

        Les tecles ("key") disparen a l'instant en entrar-hi i es repeteixen
        mentre hi tens la mà. La resta necessiten mantenir-hi la mà.
        """
        spot = self._hit(hands)
        if spot is None:
            self.reset()
            return None

        if spot["name"] != self.active:
            self.active, self._since, self._last_key = spot["name"], now, None

        if spot["kind"] == "key":
            self.progress = 0.0
            if (self._last_key is None
                    or now - self._last_key >= config.KEY_REPEAT_S):
                self._last_key = now
                return spot
            return None

        held = now - self._since
        self.progress = min(held / config.HOTSPOT_HOLD_S, 1.0)
        if held >= config.HOTSPOT_HOLD_S:
            self.reset()
            return spot
        return None

    def reset(self) -> None:
        self.active, self.progress = None, 0.0
        self._since, self._last_key = None, None

    @staticmethod
    def _arrow(frame, glyph: str, p0, p1, colour) -> None:
        """Dibuixa una fletxa dins la caixa (OpenCV no pot pintar ▲ com a text)."""
        cx, cy = (p0[0] + p1[0]) // 2, (p0[1] + p1[1]) // 2
        rx, ry = int((p1[0] - p0[0]) * 0.28), int((p1[1] - p0[1]) * 0.28)
        points = {
            "up": [(cx, cy - ry), (cx - rx, cy + ry), (cx + rx, cy + ry)],
            "down": [(cx, cy + ry), (cx - rx, cy - ry), (cx + rx, cy - ry)],
            "left": [(cx - rx, cy), (cx + rx, cy - ry), (cx + rx, cy + ry)],
            "right": [(cx + rx, cy), (cx - rx, cy - ry), (cx - rx, cy + ry)],
        }[glyph]
        cv2.fillPoly(frame, [np.array(points, dtype=np.int32)], colour)
        cv2.polylines(frame, [np.array(points, dtype=np.int32)], True, (0, 0, 0), 2)

    def draw(self, frame: np.ndarray, power_on: bool | None = None,
             current_app: str | None = None) -> np.ndarray:
        for spot in self.hotspots:
            x0, y0, x1, y1 = spot["rect"]
            p0 = (int(x0 * self.width), int(y0 * self.height))
            p1 = (int(x1 * self.width), int(y1 * self.height))
            selected = spot["name"] == self.active
            kind = spot["kind"]
            is_open = kind == "app" and spot["name"] == current_app
            if kind == "power":
                base = (90, 90, 240) if power_on else (80, 220, 120)
            elif kind == "key":
                base = (255, 190, 90)
            elif is_open:
                base = (200, 160, 255)
            else:
                base = (0, 220, 255)

            if selected and kind != "key":
                # Barra que s'omple mentre mantens la mà a dins.
                fill = int(p0[0] + (p1[0] - p0[0]) * self.progress)
                overlay = frame.copy()
                cv2.rectangle(overlay, p0, (fill, p1[1]), base, -1)
                frame = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)
            elif selected:
                overlay = frame.copy()
                cv2.rectangle(overlay, p0, p1, base, -1)
                frame = cv2.addWeighted(overlay, 0.35, frame, 0.65, 0)

            colour = base if selected else (230, 230, 230)
            cv2.rectangle(frame, p0, p1, colour, 3 if selected else 2)

            if spot.get("glyph"):
                self._arrow(frame, spot["glyph"], p0, p1, colour)
                continue

            if kind == "power":
                label = "Apagar TV" if power_on else "Encendre TV"
            elif is_open:
                label = f"< Inici ({spot['name']})"
            else:
                label = spot.get("label", spot["name"])

            scale, thick = (0.7, 2) if kind == "key" else (0.8, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                          scale, thick)
            if kind == "key":                   # OK: etiqueta dins la caixa
                tx = (p0[0] + p1[0] - tw) // 2
                ty = (p0[1] + p1[1] + th) // 2
            else:                               # apps: etiqueta sota la caixa
                tx = max(4, p0[0] + ((p1[0] - p0[0]) - tw) // 2)
                ty = p1[1] + th + 12
                if ty > self.height - 6:
                    ty = p0[1] - 10
            cv2.putText(frame, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(frame, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, colour, thick, cv2.LINE_AA)
        return frame


class TvWorker:
    """Envia ordres a la TV en un fil a part: el vídeo no es congela."""

    def __init__(self):
        self.status = ""
        self.status_ts = 0.0
        self.power_on: bool | None = None   # None = encara no se sap
        # App que hem obert nosaltres. La TV no diu quina app té oberta, així
        # que ho recordem aquí: si la canvies amb el comandament físic, aquest
        # valor queda desfasat fins que tornis a l'inici o apaguis.
        self.current_app: str | None = None
        self._busy = False
        self._lock = threading.Lock()

    def start_power_poll(self) -> None:
        """Consulta cada pocs segons si la TV està encesa, en segon pla."""
        def poll():
            while True:
                try:
                    self.power_on = tv_power_status() == "active"
                    if not self.power_on:
                        self.current_app = None
                except (ValueError, OSError, urllib.error.URLError):
                    self.power_on = None
                time.sleep(config.POWER_POLL_S)

        threading.Thread(target=poll, daemon=True).start()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def _set(self, text: str) -> None:
        with self._lock:
            self.status, self.status_ts, self._busy = text, time.time(), False
        print(text)

    def run(self, func, *args) -> bool:
        """Llança la crida. Retorna False si ja n'hi ha una en marxa."""
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def worker():
            try:
                self._set(func(*args))
            except (ValueError, OSError, urllib.error.URLError) as err:
                self._set(f"ERROR: {err}")

        threading.Thread(target=worker, daemon=True).start()
        return True


def repeteix_tecla(key: str, vegades: int) -> str:
    """Envia una tecla diverses vegades seguides."""
    for i in range(vegades):
        if i:
            time.sleep(config.VEU_PAUSA_REPETICIO_S)
        send_key(key)
    return key if vegades == 1 else f"{key} x{vegades}"


def _do(spot: dict, tv: "TvWorker") -> str:
    """Executa el que demana una zona."""
    kind = spot["kind"]
    if kind == "key" and spot.get("vegades", 1) > 1:
        return repeteix_tecla(spot["key"], spot["vegades"])
    if kind == "power":
        message = toggle_power()
        tv.current_app = None
        return message
    if kind == "key":
        return send_key(spot["key"])

    # Si l'app ja està oberta, el mateix botó serveix per tornar a l'inici.
    if tv.current_app == spot["name"]:
        send_key("Home")
        tv.current_app = None
        return f"tornat a l'inici (era {spot['name']})"

    message = launch_app(spot["uri"], spot["name"])
    tv.current_app = spot["name"]
    return message


def main() -> None:
    parser = argparse.ArgumentParser(description="Zones amb la mà -> TV Sony")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    parser.add_argument("--live", action="store_true",
                        help="actua de veritat sobre la TV")
    parser.add_argument("--test-tv", action="store_true",
                        help="només encén la TV i surt (sense càmera)")
    parser.add_argument("--veu", action="store_true",
                        help="escolta també ordres de veu en anglès")
    parser.add_argument("--test-volum", action="store_true",
                        help="puja i baixa el volum per comprovar que els "
                             "codis de volum siguin els correctes")
    args = parser.parse_args()

    if args.test_volum:
        try:
            print("pujant el volum 3 vegades...")
            print(" ", repeteix_tecla("VolumeUp", 3))
            time.sleep(1.5)
            print("baixant-lo 3 vegades...")
            print(" ", repeteix_tecla("VolumeDown", 3))
            print("\nHas vist el volum moure's a la TV? Si no, els codis de "
                  "volum de config.py no són els d'aquest model.")
        except (ValueError, OSError, urllib.error.URLError) as err:
            raise SystemExit(str(err))
        return

    if args.test_tv:
        try:
            print("estat abans:", tv_power_status())
            print(turn_tv_on())
            time.sleep(3)
            print("estat després:", tv_power_status())
        except (ValueError, OSError, urllib.error.URLError) as err:
            raise SystemExit(str(err))
        return

    live = args.live or not config.DRY_RUN
    if live:
        _check_local_ip(config.TV_IP)
        if not config.TV_PSK:
            raise SystemExit("Falta TV_PSK a config.py. Prova amb --test-tv.")

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    if not cap.isOpened():
        raise SystemExit(
            f"No puc obrir la càmera {args.camera}. Dona permís de càmera a "
            "l'app des d'on ho executes: Configuració del sistema > Privadesa i "
            "seguretat > Càmera."
        )
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("La càmera no dona imatge.")
    height, width = frame.shape[:2]
    print(f"Càmera {args.camera}: {width}x{height} | "
          f"{'MODE REAL' if live else 'MODE PROVA (no envia res)'}")

    hands = HandTracker()
    # Les zones marcades "nomes_veu" no tenen lloc a la pantalla: existeixen
    # només perquè les puguis demanar parlant.
    dibuixables = [s for s in config.HOTSPOTS if not s.get("nomes_veu")]
    hotspots = HotspotTracker(dibuixables, width, height)
    tv = TvWorker()
    if live:
        tv.start_power_poll()

    # Zones accessibles per veu però que no es dibuixen a la pantalla.
    # Per veu, encendre i apagar són ordres separades: dir "tancar tv" ha
    # d'apagar sempre, no alternar.
    per_nom = {spot["name"]: spot for spot in config.HOTSPOTS}
    per_nom["Home"] = {"name": "Home", "kind": "key", "key": "Home"}
    per_nom["PowerOff"] = {"name": "PowerOff", "kind": "key", "key": "PowerOff"}
    per_nom["PowerOn"] = {"name": "PowerOn", "kind": "key", "key": "WakeUp"}
    per_nom["VolumeUp"] = {"name": "VolumeUp", "kind": "key", "key": "VolumeUp"}
    per_nom["VolumeDown"] = {"name": "VolumeDown", "kind": "key",
                             "key": "VolumeDown"}

    escoltador = None
    if args.veu:
        from veu import EscoltadorVeu
        print("Escoltant ordres de veu en català...")
        escoltador = EscoltadorVeu()
        escoltador.comenca()
    last_voice = 0.0
    last_fire = 0.0
    status, status_ts = "", 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)   # mirall: moure't és intuïtiu
            now = time.time()

            positions = hands.update(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), now)
            # L'espera només val per a les accions lentes (apps i engegada):
            # les tecles han de poder anar seguides, com un comandament.
            cooling = now - last_fire < config.COOLDOWN_S

            chosen = hotspots.update(positions, now)
            if chosen is not None:
                is_key = chosen["kind"] == "key"
                if cooling and not is_key:
                    hotspots.reset()
                elif live:
                    tv.run(_do, chosen, tv)
                    if not is_key:
                        last_fire = now
                else:
                    if is_key:
                        accio = f"tecla {chosen['name']}"
                    elif chosen["kind"] == "power":
                        accio = "apagaria la TV" if tv.power_on else "encendria la TV"
                    elif tv.current_app == chosen["name"]:
                        accio = "tornaria a l'inici"
                        tv.current_app = None
                    else:
                        accio = f"obriria {chosen['name']}"
                        tv.current_app = chosen["name"]
                    status, status_ts = f"[PROVA] {accio}", now
                    print(status)
                    if not is_key:
                        last_fire = now

            # --- Ordres de veu ---
            if escoltador is not None:
                dit = escoltador.ordre()
                if dit is not None and now - last_voice >= config.VEU_COOLDOWN_S:
                    nom, vegades = dit
                    spot = per_nom.get(nom)
                    if spot is not None:
                        last_voice = now
                        if vegades > 1:
                            spot = {**spot, "vegades": vegades}
                        etiqueta = nom if vegades == 1 else f"{nom} x{vegades}"
                        if live:
                            tv.run(_do, spot, tv)
                            status = f"veu: {etiqueta}"
                        else:
                            status = f"[PROVA] veu: {etiqueta}"
                        status_ts = now
                        print(status)

            if tv.status and tv.status_ts > status_ts:
                status, status_ts = tv.status, tv.status_ts

            display = hotspots.draw(frame, power_on=tv.power_on,
                                    current_app=tv.current_app)
            for hx, hy in positions:
                centre = (int(hx * width), int(hy * height))
                cv2.circle(display, centre, 10, (0, 220, 255), -1)
                cv2.circle(display, centre, 10, (0, 0, 0), 2)

            hud = [
                f"mans a la vista: {len(positions)}",
                "MODE REAL" if live else "MODE PROVA",
            ]
            if hotspots.active:
                hud.append(f"{hotspots.active}: {hotspots.progress * 100:.0f}%")
            if escoltador is not None and escoltador.sentit:
                hud.append(f'sento: "{escoltador.sentit[-40:]}"')
            if tv.busy:
                hud.append("enviant ordre a la TV...")
            if cooling:
                hud.append(f"espera {config.COOLDOWN_S - (now - last_fire):.1f}s")
            for i, line in enumerate(hud):
                pos = (12, 26 + i * 24)
                cv2.putText(display, line, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(display, line, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (255, 255, 255), 1, cv2.LINE_AA)
            if status and now - status_ts < 4.0:
                pos = (12, height - 18)
                cv2.putText(display, status, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 0, 0), 5, cv2.LINE_AA)
                cv2.putText(display, status, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 255, 255), 2, cv2.LINE_AA)

            cv2.imshow("mà -> TV", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        hands.close()
        if escoltador is not None:
            escoltador.atura()


if __name__ == "__main__":
    main()
