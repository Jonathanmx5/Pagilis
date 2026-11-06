# SPDX-License-Identifier: AGPL-3.0-or-later
"""Copie de travail de la page « Modifier » : retouches, annulation, enregistrement."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pymupdf as fitz  # noqa: E402

import edition  # noqa: E402
import pdf_core as core  # noqa: E402

LIGNE = "Montant total : 1 200 euros."


def creer_pdf(chemin):
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    for i, texte in enumerate(["Le client accepte le devis.", LIGNE, "Le client signe ci-dessous."]):
        page.insert_text((60, 140 + 18 * i), texte, fontname="helv", fontsize=12)
    doc.save(chemin)
    doc.close()
    return str(chemin)


def centre(doc, needle):
    r = doc[0].search_for(needle)[0]
    return fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


def texte(doc):
    return " ".join(doc[0].get_text().split())


@pytest.fixture
def ed(tmp_path):
    source = creer_pdf(tmp_path / "contrat.pdf")
    return edition.Edition(core.open_pdf(source), source)


def test_correction_marks_modified_and_can_undo(ed):
    assert not ed.modifie and not ed.peut_annuler
    assert ed.corriger(0, centre(ed.doc, "Montant"), "Montant total : 950 euros.")
    assert ed.modifie and ed.peut_annuler
    assert "950 euros" in texte(ed.doc)
    doc = ed.annuler()
    assert doc is ed.doc
    assert LIGNE in texte(ed.doc) and "950" not in texte(ed.doc)
    assert not ed.peut_annuler


def test_noop_edit_creates_no_snapshot(ed):
    assert not ed.corriger(0, fitz.Point(5, 5), "rien")
    assert ed.deplacer(0, fitz.Rect(0, 0, 20, 20), 10, 10) == 0
    assert not ed.peut_annuler and not ed.modifie


def test_move_is_undoable(ed):
    bloc = core.text_blocks(ed.doc[0])[0]
    assert ed.deplacer(0, bloc, 0, 100) > 0
    assert ed.doc[0].search_for("Montant")[0].y0 > 200
    ed.annuler()
    assert ed.doc[0].search_for("Montant")[0].y0 < 200


def test_undo_limit_is_twenty(ed):
    for i in range(25):
        assert ed.corriger(0, centre(ed.doc, "Ligne" if i else "Montant"), f"Ligne {i}")
    for _ in range(20):
        assert ed.peut_annuler
        ed.annuler()
    assert not ed.peut_annuler
    assert "Ligne 4" in texte(ed.doc)
    with pytest.raises(IndexError):
        ed.annuler()


def test_nom_propose(tmp_path):
    doc = fitz.open()
    doc.new_page()
    pdf = os.path.join(str(tmp_path), "contrat.pdf")
    word = os.path.join(str(tmp_path), "Lettre.docx")
    assert edition.Edition(doc, pdf).nom_propose() == os.path.join(str(tmp_path), "contrat_modifie.pdf")
    assert edition.Edition(doc, word, origine_word=True).nom_propose() == os.path.join(str(tmp_path), "Lettre.pdf")


def test_enregistrer_writes_and_clears_modified(ed, tmp_path):
    ed.corriger(0, centre(ed.doc, "Montant"), "Montant total : 950 euros.")
    sortie = str(tmp_path / "out.pdf")
    ed.enregistrer(sortie)
    assert not ed.modifie
    assert "950 euros" in texte(fitz.open(sortie))
    ed.corriger(0, centre(ed.doc, "Montant"), "Montant total : 10 euros.")
    ed.enregistrer(ed.source)  # sur le fichier d'origine lui-même
    assert "10 euros" in texte(fitz.open(ed.source))


def test_failed_edit_restores_document(ed, monkeypatch):
    def casse(doc, page, point, texte_nouveau, **k):
        core._redact_rects(doc[page], [doc[page].search_for("Montant")[0]])
        raise RuntimeError("panne")

    monkeypatch.setattr(core, "rewrite_line", casse)
    with pytest.raises(RuntimeError):
        ed.corriger(0, centre(ed.doc, "Montant"), "x")
    assert LIGNE in texte(ed.doc)
    assert not ed.peut_annuler and not ed.modifie
