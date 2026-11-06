# SPDX-License-Identifier: AGPL-3.0-or-later
"""OCR : rendre un PDF scanné cherchable (texte invisible sous l'image)."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

import pdf_core as core
import theme
from pages.base import PageFonction

# Langues proposées (nom affiché -> code Tesseract) et précision (-> résolution en dpi).
LANGUES = {"Français": "fra", "Anglais": "eng", "Allemand": "deu", "Espagnol": "spa", "Italien": "ita"}
AUCUNE = "Aucune"
QUALITES = {"Rapide": 200, "Standard": 300, "Fine": 400}


class PageOcr(PageFonction):
    nom = "OCR (scans)"
    libelle = "Reconnaître le texte"
    groupe = "Outils"
    icone = "ocr"
    description = "Rendre un PDF scanné cherchable et copiable."

    def construire(self):
        config = self.app.config_data
        nom_de = {code: nom for nom, code in LANGUES.items()}
        self.section("Langue du document")
        self.langue = ctk.StringVar(value=nom_de.get(config.get("langue_ocr", "fra"), "Français"))
        self.langue2 = ctk.StringVar(value=nom_de.get(config.get("langue2_ocr"), AUCUNE))
        self._menu("Langue", list(LANGUES), self.langue)
        self._menu("2ᵉ langue", [AUCUNE] + list(LANGUES), self.langue2)
        self.section("Reconnaissance")
        self.qualite = ctk.StringVar(value="Standard")
        self.segments("Précision", list(QUALITES), self.qualite)
        self.aide("« Fine » reconnaît mieux les petits caractères, mais prend plus de temps.")
        self.encadrer_mots = ctk.BooleanVar(value=False)
        self.case(self.cadre, "Montrer les mots reconnus", self.encadrer_mots, commande=self.apercu.redessiner)

        avance = self.options_avancees()
        self.entree_pages_ocr = self.champ("Pages", "", parent=avance)
        self.entree_pages_ocr.configure(placeholder_text="Toutes")
        self.ignorer_texte = ctk.BooleanVar(value=True)
        self.case(avance, "Ignorer les pages qui ont déjà du texte", self.ignorer_texte)
        self.aide("Dossier des fichiers de langue Tesseract (.traineddata), si Pagilis ne les trouve pas.",
                  parent=avance)
        self.entree_tessdata = self.champ("Dossier", config.get("tessdata", ""), parent=avance)
        self.entree_tessdata.configure(placeholder_text="Automatique")
        self.bouton_action("Reconnaître le texte", self.lancer_ocr, icone_nom="ocr")

    def _menu(self, libelle: str, valeurs: list[str], variable):
        ligne = self.ligne()
        ctk.CTkLabel(ligne, text=libelle, width=96, anchor="w", font=theme.police(13),
                     text_color=theme.TEXTE_2).pack(side="left")
        ctk.CTkOptionMenu(ligne, values=valeurs, variable=variable, height=32, corner_radius=6,
                          font=theme.police(13), dropdown_font=theme.police(13), fg_color=theme.SURFACE_2,
                          button_color=theme.SURFACE_3, button_hover_color=theme.BORDURE, text_color=theme.TEXTE,
                          dropdown_fg_color=theme.SURFACE_2, dropdown_hover_color=theme.ACCENT_DOUX,
                          dropdown_text_color=theme.TEXTE).pack(side="left", fill="x", expand=True)

    def dessiner(self, apercu):
        if self.encadrer_mots.get():
            for rect in core.word_rects(apercu.page):
                apercu.canevas.create_rectangle(*apercu.rect_canevas(rect), outline=theme.SUCCES,
                                                tags="superposition")

    def lancer_ocr(self):
        if not self.app.exiger_pdf():
            return
        code = LANGUES.get(self.langue.get(), "fra")
        code2 = LANGUES.get(self.langue2.get())
        langue = code + (f"+{code2}" if code2 and code2 != code else "")
        dpi = QUALITES[self.qualite.get()]
        plage = self.entree_pages_ocr.get().strip()
        tessdata = self.entree_tessdata.get().strip() or None
        ignorer = self.ignorer_texte.get()
        # Préférences mémorisées pour les prochaines fois.
        self.app.config_data.update(langue_ocr=code, langue2_ocr=code2 or "aucune", tessdata=tessdata or "")
        if core.find_tessdata(tessdata) is None:
            return messagebox.showwarning("Pagilis", "Fichiers de langue Tesseract (.traineddata) introuvables.\n"
                                                        "Indiquez le dossier « tessdata » qui les contient.")
        source = self.app.chemin_pdf
        sortie = self.app.enregistrer_sous("ocr")
        if not sortie:
            return

        def travail(p):
            doc = core.open_pdf(source)
            try:
                pages = core.parse_page_ranges(plage, doc.page_count) if plage else list(range(doc.page_count))
                n = core.ocr_pages(doc, pages, langue, dpi, tessdata, ignorer, p)
                core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.app.statut("OCR en cours (peut être long)…")
        self.app.lancer(travail, fin=lambda n: self._fin_ocr(n, sortie))

    def _fin_ocr(self, n: int, sortie: str):
        if n == 0:
            self.app.statut("Aucune page traitée.")
            return messagebox.showinfo("Pagilis", "Aucune page à traiter : toutes contiennent déjà du texte.\n"
                                                     "Décochez « Ignorer les pages qui ont déjà du texte » pour forcer.")
        self.encadrer_mots.set(True)
        self.app.apres_sauvegarde(sortie, f"Texte reconnu sur {n} page(s).")
