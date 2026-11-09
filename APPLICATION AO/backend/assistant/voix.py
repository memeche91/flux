"""Voix de l'assistant : transcription (Whisper) et lecture à voix haute (Piper), en local."""
from __future__ import annotations

import io
import os
import re
import threading
import wave
from pathlib import Path

from django.conf import settings

INVITE_VOCABULAIRE = (
    "Vocabulaire : CCTP, DPGF, CCAP, RC, DCE, acte d'engagement, lot, porte-fenêtre, menuiseries extérieures, "
    "plâtrerie, DTU, maître d'ouvrage, maître d'œuvre, PSE, variante, retenue de garantie, euros HT."
)
_verrou = threading.Lock()
_whisper = None
_voix = None


def dossier_whisper() -> Path:
    return settings.IA_DOSSIER_MODELES / "whisper"


def dossier_voix() -> Path:
    return settings.IA_DOSSIER_MODELES / "voix"


def transcription_installee() -> bool:
    try:
        from faster_whisper.utils import download_model

        download_model(settings.IA_WHISPER, local_files_only=True, cache_dir=str(dossier_whisper()))
        return True
    except Exception:  # noqa: BLE001 - absent ou incomplet
        return False


def synthese_installee() -> bool:
    modele = dossier_voix() / f"{settings.IA_VOIX}.onnx"
    return modele.exists() and Path(f"{modele}.json").exists()


def preparer_transcription() -> None:
    from faster_whisper.utils import download_model

    dossier_whisper().mkdir(parents=True, exist_ok=True)
    download_model(settings.IA_WHISPER, cache_dir=str(dossier_whisper()))


def preparer_synthese() -> None:
    from piper.download_voices import download_voice

    dossier_voix().mkdir(parents=True, exist_ok=True)
    download_voice(settings.IA_VOIX, dossier_voix())


def _modele_whisper():
    global _whisper
    with _verrou:
        if _whisper is None:
            from faster_whisper import WhisperModel

            _whisper = WhisperModel(
                settings.IA_WHISPER,
                device="cpu",
                compute_type="int8",
                cpu_threads=min(8, os.cpu_count() or 4),
                download_root=str(dossier_whisper()),
            )
        return _whisper


def transcrire(chemin: Path) -> str:
    segments, _ = _modele_whisper().transcribe(
        str(chemin), language="fr", beam_size=5, vad_filter=True, initial_prompt=INVITE_VOCABULAIRE
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def _modele_voix():
    global _voix
    with _verrou:
        if _voix is None:
            from piper import PiperVoice

            if not synthese_installee():
                preparer_synthese()
            _voix = PiperVoice.load(str(dossier_voix() / f"{settings.IA_VOIX}.onnx"))
        return _voix


SIGLES = {
    "CCTP": "C C T P", "DPGF": "D P G F", "CCAP": "C C A P", "CCAG": "C C A G", "DCE": "D C E", "RC": "R C",
    "AE": "A E", "PSE": "P S E", "DTU": "D T U", "MOE": "maîtrise d'œuvre", "MOA": "maîtrise d'ouvrage",
    "PMR": "P M R", "OPC": "O P C", "SPS": "S P S", "PGC": "P G C", "DOE": "D O E", "TVA": "T V A",
    "NF": "N F", "EN": "E N", "RE2020": "R E 2020", "RE": "R E",
}
REMPLACEMENTS = [
    (re.compile(r"€\s*HT\b"), " euros hors taxes"),
    (re.compile(r"€\s*TTC\b"), " euros toutes taxes comprises"),
    (re.compile(r"€"), " euros"),
    (re.compile(r"\bHT\b"), "hors taxes"),
    (re.compile(r"\bTTC\b"), "toutes taxes comprises"),
    (re.compile(r"\bm²"), " mètres carrés"),
    (re.compile(r"\bm³"), " mètres cubes"),
    (re.compile(r"\bml\b"), " mètres linéaires"),
    (re.compile(r"\bn°\s*"), "numéro "),
    (re.compile(r"≤"), " inférieur ou égal à "),
    (re.compile(r"≥"), " supérieur ou égal à "),
    (re.compile(r"%"), " pour cent"),
    (re.compile(r"\bart\.\s*"), "article "),
]


def texte_pour_voix(texte: str) -> str:
    """Retire la mise en forme et les renvois [n], développe sigles et unités."""
    texte = re.sub(r"\[\d+(?:\s*[,–-]\s*\d+)*\]", "", texte)
    texte = re.sub(r"[*_#`>]+", "", texte)
    texte = re.sub(r"^\s*[-•]\s+", "", texte, flags=re.MULTILINE)
    for motif, remplacement in REMPLACEMENTS:
        texte = motif.sub(remplacement, texte)
    texte = re.sub(r"\b(" + "|".join(sorted(SIGLES, key=len, reverse=True)) + r")\b", lambda m: SIGLES[m.group(1)], texte)
    texte = re.sub(r"(\d) (\d{3})\b", r"\1\2", texte)  # « 2 450 » se lit comme un seul nombre
    return " ".join(texte.split())


def synthetiser(texte: str) -> bytes:
    voix = _modele_voix()
    flux = io.BytesIO()
    with wave.open(flux, "wb") as fichier:
        voix.synthesize_wav(texte_pour_voix(texte), fichier)
    return flux.getvalue()
