# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de l'auto-vérification (« Pagilis.exe --verifier »)."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pdf_core as core  # noqa: E402
import verification  # noqa: E402


def test_all_checks_pass_from_sources():
    sans_ocr = core.find_tessdata() is None
    assert verification.verifier(ignorer_ocr=sans_ocr) == []


def test_failure_is_reported_and_other_checks_still_run(monkeypatch):
    lances = []

    def casse():
        lances.append("casse")
        raise RuntimeError("DLL manquante")

    def ok():
        lances.append("ok")

    monkeypatch.setattr(verification, "CONTROLES", [("Contrôle cassé", casse), ("Contrôle sain", ok)])
    assert verification.verifier() == ["Contrôle cassé"]
    assert lances == ["casse", "ok"], "un échec ne doit pas empêcher les contrôles suivants"
