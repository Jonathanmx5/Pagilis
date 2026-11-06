# SPDX-License-Identifier: AGPL-3.0-or-later
"""Auto-vérification de l'exe : « PDFStudio.exe --verifier ».

Fait tourner les vraies fonctions dans l'exe compilé (et non dans les sources) :
un module oublié par PyInstaller, une DLL manquante ou des fichiers de langue
absents font échouer la vérification. Code de sortie 0 = tout va bien.

Utilisée :
- par la CI, sur l'exe qui va être publié ;
- par la mise à jour, sur l'exe téléchargé AVANT de remplacer la version en
  place : une version qui ne fonctionne pas n'est jamais installée.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import traceback
from typing import Callable

import pymupdf as fitz
from PIL import Image

import pdf_core as core


def _document() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((40, 80), "Bonjour verification", fontsize=24)
    return doc


def _pdf() -> None:
    doc = _document()
    assert doc[0].get_pixmap(dpi=72).width > 0, "rendu vide"
    assert core.find_text(doc, "verification") == {0: 1}, "recherche"
    assert core.replace_text(doc, "Bonjour", "Salut", [0]) == 1, "remplacement"
    assert "Salut" in doc[0].get_text(), "texte remplacé absent"


def _tampon() -> None:
    doc = _document()
    chemin = os.path.join(tempfile.mkdtemp(), "tampon.png")
    Image.new("RGB", (40, 20), "white").save(chemin)
    core.add_stamp(doc, chemin, [0], core.StampOptions(10, 10, 40, white_transparent=True))
    assert doc[0].get_images(), "image non posée"


def _ocr() -> None:
    if core.find_tessdata() is None:
        raise AssertionError("fichiers de langue Tesseract introuvables")
    # « Scan » : une page qui ne contient que l'image du texte.
    pix = _document()[0].get_pixmap(dpi=200)
    doc = fitz.open()
    doc.new_page(width=400, height=300).insert_image(fitz.Rect(0, 0, 400, 300), pixmap=pix)
    core.ocr_pages(doc, [0], "fra", 200)
    assert doc[0].search_for("Bonjour"), "OCR : mot non reconnu"


def _interface() -> None:
    import customtkinter as ctk
    racine = ctk.CTk()
    racine.withdraw()
    ctk.CTkButton(racine, text="ok").pack()
    racine.update()
    racine.destroy()


def _chiffrement() -> None:
    tampon = io.BytesIO()
    _document().save(tampon, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="x")
    doc = fitz.open(stream=tampon.getvalue())
    assert doc.needs_pass and doc.authenticate("x"), "chiffrement AES"


CONTROLES: list[tuple[str, Callable[[], None]]] = [
    ("PDF (rendu, recherche, remplacement)", _pdf),
    ("Tampon image", _tampon),
    ("Chiffrement", _chiffrement),
    ("OCR (Tesseract + fichiers de langue)", _ocr),
    ("Interface graphique", _interface),
]


def verifier(ignorer_ocr: bool = False) -> list[str]:
    """Lance tous les contrôles ; retourne la liste des échecs (vide = succès)."""
    echecs = []
    for nom, controle in CONTROLES:
        if ignorer_ocr and controle is _ocr:
            continue
        try:
            controle()
            logging.info("Vérification OK : %s", nom)
        except Exception:  # noqa: BLE001 - chaque échec est rapporté, aucun n'arrête les autres
            logging.error("Vérification ÉCHEC : %s\n%s", nom, traceback.format_exc())
            echecs.append(nom)
    return echecs
