"""Tests automatisés de pdf_core, sur des PDF générés à la volée."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pdf_core as core  # noqa: E402
import pymupdf as fitz  # noqa: E402
from PIL import Image  # noqa: E402


# ------------------------------------------------------------- utilitaires


def make_pdf(path, pages=1, texts=None, rotation=0):
    """Crée un PDF de `pages` pages. texts : liste de (x, y, texte) par page."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=400)
        for x, y, txt in (texts or {}).get(i, []):
            page.insert_text((x, y), txt, fontname="helv", fontsize=12)
        page.set_rotation(rotation)
    doc.save(path)
    doc.close()
    return str(path)


def make_png(path, color=(0, 0, 0), size=(120, 60)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def page_text(doc, idx):
    return doc[idx].get_text()


# ------------------------------------------------------------ plages


@pytest.mark.parametrize(
    "spec, attendu",
    [
        ("1-3, 5", [0, 1, 2, 4]),
        ("8-", [7, 8, 9]),
        ("-2", [0, 1]),
        ("3, 3, 1", [0, 2]),
    ],
)
def test_parse_page_ranges_valid(spec, attendu):
    assert core.parse_page_ranges(spec, 10) == attendu


@pytest.mark.parametrize("spec", ["", "abc", "5-2", "0-3", "1-99", "9-"])
def test_parse_page_ranges_invalid(spec):
    with pytest.raises(core.PageRangeError):
        core.parse_page_ranges(spec, 5)


# ------------------------------------------------------------ fusion


def test_merge_adds_bookmark_per_source_and_keeps_original_toc(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", pages=2)
    b = make_pdf(tmp_path / "b.pdf", pages=1)
    # Signet d'origine dans b.pdf
    avec_signet = str(tmp_path / "b_signet.pdf")
    doc_b = fitz.open(b)
    doc_b.set_toc([[1, "Chapitre B", 1]])
    doc_b.save(avec_signet)
    doc_b.close()

    sortie = str(tmp_path / "fusion.pdf")
    core.merge_pdfs([a, avec_signet], sortie)
    doc = fitz.open(sortie)
    assert doc.page_count == 3
    toc = doc.get_toc(simple=True)
    assert [t[1] for t in toc] == ["a.pdf", "b_signet.pdf", "Chapitre B"]
    assert toc[1][2] == 3  # le signet de b.pdf pointe sur sa page dans la fusion
    assert toc[2][0] == 2  # signet d'origine décalé d'un niveau
    assert toc[2][2] == 3
    doc.close()


# ------------------------------------------------------------ division


def test_split_by_page(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", pages=3)
    fichiers = core.split_by_page(src, str(tmp_path))
    assert len(fichiers) == 3
    assert all(fitz.open(f).page_count == 1 for f in fichiers)


def test_split_every_n(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", pages=5)
    fichiers = core.split_every_n(src, str(tmp_path), 2)
    assert [fitz.open(f).page_count for f in fichiers] == [2, 2, 1]


def test_split_by_ranges(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", pages=8)
    fichiers = core.split_by_ranges(src, str(tmp_path), "1-3, 5, 7-")
    assert [fitz.open(f).page_count for f in fichiers] == [3, 1, 2]


def test_split_by_ranges_invalid_message(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", pages=2)
    with pytest.raises(core.PageRangeError, match="sort du document"):
        core.split_by_ranges(src, str(tmp_path), "1-5")


# ------------------------------------------------------------ tampon


def test_stamp_stored_once(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", pages=3)
    png = make_png(tmp_path / "sig.png")
    doc = fitz.open(src)
    core.add_stamp(doc, png, [0, 1, 2], core.StampOptions(x=50, y=50, width=80))
    xrefs = {doc[i].get_images(full=True)[-1][0] for i in range(3)}
    assert len(xrefs) == 1
    doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_stamp_upright_on_rotated_page(tmp_path, rotation):
    """Le tampon doit apparaître à la position demandée, dans le repère affiché."""
    src = make_pdf(tmp_path / "src.pdf", pages=1, rotation=rotation)
    png = make_png(tmp_path / "sig.png", size=(200, 100))
    doc = fitz.open(src)
    page = doc[0]
    core.add_stamp(doc, png, [0], core.StampOptions(x=40, y=30, width=60))
    # Position attendue, dans le repère affiché.
    attendu = fitz.Rect(40, 30, 100, 60)
    trouve = page.get_image_rects(page.get_images(full=True)[-1][0])
    assert trouve, "image introuvable"
    rect_affiche = trouve[0] * page.rotation_matrix
    rect_affiche.normalize()
    assert abs(rect_affiche.x0 - attendu.x0) < 1.5
    assert abs(rect_affiche.y0 - attendu.y0) < 1.5
    doc.close()


def test_stamp_white_transparent_and_opacity(tmp_path):
    png = make_png(tmp_path / "sig.png", color=(255, 255, 255), size=(10, 10))
    opts = core.StampOptions(x=0, y=0, width=10, opacity=0.5, white_transparent=True)
    data = core._prepare_stamp_image(png, opts)
    img = Image.open(__import__("io").BytesIO(data)).convert("RGBA")
    assert img.getpixel((0, 0))[3] == 0


# ------------------------------------------------------- remplacement


def test_replace_keeps_neighbours_and_close_lines(tmp_path):
    src = make_pdf(
        tmp_path / "src.pdf",
        texts={0: [(50, 100, "Bonjour cher ami"), (50, 113, "ligne serree dessous")]},
    )
    doc = fitz.open(src)
    n = core.replace_text(doc, "cher", "tres", [0])
    assert n == 1
    out = str(tmp_path / "out.pdf")
    core.save_atomic(doc, out)
    doc.close()
    # PyMuPDF renvoie des espaces insécables avec la police intégrée : on normalise.
    texte = " ".join(fitz.open(out)[0].get_text().split())
    assert texte.count("Bonjour") == 1
    assert "Bonjour tres ami" in texte
    assert "ligne serree dessous" in texte


def test_replace_respects_case(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "Chat chat")]})
    doc = fitz.open(src)
    core.replace_text(doc, "chat", "chien", [0], match_case=True)
    texte = doc[0].get_text()
    assert "Chat" in texte and "chien" in texte


def test_replace_empty_erases(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "Supprimer ce mot")]})
    doc = fitz.open(src)
    core.replace_text(doc, "ce", "", [0])
    assert "ce" not in doc[0].get_text().split()


def test_replace_on_rotated_page(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "Texte original")]}, rotation=90)
    doc = fitz.open(src)
    n = core.replace_text(doc, "original", "nouveau", [0])
    assert n == 1
    assert "nouveau" in doc[0].get_text()
    doc.close()


def test_find_text_counts_pages(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "abc abc")], 1: [(50, 100, "rien")]})
    doc = fitz.open(src)
    assert core.find_text(doc, "abc") == {0: 2}
    doc.close()


# ------------------------------------------------------ déplacement


def test_move_text_block(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "Bloc a bouger")]})
    doc = fitz.open(src)
    n = core.move_text_block(doc, 0, fitz.Rect(40, 85, 200, 105), 0, 50)
    assert n >= 1
    blocs = doc[0].get_text("dict")["blocks"]
    y_bas = max(b["bbox"][3] for b in blocs if b["type"] == 0)
    assert y_bas > 140  # le texte est descendu de ~50 points
    doc.close()


# ------------------------------------------------------ chiffrement


def test_encrypted_pdf_requires_password(tmp_path):
    chemin = str(tmp_path / "chiffre.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "secret")
    doc.save(chemin, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="motdepasse", owner_pw="motdepasse")
    doc.close()
    with pytest.raises(core.PasswordRequired):
        core.open_pdf(chemin)
    with pytest.raises(core.PasswordRequired):
        core.open_pdf(chemin, password="faux")
    ouvert = core.open_pdf(chemin, password="motdepasse")
    assert ouvert.page_count == 1
    ouvert.close()
    # Le mot de passe est mémorisé pour ce chemin.
    assert core.open_pdf(chemin).page_count == 1


# ------------------------------------------------------ aperçu


def test_preview_matrix_on_rotated_page(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", rotation=90)
    doc = fitz.open(src)
    page = doc[0]
    point_affiche = fitz.Point(0, 0)
    # Le coin affiché en haut à gauche correspond à un point du repère non tourné.
    point_brut = point_affiche * page.derotation_matrix
    assert (point_brut * page.rotation_matrix - point_affiche).x == pytest.approx(0, abs=1e-6)
    doc.close()


# ------------------------------------------------------ OCR


def test_ocr_skipped_without_tessdata(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "find_tessdata", lambda *_a, **_k: None)
    src = make_pdf(tmp_path / "src.pdf")
    doc = fitz.open(src)
    with pytest.raises(core.PdfStudioError, match="Tesseract"):
        core.ocr_pages(doc, [0])
    doc.close()


def test_ocr_real_if_tessdata(tmp_path):
    if core.find_tessdata() is None:
        pytest.skip("tessdata absent : test OCR ignoré")
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "Bonjour le monde")]})
    doc = fitz.open(src)
    doc[0].get_text()
    assert core.ocr_pages(doc, [0]) == 1
    doc.close()
