# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de la vérification de mise à jour (sans réseau réel)."""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import updater  # noqa: E402


def fake_fetch(manifeste):
    return lambda _url: manifeste


@pytest.mark.parametrize(
    "remote, local, attendu",
    [("1.2.0", "1.1.9", True), ("1.10.0", "1.9.0", True), ("1.0.0", "1.0.0", False), ("0.9.0", "1.0.0", False)],
)
def test_is_newer_compares_numerically(remote, local, attendu):
    assert updater.is_newer(remote, local) is attendu


@pytest.mark.parametrize("plus_recente, plus_ancienne", [
    ("1.1.0", "1.1.0-beta.2"),        # la version finale passe après ses bêtas
    ("1.1.0-beta.2", "1.1.0-beta.1"),
    ("1.1.0-beta.1", "1.0.9"),
    ("1.0.10", "1.0.9"),
])
def test_version_ordering_with_betas(plus_recente, plus_ancienne):
    assert updater.is_newer(plus_recente, plus_ancienne)
    assert not updater.is_newer(plus_ancienne, plus_recente)


def test_notes_rewrapped_for_display():
    notes = ("- Plus sûr : une nouvelle version est d'abord vérifiée ; si elle\n"
             "  ne fonctionne pas, la version actuelle est conservée.\n"
             "- Exe plus léger.\n"
             "\n"
             "- Après une ligne vide.")
    assert updater.notes_lisibles(notes) == (
        "- Plus sûr : une nouvelle version est d'abord vérifiée ; si elle ne fonctionne pas, "
        "la version actuelle est conservée.\n- Exe plus léger.\n\n- Après une ligne vide.")


def test_notes_are_passed_to_update():
    manifeste = {"version": "2.0.0", "url": "u", "sha256": "s", "notes": "  - Nouveauté\n"}
    maj = updater.check_for_update("https://x/v.json", "1.0.0", fake_fetch(manifeste))
    assert maj.notes == "- Nouveauté"


def test_beta_channel_picks_highest_version_ignoring_drafts(monkeypatch):
    def release(tag, draft=False, avec_manifeste=True):
        assets = [{"name": "version.json", "browser_download_url": f"https://x/{tag}/version.json"}]
        return {"tag_name": tag, "draft": draft, "assets": assets if avec_manifeste else []}

    releases = [release("v1.0.2"), release("v1.2.0-beta.1"), release("v1.3.0", draft=True),
                release("v1.1.0"), release("v9.0.0", avec_manifeste=False), release("pas-une-version")]
    lus = []

    def lire(url):
        lus.append(url)
        return releases if "api" in url else {"version": url.split("/")[3].lstrip("v"), "url": "u"}

    monkeypatch.setattr(updater, "_lire_json", lire)
    assert updater.fetch_beta_manifest("https://api/releases")["version"] == "1.2.0-beta.1"
    assert lus[-1] == "https://x/v1.2.0-beta.1/version.json"


def test_stable_channel_never_uses_releases_api(monkeypatch):
    urls = []
    monkeypatch.setattr(updater, "_lire_json", lambda url: urls.append(url) or {"version": "0.0.1", "url": "u"})
    updater.check_for_update(current="1.0.0")
    updater.check_for_update(current="1.0.0", beta=True)
    assert urls == [updater.UPDATE_MANIFEST_URL, updater.RELEASES_API_URL]


def _exe_factice(dossier, nom, source):
    """Copie d'un petit exe Windows qui s'exécute et se termine aussitôt."""
    import shutil
    chemin = dossier / nom
    shutil.copy2(os.path.join(os.environ["SystemRoot"], "System32", source), chemin)
    return chemin


def _jouer_script(contenu, dossier):
    import subprocess
    import time
    script = dossier / "maj.bat"
    script.write_text(contenu, encoding="utf-8")
    subprocess.run(["cmd", "/c", str(script)], timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):  # le script s'efface lui-même en dernier
        if not script.exists():
            return
        time.sleep(0.2)


@pytest.mark.skipif(sys.platform != "win32", reason="script .bat Windows")
def test_replacement_script_swaps_and_keeps_backup(tmp_path):
    actuel = _exe_factice(tmp_path, "PDFStudio.exe", "whoami.exe")
    nouveau = _exe_factice(tmp_path, "nouveau.exe", "hostname.exe")
    octets_avant, octets_nouveau = actuel.read_bytes(), nouveau.read_bytes()
    sauvegarde = tmp_path / "sauvegarde.exe"
    _jouer_script(updater.script_remplacement(str(nouveau), str(actuel), 999999, str(sauvegarde)), tmp_path)
    assert actuel.read_bytes() == octets_nouveau, "la nouvelle version doit être en place"
    assert sauvegarde.read_bytes() == octets_avant, "l'ancienne version doit être sauvegardée"
    assert not nouveau.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="script .bat Windows")
def test_replacement_script_gives_up_and_restores(tmp_path):
    """Remplacement impossible : abandon après N essais, ancienne version intacte."""
    import time
    actuel = _exe_factice(tmp_path, "PDFStudio.exe", "whoami.exe")
    octets_avant = actuel.read_bytes()
    introuvable = tmp_path / "telechargement-disparu.exe"
    debut = time.time()
    _jouer_script(updater.script_remplacement(str(introuvable), str(actuel), 999999,
                                              str(tmp_path / "sauvegarde.exe"), essais=2), tmp_path)
    assert time.time() - debut < 30, "pas de boucle sans fin"
    assert actuel.read_bytes() == octets_avant


@pytest.mark.skipif(sys.platform != "win32", reason="exe Windows")
def test_new_version_refused_if_self_check_fails(tmp_path):
    """Un exe qui ne réussit pas « --verifier » ne doit jamais être installé."""
    pas_pdfstudio = _exe_factice(tmp_path, "PDFStudio_new.exe", "whoami.exe")
    assert updater.verifier_exe(str(pas_pdfstudio), delai=30) is False
    assert updater.verifier_exe(str(tmp_path / "absent.exe")) is False


def test_no_url_means_no_check():
    assert updater.check_for_update(manifest_url="", current="1.0.0", fetch=fake_fetch({})) is None


def test_up_to_date_returns_none():
    manifeste = {"version": "1.0.0", "url": "https://x/PDFStudio.exe"}
    assert updater.check_for_update("https://x/v.json", "1.0.0", fake_fetch(manifeste)) is None


def test_newer_version_returns_update():
    manifeste = {"version": "1.1.0", "url": "https://x/PDFStudio.exe", "sha256": "abc"}
    maj = updater.check_for_update("https://x/v.json", "1.0.0", fake_fetch(manifeste))
    assert maj == updater.Update(version="1.1.0", url="https://x/PDFStudio.exe", sha256="abc")


def test_network_error_is_silent():
    def panne(_url):
        raise OSError("pas de réseau")

    assert updater.check_for_update("https://x/v.json", "1.0.0", panne) is None


def test_malformed_manifest_is_silent():
    assert updater.check_for_update("https://x/v.json", "1.0.0", fake_fetch({"foo": 1})) is None


def test_download_checks_sha256(tmp_path, monkeypatch):
    contenu = b"nouvel exe"

    class Reponse:
        headers = {"Content-Length": str(len(contenu))}

        def __init__(self):
            self._donnees = contenu

        def read(self, _n):
            donnees, self._donnees = self._donnees, b""
            return donnees

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_a, **_k: Reponse())
    destination = str(tmp_path / "new.exe")

    bon = updater.Update("1.1.0", "u", hashlib.sha256(contenu).hexdigest())
    updater.download(bon, destination)
    assert open(destination, "rb").read() == contenu

    mauvais = updater.Update("1.1.0", "u", "0" * 64)
    with pytest.raises(ValueError):
        updater.download(mauvais, destination)
    assert not os.path.exists(destination)
