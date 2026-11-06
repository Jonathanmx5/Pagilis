# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de l'installation sur le PC, dans des dossiers et clés de registre temporaires."""

import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if sys.platform != "win32":
    pytest.skip("installation propre à Windows", allow_module_level=True)

import winreg  # noqa: E402

import installation as inst  # noqa: E402


@pytest.fixture
def emplacements(tmp_path):
    """Installation complète dans tmp_path, registre sous une clé de test jetable."""
    racine = rf"Software\PDFStudioTests\{uuid.uuid4().hex}"
    e = inst.Emplacements(
        dossier=tmp_path / "Programs" / "PDF Studio",
        menu_demarrer=tmp_path / "Menu",
        bureau=tmp_path / "Bureau",
        cle_desinstallation=rf"{racine}\Uninstall\PDFStudio",
        cle_classes=rf"{racine}\Classes",
    )
    yield e
    inst._supprimer_arborescence(racine)
    try:  # la clé parente commune, une fois vide
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\PDFStudioTests")
    except OSError:
        pass  # pas vide (autre test en cours) ou déjà supprimée


@pytest.fixture
def exe_portable(tmp_path):
    # Un VRAI exécutable : Windows refuse de créer un raccourci vers un faux exe.
    import shutil
    chemin = tmp_path / "Téléchargements" / "PDFStudio.exe"  # accents : comme un vrai profil
    chemin.parent.mkdir()
    shutil.copy2(sys.executable, chemin)
    return chemin


def lire(chemin, nom=""):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin) as cle:
        return winreg.QueryValueEx(cle, nom)[0]


def cle_existe(chemin):
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin).Close()
        return True
    except FileNotFoundError:
        return False


def test_install_copies_exe_creates_shortcuts_and_registers(emplacements, exe_portable):
    assert not inst.est_installe(emplacements)
    installe = inst.installer(exe_portable, "1.2.3", emplacements=emplacements)

    assert installe == emplacements.exe and installe.read_bytes() == exe_portable.read_bytes()
    assert inst.est_installe(emplacements)
    assert all(lien.exists() for lien in emplacements.raccourcis)
    # Inscription dans « Applications installées ».
    cle = emplacements.cle_desinstallation
    assert lire(cle, "DisplayName") == "PDF Studio"
    assert lire(cle, "DisplayVersion") == "1.2.3"
    assert lire(cle, "UninstallString") == f'"{emplacements.exe}" --desinstaller'
    # « Ouvrir avec » pour les PDF.
    assert lire(rf"{emplacements.cle_classes}\{inst.PROGID}\shell\open\command") == f'"{emplacements.exe}" "%1"'
    assert lire(rf"{emplacements.cle_classes}\.pdf\OpenWithProgids", inst.PROGID) is None


def test_shortcut_points_to_installed_exe(emplacements, exe_portable):
    import subprocess
    inst.installer(exe_portable, "1.0.0", emplacements=emplacements)
    lien = emplacements.raccourcis[0]
    cible = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lien}').TargetPath"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert os.path.normcase(cible) == os.path.normcase(str(emplacements.exe))


def test_options_off_and_reinstall(emplacements, exe_portable):
    inst.installer(exe_portable, "1.0.0", emplacements=emplacements)
    # Réinstallation sans raccourci Bureau ni « Ouvrir avec » : on les retire.
    inst.installer(exe_portable, "1.0.1", raccourci_bureau=False, ouvrir_avec=False, emplacements=emplacements)
    assert emplacements.raccourcis[0].exists() and not emplacements.raccourcis[1].exists()
    assert not cle_existe(rf"{emplacements.cle_classes}\{inst.PROGID}")
    assert lire(emplacements.cle_desinstallation, "DisplayVersion") == "1.0.1"


def test_version_refreshed_after_update(emplacements, exe_portable):
    inst.installer(exe_portable, "1.0.0", emplacements=emplacements)
    inst.mettre_a_jour_version("1.0.5", emplacements)
    assert lire(emplacements.cle_desinstallation, "DisplayVersion") == "1.0.5"


def test_uninstall_removes_everything(emplacements, exe_portable):
    inst.installer(exe_portable, "1.0.0", emplacements=emplacements)
    inst.desinstaller(emplacements)
    assert not emplacements.dossier.exists()
    assert not any(lien.exists() for lien in emplacements.raccourcis)
    assert not cle_existe(emplacements.cle_desinstallation)
    assert not cle_existe(rf"{emplacements.cle_classes}\{inst.PROGID}")
    assert exe_portable.exists()  # la version portable n'est pas touchée


def test_uninstall_from_running_exe_waits_for_process(emplacements, exe_portable):
    """Désinstallation lancée par l'exe installé : le dossier part après la fin du processus."""
    import subprocess
    inst.installer(exe_portable, "1.0.0", emplacements=emplacements)
    processus = subprocess.Popen(["cmd", "/c", "ping -n 4 127.0.0.1 >nul"], creationflags=subprocess.CREATE_NO_WINDOW)
    inst.desinstaller(emplacements, attendre_pid=processus.pid)
    time.sleep(1)
    assert emplacements.dossier.exists(), "supprimé avant la fin du processus"
    processus.wait()
    for _ in range(20):
        if not emplacements.dossier.exists():
            break
        time.sleep(0.5)
    assert not emplacements.dossier.exists()


def test_running_portable_is_not_the_installed_copy(emplacements, monkeypatch, exe_portable):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_portable))
    inst.installer(exe_portable, "1.0.0", emplacements=emplacements)
    assert not inst.tourne_depuis_installation(emplacements)
    monkeypatch.setattr(sys, "executable", str(emplacements.exe))
    assert inst.tourne_depuis_installation(emplacements)
