"""Configuració: zones amb la mà per controlar la TV Sony."""

# --- Càmera ---
CAMERA_INDEX = 0          # 0 = webcam del Mac
FRAME_WIDTH = 960
FRAME_HEIGHT = 540

# --- Mode de proves ---
# True  -> no envia res a la TV, només ensenya a pantalla què faria.
# False -> actua de veritat (o posa --live).
DRY_RUN = True

# --- TV Sony XR-75X90L ---
# S'encén per l'API de control IP de Sony (aquest model ignora el Wake-on-LAN
# clàssic: manté la xarxa viva en espera, però no respon al paquet màgic).
TV_IP = "192.168.1.10"   # <- la IP local de la teva TV

# Clau compartida (Pre-Shared Key) que has de posar a la TV:
#   Configuració > Xarxa > Configuració de xarxa domèstica > Control per IP
#     - Autenticació: "Normal i clau precompartida"
#     - Clau precompartida: la que escriguis aquí
# No facis servir cap contrasenya important: viatja en clar per la xarxa local.
TV_PSK = "canvia-aixo"   # <- la clau que has posat a la TV

# Codis de tecla, tal com els declara aquesta TV (getRemoteControllerInfo).
KEYS = {
    "WakeUp": "AAAAAQAAAAEAAAAuAw==",
    "PowerOff": "AAAAAQAAAAEAAAAvAw==",
    "Up": "AAAAAQAAAAEAAAB0Aw==",
    "Down": "AAAAAQAAAAEAAAB1Aw==",
    "Left": "AAAAAQAAAAEAAAA0Aw==",
    "Right": "AAAAAQAAAAEAAAAzAw==",
    "Confirm": "AAAAAQAAAAEAAABlAw==",
    "Home": "AAAAAQAAAAEAAABgAw==",
    # PENDENT DE VERIFICAR: aquests dos són els codis estàndard de Sony, però
    # la TV estava en espera profunda i no els he pogut llegir de la seva
    # pròpia llista com la resta. Comprova'ls amb la TV encesa:
    #   .venv/bin/python zones_tv.py --test-volum
    "VolumeUp": "AAAAAQAAAAEAAAASAw==",
    "VolumeDown": "AAAAAQAAAAEAAAATAw==",
}

# Passos de volum que envia una ordre de "more" / "less".
PAS_VOLUM = 5

# --- Zones ---
# rect = (x0, y0, x1, y1) en fraccions del frame. La imatge està en mirall,
# així que "dalt a la dreta" és dalt a la dreta tal com et veus a la pantalla.
#
# kind:
#   "app"   -> obre una app (uri). Cal mantenir-hi la mà.
#   "power" -> encén o apaga, segons com estigui. Cal mantenir-hi la mà.
#   "key"   -> tecla del comandament. Instantània, sense mantenir.
HOTSPOTS = [
    # Cantonades: apps i engegada. Caixes petites, per no tocar-les sense voler.
    {
        "name": "YouTube", "kind": "app",
        "rect": (0.03, 0.05, 0.20, 0.20),
        "uri": "com.sony.dtv.com.google.android.youtube.tv"
               ".com.google.android.apps.youtube.tv.activity.ShellActivity",
    },
    {
        "name": "Netflix", "kind": "app",
        "rect": (0.80, 0.05, 0.97, 0.20),
        "uri": "com.sony.dtv.com.netflix.ninja.com.netflix.ninja.MainActivity",
    },
    {
        "name": "3Cat", "kind": "app",
        "rect": (0.03, 0.80, 0.20, 0.95),
        "uri": "com.sony.dtv.cat.ccma.androidtv.tv3"
               ".cat.ccma.androidtv.views.activities.GatewayActivity",
    },
    {"name": "power", "kind": "power", "rect": (0.80, 0.80, 0.97, 0.95)},

    # Només per veu: no es dibuixen, no hi ha lloc a la pantalla.
    {
        "name": "Spotify", "kind": "app", "nomes_veu": True,
        "uri": "com.sony.dtv.com.spotify.tv.android"
               ".com.spotify.tv.android.SpotifyTVActivity",
    },
    {
        "name": "HBO", "kind": "app", "nomes_veu": True,
        "uri": "com.sony.dtv.com.wbd.stream.com.wbd.beam.BeamActivity",
    },

    # Creueta del comandament, als costats. Instantànies.
    {"name": "Up", "kind": "key", "key": "Up", "glyph": "up",
     "rect": (0.45, 0.04, 0.55, 0.17)},
    {"name": "Down", "kind": "key", "key": "Down", "glyph": "down",
     "rect": (0.45, 0.83, 0.55, 0.96)},
    {"name": "Left", "kind": "key", "key": "Left", "glyph": "left",
     "rect": (0.03, 0.435, 0.13, 0.565)},
    {"name": "Right", "kind": "key", "key": "Right", "glyph": "right",
     "rect": (0.87, 0.435, 0.97, 0.565)},

    # Volum, just al costat de la fletxa dreta.
    {"name": "Vol+", "kind": "key", "key": "VolumeUp", "glyph": "up",
     "label": "Vol+", "rect": (0.87, 0.28, 0.97, 0.40)},
    {"name": "Vol-", "kind": "key", "key": "VolumeDown", "glyph": "down",
     "label": "Vol-", "rect": (0.87, 0.60, 0.97, 0.72)},

    # Seleccionar, al mig.
    {"name": "OK", "kind": "key", "key": "Confirm", "label": "OK",
     "rect": (0.455, 0.44, 0.545, 0.56)},
]

# Segons que cal mantenir la mà en una zona d'app o d'engegada.
HOTSPOT_HOLD_S = 1.2
# Repetició de les tecles instantànies mentre hi tens la mà a sobre.
KEY_REPEAT_S = 0.7
# Espera entre accions lentes (apps i engegada), per no repetir sense voler.
COOLDOWN_S = 8.0
# Cada quant es consulta si la TV està encesa (per l'etiqueta encendre/apagar).
POWER_POLL_S = 3.0

# --- Ordres de veu (anglès, reconegudes en local) ---
# En anglès el model de Vosk és força millor que el català, i les ordres són
# paraules curtes i clares.
VEU_MODEL = "vosk-model-small-en-us-0.15"

# Direccions. Admeten un número al darrere: "down two" baixa dues vegades.
# Es comparen com a paraula sencera i pel so, no com a tros de text.
VEU_DIRECCIONS = {
    "down": "Down", "up": "Up", "left": "Left", "right": "Right",
    "more": "VolumeUp", "less": "VolumeDown",
    "louder": "VolumeUp", "quieter": "VolumeDown",
}

# Formes que el reconeixedor separa o escriu diferent. S'unifiquen abans de
# comparar. Sense això, "you tube" no coincidiria mai amb "youtube".
VEU_VARIANTS = {
    "you tube": "youtube", "u tube": "youtube", "yu tube": "youtube",
    "three cat": "3cat", "tv three": "3cat", "t v three": "3cat",
    "free cat": "3cat",
    "h b o": "hbo", "age b o": "hbo", "each b o": "hbo", "hb o": "hbo",
    "a b o": "hbo", "h bo": "hbo",
    "net flix": "netflix", "spot if y": "spotify", "spot i fy": "spotify",
    "turn on": "open", "turn off": "close", "switch off": "close",
    "switch on": "open", "go home": "home",
}

# Accions sense número. Es comparen pel so, la frase més llarga primer.
VEU_ACCIONS = {
    "netflix": "Netflix",
    "youtube": "YouTube",
    "3cat": "3Cat",
    "spotify": "Spotify",
    "hbo": "HBO",
    "home": "Home",
    "close": "PowerOff",
    "open": "PowerOn",
    "ok": "OK", "okay": "OK", "select": "OK", "enter": "OK",
}

# Números en anglès que poden seguir una direcció.
VEU_NUMEROS = {
    "one": 1, "won": 1, "two": 2, "to": 2, "too": 2, "three": 3, "tree": 3,
    "four": 4, "for": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "ate": 8, "nine": 9, "ten": 10,
}
# Límit de repeticions, per si t'entén malament un número. El volum en té un
# de més alt perquè cada ordre ja val 5 passos: "more three" són 15.
VEU_MAX_REPETICIONS = 10
VEU_MAX_VOLUM = 30

# Com de semblant ha de sonar una ordre per acceptar-la (0..1). Més baix =
# entén més variants però es dispara més fàcilment amb frases qualsevol.
# Calibrat amb 23 ordres i 14 frases de conversa normal: a 0.82 es disparava
# amb "see you tomorrow" i "it looks like rain"; a 0.88, cap fals positiu i
# segueix encertant totes les ordres.
VEU_LLINDAR_SEMBLANCA = 0.88
# Pausa entre tecles repetides, perquè la TV les processi totes.
VEU_PAUSA_REPETICIO_S = 0.35

# Segons d'espera entre dues ordres de veu, per no repetir sense voler.
VEU_COOLDOWN_S = 1.5
