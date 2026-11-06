# SPDX-License-Identifier: AGPL-3.0-or-later
"""OCR : rendre un PDF scanné cherchable (texte invisible sous l'image)."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

import pdf_core as core
from pages.base import PageFonction


class PageOcr(PageFonction):
    nom = "OCR (scans)"
    libelle = "Reconnaître le texte"
    groupe = "Outils"
    icone = "ocr"
    description = "Rendre un PDF scanné cherchable et copiable."

    def construire(self):
        config = self.app.config_data
        self.section("Langues")
        langues = ["fra", "eng", "deu", "spa", "ita"]
        self.langue_ocr = ctk.StringVar(value=config.get("langue_ocr", "fra"))
        self.langue2_ocr = ctk.StringVar(value=config.get("langue2_ocr", "aucune"))
        for libelle, var, valeurs in [("Langue", self.langue_ocr, langues),
                                      ("2ᵉ langue", self.langue2_ocr, ["aucune"] + langues)]:
            ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
            ligne.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(ligne, text=libelle, width=130, anchor="w").pack(side="left")
            ctk.CTkOptionMenu(ligne, values=valeurs, variable=var).pack(side="left", fill="x", expand=True)
        self.section("Options")
        self.dpi_ocr = ctk.StringVar(value="300")
        ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text="Résolution (dpi)", width=130, anchor="w").pack(side="left")
        ctk.CTkSegmentedButton(ligne, values=["200", "300", "400"], variable=self.dpi_ocr).pack(
            side="left", fill="x", expand=True)
        self.entree_pages_ocr = self.champ("Pages", "")
        self.entree_pages_ocr.configure(placeholder_text="vide = toutes")
        self.ignorer_texte = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.cadre, text="Ignorer les pages qui ont déjà du texte",
                        variable=self.ignorer_texte).pack(anchor="w", padx=12, pady=(8, 2))
        self.encadrer_mots = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.cadre, text="Encadrer les mots reconnus dans l'aperçu", variable=self.encadrer_mots,
                        command=self.apercu.redessiner).pack(anchor="w", padx=12, pady=2)
        self.section("Fichiers de langue")
        self.entree_tessdata = self.champ("Dossier tessdata", config.get("tessdata", ""))
        self.entree_tessdata.configure(placeholder_text="automatique")
        self.continuer_ocr = self.case_continuer()
        self.bouton_action("Lancer l'OCR…", self.lancer_ocr)

    def dessiner(self, apercu):
        if self.encadrer_mots.get():
            for rect in core.word_rects(apercu.page):
                apercu.canevas.create_rectangle(*apercu.rect_canevas(rect), outline="#2F9E44",
                                                tags="superposition")

    def lancer_ocr(self):
        if not self.app.exiger_pdf():
            return
        langue = self.langue_ocr.get()
        if self.langue2_ocr.get() not in ("aucune", langue):
            langue += "+" + self.langue2_ocr.get()
        dpi = int(self.dpi_ocr.get())
        plage = self.entree_pages_ocr.get().strip()
        tessdata = self.entree_tessdata.get().strip() or None
        ignorer = self.ignorer_texte.get()
        # Préférences mémorisées pour les prochaines fois.
        self.app.config_data.update(langue_ocr=self.langue_ocr.get(), langue2_ocr=self.langue2_ocr.get(),
                                    tessdata=tessdata or "")
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
        self.app.apres_sauvegarde(sortie, self.continuer_ocr, f"OCR terminé sur {n} page(s).")
