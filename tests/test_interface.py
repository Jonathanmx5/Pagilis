# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de l'interface : la vraie fenêtre Pagilis, pilotée par programme.

Chaque test est un scénario (générateur) exécuté DANS mainloop() : les
traitements en arrière-plan rendent la main à l'interface par after(), qui
exige une vraie boucle Tk. Un scénario rend :
- un nombre : attendre ce nombre de millisecondes ;
- "travaux" : attendre la fin des traitements en cours.
Les boîtes de dialogue (fichiers, messages, mot de passe) sont remplacées par
des réponses préparées, enregistrées pour être vérifiées.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pymupdf as fitz  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import installation  # noqa: E402
import pdf_core as core  # noqa: E402
import updater  # noqa: E402

TRAVAUX = "travaux"


# ----------------------------------------------------------------- harnais


class Dialogues:
    """Réponses préparées aux boîtes de dialogue, et trace de ce qui a été affiché."""

    def __init__(self):
        self.messages = []        # (type, titre, texte)
        self.mot_de_passe = None  # réponse (ou liste de réponses successives) au mot de passe
        self.demandes_mdp = 0
        self.enregistrer_sous = None
        self.dossier = None
        self.oui_non = False
        self.oui_non_annuler = None  # réponse à « Enregistrer les modifications ? »
        self.demandes_enregistrer = []  # options passées au dialogue « Enregistrer sous »


@pytest.fixture
def ui(monkeypatch, tmp_path):
    """Crée l'application avec des dialogues simulés ; fournit (créer_app, dialogues)."""
    import pagilis as s
    d = Dialogues()
    monkeypatch.setattr(s, "sauver_config", lambda c: None)
    monkeypatch.setattr(s, "charger_config", lambda: {})
    monkeypatch.setattr(updater, "UPDATE_MANIFEST_URL", "")
    for nom in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(s.messagebox, nom, lambda titre, texte, _n=nom, **k: d.messages.append((_n, titre, texte)))
    monkeypatch.setattr(s.messagebox, "askyesno", lambda *a, **k: d.oui_non)

    def mot_de_passe(*a, **k):
        d.demandes_mdp += 1
        if isinstance(d.mot_de_passe, list):
            return d.mot_de_passe.pop(0)
        return d.mot_de_passe
    monkeypatch.setattr(s.simpledialog, "askstring", mot_de_passe)
    monkeypatch.setattr(s.messagebox, "askyesnocancel", lambda *a, **k: d.oui_non_annuler)

    def enregistrer_sous(**k):
        d.demandes_enregistrer.append(k)
        return d.enregistrer_sous
    monkeypatch.setattr(s.filedialog, "asksaveasfilename", enregistrer_sous)
    monkeypatch.setattr(s.filedialog, "askdirectory", lambda **k: d.dossier)
    applis = []

    def creer():
        app = s.Pagilis()
        app.geometry("1280x780+0+0")
        applis.append(app)
        return app

    yield s, creer, d
    for app in applis:
        try:
            app.destroy()
        except Exception:  # noqa: BLE001 - déjà détruite par le scénario
            pass
    applis.clear()


def executer(app, scenario, delai_max=90):
    """Joue le scénario dans mainloop() ; relève dans le test toute erreur du scénario."""
    erreurs = []
    etapes = scenario()

    def avancer(attente=None):
        try:
            if attente == TRAVAUX and app.travaux_en_cours:
                app.after(50, lambda: avancer(TRAVAUX))
                return
            suite = next(etapes)
            if suite == TRAVAUX:
                app.after(50, lambda: avancer(TRAVAUX))
            else:
                app.after(suite or 1, avancer)
        except StopIteration:
            app.quit()
        except BaseException as exc:  # noqa: BLE001 - relevée après la boucle
            erreurs.append(exc)
            app.quit()

    def trop_long():
        erreurs.append(TimeoutError("scénario trop long"))
        app.quit()

    app.after(200, avancer)
    garde = app.after(delai_max * 1000, trop_long)
    app.mainloop()
    app.after_cancel(garde)
    if erreurs:
        raise erreurs[0]


# ----------------------------------------------------------- PDF d'essai


@pytest.fixture
def contrat(tmp_path):
    """Contrat de 2 pages ; la page 2 est tournée à 90° (texte droit à l'affichage)."""
    chemin = tmp_path / "contrat.pdf"
    doc = fitz.open()
    for rot in (0, 90):
        page = doc.new_page(width=595, height=842)
        page.set_rotation(rot)
        m = page.derotation_matrix
        page.insert_text(fitz.Point(60, 90) * m, "Contrat de prestation", fontsize=22, rotate=rot)
        for i, ligne in enumerate(["Le client accepte le devis.", "Montant total : 1 200 euros.",
                                   "Le client signe ci-dessous."]):
            page.insert_text(fitz.Point(60, 140 + 18 * i) * m, ligne, fontsize=12, rotate=rot)
    doc.save(chemin)
    return chemin


@pytest.fixture
def signature(tmp_path):
    chemin = tmp_path / "signature.png"
    img = Image.new("RGB", (400, 160), "white")
    ImageDraw.Draw(img).line([(20, 120), (200, 30), (380, 110)], fill=(20, 40, 160), width=10)
    img.save(chemin)
    return chemin


def superpositions(app):
    return app.apercu.canevas.find_withtag("superposition")


# ------------------------------------------------------------------ tests


def test_encrypted_pdf_asks_password_then_opens(ui, contrat, tmp_path):
    s, creer, d = ui
    protege = tmp_path / "protege.pdf"
    fitz.open(contrat).save(protege, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    app = creer()

    def scenario():
        d.mot_de_passe = ["faux", "secret"]
        app.charger_fichier(str(protege))
        yield 300
        assert d.demandes_mdp == 2, "un mot de passe faux doit être redemandé"
        assert app.apercu.doc is not None and app.apercu.doc.page_count == 2

    executer(app, scenario)


def test_cancelled_password_leaves_no_document(ui, contrat, tmp_path):
    s, creer, d = ui
    protege = tmp_path / "protege.pdf"
    fitz.open(contrat).save(protege, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="x")
    app = creer()

    def scenario():
        d.mot_de_passe = None  # l'utilisateur annule
        app.charger_fichier(str(protege))
        yield 200
        assert app.apercu.doc is None and app.chemin_pdf is None
        assert "annulée" in app.etat.cget("text")

    executer(app, scenario)


def test_search_highlights_occurrences_and_lists_pages(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        app.charger_fichier(str(contrat))
        app.afficher_page("Modifier")
        m = app.fonctions["Modifier"]
        m.entree_recherche.insert(0, "client")
        m.rechercher()
        yield 300
        assert sorted(m.resultats_recherche) == [0, 1]
        assert len(superpositions(app)) == 2, "les 2 occurrences de la page 1 doivent être surlignées"
        app.apercu.aller(1)  # page tournée : surlignage aussi
        yield 300
        assert len(superpositions(app)) == 2

    executer(app, scenario)


def test_search_on_scan_suggests_ocr(ui, tmp_path):
    s, creer, d = ui
    scan = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()  # aucune couche texte
    doc.save(scan)
    app = creer()

    def scenario():
        app.charger_fichier(str(scan))
        app.afficher_page("Modifier")
        m = app.fonctions["Modifier"]
        m.entree_recherche.insert(0, "contrat")
        m.rechercher()
        yield 100
        textes = [w.cget("text") for w in m.cadre_resultats.winfo_children()]
        assert any("Reconnaître le texte" in t for t in textes)

    executer(app, scenario)


def test_replace_all_from_modifier_is_undoable(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        app.charger_fichier(str(contrat))
        app.afficher_page("Modifier")
        m = app.fonctions["Modifier"]
        m.entree_recherche.insert(0, "client")
        m.entree_remplacement.insert(0, "acheteur")
        m.remplacer_tout()
        yield 100
        texte = " ".join(app.edition.doc[0].get_text().split())
        assert "acheteur accepte" in texte and "client" not in texte
        assert app.edition.modifie and "4 remplacement(s)" in app.etat.cget("text")
        m.annuler_retouche()
        assert "client accepte" in " ".join(app.edition.doc[0].get_text().split())

    executer(app, scenario)


def test_stamp_click_drag_then_applied_on_displayed_page(ui, contrat, signature, tmp_path):
    s, creer, d = ui
    app = creer()
    sortie = tmp_path / "signe.pdf"

    def scenario():
        app.charger_fichier(str(contrat))
        app.afficher_page("Signature / Tampon")
        app.fonctions["Signature / Tampon"].image_tampon = str(signature)
        app.fonctions["Signature / Tampon"].ratio_tampon = 160 / 400
        app.apercu.aller(1)
        yield 300
        app._souris_appui(fitz.Point(300, 200))  # clic : l'image est centrée sur le clic
        app._souris_glisse(fitz.Point(330, 250))  # glisser
        app._souris_relache(fitz.Point(330, 250))
        rect = app.fonctions["Signature / Tampon"]._rect_tampon()
        assert abs(rect.x0 + rect.width / 2 - 330) < 1 and abs(rect.y0 + rect.height / 2 - 250) < 1
        assert len(superpositions(app)) >= 2  # image + cadre en surimpression
        d.enregistrer_sous = str(sortie)
        app.fonctions["Signature / Tampon"].lancer_tampon()
        yield TRAVAUX
        resultat = fitz.open(sortie)
        assert not resultat[0].get_images() and resultat[1].get_images(), "tampon sur la page affichée (2)"
        pose = core.to_displayed(resultat[1], resultat[1].get_image_rects(resultat[1].get_images()[0][0])[0])
        assert abs(pose.x0 - rect.x0) < 1 and abs(pose.y0 - rect.y0) < 1

    executer(app, scenario)


def test_merge_reorders_selected_file(ui, tmp_path):
    s, creer, d = ui
    fichiers = []
    for nom, pages in (("a", 1), ("b", 2), ("c", 3)):
        doc = fitz.open()
        for _ in range(pages):
            doc.new_page()
        doc.save(tmp_path / f"{nom}.pdf")
        fichiers.append(str(tmp_path / f"{nom}.pdf"))
    app = creer()
    sortie = tmp_path / "fusion.pdf"

    def scenario():
        app.afficher_page("Fusion")
        app.fonctions["Fusion"].liste_fusion = list(fichiers)
        app.fonctions["Fusion"]._choisir_fusion(2)
        app.fonctions["Fusion"].deplacer_fusion(-1)  # c remonte avant b
        app.fonctions["Fusion"].deplacer_fusion(-1)  # puis avant a
        app.fonctions["Fusion"]._choisir_fusion(2)
        app.fonctions["Fusion"].retirer_fusion()     # b retiré
        assert [os.path.basename(f) for f in app.fonctions["Fusion"].liste_fusion] == ["c.pdf", "a.pdf"]
        d.enregistrer_sous = str(sortie)
        app.fonctions["Fusion"].lancer_fusion()
        yield TRAVAUX
        resultat = fitz.open(sortie)
        assert resultat.page_count == 4
        assert [t[1] for t in resultat.get_toc()] == ["c.pdf", "a.pdf"]

    executer(app, scenario)


def test_business_error_is_shown_not_crashing(ui, contrat, tmp_path):
    """Régression : le message d'erreur plantait (variable `exc` lue après le except)."""
    s, creer, d = ui
    app = creer()

    def scenario():
        app.charger_fichier(str(contrat))
        app.afficher_page("Division")
        app.fonctions["Division"].mode_division.set("plages")
        app.fonctions["Division"].entree_plages.insert(0, "1-9")
        d.dossier = str(tmp_path)
        app.fonctions["Division"].lancer_division()
        yield TRAVAUX
        yield 100
        assert ("showwarning", "Pagilis PDF", "« 1-9 » sort du document (1 à 2 pages).") in d.messages

    executer(app, scenario)


def test_ocr_from_interface_frames_words(ui, tmp_path):
    if core.find_tessdata() is None:
        pytest.skip("tessdata absent")
    s, creer, d = ui
    texte = fitz.open()
    texte.new_page(width=400, height=300).insert_text((40, 80), "Bonjour le monde", fontsize=24)
    scan = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=300).insert_image(fitz.Rect(0, 0, 400, 300), pixmap=texte[0].get_pixmap(dpi=200))
    doc.save(scan)
    app = creer()
    sortie = tmp_path / "scan_ocr.pdf"

    def scenario():
        app.charger_fichier(str(scan))
        app.afficher_page("OCR (scans)")
        d.enregistrer_sous = str(sortie)
        app.fonctions["OCR (scans)"].lancer_ocr()
        yield TRAVAUX
        assert set(app.actions_notification) == {"Ouvrir", "Continuer dessus"}
        app.action_notification("Continuer dessus")
        yield 300
        assert fitz.open(sortie)[0].search_for("Bonjour")
        assert app.chemin_pdf == str(sortie), "continuer sur le fichier résultat"
        assert len(superpositions(app)) >= 3, "mots reconnus encadrés"

    executer(app, scenario)


@pytest.mark.parametrize("portable, installe, attendu", [
    (True, False, "Installer sur ce PC"),
    (True, True, "Réinstaller sur ce PC"),
    (False, False, None),  # lancé depuis les sources, ou version installée
])
def test_install_button_only_in_portable_mode(ui, monkeypatch, portable, installe, attendu):
    s, creer, d = ui
    monkeypatch.setattr(installation, "exe_courant", lambda: "Pagilis.exe" if portable else None)
    monkeypatch.setattr(installation, "tourne_depuis_installation", lambda *a: False)
    monkeypatch.setattr(installation, "est_installe", lambda *a: installe)
    app = creer()

    def scenario():
        yield 100
        def boutons(widget):
            for enfant in widget.winfo_children():
                if isinstance(enfant, s.ctk.CTkButton):
                    yield enfant
                yield from boutons(enfant)
        textes = [w.cget("text") for w in boutons(app)]
        trouves = [t for t in textes if "nstaller sur ce PC" in t]
        if attendu is None:
            assert not trouves
        else:
            assert trouves and attendu in trouves[0]

    executer(app, scenario)


def test_update_popup_offers_and_can_skip_version(ui, monkeypatch):
    s, creer, d = ui
    enregistre = {}
    monkeypatch.setattr(s, "sauver_config", lambda c: enregistre.update(c))
    app = creer()

    def scenario():
        app._popup_mise_a_jour(updater.Update("9.9.9", "https://exemple/Pagilis.exe", None, "Nouveautés"))
        yield 300
        popup = [w for w in app.winfo_children() if isinstance(w, s.ctk.CTkToplevel)][-1]
        cases = [w for w in popup.winfo_children() if isinstance(w, s.ctk.CTkCheckBox)]
        cases[0].select()
        [w for w in popup.winfo_children() if isinstance(w, s.ctk.CTkButton) and w.cget("text") == "Plus tard"][0].invoke()
        yield 100
        assert enregistre.get("version_ignoree") == "9.9.9"
        assert not popup.winfo_exists()

    executer(app, scenario)


# ------------------------------------------------------- page « Modifier »


def test_modifier_is_first_function(ui):
    s, creer, d = ui
    app = creer()
    assert list(app.boutons_nav)[0] == "Modifier"
    textes = []

    def parcourir(w):
        for enfant in w.winfo_children():
            if hasattr(enfant, "cget"):
                try:
                    textes.append(enfant.cget("text"))
                except Exception:  # noqa: BLE001 - widget sans texte
                    pass
            parcourir(enfant)
    parcourir(app.pages["Modifier"])
    assert any("Cliquez sur une ligne pour la corriger" in t and "glisser un bloc" in t for t in textes)


def test_open_pdf_creates_working_copy(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        app.afficher_page("Modifier")
        app.ouvrir_document(str(contrat))
        yield 100
        assert app.edition.source == str(contrat) and not app.edition.origine_word
        assert app.apercu.doc is app.edition.doc

    executer(app, scenario)


def test_open_word_converts_then_loads(ui, contrat, tmp_path, monkeypatch):
    import shutil
    s, creer, d = ui
    app = creer()
    source = tmp_path / "lettre.docx"
    source.write_bytes(b"faux word")

    def convertir(chemin, dossier, delai=120):
        sortie = os.path.join(dossier, "lettre.pdf")
        shutil.copy(contrat, sortie)
        return sortie

    monkeypatch.setattr(s.conversion, "word_vers_pdf", convertir)

    def scenario():
        app.afficher_page("Modifier")
        app.ouvrir_document(str(source))
        yield TRAVAUX
        assert app.edition.origine_word and app.edition.source == str(source)
        assert app.apercu.doc is app.edition.doc and app.apercu.doc.page_count == 2

    executer(app, scenario)


def test_word_conversion_error_is_shown(ui, tmp_path, monkeypatch):
    s, creer, d = ui
    app = creer()
    message = "Pour ouvrir un fichier Word, Microsoft Word ou LibreOffice doit être installé."

    def echec(*a, **k):
        raise core.PagilisError(message)

    monkeypatch.setattr(s.conversion, "word_vers_pdf", echec)

    def scenario():
        app.ouvrir_document(str(tmp_path / "a.docx"))
        yield TRAVAUX
        assert app.edition is None
        assert ("showwarning", "Pagilis PDF", message) in d.messages

    executer(app, scenario)


def ouvrir_modifier(app, chemin, page=1):
    app.afficher_page("Modifier")
    app.ouvrir_document(str(chemin))
    app.apercu.aller(page)


def centre_mot(page, mot):
    r = [core.to_displayed(page, w[:4]) for w in page.get_text("words") if w[4] == mot][0]
    return fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


def cliquer(app, point):
    app._souris_appui(point)
    app._souris_relache(point)


def test_click_line_opens_entry_with_its_text(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        cliquer(app, centre_mot(app.apercu.page, "Montant"))
        yield 50
        assert app.fonctions["Modifier"].saisie is not None and app.fonctions["Modifier"].saisie.winfo_ismapped()
        assert app.fonctions["Modifier"].saisie.get() == "Montant total : 1 200 euros."

    executer(app, scenario)


def test_enter_applies_correction(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        cliquer(app, centre_mot(app.apercu.page, "Montant"))
        yield 50
        app.fonctions["Modifier"].saisie.delete(0, "end")
        app.fonctions["Modifier"].saisie.insert(0, "Montant total : 950 euros.")
        app.fonctions["Modifier"].saisie._entry.focus_force()
        yield 50
        app.fonctions["Modifier"].saisie._entry.event_generate("<Return>", when="tail")
        yield 300
        assert app.fonctions["Modifier"].saisie is None and app.edition.modifie
        assert app.apercu.index == 1
        assert "Montant total : 950 euros." in " ".join(app.apercu.page.get_text().split())

    executer(app, scenario)


def test_escape_cancels(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        cliquer(app, centre_mot(app.apercu.page, "Montant"))
        yield 50
        app.fonctions["Modifier"].saisie.insert(0, "xxx")
        app.fonctions["Modifier"].saisie._entry.event_generate("<Escape>")
        yield 50
        assert app.fonctions["Modifier"].saisie is None and not app.edition.modifie

    executer(app, scenario)


@pytest.mark.parametrize("action", ["zoom", "page", "travail"])
def test_entry_closes_on_zoom_page_change_or_job(ui, contrat, action):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        cliquer(app, centre_mot(app.apercu.page, "Montant"))
        yield 50
        app.fonctions["Modifier"].saisie.insert(0, "xxx")
        if action == "zoom":
            app.apercu.zoomer(1.25)
            yield 300
        elif action == "page":
            app.apercu.aller(0)
            yield 50
        else:
            app.lancer(lambda p: None)
            yield TRAVAUX
        assert app.fonctions["Modifier"].saisie is None and not app.edition.modifie

    executer(app, scenario)


def test_drag_moves_block_with_ghost(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        avant = centre_mot(app.apercu.page, "signe")
        app._souris_appui(avant)
        app._souris_glisse(avant + (0, 100))
        assert superpositions(app)  # fantôme du bloc
        app._souris_relache(avant + (0, 100))
        yield 300
        assert app.fonctions["Modifier"].saisie is None and app.edition.modifie
        apres = centre_mot(app.apercu.page, "signe")
        assert abs(apres.y - (avant.y + 100)) < 3

    executer(app, scenario)


def test_small_jitter_is_a_click(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        point = centre_mot(app.apercu.page, "Montant")
        app._souris_appui(point)
        app._souris_glisse(point + (1, 0))
        app._souris_relache(point + (1, 0))
        yield 50
        assert app.fonctions["Modifier"].saisie is not None and not app.edition.modifie

    executer(app, scenario)


def test_click_on_scan_suggests_ocr(ui, tmp_path):
    s, creer, d = ui
    app = creer()
    scan = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(scan)

    def scenario():
        ouvrir_modifier(app, scan, page=0)
        yield 300
        cliquer(app, fitz.Point(200, 200))
        assert app.fonctions["Modifier"].saisie is None
        assert app.etat.cget("text") == "Aucun texte ici. Page scannée ? Utilisez l'OCR d'abord."

    executer(app, scenario)


def corriger_montant(app, texte="Montant total : 950 euros."):
    cliquer(app, centre_mot(app.apercu.page, "Montant"))
    app.fonctions["Modifier"].saisie.delete(0, "end")
    app.fonctions["Modifier"].saisie.insert(0, texte)
    app.fonctions["Modifier"]._valider_saisie()


def texte_de(chemin, page=1):
    return " ".join(fitz.open(chemin)[page].get_text().split())


def test_ctrl_z_undoes_and_disables_button(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        assert app.bouton_annuler.cget("state") == "normal"
        app.fonctions["Modifier"].annuler_retouche()
        yield 100
        assert "1 200 euros" in " ".join(app.apercu.page.get_text().split())
        assert app.bouton_annuler.cget("state") == "disabled"

    executer(app, scenario)


def test_ctrl_s_saves_proposed_name(ui, contrat, tmp_path):
    s, creer, d = ui
    app = creer()
    sortie = tmp_path / "out.pdf"

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.enregistrer_sous = str(sortie)
        app.fonctions["Modifier"].enregistrer_edition()
        yield TRAVAUX
        assert "950 euros" in texte_de(sortie)
        assert not app.edition.modifie and "•" not in app.title()
        options = d.demandes_enregistrer[-1]
        assert options["initialfile"] == "contrat_modifie.pdf"
        assert os.path.normcase(options["initialdir"]) == os.path.normcase(str(contrat.parent))

    executer(app, scenario)


def test_word_save_proposes_pdf_next_to_document(ui, contrat, tmp_path, monkeypatch):
    import shutil
    s, creer, d = ui
    app = creer()
    source = tmp_path / "lettre.docx"
    source.write_bytes(b"faux word")

    def convertir(chemin, dossier, delai=120):
        sortie = os.path.join(dossier, "lettre.pdf")
        shutil.copy(contrat, sortie)
        return sortie

    monkeypatch.setattr(s.conversion, "word_vers_pdf", convertir)

    def scenario():
        app.afficher_page("Modifier")
        app.ouvrir_document(str(source))
        yield TRAVAUX
        app.apercu.aller(1)
        yield 300
        corriger_montant(app)
        d.enregistrer_sous = None  # l'utilisateur annule
        app.fonctions["Modifier"].enregistrer_edition()
        options = d.demandes_enregistrer[-1]
        assert options["initialfile"] == "lettre.pdf"
        assert os.path.normcase(options["initialdir"]) == os.path.normcase(str(tmp_path))
        assert app.edition.modifie

    executer(app, scenario)


def test_title_marks_unsaved_changes(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        assert "•" not in app.title()
        corriger_montant(app)
        assert "•" in app.title()

    executer(app, scenario)


def test_close_with_changes_cancel_keeps_window(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.oui_non_annuler = None
        app._fermer()
        yield 50
        assert app.winfo_exists() and app.edition.modifie

    executer(app, scenario)


def test_close_with_changes_no_discards(ui, contrat, tmp_path):
    s, creer, d = ui
    app = creer()
    fermee = []

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.oui_non_annuler = False
        app.after(10, lambda: (fermee.append(True), app.quit()))  # quitte la boucle si destroy réussit
        app._fermer()

    try:
        executer(app, scenario)
    except Exception:  # noqa: BLE001 - la fenêtre détruite interrompt le scénario
        pass
    assert "1 200 euros" in texte_de(contrat)  # rien d'écrit
    assert d.demandes_enregistrer == []


def test_close_with_changes_yes_saves_first(ui, contrat, tmp_path):
    s, creer, d = ui
    app = creer()
    sortie = tmp_path / "avant_fermeture.pdf"

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.oui_non_annuler = True
        d.enregistrer_sous = str(sortie)
        app._fermer()

    try:
        executer(app, scenario)
    except Exception:  # noqa: BLE001 - la fenêtre détruite interrompt le scénario
        pass
    assert "950 euros" in texte_de(sortie)


def test_leave_page_or_open_other_file_asks(ui, contrat, tmp_path):
    s, creer, d = ui
    app = creer()
    autre = tmp_path / "autre.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Autre document")
    doc.save(autre)

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.oui_non_annuler = None
        app.afficher_page("Fusion")
        assert app.page_active == "Modifier"
        app.ouvrir_document(str(autre))
        yield 100
        assert app.edition.source == str(contrat) and app.edition.modifie
        d.oui_non_annuler = False  # « Non » : on quitte sans enregistrer, retouches abandonnées
        app.afficher_page("Fusion")
        assert app.page_active == "Fusion"
        assert not app.edition.modifie
        assert "1 200 euros" in " ".join(app.edition.doc[1].get_text().split())

    executer(app, scenario)


def test_navigation_refused_while_a_job_runs(ui, contrat):
    import threading
    s, creer, d = ui
    app = creer()
    feu = threading.Event()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        app.lancer(lambda p: feu.wait(10))
        app.afficher_page("Fusion")
        app.ouvrir_document(str(contrat))
        app._fermer()
        assert app.page_active == "Modifier" and app.winfo_exists()
        assert app.etat.cget("text") == "Traitement en cours, patientez…"
        assert d.demandes_enregistrer == []  # aucune question pendant le traitement
        feu.set()
        yield TRAVAUX

    executer(app, scenario)


def test_other_pages_use_the_saved_file(ui, contrat, tmp_path):
    s, creer, d = ui
    app = creer()
    sortie = tmp_path / "corrige.pdf"

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.enregistrer_sous = str(sortie)
        app.fonctions["Modifier"].enregistrer_edition()
        yield TRAVAUX
        assert app.chemin_pdf == str(sortie)
        assert app.label_fichier.cget("text") == "corrige.pdf"
        corriger_montant(app, "Montant total : 10 euros.")
        d.oui_non_annuler = True
        d.enregistrer_sous = str(tmp_path / "corrige2.pdf")
        app.afficher_page("Fusion")
        assert app.chemin_pdf == str(tmp_path / "corrige2.pdf")

    executer(app, scenario)


@pytest.mark.parametrize("niveau, attendu", [
    ("origine", "Ligne corrigée, police d'origine conservée."),
    ("installee", "Ligne corrigée avec la police d'origine, installée sur ce PC."),
    ("remplacement", "Ligne corrigée. Police d'origine indisponible pour ces caractères : "
                     "réécrite en Arial, Times ou Courier."),
])
def test_status_tells_which_font_was_used(ui, contrat, monkeypatch, niveau, attendu):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        cliquer(app, centre_mot(app.apercu.page, "Montant"))
        monkeypatch.setattr(app.edition, "corriger", lambda *a: niveau)
        app.fonctions["Modifier"]._valider_saisie()
        assert app.etat.cget("text") == attendu

    executer(app, scenario)


# --------------------------------------------------------- page « Pages »


@pytest.fixture
def cinq_pages(tmp_path):
    chemin = tmp_path / "cinq.pdf"
    doc = fitz.open()
    for i in range(5):
        doc.new_page(width=300, height=400).insert_text((50, 50), f"Page {i + 1}", fontsize=14)
    doc.save(chemin)
    return chemin


def ordre_pages(doc):
    return [p.get_text().strip() for p in doc]


def ouvrir_pages(app, chemin):
    app.ouvrir_document(str(chemin))
    app.afficher_page("Pages")
    return app.fonctions["Pages"]


def test_pages_shows_thumbnails_and_selects(ui, cinq_pages):
    s, creer, d = ui
    app = creer()

    def scenario():
        p = ouvrir_pages(app, cinq_pages)
        yield 300
        assert len(p.vignettes) == 5
        p.cliquer(2)
        assert p.selection == {2} and app.apercu.index == 2
        p.cliquer(4, ctrl=True)
        assert p.selection == {2, 4}
        p.cliquer(0, maj=True)  # comme l'Explorateur : la suite part du dernier Ctrl+clic (4)
        assert p.selection == {0, 1, 2, 3, 4}
        p.cliquer(1)
        assert p.selection == {1}

    executer(app, scenario)


def test_pages_rotate_delete_move_undo_and_save(ui, cinq_pages, tmp_path):
    s, creer, d = ui
    app = creer()
    sortie = tmp_path / "range.pdf"

    def scenario():
        p = ouvrir_pages(app, cinq_pages)
        yield 300
        p.cliquer(1)
        p.tourner(90)
        assert app.edition.doc[1].rotation == 90 and "•" in app.title()
        p.cliquer(3)
        p.supprimer()
        assert ordre_pages(app.edition.doc) == ["Page 1", "Page 2", "Page 3", "Page 5"]
        assert len(p.vignettes) == 4
        p.cliquer(3)
        p.deplacer(-1)
        assert ordre_pages(app.edition.doc) == ["Page 1", "Page 2", "Page 5", "Page 3"]
        assert p.selection == {2}
        p.touche_annuler()
        assert ordre_pages(app.edition.doc) == ["Page 1", "Page 2", "Page 3", "Page 5"]
        d.enregistrer_sous = str(sortie)
        p.touche_enregistrer()
        yield TRAVAUX
        enregistre = fitz.open(sortie)
        assert ordre_pages(enregistre) == ["Page 1", "Page 2", "Page 3", "Page 5"]
        assert enregistre[1].rotation == 90 and "•" not in app.title()

    executer(app, scenario)


def test_pages_insert_pdf_after_selection(ui, cinq_pages, tmp_path, monkeypatch):
    s, creer, d = ui
    app = creer()
    autre = tmp_path / "annexe.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Annexe")
    doc.save(autre)
    monkeypatch.setattr(s.filedialog, "askopenfilename", lambda **k: str(autre))

    def scenario():
        p = ouvrir_pages(app, cinq_pages)
        yield 300
        p.cliquer(0)
        p.inserer()
        assert ordre_pages(app.edition.doc)[:3] == ["Page 1", "Annexe", "Page 2"]
        assert p.selection == {1} and len(p.vignettes) == 6

    executer(app, scenario)


def test_pages_extract_selection_leaves_document(ui, cinq_pages, tmp_path):
    s, creer, d = ui
    app = creer()
    sortie = tmp_path / "extrait.pdf"

    def scenario():
        p = ouvrir_pages(app, cinq_pages)
        yield 300
        p.cliquer(4)
        p.cliquer(1, ctrl=True)
        d.enregistrer_sous = str(sortie)
        p.extraire()
        yield TRAVAUX
        assert ordre_pages(fitz.open(sortie)) == ["Page 2", "Page 5"]
        assert not app.edition.modifie and app.edition.doc.page_count == 5
        assert d.demandes_enregistrer[-1]["initialfile"] == "cinq_pages_2,5.pdf"

    executer(app, scenario)


def test_pages_refuse_deleting_every_page(ui, cinq_pages):
    s, creer, d = ui
    app = creer()

    def scenario():
        p = ouvrir_pages(app, cinq_pages)
        yield 300
        p.cliquer(0)
        p.cliquer(4, maj=True)
        p.supprimer()
        assert app.edition.doc.page_count == 5 and not app.edition.modifie
        assert any(m[0] == "showwarning" and "au moins une" in m[2] for m in d.messages)

    executer(app, scenario)


def test_switching_between_modifier_and_pages_keeps_edits(ui, contrat):
    s, creer, d = ui
    app = creer()

    def scenario():
        ouvrir_modifier(app, contrat)
        yield 300
        corriger_montant(app)
        d.oui_non_annuler = None  # une question ici bloquerait le changement de page
        app.afficher_page("Pages")
        assert app.page_active == "Pages" and app.edition.modifie
        app.afficher_page("Modifier")
        assert app.page_active == "Modifier"
        app.afficher_page("Fusion")
        assert app.page_active == "Modifier"  # vers une autre fonction : la question est posée

    executer(app, scenario)


# ------------------------------------------------------ accueil et récents


def test_welcome_screen_until_a_document_is_open(ui, contrat, tmp_path):
    s, creer, d = ui
    app = creer()
    absent = tmp_path / "parti.pdf"

    def scenario():
        yield 100
        assert app.accueil.winfo_ismapped()
        app.config_data["recents"] = [str(absent), str(contrat)]
        app.afficher_accueil()
        yield 50
        assert app.boutons_recents == [str(contrat)]  # un fichier disparu n'est pas proposé
        app.ouvrir_document(app.boutons_recents[0])
        yield 100
        assert not app.accueil.winfo_ismapped() and app.chemin_pdf == str(contrat)

    executer(app, scenario)


def test_opened_files_become_recent(ui, contrat, cinq_pages):
    s, creer, d = ui
    app = creer()

    def scenario():
        app.ouvrir_document(str(cinq_pages))
        app.ouvrir_document(str(contrat))
        app.ouvrir_document(str(cinq_pages))
        yield 50
        assert app.config_data["recents"][:2] == [str(cinq_pages), str(contrat)]

    executer(app, scenario)


def test_window_shows_display_name(ui):
    s, creer, d = ui
    app = creer()
    assert app.title() == "Pagilis PDF"
