# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vérification et installation des mises à jour de PDF Studio.

Aucune interface ici : le module est testable sans écran.

Le serveur publie un petit fichier JSON, par exemple :
    {"version": "1.2.0", "url": "https://.../PDFStudio.exe", "sha256": "..."}

Si la vérification échoue (pas de réseau, fichier absent), on ne fait rien :
l'application démarre normalement.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

# Version de l'exe. À la publication, la CI la remplace par celle du tag git
# (v1.2.3 -> "1.2.3") : ne la modifiez pas à la main pour sortir une version.
APP_VERSION = "1.0.1"

# Dépôt GitHub qui héberge les versions publiées (voir .github/workflows/release.yml).
GITHUB_REPO = "Jonathanmx5/PDFStudio"

# Fichier de version joint à la DERNIÈRE release GitHub. Vide = pas de vérification.
UPDATE_MANIFEST_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/version.json"

TIMEOUT_SECONDES = 10

# Ligne de script .bat qui boucle tant que le processus %PID% tourne.
# - tasklist/find par chemin complet : un `find` Unix (Git) dans le PATH répondrait faux ;
# - ping comme pause : `timeout` échoue aussitôt dans un script lancé sans console.
ATTENTE_PROCESSUS = (
    r'"%SystemRoot%\System32\tasklist.exe" /FI "PID eq %PID%" | "%SystemRoot%\System32\find.exe" "%PID%" >nul'
    r" && (ping -n 2 127.0.0.1 >nul & goto attente)" "\r\n"
)


@dataclass
class Update:
    """Une mise à jour disponible."""

    version: str
    url: str
    sha256: Optional[str]


def parse_version(texte: str) -> tuple[int, ...]:
    """« 1.10.0 » -> (1, 10, 0). Lève ValueError si le format est mauvais."""
    morceaux = texte.strip().lstrip("vV").split(".")
    return tuple(int(m) for m in morceaux)


def is_newer(remote: str, local: str) -> bool:
    """Vrai si la version distante est strictement plus récente."""
    return parse_version(remote) > parse_version(local)


def fetch_manifest(url: str) -> dict:
    """Télécharge le fichier de version. Lève une exception en cas d'échec."""
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDES) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def check_for_update(
    manifest_url: str = UPDATE_MANIFEST_URL,
    current: str = APP_VERSION,
    fetch: Callable[[str], dict] = fetch_manifest,
) -> Optional[Update]:
    """Retourne la mise à jour disponible, ou None.

    Ne lève jamais d'exception : toute erreur est journalisée et donne None,
    pour que l'application démarre quand même.
    """
    if not manifest_url:
        return None
    try:
        manifeste = fetch(manifest_url)
        version = str(manifeste["version"])
        if not is_newer(version, current):
            return None
        return Update(version=version, url=str(manifeste["url"]), sha256=manifeste.get("sha256"))
    except Exception:  # noqa: BLE001 - la vérification ne doit jamais bloquer le démarrage
        logging.exception("Vérification de mise à jour impossible")
        return None


def download(
    update: Update,
    destination: str,
    progress: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Télécharge la nouvelle version et vérifie son empreinte SHA-256 si elle est fournie.

    Lève ValueError si l'empreinte ne correspond pas : le fichier est supprimé.
    """
    with urllib.request.urlopen(update.url, timeout=TIMEOUT_SECONDES) as reponse, open(destination, "wb") as fh:
        total = int(reponse.headers.get("Content-Length") or 0)
        lu = 0
        while True:
            bloc = reponse.read(64 * 1024)
            if not bloc:
                break
            fh.write(bloc)
            lu += len(bloc)
            if progress:
                progress(lu, total)
    if update.sha256:
        with open(destination, "rb") as fh:
            empreinte = hashlib.sha256(fh.read()).hexdigest()
        if empreinte.lower() != update.sha256.lower():
            os.remove(destination)
            raise ValueError("Empreinte SHA-256 incorrecte : téléchargement rejeté.")


def install_and_restart(new_exe: str) -> None:
    """Remplace l'exe en cours par new_exe puis relance l'application.

    Un fichier .exe en cours d'exécution ne peut pas être écrasé directement :
    un script .bat attend la fin du processus, remplace le fichier, relance
    l'application puis s'efface. Ne fait rien hors exécutable compilé.
    """
    if not getattr(sys, "frozen", False):
        logging.info("Mode développement : installation de la mise à jour ignorée.")
        return
    actuel = sys.executable
    script = os.path.join(tempfile.gettempdir(), "pdfstudio_update.bat")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"  # le fichier est en UTF-8 : chemins accentués compris
            f"set PID={os.getpid()}\r\n"
            ":attente\r\n"
            + ATTENTE_PROCESSUS +
            ":remplacer\r\n"
            f'move /Y "{new_exe}" "{actuel}" >nul 2>&1 || (ping -n 2 127.0.0.1 >nul & goto remplacer)\r\n'
            f'start "" "{actuel}"\r\n'
            'del "%~f0"\r\n'
        )
    subprocess.Popen(["cmd", "/c", script], env=environnement_lancement(),
                     creationflags=subprocess.CREATE_NO_WINDOW)


def environnement_lancement() -> dict:
    """Environnement pour lancer un AUTRE exe PDF Studio depuis celui-ci.

    Sans PYINSTALLER_RESET_ENVIRONMENT, le nouvel exe hériterait des variables
    internes de PyInstaller et pourrait réutiliser notre dossier temporaire,
    effacé dès notre fermeture.
    """
    return dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
