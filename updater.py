# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vérification et installation des mises à jour de Pagilis.

Aucune interface ici : le module est testable sans écran.

Chaque release GitHub contient un petit fichier JSON, par exemple :
    {"version": "1.2.0", "url": "https://.../Pagilis.exe", "sha256": "...",
     "notes": "- Nouveauté…"}

Deux canaux :
- stable (défaut) : la dernière release publiée, jamais une bêta ;
- bêta (choix de l'utilisateur) : la release la plus récente, bêta comprise
  (tags du type v1.2.0-beta.1).

Si la vérification échoue (pas de réseau, fichier absent), on ne fait rien :
l'application démarre normalement. Une version téléchargée doit réussir son
auto-vérification (--verifier) avant de remplacer la version en place.
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

import identite

# Version EN COURS DE DÉVELOPPEMENT (doit avoir sa section dans CHANGELOG.md).
# À la publication, la CI la remplace par celle du tag git (v1.2.3 -> "1.2.3").
APP_VERSION = "1.4.0"

# Dépôt GitHub qui héberge les versions publiées (voir .github/workflows/release.yml).
GITHUB_REPO = identite.DEPOT_GITHUB

# Fichier de version joint à la DERNIÈRE release GitHub (GitHub n'y range jamais
# une bêta). Vide = pas de vérification.
UPDATE_MANIFEST_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/version.json"

# Liste des releases (bêtas comprises), pour le canal bêta.
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=20"

# Sauvegarde de la version remplacée par la dernière mise à jour.
DOSSIER_SAUVEGARDE = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
                                  identite.DOSSIER_DONNEES, "version-precedente")

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
    notes: str = ""  # nouveautés, affichées dans la fenêtre de mise à jour


def parse_version(texte: str) -> tuple[int, ...]:
    """Clé de comparaison d'une version.

    « 1.10.0 » -> (1, 10, 0, 1, 0) ; « 1.2.0-beta.3 » -> (1, 2, 0, 0, 3).
    Une pré-version (bêta) passe AVANT la version finale du même numéro.
    Lève ValueError si le format est mauvais.
    """
    base, _, pre = texte.strip().lstrip("vV").partition("-")
    nombres = tuple(int(m) for m in base.split("."))
    if not pre:
        return nombres + (1, 0)
    numero = pre.rsplit(".", 1)[-1]
    return nombres + (0, int(numero) if numero.isdigit() else 0)


def is_newer(remote: str, local: str) -> bool:
    """Vrai si la version distante est strictement plus récente."""
    return parse_version(remote) > parse_version(local)


def notes_lisibles(notes: str) -> str:
    """Notes du CHANGELOG -> texte pour la fenêtre de mise à jour.

    Dans le fichier, une puce longue continue sur des lignes indentées (coupure
    à 80 caractères pour la lecture du fichier). Affichées telles quelles, ces
    coupures hachent les phrases : on recolle chaque suite à sa puce, et
    l'affichage fait lui-même le retour à la ligne.
    """
    lignes: list[str] = []
    for ligne in notes.splitlines():
        if ligne[:1].isspace() and ligne.strip() and lignes:
            lignes[-1] += " " + ligne.strip()
        else:
            lignes.append(ligne.rstrip())
    return "\n".join(lignes).strip()


def _lire_json(url: str):
    requete = urllib.request.Request(url, headers={
        "User-Agent": "Pagilis-mise-a-jour",  # exigé par l'API GitHub
        "Accept": "application/json",
    })
    with urllib.request.urlopen(requete, timeout=TIMEOUT_SECONDES) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def fetch_manifest(url: str) -> dict:
    """Télécharge le fichier de version. Lève une exception en cas d'échec."""
    return _lire_json(url)


def fetch_beta_manifest(url: str) -> dict:
    """Canal bêta : version.json de la release la plus récente, bêta comprise.

    `url` est celle de la liste des releases (API GitHub). Les brouillons sont
    ignorés, et on compare les numéros de version plutôt que les dates.
    """
    candidates = []
    for release in _lire_json(url):
        fichier = next((a for a in release.get("assets", []) if a.get("name") == "version.json"), None)
        if release.get("draft") or fichier is None:
            continue
        try:
            candidates.append((parse_version(release["tag_name"]), fichier["browser_download_url"]))
        except (KeyError, ValueError):
            continue
    if not candidates:
        raise ValueError("aucune release avec version.json")
    return _lire_json(max(candidates)[1])


def check_for_update(
    manifest_url: Optional[str] = None,
    current: Optional[str] = None,
    fetch: Optional[Callable[[str], dict]] = None,
    beta: bool = False,
) -> Optional[Update]:
    """Retourne la mise à jour disponible, ou None.

    Ne lève jamais d'exception : toute erreur est journalisée et donne None,
    pour que l'application démarre quand même.
    """
    # Lus à l'APPEL, pas à la définition : sinon modifier UPDATE_MANIFEST_URL
    # (tests, configuration) resterait sans effet.
    if manifest_url is None:
        manifest_url = (RELEASES_API_URL if UPDATE_MANIFEST_URL else "") if beta else UPDATE_MANIFEST_URL
    if fetch is None:
        fetch = fetch_beta_manifest if beta else fetch_manifest
    current = APP_VERSION if current is None else current
    if not manifest_url:
        return None
    try:
        manifeste = fetch(manifest_url)
        version = str(manifeste["version"])
        if not is_newer(version, current):
            return None
        return Update(version=version, url=str(manifeste["url"]), sha256=manifeste.get("sha256"),
                      notes=str(manifeste.get("notes", "")).strip())
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


def verifier_exe(chemin: str, delai: int = 90) -> bool:
    """Lance `chemin --verifier` et dit si la nouvelle version fonctionne.

    Faux si l'exe échoue, plante ou ne répond pas dans le délai (un exe abîmé
    peut afficher une boîte d'erreur et attendre indéfiniment ; il est alors
    arrêté) : il ne doit surtout pas remplacer la version en place. Une
    vérification normale prend quelques secondes.
    """
    chemin = os.path.abspath(chemin)  # un chemin relatif avec « / » n'est pas trouvé au lancement
    try:
        resultat = subprocess.run([chemin, "--verifier"], env=environnement_lancement(),
                                  timeout=delai, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        logging.exception("Auto-vérification de %s impossible", chemin)
        return False
    logging.info("Auto-vérification de %s : code %s", chemin, resultat.returncode)
    return resultat.returncode == 0


def script_remplacement(new_exe: str, actuel: str, pid: int, sauvegarde: str, essais: int = 30) -> str:
    """Script .bat qui remplace `actuel` par `new_exe` une fois le processus `pid` fermé.

    - la version en place est d'abord copiée dans `sauvegarde` ;
    - le remplacement est retenté `essais` fois (antivirus qui verrouille le fichier…),
      puis on abandonne en RESTAURANT la sauvegarde : jamais de boucle sans fin,
      jamais d'exe à moitié remplacé ;
    - l'application (nouvelle, ou ancienne en cas d'échec) est relancée.
    """
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"  # le fichier est en UTF-8 : chemins accentués compris
        f"set PID={pid}\r\n"
        ":attente\r\n"
        + ATTENTE_PROCESSUS +
        f'copy /Y "{actuel}" "{sauvegarde}" >nul 2>&1\r\n'
        "set ESSAIS=0\r\n"
        ":remplacer\r\n"
        f'move /Y "{new_exe}" "{actuel}" >nul 2>&1 && goto relancer\r\n'
        "set /a ESSAIS+=1\r\n"
        f"if %ESSAIS% GEQ {essais} goto restaurer\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto remplacer\r\n"
        ":restaurer\r\n"
        f'copy /Y "{sauvegarde}" "{actuel}" >nul 2>&1\r\n'
        ":relancer\r\n"
        f'start "" "{actuel}"\r\n'
        'del "%~f0"\r\n'
    )


def install_and_restart(new_exe: str) -> None:
    """Remplace l'exe en cours par new_exe puis relance l'application.

    Un fichier .exe en cours d'exécution ne peut pas être écrasé directement :
    un script .bat attend la fin du processus, remplace le fichier, relance
    l'application puis s'efface. Ne fait rien hors exécutable compilé.
    """
    if not getattr(sys, "frozen", False):
        logging.info("Mode développement : installation de la mise à jour ignorée.")
        return
    os.makedirs(DOSSIER_SAUVEGARDE, exist_ok=True)
    script = os.path.join(tempfile.gettempdir(), "pagilis_update.bat")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(script_remplacement(new_exe, sys.executable, os.getpid(),
                                     os.path.join(DOSSIER_SAUVEGARDE, "Pagilis.exe")))
    subprocess.Popen(["cmd", "/c", script], env=environnement_lancement(),
                     creationflags=subprocess.CREATE_NO_WINDOW)


def environnement_lancement() -> dict:
    """Environnement pour lancer un AUTRE exe Pagilis depuis celui-ci.

    Sans PYINSTALLER_RESET_ENVIRONMENT, le nouvel exe hériterait des variables
    internes de PyInstaller et pourrait réutiliser notre dossier temporaire,
    effacé dès notre fermeture.
    """
    return dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
