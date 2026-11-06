# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installation de Pagilis sur le PC à partir de l'exe portable.

L'exe fonctionne sans installation (clé USB, dossier Téléchargements). Une fois
lancé, il peut s'installer pour l'utilisateur courant, SANS droits
administrateur, comme le font la plupart des applications récentes :

- copie de l'exe dans %LOCALAPPDATA%\\Programs\\Pagilis ;
- raccourcis dans le menu Démarrer et, au choix, sur le Bureau ;
- inscription dans « Applications installées » de Windows (désinstallation) ;
- au choix, Pagilis proposé dans « Ouvrir avec » pour les PDF (sans
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

import identite
from updater import ATTENTE_PROCESSUS

CLE_DESINSTALLATIONS = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
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
    """Où et sous quel nom installer. Les valeurs par défaut sont les vrais
    emplacements Windows de Pagilis ; `ancienne_installation()` décrit ceux de
    PDF Studio (le nom d'avant), pour la migration."""

    dossier: Path = field(default_factory=lambda: Path(os.environ["LOCALAPPDATA"]) / "Programs" / identite.NOM)
    menu_demarrer: Path = field(default_factory=lambda: _dossier_shell(
        "Programs", Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs"))
    bureau: Path = field(default_factory=lambda: _dossier_shell("Desktop", Path.home() / "Desktop"))
    cle_desinstallation: str = rf"{CLE_DESINSTALLATIONS}\{identite.CLE_REGISTRE}"
    cle_classes: str = CLE_CLASSES
    nom: str = identite.NOM
    nom_exe: str = identite.NOM_EXE
    progid: str = identite.PROGID_PDF

    @property
    def exe(self) -> Path:
        return self.dossier / self.nom_exe

    @property
    def raccourcis(self) -> list[Path]:
        return [self.menu_demarrer / f"{self.nom}.lnk", self.bureau / f"{self.nom}.lnk"]


def ancienne_installation(**autres) -> Emplacements:
    """Emplacements d'une installation de PDF Studio (avant le renommage en Pagilis)."""
    valeurs = dict(
        dossier=Path(os.environ["LOCALAPPDATA"]) / "Programs" / identite.ANCIEN_NOM,
        cle_desinstallation=rf"{CLE_DESINSTALLATIONS}\{identite.ANCIENNE_CLE_REGISTRE}",
        nom=identite.ANCIEN_NOM, nom_exe=identite.ANCIEN_NOM_EXE, progid=identite.ANCIEN_PROGID_PDF,
    )
    valeurs.update(autres)
    return Emplacements(**valeurs)


def exe_courant() -> Path | None:
    """Chemin de l'exe en cours, ou None quand on tourne depuis les sources Python."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def est_installe(emplacements: Emplacements | None = None) -> bool:
    """Vrai si Pagilis est installé (l'exe est à sa place)."""
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

    _creer_raccourci(e.raccourcis[0], e.exe, e.nom)
    if raccourci_bureau:
        _creer_raccourci(e.raccourcis[1], e.exe, e.nom)
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


def _creer_raccourci(lien: Path, cible: Path, nom: str = identite.NOM) -> None:
    """Crée un raccourci .lnk via l'objet COM WScript.Shell (aucune dépendance)."""
    lien.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PDFS_LIEN); "
        "$s.TargetPath = $env:PDFS_CIBLE; $s.WorkingDirectory = $env:PDFS_DOSSIER; "
        "$s.IconLocation = $env:PDFS_CIBLE + ',0'; $s.Description = $env:PDFS_NOM; $s.Save()"
    )
    # Chemins passés par variables d'environnement : aucun souci de guillemets ni d'accents.
    env = dict(os.environ, PDFS_LIEN=str(lien), PDFS_CIBLE=str(cible), PDFS_DOSSIER=str(cible.parent), PDFS_NOM=nom)
    resultat = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              env=env, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if resultat.returncode:
        message = resultat.stderr.decode("oem", "replace").strip()
        raise OSError(f"Impossible de créer le raccourci « {lien} » : {message}")


def _inscrire_desinstallation(e: Emplacements, version: str) -> None:
    taille_ko = e.exe.stat().st_size // 1024
    valeurs = {
        "DisplayName": e.nom,
        "DisplayVersion": version,
        "Publisher": identite.EDITEUR,
        "DisplayIcon": f"{e.exe},0",
        "InstallLocation": str(e.dossier),
        "UninstallString": f'"{e.exe}" --desinstaller',
        "URLInfoAbout": f"https://github.com/{identite.DEPOT_GITHUB}",
    }
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, e.cle_desinstallation) as cle:
        for nom, valeur in valeurs.items():
            winreg.SetValueEx(cle, nom, 0, winreg.REG_SZ, valeur)
        winreg.SetValueEx(cle, "EstimatedSize", 0, winreg.REG_DWORD, taille_ko)
        winreg.SetValueEx(cle, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(cle, "NoRepair", 0, winreg.REG_DWORD, 1)


def _inscrire_ouvrir_avec(e: Emplacements) -> None:
    """Ajoute Pagilis à « Ouvrir avec » pour les .pdf, sans devenir l'application par défaut."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\{e.progid}") as cle:
        winreg.SetValueEx(cle, "", 0, winreg.REG_SZ, f"Document PDF ({e.nom})")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\{e.progid}\DefaultIcon") as cle:
        winreg.SetValueEx(cle, "", 0, winreg.REG_SZ, f"{e.exe},0")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\{e.progid}\shell\open\command") as cle:
        winreg.SetValueEx(cle, "", 0, winreg.REG_SZ, f'"{e.exe}" "%1"')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\.pdf\OpenWithProgids") as cle:
        winreg.SetValueEx(cle, e.progid, 0, winreg.REG_NONE, b"")
    _prevenir_explorateur()


def _retirer_ouvrir_avec(e: Emplacements) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\.pdf\OpenWithProgids",
                            0, winreg.KEY_SET_VALUE) as cle:
            winreg.DeleteValue(cle, e.progid)
    except OSError:
        pass
    _supprimer_arborescence(rf"{e.cle_classes}\{e.progid}")
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

    Les préférences et le journal (%LOCALAPPDATA%\\Pagilis) sont conservés,
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
    script = Path(tempfile.gettempdir()) / "pagilis_desinstallation.bat"
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


# ------------------------------------------------- migration depuis PDF Studio


def _ouvrir_avec_inscrit(e: Emplacements) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{e.cle_classes}\.pdf\OpenWithProgids") as cle:
            winreg.QueryValueEx(cle, e.progid)
            return True
    except OSError:
        return False


def migrer_depuis_pdf_studio(
    version: str,
    source: Path | None = None,
    ancienne: Emplacements | None = None,
    nouvelle: Emplacements | None = None,
    attendre_pid: int | None = None,
) -> Path | None:
    """Transforme une installation de PDF Studio en installation de Pagilis.

    Reprend les choix faits à l'installation (raccourci Bureau, « Ouvrir avec »),
    installe Pagilis à sa place, puis retire tout ce que PDF Studio avait laissé
    (dossier, raccourcis, entrées du registre). `source` est l'exe à installer
    (par défaut celui de l'ancienne installation, déjà mis à jour) ; si c'est
    l'exe en cours, passer `attendre_pid` pour que l'ancien dossier ne soit
    effacé qu'après sa fermeture. Retourne le nouvel exe, ou None s'il n'y
    avait aucune installation de PDF Studio.
    """
    a = ancienne or ancienne_installation()
    if not a.exe.exists():
        return None
    installe = installer(source or a.exe, version, raccourci_bureau=a.raccourcis[1].exists(),
                         ouvrir_avec=_ouvrir_avec_inscrit(a), emplacements=nouvelle)
    desinstaller(a, attendre_pid=attendre_pid)
    return installe


def reprendre_preferences(ancien_dossier: Path, nouveau_dossier: Path) -> bool:
    """Copie les préférences de PDF Studio vers Pagilis, une seule fois.

    Ne touche à rien si Pagilis a déjà ses propres préférences.
    """
    ancien, nouveau = Path(ancien_dossier) / "config.json", Path(nouveau_dossier) / "config.json"
    if nouveau.exists() or not ancien.exists():
        return False
    nouveau.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ancien, nouveau)
    return True
