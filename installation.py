# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation de PDF Studio sur le PC à partir de l'exe portable.

L'exe fonctionne sans installation (clé USB, dossier Téléchargements). Une fois
lancé, il peut s'installer pour l'utilisateur courant, SANS droits
administrateur, comme le font la plupart des applications récentes :

- copie de l'exe dans %LOCALAPPDATA%\\Programs\\PDF Studio ;
- raccourcis dans le menu Démarrer et, au choix, sur le Bureau ;
- inscription dans « Applications installées » de Windows (désinstallation) ;
- au choix, PDF Studio proposé dans « Ouvrir avec » pour les PDF (sans
  remplacer le lecteur PDF par défaut).

Aucune interface ici. Les emplacements sont des paramètres : les tests
installent dans des dossiers et des clés de registre temporaires.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from updater import ATTENTE_PROCESSUS

NOM = "PDF Studio"
NOM_EXE = "PDFStudio.exe"
EDITEUR = "Jonathanmx5"
PROGID = "PDFStudio.pdf"
CLE_DESINSTALLATION = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFStudio"
CLE_CLASSES = r"Software\Classes"


def _dossier_shell(nom: str, repli: Path) -> Path:
    """Dossier spécial Windows (Bureau, Programmes du menu Démarrer…)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as cle:
            return Path(os.path.expandvars(winreg.QueryValueEx(cle, nom)[0]))
    except OSError:
        return repli


@dataclass
class Emplacements:
    """Où installer. Les valeurs par défaut sont les vrais emplacements Windows."""

    dossier: Path = field(default_factory=lambda: Path(os.environ["LOCALAPPDATA"]) / "Programs" / NOM)
    menu_demarrer: Path = field(default_factory=lambda: _dossier_shell(
        "Programs", Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs"))
    bureau: Path = field(default_factory=lambda: _dossier_shell("Desktop", Path.home() / "Desktop"))
    cle_desinstallation: str = CLE_DESINSTALLATION
    cle_classes: str = CLE_CLASSES

    @property
    def exe(self) -> Path:
        return self.dossier / NOM_EXE

    @property
    def raccourcis(self) -> list[Path]:
        return [self.menu_demarrer / f"{NOM}.lnk", self.bureau / f"{NOM}.lnk"]


def exe_courant() -> Path | None:
    """Chemin de l'exe en cours, ou None quand on tourne depuis les sources Python."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def est_installe(emplacements: Emplacements | None = None) -> bool:
    """Vrai si PDF Studio est installé (l'exe est à sa place)."""
    return (emplacements or Emplacements()).exe.exists()


def tourne_depuis_installation(emplacements: Emplacements | None = None) -> bool:
    """Vrai si l'exe en cours EST la copie installée (et non la version portable)."""
    exe = exe_courant()
    return exe is not None and exe == (emplacements or Emplacements()).exe.resolve()


# ------------------------------------------------------------ installation


def installer(
    source: Path,
    version: str,
    raccourci_bureau: bool = True,
    ouvrir_avec: bool = True,
    emplacements: Emplacements | None = None,
) -> Path:
    """Installe l'exe `source` et retourne le chemin de la copie installée.

    Lève PermissionError si la copie installée est en cours d'exécution
    (Windows interdit d'écraser un exe ouvert).
    """
    e = emplacements or Emplacements()
    e.dossier.mkdir(parents=True, exist_ok=True)
    if Path(source).resolve() != e.exe.resolve():
        # Copie dans un fichier temporaire puis remplacement : jamais d'exe à moitié copié.
        temporaire = e.exe.with_suffix(".tmp")
        shutil.copy2(source, temporaire)
        os.replace(temporaire, e.exe)

    _creer_raccourci(e.raccourcis[0], e.exe)
    if raccourci_bureau:
        _creer_raccourci(e.raccourcis[1], e.exe)
    elif e.raccourcis[1].exists():
        e.raccourcis[1].unlink()

    _inscrire_desinstallation(e, version)
    if ouvrir_avec:
        _inscrire_ouvrir_avec(e)
    else:
        _retirer_ouvrir_avec(e)
    return e.exe


def mettre_a_jour_version(version: str, emplacements: Emplacements | None = None) -> None:
    """Tient la version affichée dans « Applications installées » à jour (après une mise à jour)."""
    e = emplacements or Emplacements()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, e.cle_desinstallation, 0, winreg.KEY_ALL_ACCESS) as cle:
            if winreg.QueryValueEx(cle, "DisplayVersion")[0] != version:
                winreg.SetValueEx(cle, "DisplayVersion", 0, winreg.REG_SZ, version)
    except OSError:
        pass  # pas installé : rien à faire


def _creer_raccourci(lien: Path, cible: Path) -> None:
    """Crée un raccourci .lnk via l'objet COM WScript.Shell (aucune dépendance)."""
    lien.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PDFS_LIEN); "
        "$s.TargetPath = $env:PDFS_CIBLE; $s.WorkingDirectory = $env:PDFS_DOSSIER; "
        "$s.IconLocation = $env:PDFS_CIBLE + ',0'; $s.Description = 'PDF Studio'; $s.Save()"
    )
    # Chemins passés par variables d'environnement : aucun souci de guillemets ni d'accents.
    env = dict(os.environ, PDFS_LIEN=str(lien), PDFS_CIBLE=str(cible), PDFS_DOSSIER=str(cible.parent))
    resultat = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              env=env, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if resultat.returncode:
        message = resultat.stderr.decode("oem", "replace").strip()
        raise OSError(f"Impossible de créer le raccourci « {lien} » : {message}")


def _inscrire_desinstallation(e: Emplacements, version: str) -> None:
    taille_ko = e.exe.stat().st_size // 1024
    valeurs = {
        "DisplayName": NOM,
        "DisplayVersion": version,
        "Publisher": EDITEUR,
        "DisplayIcon": f"{e.exe},0",
        "InstallLocation": str(e.dossier),
        "UninstallString": f'"{e.exe}" --desinstaller',
        "URLInfoAbout": "https://github.com/Jonathanmx5/PDFStudio",
    }
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, e.cle_desinstallation) as cle:
        for nom, valeur in valeurs.items():
            winreg.SetValueEx(cle, nom, 0, winreg.REG_SZ, valeur)
        winreg.SetValueEx(cle, "EstimatedSize", 0, winreg.REG_DWORD, taille_ko)
        winreg.SetValueEx(cle, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(cle, "NoRepair", 0, winreg.REG_DWORD, 1)


def _inscrire_ouvrir_avec(e: Emplacements) -> None:
    """Ajoute PDF Studio à « Ouvrir avec » pour les .pdf, sans devenir l'application par défaut."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\{PROGID}") as cle:
        winreg.SetValueEx(cle, "", 0, winreg.REG_SZ, "Document PDF (PDF Studio)")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\{PROGID}\DefaultIcon") as cle:
        winreg.SetValueEx(cle, "", 0, winreg.REG_SZ, f"{e.exe},0")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\{PROGID}\shell\open\command") as cle:
        winreg.SetValueEx(cle, "", 0, winreg.REG_SZ, f'"{e.exe}" "%1"')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\.pdf\OpenWithProgids") as cle:
        winreg.SetValueEx(cle, PROGID, 0, winreg.REG_NONE, b"")
    _prevenir_explorateur()


def _retirer_ouvrir_avec(e: Emplacements) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\.pdf\OpenWithProgids",
                            0, winreg.KEY_SET_VALUE) as cle:
            winreg.DeleteValue(cle, PROGID)
    except OSError:
        pass
    _supprimer_arborescence(rf"{e.cle_classes}\{PROGID}")
    _prevenir_explorateur()


def _supprimer_arborescence(chemin: str) -> None:
    """Supprime une clé de registre HKCU et toutes ses sous-clés (ignore si absente)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin, 0, winreg.KEY_ALL_ACCESS) as cle:
            while True:
                try:
                    sous_cle = winreg.EnumKey(cle, 0)
                except OSError:
                    break
                _supprimer_arborescence(rf"{chemin}\{sous_cle}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, chemin)
    except FileNotFoundError:
        pass


def _prevenir_explorateur() -> None:
    """Signale à l'Explorateur que les associations de fichiers ont changé."""
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------- désinstallation


def desinstaller(emplacements: Emplacements | None = None, attendre_pid: int | None = None) -> None:
    """Retire raccourcis, inscriptions et dossier d'installation.

    Les préférences et le journal (%LOCALAPPDATA%\\PDFStudio) sont conservés,
    comme le font la plupart des applications. Si `attendre_pid` est donné
    (désinstallation lancée depuis l'exe installé lui-même), le dossier est
    supprimé par un script qui attend la fin de ce processus : Windows
    interdit d'effacer un exe en cours d'exécution.
    """
    e = emplacements or Emplacements()
    for lien in e.raccourcis:
        if lien.exists():
            lien.unlink()
    _retirer_ouvrir_avec(e)
    _supprimer_arborescence(e.cle_desinstallation)
    if attendre_pid is None:
        shutil.rmtree(e.dossier, ignore_errors=True)
        return
    script = Path(tempfile.gettempdir()) / "pdfstudio_desinstallation.bat"
    script.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"  # chemins en UTF-8 (nom d'utilisateur accentué)
        f"set PID={attendre_pid}\r\n"
        ":attente\r\n"
        + ATTENTE_PROCESSUS +
        f'rmdir /s /q "{e.dossier}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=subprocess.CREATE_NO_WINDOW)
