# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remplacer du texte : rechercher (surligné dans l'aperçu) et remplacer."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk
import pymupdf as fitz

import pdf_core as core
from pages.base import PageFonction


class PageRemplacer(PageFonction):
    nom = "Remplacer du texte"
    icone = "⇄"
    description = "Rechercher et remplacer du texte"

    def construire(self):
        self.resultats_recherche: dict[int, list[fitz.Rect]] = {}
        self.section("Texte")
        self.entree_ancien = self.champ("Rechercher", "")
        self.entree_nouveau = self.champ("Remplacer par", "")
        self.entree_nouveau.configure(placeholder_text="vide = effacer")
        self.entree_plage_rempl = self.champ("Pages", "")
        self.entree_plage_rempl.configure(placeholder_text="vide = toutes")
        self.casse = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.cadre, text="Respecter la casse", variable=self.casse).pack(
            anchor="w", padx=12, pady=(8, 2))
        self.reduire = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.cadre, text="Réduire la taille si le texte est plus long",
                        variable=self.reduire).pack(anchor="w", padx=12, pady=2)
        ctk.CTkButton(self.cadre, text="Rechercher (aperçu)", fg_color="gray50", hover_color="gray40",
                      command=self.rechercher_texte).pack(fill="x", padx=12, pady=(10, 4))
        self.entree_ancien.bind("<Return>", lambda _e: self.rechercher_texte())
        self.cadre_resultats = ctk.CTkFrame(self.cadre, fg_color="transparent")
        self.cadre_resultats.pack(fill="x", padx=12)
        self.continuer_rempl = self.case_continuer()
        self.bouton_action("Remplacer…", self.lancer_remplacement)

    def document_charge(self):
        self.resultats_recherche = {}

    def dessiner(self, apercu):
        for rect in self.resultats_recherche.get(apercu.index, []):
            apercu.canevas.create_rectangle(*apercu.rect_canevas(rect), outline="#E0A800", width=2,
                                            fill="#FFD43B", stipple="gray25", tags="superposition")

    def rechercher_texte(self):
        if not self.app.exiger_pdf():
            return
        needle = self.entree_ancien.get()
        if not needle:
            return self.app.statut("Saisissez le texte à rechercher.")
        casse = self.casse.get()
        source = self.app.chemin_pdf

        def travail(p):
            doc = core.open_pdf(source)
            try:
                return core.find_text_rects(doc, needle, casse, p)
            finally:
                doc.close()

        self.app.statut("Recherche…")
        self.app.lancer(travail, fin=self._afficher_resultats)

    def _afficher_resultats(self, resultats: dict[int, list[fitz.Rect]]):
        self.resultats_recherche = resultats
        for enfant in self.cadre_resultats.winfo_children():
            enfant.destroy()
        if not resultats:
            self.aide("Aucune occurrence. Si ce PDF est un scan, le texte n'est "
                      "qu'une image : passez d'abord par « OCR (scans) ».", parent=self.cadre_resultats)
            self.app.statut("Aucune occurrence.")
        else:
            total = sum(len(r) for r in resultats.values())
            self.app.statut(f"{total} occurrence(s) sur {len(resultats)} page(s).")
            pages = sorted(resultats)
            for page in pages[:30]:
                ctk.CTkButton(self.cadre_resultats, text=f"Page {page + 1} — {len(resultats[page])} occurrence(s)",
                              anchor="w", height=26, fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray75", "gray30"),
                              command=lambda page=page: self.apercu.aller(page)).pack(fill="x")
            if len(pages) > 30:
                self.aide(f"… et {len(pages) - 30} autre(s) page(s).", parent=self.cadre_resultats)
            if self.apercu.index not in resultats:
                self.apercu.aller(pages[0])
        self.apercu.redessiner()

    def lancer_remplacement(self):
        if not self.app.exiger_pdf():
            return
        ancien = self.entree_ancien.get()
        if not ancien:
            return messagebox.showinfo("Pagilis", "Saisissez le texte à remplacer.")
        nouveau = self.entree_nouveau.get()
        casse = self.casse.get()
        reduire = self.reduire.get()
        plage = self.entree_plage_rempl.get().strip()
        source = self.app.chemin_pdf
        sortie = self.app.enregistrer_sous("remplace")
        if not sortie:
            return

        def travail(p):
            doc = core.open_pdf(source)
            try:
                pages = core.parse_page_ranges(plage, doc.page_count) if plage else list(range(doc.page_count))
                n = core.replace_text(doc, ancien, nouveau, pages, casse, reduire, p)
                core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.app.statut("Remplacement en cours…")
        self.app.lancer(travail, fin=lambda n: self._fin_remplacement(n, sortie))

    def _fin_remplacement(self, n: int, sortie: str):
        self.resultats_recherche = {}
        if n == 0:
            self.app.statut("Aucune occurrence remplacée.")
            return messagebox.showinfo("Pagilis", "Aucune occurrence trouvée : le fichier créé est identique.\n"
                                                     "Si c'est un scan, passez d'abord par « OCR (scans) ».")
        self.app.apres_sauvegarde(sortie, self.continuer_rempl, f"{n} remplacement(s).")
