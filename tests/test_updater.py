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
