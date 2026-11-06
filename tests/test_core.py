# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests automatisés de pdf_core, sur des PDF générés à la volée."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pdf_core as core  # noqa: E402
import pymupdf as fitz  # noqa: E402
from PIL import Image  # noqa: E402


# ------------------------------------------------------------- utilitaires


def make_pdf(path, pages=1, texts=None, rotation=0, size=(400, 400)):
    """Crée un PDF de `pages` pages tournées de `rotation`.

    texts : {page: [(x, y, texte)]}, avec (x, y) la ligne de base dans le repère
    AFFICHÉ ; le texte apparaît droit à l'affichage, comme dans un vrai document.
    """
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        page.set_rotation(rotation)
        for x, y, txt in (texts or {}).get(i, []):
            page.insert_text(fitz.Point(x, y) * page.derotation_matrix, txt,
                             fontname="helv", fontsize=12, rotate=rotation)
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


def displayed_rect(page, needle):
    """Rectangle d'un mot dans le repère affiché."""
    r = page.search_for(needle)[0] * page.rotation_matrix
    r.normalize()
    return r


def displayed_origin(page, needle):
    """Origine (ligne de base) du segment contenant `needle`, dans le repère affiché.

    Indépendante de la police, contrairement au rectangle (jambages différents).
    """
    for bloc in page.get_text("dict")["blocks"]:
        for line in bloc.get("lines", []):
            for span in line["spans"]:
                if needle in span["text"]:
                    return fitz.Point(span["origin"]) * page.rotation_matrix
    raise AssertionError(f"{needle!r} introuvable")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_replace_on_rotated_page(tmp_path, rotation):
    src = make_pdf(
        tmp_path / "src.pdf",
        texts={0: [(50, 100, "Texte original ici"), (50, 113, "ligne serree")]},
        rotation=rotation,
        size=(400, 500),  # page non carrée : une erreur de repère se verrait
    )
    doc = fitz.open(src)
    page = doc[0]
    avant = displayed_origin(page, "Texte")
    n = core.replace_text(doc, "original", "nouveau", [0])
    assert n == 1
    texte = " ".join(page.get_text().split())
    assert "Texte nouveau ici" in texte and "ligne serree" in texte
    assert texte.count("Texte") == 1  # pas de doublon
    # Même ligne de base, et la ligne se lit toujours horizontalement.
    apres = displayed_origin(page, "Texte")
    assert abs(apres.x - avant.x) < 0.5 and abs(apres.y - avant.y) < 0.5
    rect = displayed_rect(page, "Texte")
    assert rect.width > rect.height
    doc.close()


def test_replace_keeps_bold_and_serif_styles(tmp_path):
    """Gras et normal sur la même ligne : chacun garde sa police (bug du nom commun)."""
    chemin = str(tmp_path / "styles.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Titre", fontname="hebo", fontsize=12)  # Helvetica gras
    page.insert_text((90, 100), "normal", fontname="helv", fontsize=12)
    page.insert_text((50, 140), "Serif ici", fontname="tiro", fontsize=12)  # Times
    doc.save(chemin)
    doc.close()
    doc = fitz.open(chemin)
    core.replace_text(doc, "normal", "changé", [0])
    core.replace_text(doc, "ici", "là", [0])
    polices = {" ".join(s["text"].split()): s["font"] for b in doc[0].get_text("dict")["blocks"]
               for l in b["lines"] for s in l["spans"]}
    assert "Bold" in polices["Titre"]
    assert "Bold" not in polices["changé"]
    assert "Times" in polices["Serif là"]
    doc.close()


def test_stamp_preparation_is_fast_and_partial_opacity(tmp_path):
    import io
    import time
    png = make_png(tmp_path / "grande.png", color=(10, 20, 30), size=(3000, 2000))
    debut = time.time()
    data = core._prepare_stamp_image(png, core.StampOptions(0, 0, 10, opacity=0.5, white_transparent=True))
    assert time.time() - debut < 1.0
    pixel = Image.open(io.BytesIO(data)).getpixel((0, 0))
    assert pixel[:3] == (10, 20, 30) and pixel[3] == 127  # sombre : gardé, à moitié opaque


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_find_text_rects_in_displayed_space(tmp_path, rotation):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(60, 120, "cible")]}, rotation=rotation, size=(400, 500))
    doc = fitz.open(src)
    rects = core.find_text_rects(doc, "cible")[0]
    # La ligne de base affichée est à (60, 120) : le rectangle doit l'entourer.
    assert abs(rects[0].x0 - 60) < 1 and rects[0].y0 < 120 < rects[0].y1 + 3
    assert rects[0].width > rects[0].height
    blocs = core.text_blocks(doc[0])
    assert len(blocs) == 1 and blocs[0].contains(rects[0])
    doc.close()


def test_find_text_counts_pages(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "abc abc")], 1: [(50, 100, "rien")]})
    doc = fitz.open(src)
    assert core.find_text(doc, "abc") == {0: 2}
    doc.close()


# ------------------------------------------------------ déplacement


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_move_text_block(tmp_path, rotation):
    src = make_pdf(tmp_path / "src.pdf", texts={0: [(50, 100, "Bloc a bouger")]},
                   rotation=rotation, size=(400, 500))
    doc = fitz.open(src)
    page = doc[0]
    avant = displayed_origin(page, "Bloc")
    # Zone et décalage saisis dans le repère affiché : 30 à droite, 50 vers le bas.
    n = core.move_text_block(doc, 0, fitz.Rect(40, 85, 200, 105), 30, 50)
    assert n >= 1
    apres = displayed_origin(page, "Bloc")
    assert abs(apres.x - avant.x - 30) < 0.5
    assert abs(apres.y - avant.y - 50) < 0.5
    assert len(page.search_for("Bloc")) == 1  # l'original a bien été effacé
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
    with pytest.raises(core.PagilisError, match="Tesseract"):
        core.ocr_pages(doc, [0])
    doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_ocr_real_if_tessdata(tmp_path, rotation):
    if core.find_tessdata() is None:
        pytest.skip("tessdata absent : test OCR ignoré")
    # Fabrique un « scan » : une page qui ne contient qu'une image du texte.
    texte = fitz.open()
    texte.new_page(width=400, height=400).insert_text((50, 100), "Bonjour le monde", fontsize=24)
    pix = texte[0].get_pixmap(dpi=200)
    doc = fitz.open()
    # Comme un vrai scan tourné : image couchée dans le fichier, redressée par /Rotate.
    page = doc.new_page(width=400, height=400)
    page.set_rotation(rotation)
    page.insert_image(fitz.Rect(0, 0, 400, 400), pixmap=pix, rotate=rotation)
    # Le surlignage doit tomber sur le mot IMPRIMÉ, dans le repère affiché.
    attendu = fitz.Rect(50, 78, 145, 104)
    assert not core.has_text(doc[0])
    assert core.ocr_pages(doc, [0]) == 1
    rects = doc[0].search_for("Bonjour")
    assert rects, f"mot introuvable après OCR (rotation {rotation})"
    # search_for répond dans le repère non tourné : on compare dans le repère affiché.
    trouve = rects[0] * doc[0].rotation_matrix
    trouve.normalize()
    assert trouve.intersects(attendu)
    doc.close()


# ------------------------------------------------- édition rapide d'une ligne

LIGNES = [(60, 140, "Le client accepte le devis."), (60, 158, "Montant total : 1 200 euros."),
          (60, 176, "Le client signe ci-dessous.")]


def centre_ligne(page, needle):
    r = displayed_rect(page, needle)
    return fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


def texte_page(page):
    return " ".join(page.get_text().split())


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_line_at_finds_displayed_line(tmp_path, rotation):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}, rotation=rotation, size=(400, 500)))
    page = doc[0]
    point = centre_ligne(page, "Montant")
    info = core.line_at(page, point)
    assert info is not None
    assert info.text == "Montant total : 1 200 euros."
    assert info.rect.contains(point)
    assert info.block_rect.contains(info.rect)
    assert info.rect.width > info.rect.height  # repère affiché
    assert abs(info.size - 12) < 0.1


def test_line_at_outside_text_is_none(tmp_path):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", pages=2, texts={0: LIGNES}))
    assert core.line_at(doc[0], fitz.Point(5, 5)) is None
    assert core.line_at(doc[1], fitz.Point(100, 150)) is None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rewrite_line_replaces_only_that_line(tmp_path, rotation):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}, rotation=rotation, size=(400, 500)))
    page = doc[0]
    avant = displayed_origin(page, "Montant")
    assert core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant total : 950 euros.")
    texte = texte_page(page)
    assert "Montant total : 950 euros." in texte and "1 200" not in texte
    assert "Le client accepte le devis." in texte and "Le client signe ci-dessous." in texte
    apres = displayed_origin(page, "Montant")
    assert abs(apres.x - avant.x) < 2 and abs(apres.y - avant.y) < 2
    rect = displayed_rect(page, "Montant")
    assert rect.width > rect.height


def test_rewrite_line_empty_text_erases(tmp_path):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}))
    assert core.rewrite_line(doc, 0, centre_ligne(doc[0], "Montant"), "")
    texte = texte_page(doc[0])
    assert "Montant" not in texte
    assert "Le client accepte le devis." in texte and "Le client signe ci-dessous." in texte


def test_rewrite_line_shrinks_longer_text(tmp_path):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}))
    page = doc[0]
    largeur = core.line_at(page, centre_ligne(page, "Montant")).rect.width
    core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant total : 1 200 euros. " * 2)
    info = core.line_at(page, centre_ligne(page, "Montant"))
    assert info.rect.width <= largeur + 1


def test_rewrite_line_mixed_styles_uses_longest_span(tmp_path):
    chemin = str(tmp_path / "mixte.pdf")
    doc = fitz.open()
    page = doc.new_page()
    x = 50
    for texte, police in (("Total ", "helv"), ("TTC", "hebo"), (" à payer maintenant", "helv")):
        page.insert_text((x, 100), texte, fontname=police, fontsize=12)
        x += fitz.get_text_length(texte, fontname=police, fontsize=12)
    page.insert_text((50, 140), "Autre ligne", fontname="helv", fontsize=12)
    doc.save(chemin)
    doc = fitz.open(chemin)
    page = doc[0]
    assert core.rewrite_line(doc, 0, centre_ligne(page, "payer"), "Total HT à payer demain")
    spans = [s for b in page.get_text("dict")["blocks"] for l in b["lines"] for s in l["spans"]
             if "payer" in s["text"]]
    assert len(spans) == 1 and "Bold" not in spans[0]["font"]
    assert "Total HT à payer demain" in texte_page(page) and "Autre ligne" in texte_page(page)


def test_rewrite_line_unchanged_text_is_noop(tmp_path):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}))
    page = doc[0]
    avant = page.read_contents()
    assert not core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant total : 1 200 euros.")
    assert page.read_contents() == avant


def test_rewrite_line_no_line_returns_false(tmp_path):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}))
    assert not core.rewrite_line(doc, 0, fitz.Point(5, 5), "rien")


@pytest.mark.parametrize("police, drapeaux, serif", [
    ("Aptos", 4, False),            # Word marque Aptos « serif » à tort
    ("ABCDEF+Calibri", 4, False),
    ("ArialMT", 4, False),
    ("Cambria", 0, True),
    ("TimesNewRomanPSMT", 0, True),
    ("Georgia-Bold", 0, True),
    ("PoliceInconnue", 4, True),    # nom inconnu : on suit le drapeau
    ("PoliceInconnue", 0, False),
])
def test_serif_style_trusts_font_name_before_flag(police, drapeaux, serif):
    assert core._style_flags({"font": police, "flags": drapeaux})[2] is serif


# ------------------------------------------- police d'origine à la réécriture

GEORGIA = r"C:\Windows\Fonts\georgia.ttf"
avec_georgia = pytest.mark.skipif(not os.path.exists(GEORGIA), reason="Georgia absente")


def pdf_georgia(path, sous_ensemble=False):
    """Ligne écrite en Georgia embarquée (entière, ou réduite aux caractères utilisés)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F1", fontfile=GEORGIA)
    page.insert_text((50, 100), "Montant total : 1 200 euros.", fontname="F1", fontsize=12)
    page.insert_text((50, 140), "Autre ligne", fontname="helv", fontsize=12)
    if sous_ensemble:
        doc.subset_fonts()
    doc.save(path)
    return str(path)


def police_de(page, needle):
    return [s["font"] for b in page.get_text("dict")["blocks"] for l in b["lines"]
            for s in l["spans"] if needle in s["text"]][0]


@pytest.fixture
def sans_polices_installees(monkeypatch):
    monkeypatch.setattr(core, "polices_installees", lambda: {})


@avec_georgia
def test_rewrite_keeps_embedded_font_when_all_glyphs_exist(tmp_path, sans_polices_installees):
    doc = fitz.open(pdf_georgia(tmp_path / "g.pdf"))
    page = doc[0]
    assert core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant total : 950 euros.") == core.POLICE_ORIGINE
    assert "Georgia" in police_de(page, "950")
    assert "Montant total : 950 euros." in texte_page(page)


def test_rewrite_keeps_standard_pdf_font(tmp_path, sans_polices_installees):
    doc = fitz.open(make_pdf(tmp_path / "l.pdf", texts={0: LIGNES}))  # Helvetica, non embarquée
    page = doc[0]
    assert core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant : 5 euros.") == core.POLICE_ORIGINE
    assert police_de(page, "5 euros") == "Helvetica"


@avec_georgia
def test_rewrite_falls_back_when_a_glyph_is_missing(tmp_path, sans_polices_installees):
    doc = fitz.open(pdf_georgia(tmp_path / "g.pdf", sous_ensemble=True))
    page = doc[0]
    niveau = core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant total : 950 euros.")
    assert niveau == core.POLICE_REMPLACEMENT
    assert "Georgia" not in police_de(page, "950")
    assert "Montant total : 950 euros." in texte_page(page)


@avec_georgia
def test_rewrite_uses_installed_font_with_same_name(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "polices_installees", lambda: {core._cle_police("Georgia"): GEORGIA})
    doc = fitz.open(pdf_georgia(tmp_path / "g.pdf", sous_ensemble=True))
    page = doc[0]
    niveau = core.rewrite_line(doc, 0, centre_ligne(page, "Montant"), "Montant total : 950 € été.")
    assert niveau == core.POLICE_INSTALLEE
    assert "Georgia" in police_de(page, "950")
    assert "Montant total : 950 € été." in texte_page(page)


@pytest.mark.parametrize("pdf, installee", [
    ("ABCDEF+TimesNewRomanPSMT", "Times New Roman"),
    ("TimesNewRomanPS-BoldMT", "Times New Roman Bold"),
    ("ArialMT", "Arial"),
    ("Calibri-Bold", "Calibri Bold"),
    ("BCDEEE+Aptos", "Aptos Regular"),
    ("Georgia", "Georgia"),
])
def test_font_keys_match_pdf_and_windows_names(pdf, installee):
    assert core._cle_police(pdf) == core._cle_police(installee)


def test_installed_fonts_come_from_windows():
    polices = core.polices_installees()
    assert polices.get(core._cle_police("Arial")) and os.path.exists(polices[core._cle_police("Arial")])


# ------------------------------------------------------- gestion des pages


def doc_numerote(n=5):
    """Document de n pages ; la page i porte le texte « Page i+1 »."""
    doc = fitz.open()
    for i in range(n):
        doc.new_page(width=300, height=400).insert_text((50, 50), f"Page {i + 1}", fontsize=14)
    return doc


def ordre(doc):
    return [p.get_text().strip() for p in doc]


def test_rotate_pages_adds_to_current_rotation():
    doc = doc_numerote(3)
    doc[1].set_rotation(90)
    core.rotate_pages(doc, [0, 1], 90)
    assert [p.rotation for p in doc] == [90, 180, 0]
    core.rotate_pages(doc, [0], -90)
    assert doc[0].rotation == 0


def test_delete_pages_and_refuse_deleting_all():
    doc = doc_numerote(4)
    assert core.delete_pages(doc, [3, 1]) == 2
    assert ordre(doc) == ["Page 1", "Page 3"]
    with pytest.raises(core.PagilisError):
        core.delete_pages(doc, [0, 1])
    assert doc.page_count == 2


@pytest.mark.parametrize("selection, sens, attendu, nouvelle", [
    ([1], -1, ["Page 2", "Page 1", "Page 3", "Page 4", "Page 5"], [0]),
    ([1, 2], 1, ["Page 1", "Page 4", "Page 2", "Page 3", "Page 5"], [2, 3]),
    ([0, 3], 1, ["Page 2", "Page 1", "Page 3", "Page 5", "Page 4"], [1, 4]),
    ([0], -1, ["Page 1", "Page 2", "Page 3", "Page 4", "Page 5"], []),   # déjà en tête : rien
    ([4], 1, ["Page 1", "Page 2", "Page 3", "Page 4", "Page 5"], []),    # déjà en fin : rien
])
def test_move_pages_one_step(selection, sens, attendu, nouvelle):
    doc = doc_numerote(5)
    assert core.move_pages(doc, selection, sens) == nouvelle
    assert ordre(doc) == attendu


def test_insert_pdf_after_selection_or_at_end(tmp_path):
    autre = tmp_path / "autre.pdf"
    a = fitz.open()
    for t in ("A", "B"):
        a.new_page().insert_text((50, 50), t)
    a.save(autre)
    doc = doc_numerote(3)
    assert core.insert_pdf(doc, str(autre), apres=0) == [1, 2]
    assert ordre(doc) == ["Page 1", "A", "B", "Page 2", "Page 3"]
    assert core.insert_pdf(doc, str(autre), apres=None) == [5, 6]
    assert ordre(doc)[-2:] == ["A", "B"]


def test_extract_pages_keeps_order_and_rotation(tmp_path):
    doc = doc_numerote(4)
    doc[2].set_rotation(90)
    sortie = tmp_path / "extrait.pdf"
    core.extract_pages(doc, [2, 0], str(sortie))
    extrait = fitz.open(sortie)
    assert ordre(extrait) == ["Page 1", "Page 3"]
    assert extrait[1].rotation == 90
    assert doc.page_count == 4  # le document n'est pas touché


# ------------------------------------------------------------ performances


def test_search_and_replace_skip_pages_without_the_word(monkeypatch):
    """Seules les pages qui contiennent le mot sont lues en détail (lecture caractère par caractère)."""
    doc = fitz.open()
    for i in range(10):
        doc.new_page().insert_text((50, 50), "Le montant est dû." if i == 3 else "Rien ici.", fontsize=12)
    lues = []
    vraie = core.iter_lines
    monkeypatch.setattr(core, "iter_lines", lambda page: (lues.append(page.number), vraie(page))[1])
    assert list(core.find_text_rects(doc, "MONTANT")) == [3]
    assert set(lues) == {3}
    lues.clear()
    assert core.replace_text(doc, "montant", "total", range(10)) == 1
    assert set(lues) == {3}
    assert "total" in doc[3].get_text()


def test_shrink_not_computed_when_new_text_is_not_longer(monkeypatch):
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Montant total : 1 200 euros.", fontsize=12)
    appels = []
    monkeypatch.setattr(core, "_reduction", lambda *a: appels.append(a) or 1.0)
    core.replace_text(doc, "1 200", "950", [0], shrink_if_longer=True)
    assert appels == []
    core.replace_text(doc, "950", "95 000 000", [0], shrink_if_longer=True)
    assert len(appels) == 1
