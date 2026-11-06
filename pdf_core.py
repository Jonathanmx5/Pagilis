"""Cœur de PDF Studio : toute la logique PDF, sans aucun import d'interface.

Conventions :
- les PDF sont ouverts en mémoire, donc aucun fichier n'est verrouillé ;
- les coordonnées saisies par l'utilisateur sont dans le repère de la page
  AFFICHÉE (rotation /Rotate prise en compte via rotation_matrix et
  derotation_matrix) ;
- chaque traitement long accepte un rappel progress(i, n).
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

try:
    import pymupdf as fitz  # PyMuPDF récent
except ImportError:  # pragma: no cover - repli pour les vieilles versions
    import fitz

from PIL import Image

Progress = Optional[Callable[[int, int], None]]

# Polices système Windows utilisées pour réécrire le texte (gèrent € et œ).
WINDOWS_FONTS = {
    (False, False): r"C:\Windows\Fonts\arial.ttf",
    (True, False): r"C:\Windows\Fonts\arialbd.ttf",
    (False, True): r"C:\Windows\Fonts\ariali.ttf",
    (True, True): r"C:\Windows\Fonts\arialbi.ttf",
}


class PdfStudioError(Exception):
    """Erreur générale du cœur, message destiné à l'utilisateur."""


class PageRangeError(PdfStudioError):
    """Plage de pages invalide."""


class PasswordRequired(PdfStudioError):
    """Le PDF est chiffré et aucun mot de passe valable n'a été fourni."""

    def __init__(self, path: str):
        super().__init__(f"Mot de passe requis : {path}")
        self.path = path


# Mots de passe mémorisés par chemin pendant la session.
_known_passwords: dict[str, str] = {}


# ---------------------------------------------------------------- ouverture


def open_pdf(path: str, password: Optional[str] = None) -> fitz.Document:
    """Ouvre un PDF en mémoire. Lève PasswordRequired s'il est chiffré."""
    with open(path, "rb") as fh:
        data = fh.read()
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        pwd = password or _known_passwords.get(os.path.abspath(path))
        if not pwd or not doc.authenticate(pwd):
            doc.close()
            raise PasswordRequired(path)
        _known_passwords[os.path.abspath(path)] = pwd
    return doc


def remember_password(path: str, password: str) -> None:
    """Mémorise un mot de passe pour un chemin donné."""
    _known_passwords[os.path.abspath(path)] = password


def save_atomic(doc: fitz.Document, path: str) -> None:
    """Enregistre via un fichier temporaire puis os.replace (sûr sur place)."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=folder)
    os.close(fd)
    try:
        doc.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def page_size_displayed(page: fitz.Page) -> tuple[float, float]:
    """Largeur et hauteur de la page telle qu'affichée (rotation prise en compte)."""
    r = page.rect
    if page.rotation in (90, 270):
        return r.height, r.width
    return r.width, r.height


# ------------------------------------------------------------ plages de pages


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """Convertit « 1-3, 5, 8- » en indices 0-based, sans doublon, triés.

    Lève PageRangeError avec un message clair pour une plage invalide.
    """
    if not spec or not spec.strip():
        raise PageRangeError("Indiquez au moins une page (ex. « 1-3, 5 »).")
    result: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            debut = int(m.group(1)) if m.group(1) else 1
            fin = int(m.group(2)) if m.group(2) else page_count
            if debut > fin:
                raise PageRangeError(f"Plage à l'envers : « {part} ».")
        elif part.isdigit():
            debut = fin = int(part)
        else:
            raise PageRangeError(f"Plage invalide : « {part} ».")
        if debut < 1 or fin > page_count:
            raise PageRangeError(
                f"« {part} » sort du document (1 à {page_count} pages)."
            )
        result.update(range(debut - 1, fin))
    if not result:
        raise PageRangeError("Aucune page sélectionnée.")
    return sorted(result)


# ------------------------------------------------------------------- fusion


def merge_pdfs(paths: list[str], output: str, progress: Progress = None) -> None:
    """Fusionne des PDF dans l'ordre donné, avec un signet par fichier source.

    Les signets d'origine sont conservés, décalés d'un niveau sous le signet
    du fichier.
    """
    if not paths:
        raise PdfStudioError("Aucun fichier à fusionner.")
    out = fitz.open()
    toc: list[list] = []
    n = len(paths)
    for i, path in enumerate(paths):
        src = open_pdf(path)
        debut = out.page_count
        out.insert_pdf(src)
        toc.append([1, os.path.basename(path), debut + 1])
        for niveau, titre, page in src.get_toc(simple=True):
            toc.append([niveau + 1, titre, page + debut])
        src.close()
        if progress:
            progress(i + 1, n)
    out.set_toc(toc)
    save_atomic(out, output)
    out.close()


# ------------------------------------------------------------------ division


def split_by_page(path: str, out_dir: str, progress: Progress = None) -> list[str]:
    """Une page par fichier."""
    src = open_pdf(path)
    base = os.path.splitext(os.path.basename(path))[0]
    result = []
    n = src.page_count
    for i in range(n):
        doc = fitz.open()
        doc.insert_pdf(src, from_page=i, to_page=i)
        dest = os.path.join(out_dir, f"{base}_p{i + 1:03d}.pdf")
        save_atomic(doc, dest)
        doc.close()
        result.append(dest)
        if progress:
            progress(i + 1, n)
    src.close()
    return result


def split_every_n(path: str, out_dir: str, n_pages: int, progress: Progress = None) -> list[str]:
    """Un fichier toutes les N pages."""
    if n_pages < 1:
        raise PdfStudioError("Le nombre de pages doit être au moins 1.")
    src = open_pdf(path)
    base = os.path.splitext(os.path.basename(path))[0]
    result = []
    total = (src.page_count + n_pages - 1) // n_pages
    for k, debut in enumerate(range(0, src.page_count, n_pages)):
        fin = min(debut + n_pages, src.page_count) - 1
        doc = fitz.open()
        doc.insert_pdf(src, from_page=debut, to_page=fin)
        dest = os.path.join(out_dir, f"{base}_part{k + 1:03d}.pdf")
        save_atomic(doc, dest)
        doc.close()
        result.append(dest)
        if progress:
            progress(k + 1, total)
    src.close()
    return result


def split_by_ranges(path: str, out_dir: str, spec: str, progress: Progress = None) -> list[str]:
    """Une plage = un fichier. Ex. « 1-3, 5, 8- »."""
    src = open_pdf(path)
    base = os.path.splitext(os.path.basename(path))[0]
    groupes = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            groupes.append(parse_page_ranges(part, src.page_count))
    if not groupes:
        src.close()
        raise PageRangeError("Indiquez au moins une plage.")
    result = []
    for k, pages in enumerate(groupes):
        doc = fitz.open()
        for p in pages:
            doc.insert_pdf(src, from_page=p, to_page=p)
        dest = os.path.join(out_dir, f"{base}_plage{k + 1:02d}.pdf")
        save_atomic(doc, dest)
        doc.close()
        result.append(dest)
        if progress:
            progress(k + 1, len(groupes))
    src.close()
    return result


# ------------------------------------------------------- signature / tampon


@dataclass
class StampOptions:
    """Paramètres d'un tampon. x, y, width en points, repère affiché."""

    x: float
    y: float
    width: float
    opacity: float = 1.0  # 0.0 à 1.0
    rotation: int = 0  # 0, 90, 180 ou 270
    white_transparent: bool = False  # pour une signature scannée


def _prepare_stamp_image(image_path: str, opts: StampOptions) -> bytes:
    """Charge l'image, rend le blanc transparent et applique l'opacité."""
    img = Image.open(image_path).convert("RGBA")
    pixels = img.load()
    largeur, hauteur = img.size
    for y in range(hauteur):
        for x in range(largeur):
            r, g, b, a = pixels[x, y]
            if opts.white_transparent and r > 240 and g > 240 and b > 240:
                a = 0
            else:
                a = int(a * opts.opacity)
            pixels[x, y] = (r, g, b, a)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def add_stamp(
    doc: fitz.Document,
    image_path: str,
    pages: Iterable[int],
    opts: StampOptions,
    progress: Progress = None,
) -> None:
    """Pose une image sur les pages indiquées (indices 0-based).

    L'image n'est stockée qu'une fois : les pages suivantes réutilisent son xref.
    La position est donnée dans le repère affiché, puis convertie en repère
    non tourné, et l'image est tournée de (rotation + /Rotate) pour apparaître droite.
    """
    pages = list(pages)
    png = _prepare_stamp_image(image_path, opts)
    with Image.open(io.BytesIO(png)) as im:
        ratio = im.height / im.width
    # Largeur en points et hauteur calculée selon les proportions.
    if opts.rotation in (90, 270):
        largeur, hauteur = opts.width * ratio, opts.width
    else:
        largeur, hauteur = opts.width, opts.width * ratio
    xref = 0
    for k, idx in enumerate(pages):
        page = doc[idx]
        # Rectangle dans le repère affiché, converti vers le repère non tourné.
        rect_affiche = fitz.Rect(opts.x, opts.y, opts.x + largeur, opts.y + hauteur)
        rect = rect_affiche * page.derotation_matrix
        rect.normalize()
        rot = (opts.rotation + page.rotation) % 360
        if xref == 0:
            page.insert_image(rect, stream=png, rotate=rot, overlay=True)
            xref = page.get_images(full=True)[-1][0]
        else:
            page.insert_image(rect, xref=xref, rotate=rot, overlay=True)
        if progress:
            progress(k + 1, len(pages))


# ----------------------------------------------- texte : lecture et réécriture


@dataclass
class TextSpan:
    """Un morceau de ligne d'un même style."""

    text: str
    bbox: fitz.Rect  # repère non tourné
    origin: fitz.Point
    font: str
    size: float
    color: int
    bold: bool
    italic: bool
    serif: bool
    mono: bool


def _style_flags(span: dict) -> tuple[bool, bool, bool, bool]:
    flags = span.get("flags", 0)
    nom = span.get("font", "").lower()
    gras = bool(flags & 16) or "bold" in nom or "black" in nom
    italique = bool(flags & 2) or "italic" in nom or "oblique" in nom
    mono = bool(flags & 8) or "courier" in nom or "mono" in nom
    serif = bool(flags & 4) or "times" in nom or "serif" in nom and "sans" not in nom
    return gras, italique, serif, mono


def _horizontal_line(line: dict) -> bool:
    """Ne garde que les lignes qui se lisent horizontalement sur la page affichée.

    get_text renvoie les coordonnées dans le repère AFFICHÉ, donc la direction
    de lecture 'dir' s'interprète directement.
    """
    dx, dy = line.get("dir", (1.0, 0.0))
    return abs(dy) < 0.01 and dx > 0


def iter_lines(page: fitz.Page) -> Iterable[tuple[dict, list[dict]]]:
    """Itère sur les lignes lisibles horizontalement, avec leurs caractères."""
    data = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_LIGATURES)
    for bloc in data["blocks"]:
        if bloc.get("type") != 0:
            continue
        for line in bloc["lines"]:
            if _horizontal_line(line):
                yield line, [c for s in line["spans"] for c in s.get("chars", [])]


def _find_matches(page: fitz.Page, needle: str, match_case: bool) -> list[fitz.Rect]:
    """Recherche caractère par caractère, ligne par ligne (pas de search_for).

    Retourne les rectangles (repère affiché) des occurrences trouvées
    sur UNE seule ligne.
    """
    if not needle:
        return []
    cible = needle if match_case else needle.lower()
    rects: list[fitz.Rect] = []
    for _line, chars in iter_lines(page):
        texte = "".join(c["c"] for c in chars)
        comparé = texte if match_case else texte.lower()
        debut = 0
        while True:
            pos = comparé.find(cible, debut)
            if pos < 0:
                break
            morceau = chars[pos : pos + len(cible)]
            rect = fitz.Rect(morceau[0]["bbox"])
            for c in morceau[1:]:
                rect |= fitz.Rect(c["bbox"])
            rects.append(rect)
            debut = pos + len(cible)
    return rects


def find_text(doc: fitz.Document, needle: str, match_case: bool = False) -> dict[int, int]:
    """Retourne {indice de page: nombre d'occurrences} pour l'aperçu."""
    resultat = {}
    for i in range(doc.page_count):
        n = len(_find_matches(doc[i], needle, match_case))
        if n:
            resultat[i] = n
    return resultat


def _char_style(span: dict) -> tuple:
    return (span.get("font"), span.get("size"), span.get("color"))


def _spans_of_line(line: dict) -> list[TextSpan]:
    """Découpe une ligne en segments de style homogène (police, taille, couleur)."""
    spans = []
    for s in line["spans"]:
        chars = s.get("chars", [])
        if not chars:
            continue
        gras, italique, serif, mono = _style_flags(s)
        texte = "".join(c["c"] for c in chars)
        rect = fitz.Rect(chars[0]["bbox"])
        for c in chars[1:]:
            rect |= fitz.Rect(c["bbox"])
        spans.append(
            TextSpan(
                text=texte,
                bbox=rect,
                origin=fitz.Point(s["origin"]),
                font=s.get("font", ""),
                size=s.get("size", 10.0),
                color=s.get("color", 0),
                bold=gras,
                italic=italique,
                serif=serif,
                mono=mono,
            )
        )
    return spans


def _font_for(span: TextSpan) -> tuple[Optional[str], Optional[str]]:
    """Choisit une police : fichier système Windows, sinon police PDF standard.

    Retourne (fontname, fontfile).
    """
    if span.mono:
        if os.path.exists(r"C:\Windows\Fonts\cour.ttf"):
            return "cour", r"C:\Windows\Fonts\cour.ttf"
        return "cour", None
    chemin = WINDOWS_FONTS.get((span.bold, span.italic))
    if chemin and os.path.exists(chemin):
        return "pdfstudio", chemin
    if span.serif:
        return "tiro", None
    return "helv", None


def _redact_rects(page: fitz.Page, rects: list[fitz.Rect]) -> None:
    """Efface le texte sans boîte blanche, en ne touchant ni images ni dessins.

    La zone est réduite à sa bande verticale centrale pour ne pas effacer
    les lignes voisines serrées. Les rectangles sont dans le repère affiché.
    """
    for rect in rects:
        marge = rect.height * 0.15
        bande = fitz.Rect(rect.x0 - 0.5, rect.y0 + marge, rect.x1 + 0.5, rect.y1 - marge)
        page.add_redact_annot(bande, fill=False)
    if rects:
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        )


def _write_span(page: fitz.Page, span: TextSpan, origin: fitz.Point, shrink: float = 1.0) -> None:
    """Réécrit un segment au même style, à la même ligne de base.

    origin est dans le repère affiché ; insert_text attend le repère non tourné.
    """
    fontname, fontfile = _font_for(span)
    kwargs = dict(
        fontname=fontname,
        fontsize=span.size * shrink,
        color=_rgb(span.color),
        rotate=page.rotation,
    )
    if fontfile:
        kwargs["fontfile"] = fontfile
    page.insert_text(fitz.Point(origin) * page.derotation_matrix, span.text, **kwargs)


def _rgb(color: int) -> tuple[float, float, float]:
    return (((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255)


def replace_text(
    doc: fitz.Document,
    old: str,
    new: str,
    pages: Iterable[int],
    match_case: bool = False,
    shrink_if_longer: bool = False,
    progress: Progress = None,
) -> int:
    """Remplace une chaîne sur les pages données. Retourne le nombre de remplacements.

    Un remplacement vide efface simplement le texte. Les mots voisins sur la
    même ligne sont réécrits à l'identique ; les lignes voisines ne sont pas touchées.
    """
    if not old:
        raise PdfStudioError("Le texte à remplacer est vide.")
    pages = list(pages)
    total = 0
    for k, idx in enumerate(pages):
        page = doc[idx]
        rects = _find_matches(page, old, match_case)
        if rects:
            # Pour chaque ligne concernée, on réécrit l'intégralité des segments.
            morceaux_a_reecrire = []
            for line, _chars in iter_lines(page):
                if any(fitz.Rect(line["bbox"]).intersects(r) for r in rects):
                    morceaux_a_reecrire.append(_spans_of_line(line))
            # On efface TOUTE la ligne touchée (mots voisins compris), puis on réécrit.
            _redact_rects(page, [s.bbox for spans in morceaux_a_reecrire for s in spans])
            for spans in morceaux_a_reecrire:
                for span in spans:
                    texte_nouveau = _substitute(span.text, old, new, match_case)
                    if texte_nouveau == span.text:
                        _write_span(page, span, span.origin)
                        continue
                    shrink = 1.0
                    if shrink_if_longer and texte_nouveau:
                        largeur_ancienne = fitz.get_text_length(span.text, fontname="helv", fontsize=span.size)
                        largeur_nouvelle = fitz.get_text_length(texte_nouveau, fontname="helv", fontsize=span.size)
                        if largeur_nouvelle > largeur_ancienne > 0:
                            shrink = largeur_ancienne / largeur_nouvelle
                    if texte_nouveau:
                        span.text = texte_nouveau
                        _write_span(page, span, span.origin, shrink)
            total += len(rects)
        if progress:
            progress(k + 1, len(pages))
    return total


def _substitute(texte: str, old: str, new: str, match_case: bool) -> str:
    """Remplace old par new dans texte, en respectant la casse si demandé."""
    if match_case:
        return texte.replace(old, new)
    return re.sub(re.escape(old), lambda _m: new, texte, flags=re.IGNORECASE)


def move_text_block(
    doc: fitz.Document,
    page_index: int,
    rect: fitz.Rect,
    dx: float,
    dy: float,
) -> int:
    """Déplace les lignes comprises dans rect de dx/dy (repère affiché).

    Redaction du bloc puis réécriture de chaque segment au même style.
    Retourne le nombre de segments déplacés.
    """
    page = doc[page_index]
    # rect et les coordonnées du texte sont tous deux dans le repère affiché.
    zone = fitz.Rect(rect)
    zone.normalize()
    lignes = []
    for line, _chars in iter_lines(page):
        if fitz.Rect(line["bbox"]).intersects(zone):
            lignes.append(_spans_of_line(line))
    if not lignes:
        return 0
    rects = [span.bbox for spans in lignes for span in spans]
    _redact_rects(page, rects)
    compte = 0
    for spans in lignes:
        for span in spans:
            _write_span(page, span, span.origin + fitz.Point(dx, dy))
            compte += 1
    return compte


# ----------------------------------------------------------------- OCR


def find_tessdata(user_dir: Optional[str] = None) -> Optional[str]:
    """Cherche le dossier contenant les .traineddata, dans l'ordre prévu."""
    candidats = []
    if user_dir:
        candidats.append(user_dir)
    if os.environ.get("TESSDATA_PREFIX"):
        candidats.append(os.environ["TESSDATA_PREFIX"])
    if getattr(os.sys, "frozen", False):
        candidats.append(os.path.join(os.path.dirname(os.sys.executable), "tessdata"))
    candidats.append(os.path.join(getattr(os.sys, "_MEIPASS", ""), "tessdata"))
    candidats.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata"))
    candidats += [
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tessdata",
    ]
    for dossier in candidats:
        if dossier and os.path.isdir(dossier) and any(
            f.endswith(".traineddata") for f in os.listdir(dossier)
        ):
            return dossier
    return None


def has_text(page: fitz.Page) -> bool:
    """Vrai si la page contient déjà du texte exploitable."""
    return len(page.get_text("words")) > 0


def ocr_pages(
    doc: fitz.Document,
    pages: Iterable[int],
    language: str = "fra",
    dpi: int = 300,
    tessdata: Optional[str] = None,
    skip_text_pages: bool = True,
    progress: Progress = None,
) -> int:
    """Rend les scans cherchables : texte invisible placé sur chaque mot reconnu.

    L'OCR porte sur le rendu de la page AFFICHÉE (pdfocr_tobytes), puis chaque
    mot est reporté dans le repère non tourné. Retourne le nombre de pages traitées.
    """
    dossier = find_tessdata(tessdata)
    if dossier is None:
        raise PdfStudioError("Fichiers de langue Tesseract introuvables (.traineddata).")
    pages = list(pages)
    traitees = 0
    for k, idx in enumerate(pages):
        page = doc[idx]
        if skip_text_pages and has_text(page):
            if progress:
                progress(k + 1, len(pages))
            continue
        pix = page.get_pixmap(dpi=dpi)
        pdf_ocr = fitz.open("pdf", pix.pdfocr_tobytes(language=language, tessdata=dossier))
        mots = pdf_ocr[0].get_text("words")
        echelle = 72.0 / dpi
        for x0, y0, x1, y1, mot, *_ in mots:
            # Coordonnées pixel -> points, dans le repère affiché (celui de l'OCR).
            rect_affiche = fitz.Rect(x0 * echelle, y0 * echelle, x1 * echelle, y1 * echelle)
            hauteur = max(rect_affiche.height, 1.0)
            taille = hauteur * 0.9
            largeur_texte = fitz.get_text_length(mot, fontname="helv", fontsize=taille)
            etirement = rect_affiche.width / largeur_texte if largeur_texte > 0 else 1.0
            origine_affichee = fitz.Point(rect_affiche.x0, rect_affiche.y1 - hauteur * 0.2)
            # Insertion dans le repère non tourné ; l'étirement pivote sur le même point.
            origine = origine_affichee * page.derotation_matrix
            page.insert_text(
                origine,
                mot,
                fontname="helv",
                fontsize=taille,
                render_mode=3,
                morph=(origine, fitz.Matrix(etirement, 0, 0, 1, 0, 0)),
                rotate=page.rotation,
            )
        pdf_ocr.close()
        traitees += 1
        if progress:
            progress(k + 1, len(pages))
    return traitees
