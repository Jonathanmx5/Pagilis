# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de la préparation des publications (notes de version, version.json)."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import publication  # noqa: E402
import updater  # noqa: E402

CHANGELOG = """# Nouveautés

## [1.2.0]

- Nouveauté A
- Nouveauté B

## [1.1.0]

- Ancienne
"""


def test_notes_for_exact_version():
    assert publication.notes_de_version(CHANGELOG, "1.2.0") == "- Nouveauté A\n- Nouveauté B"
    assert publication.notes_de_version(CHANGELOG, "1.1.0") == "- Ancienne"


def test_beta_reuses_notes_of_its_version():
    assert publication.notes_de_version(CHANGELOG, "1.2.0-beta.3") == "- Nouveauté A\n- Nouveauté B"


def test_missing_section_refuses_to_publish():
    with pytest.raises(ValueError, match=r"\[1.3.0\]"):
        publication.notes_de_version(CHANGELOG, "1.3.0")


def test_real_changelog_has_notes_for_current_version():
    """Garde-fou : la version du code a bien ses notes dans CHANGELOG.md."""
    changelog = (Path(__file__).parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    for version in ("1.0.0", "1.0.1", "1.0.2", "1.1.0"):
        assert publication.notes_de_version(changelog, version)


def test_main_writes_manifest_read_by_the_updater(tmp_path, monkeypatch):
    exe = tmp_path / "PDFStudio.exe"
    exe.write_bytes(b"MZ exe")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert publication.main(["1.2.0-beta.1", "moi/PDFStudio", str(exe), str(tmp_path / "dist")]) == 0
    contenu = json.loads((tmp_path / "dist" / "version.json").read_text(encoding="utf-8"))
    assert contenu["prerelease"] is True
    assert contenu["url"].endswith("/v1.2.0-beta.1/PDFStudio.exe")
    # Le fichier produit est bien compris par l'application installée.
    maj = updater.check_for_update("x", "1.1.0", lambda _url: contenu)
    assert maj.version == "1.2.0-beta.1" and "Nouveauté A" in maj.notes
    assert (tmp_path / "dist" / "notes.md").read_text(encoding="utf-8").startswith("- Nouveauté A")
