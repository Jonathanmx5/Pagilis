# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conversion des documents Word en PDF (Word, sinon LibreOffice)."""

import os
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pymupdf as fitz  # noqa: E402

import conversion  # noqa: E402
import pdf_core as core  # noqa: E402


class Faux:
    """Remplace l'exécution des convertisseurs ; note les commandes reçues."""

    def __init__(self, code=0, stderr="", creer_pdf=True, exception=None):
        self.code, self.stderr, self.creer_pdf, self.exception = code, stderr, creer_pdf, exception
        self.commandes = []

    def __call__(self, commande, delai):
        self.commandes.append(commande)
        if self.exception:
            raise self.exception
        if self.creer_pdf:
            sortie = commande[-2] if commande[0].endswith("powershell") else os.path.join(
                commande[commande.index("--outdir") + 1],
                os.path.splitext(os.path.basename(commande[-1]))[0] + ".pdf")
            doc = fitz.open()
            doc.new_page()
            doc.save(sortie)
        return subprocess.CompletedProcess(commande, self.code, "", self.stderr)


@pytest.fixture
def faux(monkeypatch):
    def installer(word=True, libreoffice=None, **options):
        f = Faux(**options)
        monkeypatch.setattr(conversion, "word_installe", lambda: word)
        monkeypatch.setattr(conversion, "chemin_libreoffice", lambda: libreoffice)
        monkeypatch.setattr(conversion, "_executer", f)
        return f
    return installer


def test_est_word():
    for nom in ("a.docx", "B.DOC", "c.rtf", "d.odt"):
        assert conversion.est_word(nom)
    for nom in ("a.pdf", "b.txt", "docx"):
        assert not conversion.est_word(nom)


def test_uses_word_when_installed(faux, tmp_path):
    f = faux(word=True)
    source = str(tmp_path / "L'été 2026.docx")
    pdf = conversion.word_vers_pdf(source, str(tmp_path))
    assert pdf == os.path.join(str(tmp_path), "L'été 2026.pdf") and os.path.exists(pdf)
    commande = f.commandes[0]
    assert commande[0] == "powershell" and "-File" in commande
    assert commande[-3:-1] == [source, pdf]  # chemins en arguments, jamais dans le texte du script
    script = open(commande[commande.index("-File") + 1], encoding="utf-8-sig").read()
    assert "été" not in script and "ExportAsFixedFormat" in script


def test_falls_back_to_libreoffice(faux, tmp_path):
    f = faux(word=False, libreoffice="C:/LO/soffice.exe")
    source = str(tmp_path / "lettre.odt")
    pdf = conversion.word_vers_pdf(source, str(tmp_path))
    assert f.commandes[0] == ["C:/LO/soffice.exe", "--headless", "--convert-to", "pdf",
                              "--outdir", str(tmp_path), source]
    assert pdf == os.path.join(str(tmp_path), "lettre.pdf")


def test_no_converter_raises_clear_message(faux, tmp_path):
    faux(word=False, libreoffice=None)
    with pytest.raises(core.PagilisError) as exc:
        conversion.word_vers_pdf(str(tmp_path / "a.docx"), str(tmp_path))
    assert str(exc.value) == "Pour ouvrir un fichier Word, Microsoft Word ou LibreOffice doit être installé."


@pytest.mark.parametrize("options", [
    dict(code=1, creer_pdf=False),
    dict(exception=subprocess.TimeoutExpired("powershell", 120)),
    dict(code=0, creer_pdf=False),
])
def test_converter_failure_or_timeout_raises(faux, tmp_path, options):
    faux(**options)
    with pytest.raises(core.PagilisError):
        conversion.word_vers_pdf(str(tmp_path / "a.docx"), str(tmp_path))


def test_protected_word_message(faux, tmp_path):
    faux(code=2, stderr="MOT_DE_PASSE", creer_pdf=False)
    with pytest.raises(core.PagilisError) as exc:
        conversion.word_vers_pdf(str(tmp_path / "a.docx"), str(tmp_path))
    assert str(exc.value) == "Ce fichier Word est protégé : ouvrez-le dans Word pour retirer le mot de passe."


def docx_minimal(chemin, texte):
    """Plus petit .docx valide : trois parties XML dans un zip."""
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{texte}</w:t></w:r></w:p></w:body></w:document>')
    return str(chemin)


@pytest.mark.skipif(not conversion.word_installe(), reason="Microsoft Word absent")
def test_real_word_conversion(tmp_path):
    source = docx_minimal(tmp_path / "L'été 2026.docx", "Bonjour Pagilis")
    pdf = conversion.word_vers_pdf(source, str(tmp_path / "sortie"))
    assert "Bonjour Pagilis" in fitz.open(pdf)[0].get_text()


def test_timeout_kills_the_word_started_by_the_script(faux, tmp_path, monkeypatch):
    """Word lancé par COM n'est pas un enfant de powershell : il faut l'arrêter nommément."""
    tues = []
    monkeypatch.setattr(conversion, "_tuer", tues.append)
    faux(word=True, creer_pdf=False)

    def lent(commande, delai):
        with open(commande[-1], "w", encoding="ascii") as fh:  # fichier des PID écrit par le script
            fh.write("4242\n")
        raise subprocess.TimeoutExpired("powershell", delai)

    monkeypatch.setattr(conversion, "_executer", lent)
    with pytest.raises(core.PagilisError):
        conversion.word_vers_pdf(str(tmp_path / "a.docx"), str(tmp_path))
    assert tues == [4242]


def test_word_script_never_quits_a_word_already_in_use():
    assert "Documents.Count -eq 0" in conversion.SCRIPT_WORD
