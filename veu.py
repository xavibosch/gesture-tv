"""Ordres de veu en anglès, reconegudes en local amb Vosk.

Cap àudio surt del Mac: el model és un fitxer d'aquesta carpeta i tot el
reconeixement es fa aquí. No es desa cap gravació.

Ordres: down · up · left · right · more · less · ok · netflix · youtube ·
3cat · spotify · hbo · home · close · open
Les direccions i el volum admeten un número: "down two", "more three".
"""

from __future__ import annotations

import difflib
import json
import queue
import re
import threading
from pathlib import Path

import sounddevice as sd
import vosk

import config

MODEL_DIR = Path(__file__).parent / "models" / config.VEU_MODEL
SAMPLE_RATE = 16000
# Llargada (en sons) per sota de la qual una ordre es considera massa curta
# per buscar-la dins d'una frase: cal que sigui una paraula sencera.
CURTA = 3


def normalitza(text: str) -> str:
    """Minúscules, sense apòstrofs ni signes, espais col·lapsats."""
    text = re.sub(r"[’'`´]", " ", text.lower())
    text = re.sub(r"[^0-9a-z ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def unifica_variants(text: str) -> str:
    """Ajunta les formes que el reconeixedor separa o escriu diferent.

    Vosk transcriu "youtube" com a "you tube" i "hbo" com a "h b o", i sense
    unificar-ho no coincidirien mai. Les variants més llargues es proven
    primer, perquè "t v three" guanyi abans que "tv".
    """
    for variant in sorted(config.VEU_VARIANTS, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(variant)}\b",
                      config.VEU_VARIANTS[variant], text)
    return text


def fonetica(text: str) -> str:
    """Redueix el text als seus sons en anglès, no a la seva ortografia.

    El reconeixedor escriu el que sona: "less" pot sortir "les", "more" pot
    sortir "mor". Plegant els sons equivalents i llevant els espais, les
    variants acaben igual.
    """
    t = normalitza(text)
    t = re.sub(r"\bkn|\bwr|\bgn", lambda m: m.group()[1], t)   # knee, write
    t = re.sub(r"ough|augh", "o", t)
    t = t.replace("ph", "f").replace("gh", "")
    t = re.sub(r"[ck]k?|q(?=u)|qu", "k", t)
    t = t.replace("x", "ks").replace("z", "s")
    t = re.sub(r"sh|ch|tio|ti(?=on)", "x", t)
    t = t.replace("th", "t")
    t = re.sub(r"[aeiou]+", "a", t)        # les vocals angleses són inestables
    t = t.replace("v", "f").replace("w", "u")
    t = t.replace(" ", "")
    return re.sub(r"(.)\1+", r"\1", t)     # lletres dobles


def _semblanca(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _conte_aproximat(sentit: str, ordre: str) -> float:
    """Millor semblança de l'ordre dins de tot el que s'ha sentit."""
    if not ordre:
        return 0.0
    if ordre in sentit:
        return 1.0
    millor = _semblanca(sentit, ordre)
    finestra = len(ordre)
    for inici in range(0, max(1, len(sentit) - finestra + 1)):
        for llarg in (finestra, finestra + 2, max(1, finestra - 2)):
            tros = sentit[inici:inici + llarg]
            if tros:
                millor = max(millor, _semblanca(tros, ordre))
    return millor


def _numero(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return config.VEU_NUMEROS.get(token)


def _direccio_a(tokens: list[str], i: int) -> str | None:
    """Direcció que comença al token i, mirant també la parella de tokens."""
    for llarg in (2, 1):
        if i + llarg > len(tokens):
            continue
        so = fonetica(" ".join(tokens[i:i + llarg]))
        for paraula, zona in config.VEU_DIRECCIONS.items():
            if so == fonetica(paraula):
                return zona
    return None


def interpreta(text: str) -> tuple[str, int] | None:
    """Tradueix el que s'ha sentit a (nom de zona, vegades a repetir).

    Retorna None si no s'hi reconeix cap ordre.
    """
    net = unifica_variants(normalitza(text))
    if not net:
        return None
    tokens = net.split()

    # Direccions i volum: es comparen pel so i poden portar un número.
    for i in range(len(tokens)):
        zona = _direccio_a(tokens, i)
        if zona is None:
            continue
        vegades = 1
        for salt in (2, 1):
            if i + salt < len(tokens):
                trobat = _numero(tokens[i + salt])
                if trobat:
                    vegades = trobat
                    break
        # "more" i "less" mouen el volum uns quants passos de cop: un sol pas
        # no es nota, i dir "more five" hauria de pujar cinc vegades això.
        if zona in ("VolumeUp", "VolumeDown"):
            vegades *= config.PAS_VOLUM
            return zona, max(1, min(vegades, config.VEU_MAX_VOLUM))
        return zona, max(1, min(vegades, config.VEU_MAX_REPETICIONS))

    # Accions: comparació fonètica, la frase més llarga primer.
    so_sentit = fonetica(net)
    sons_tokens = [fonetica(t) for t in tokens]
    millor_zona, millor_punt = None, 0.0
    for frase in sorted(config.VEU_ACCIONS, key=len, reverse=True):
        so_frase = fonetica(frase)
        if len(so_frase) <= CURTA:
            # Les ordres curtes ("ok" -> "ak") encaixarien dins de qualsevol
            # frase llarga. Per a aquestes cal una paraula sencera igual.
            punt = 1.0 if so_frase in sons_tokens else 0.0
        else:
            punt = _conte_aproximat(so_sentit, so_frase)
        if punt > millor_punt:
            millor_zona, millor_punt = config.VEU_ACCIONS[frase], punt
        if punt == 1.0:
            break
    if millor_punt >= config.VEU_LLINDAR_SEMBLANCA:
        return millor_zona, 1
    return None


class EscoltadorVeu:
    """Escolta el micròfon i tradueix el que sent a ordres."""

    def __init__(self, device: int | None = None):
        if not MODEL_DIR.exists():
            raise SystemExit(f"Falta el model de veu: {MODEL_DIR}")
        self.device = device
        self.sentit = ""            # última frase sentida, per ensenyar-la
        self._cua: queue.Queue = queue.Queue()
        self._resultats: queue.Queue = queue.Queue()
        self._atura = threading.Event()

    def _callback(self, indata, frames, time_info, status) -> None:
        self._cua.put(bytes(indata))

    def _bucle(self) -> None:
        vosk.SetLogLevel(-1)
        model = vosk.Model(str(MODEL_DIR))
        rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000,
                               device=self.device, dtype="int16",
                               channels=1, callback=self._callback):
            while not self._atura.is_set():
                dades = self._cua.get()
                # Només resultats finals: amb els parcials, "down two"
                # dispararia en sentir "down", abans que arribés el número.
                if not rec.AcceptWaveform(dades):
                    parcial = json.loads(rec.PartialResult()).get("partial", "")
                    if parcial:
                        self.sentit = parcial
                    continue
                text = json.loads(rec.Result()).get("text", "")
                if not text:
                    continue
                self.sentit = text
                ordre = interpreta(text)
                if ordre is not None:
                    self._resultats.put(ordre)

    def comenca(self) -> None:
        threading.Thread(target=self._bucle, daemon=True).start()

    def ordre(self) -> tuple[str, int] | None:
        """Retorna (zona, vegades) si s'ha demanat res per veu."""
        try:
            return self._resultats.get_nowait()
        except queue.Empty:
            return None

    def atura(self) -> None:
        self._atura.set()
