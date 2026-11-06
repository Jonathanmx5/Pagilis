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
    racine = rf"Software\PagilisTests\{uuid.uuid4().hex}"
    e = inst.Emplacements(
        dossier=tmp_path / "Programs" / "Pagilis",
        menu_demarrer=tmp_path / "Menu",
        bureau=tmp_path / "Bureau",
        cle_desinstallation=rf"{racine}\Uninstall\Pagilis",
        cle_classes=rf"{racine}\Classes",
    )
    yield e
    inst._supprimer_arborescence(racine)
    try:  # la clé parente commune, une fois vide
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\PagilisTests")
    except OSError:
        pass  # pas vide (autre test en cours) ou déjà supprimée


@pytest.fixture
def exe_portable(tmp_path):
    # Un VRAI exécutable : Windows refuse de créer un raccourci vers un faux exe.
    import shutil
    chemin = tmp_path / "Téléchargements" / "Pagilis.exe"  # accents : comme un vrai profil
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
    assert lire(cle, "DisplayName") == "Pagilis PDF"
    assert lire(cle, "DisplayVersion") == "1.2.3"
    assert lire(cle, "UninstallString") == f'"{emplacements.exe}" --desinstaller'
    # « Ouvrir avec » pour les PDF.
    assert lire(rf"{emplacements.cle_classes}\{emplacements.progid}\shell\open\command") == f'"{emplacements.exe}" "%1"'
    assert lire(rf"{emplacements.cle_classes}\.pdf\OpenWithProgids", emplacements.progid) is None


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
    assert not cle_existe(rf"{emplacements.cle_classes}\{emplacements.progid}")
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
    assert not cle_existe(rf"{emplacements.cle_classes}\{emplacements.progid}")
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


# ------------------------------------------------- migration depuis PDF Studio


@pytest.fixture
def ancienne(emplacements):
    """Installation de PDF Studio (nom d'avant), à côté de celle de Pagilis et dans la même zone de test."""
    racine = emplacements.cle_desinstallation.rsplit("\\", 2)[0]
    return inst.ancienne_installation(
        dossier=emplacements.dossier.parent / "PDF Studio",
        menu_demarrer=emplacements.menu_demarrer,
        bureau=emplacements.bureau,
        cle_desinstallation=rf"{racine}\Uninstall\PDFStudio",
        cle_classes=emplacements.cle_classes,
    )


def test_legacy_layout_uses_old_names(ancienne):
    assert ancienne.exe.name == "PDFStudio.exe"
    assert [l.name for l in ancienne.raccourcis] == ["PDF Studio.lnk", "PDF Studio.lnk"]
    assert ancienne.progid == "PDFStudio.pdf"


@pytest.mark.parametrize("bureau, ouvrir_avec", [(True, True), (False, False)])
def test_pdf_studio_install_becomes_pagilis(emplacements, ancienne, exe_portable, bureau, ouvrir_avec):
    inst.installer(exe_portable, "1.1.0", raccourci_bureau=bureau, ouvrir_avec=ouvrir_avec, emplacements=ancienne)
    assert ancienne.exe.exists()

    nouveau = inst.migrer_depuis_pdf_studio("1.2.0", ancienne=ancienne, nouvelle=emplacements)

    # Pagilis est installé, avec les MÊMES choix que PDF Studio.
    assert nouveau == emplacements.exe and nouveau.exists()
    assert emplacements.raccourcis[0].exists()
    assert emplacements.raccourcis[1].exists() is bureau
    assert lire(emplacements.cle_desinstallation, "DisplayName") == "Pagilis PDF"
    assert lire(emplacements.cle_desinstallation, "DisplayVersion") == "1.2.0"
    assert cle_existe(rf"{emplacements.cle_classes}\Pagilis.pdf") is ouvrir_avec
    # Plus aucune trace de PDF Studio.
    assert not ancienne.dossier.exists()
    assert not any(lien.exists() for lien in ancienne.raccourcis)
    assert not cle_existe(ancienne.cle_desinstallation)
    assert not cle_existe(rf"{ancienne.cle_classes}\PDFStudio.pdf")
    assert not inst._ouvrir_avec_inscrit(ancienne)


def test_no_pdf_studio_install_nothing_to_migrate(emplacements, ancienne):
    assert inst.migrer_depuis_pdf_studio("1.2.0", ancienne=ancienne, nouvelle=emplacements) is None
    assert not emplacements.exe.exists()


def test_preferences_carried_over_once(tmp_path):
    ancien, nouveau = tmp_path / "PDFStudio", tmp_path / "Pagilis"
    ancien.mkdir()
    (ancien / "config.json").write_text('{"apparence": "dark"}', encoding="utf-8")
    assert inst.reprendre_preferences(ancien, nouveau) is True
    assert (nouveau / "config.json").read_text(encoding="utf-8") == '{"apparence": "dark"}'
    # Pagilis a désormais ses propres préférences : on n'y touche plus.
    (nouveau / "config.json").write_text('{"apparence": "light"}', encoding="utf-8")
    assert inst.reprendre_preferences(ancien, nouveau) is False
    assert "light" in (nouveau / "config.json").read_text(encoding="utf-8")


def test_nothing_to_carry_over(tmp_path):
    assert inst.reprendre_preferences(tmp_path / "absent", tmp_path / "Pagilis") is False


def test_startup_migrates_updated_pdf_studio_and_relaunches(monkeypatch, tmp_path):
    """Au démarrage, un PDF Studio installé et tout juste mis à jour devient Pagilis et passe la main."""
    import pagilis
    appels, lances = {}, []
    monkeypatch.setattr(inst, "tourne_depuis_installation", lambda e=None: e is not None and e.nom == "PDF Studio")
    monkeypatch.setattr(inst, "exe_courant", lambda: tmp_path / "PDFStudio.exe")

    def migrer(version, source=None, attendre_pid=None, **k):
        appels.update(version=version, source=source, attendre_pid=attendre_pid)
        return tmp_path / "Pagilis" / "Pagilis.exe"

    monkeypatch.setattr(inst, "migrer_depuis_pdf_studio", migrer)
    monkeypatch.setattr(pagilis.subprocess, "Popen", lambda args, **k: lances.append(args))
    assert pagilis.migrer_installation_pdf_studio(["contrat.pdf"]) is True
    assert appels["attendre_pid"] == os.getpid(), "l'ancien dossier ne doit partir qu'après notre fermeture"
    assert appels["source"] == tmp_path / "PDFStudio.exe"
    assert lances == [[str(tmp_path / "Pagilis" / "Pagilis.exe"), "--renomme", "contrat.pdf"]]


def test_startup_does_nothing_outside_pdf_studio_install(monkeypatch):
    import pagilis
    monkeypatch.setattr(inst, "tourne_depuis_installation", lambda e=None: False)
    assert pagilis.migrer_installation_pdf_studio([]) is False


def test_failed_migration_does_not_block_the_app(monkeypatch):
    import pagilis
    monkeypatch.setattr(inst, "tourne_depuis_installation", lambda e=None: e is not None)
    monkeypatch.setattr(inst, "exe_courant", lambda: None)

    def echec(*a, **k):
        raise PermissionError("fichier verrouillé")

    monkeypatch.setattr(inst, "migrer_depuis_pdf_studio", echec)
    assert pagilis.migrer_installation_pdf_studio([]) is False


# ------------------------------------------------- nom affiché « Pagilis PDF »


def test_install_uses_display_name(emplacements, exe_portable):
    inst.installer(exe_portable, "1.7.1", emplacements=emplacements)
    assert (emplacements.menu_demarrer / "Pagilis PDF.lnk").exists()
    assert (emplacements.bureau / "Pagilis PDF.lnk").exists()
    assert lire(emplacements.cle_desinstallation, "DisplayName") == "Pagilis PDF"
    assert emplacements.exe.name == "Pagilis.exe"  # le fichier garde son nom


def installation_sous_ancien_nom(emplacements, exe_portable, bureau=True):
    """Installation faite par une version d'avant « Pagilis PDF » (raccourcis « Pagilis »)."""
    ancienne = inst.Emplacements(**{**emplacements.__dict__, "nom": "Pagilis"})
    inst.installer(exe_portable, "1.7.0", raccourci_bureau=bureau, emplacements=ancienne)
    return ancienne


@pytest.mark.parametrize("bureau", [True, False])
def test_update_renames_shortcuts_and_windows_entry(emplacements, exe_portable, bureau):
    installation_sous_ancien_nom(emplacements, exe_portable, bureau)
    inst.mettre_a_jour_version("1.7.1", emplacements)
    assert not (emplacements.menu_demarrer / "Pagilis.lnk").exists()
    assert (emplacements.menu_demarrer / "Pagilis PDF.lnk").exists()
    assert not (emplacements.bureau / "Pagilis.lnk").exists()
    assert (emplacements.bureau / "Pagilis PDF.lnk").exists() is bureau  # le choix est gardé
    assert lire(emplacements.cle_desinstallation, "DisplayName") == "Pagilis PDF"
    assert lire(emplacements.cle_desinstallation, "DisplayVersion") == "1.7.1"
    assert lire(rf"{emplacements.cle_classes}\{emplacements.progid}") == "Document PDF (Pagilis PDF)"


def test_uninstall_also_removes_old_named_shortcuts(emplacements, exe_portable):
    installation_sous_ancien_nom(emplacements, exe_portable)
    inst.desinstaller(emplacements)
    assert not (emplacements.menu_demarrer / "Pagilis.lnk").exists()
    assert not (emplacements.bureau / "Pagilis.lnk").exists()
