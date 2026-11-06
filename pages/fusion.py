# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fusion : assembler plusieurs PDF dans l'ordre choisi."""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

import identite
import pdf_core as core
import theme
from pages.base import PageFonction


class PageFusion(PageFonction):
    nom = "Fusion"
    libelle = "Fusionner"
    groupe = "Assembler"
    icone = "fusion"
    description = "Assembler plusieurs PDF dans l'ordre choisi."

    def construire(self):
        self.liste_fusion: list[str] = []
        self.selection_fusion: int | None = None
        self.section("Fichiers à assembler")
        self.aide("Dans l'ordre de la liste. Chaque fichier devient un signet ; ses signets sont conservés.")
        self.cadre_fusion = ctk.CTkFrame(self.cadre, fg_color=theme.SURFACE_2, corner_radius=8)
        self.cadre_fusion.pack(fill="x", padx=16, pady=4)
        ligne = self.ligne()
        theme.bouton(ligne, "Ajouter des PDF…", self.ajouter_fusion, icone_nom="ajouter").pack(side="left")
        for icone_nom, commande, bulle in (("monter", lambda: self.deplacer_fusion(-1), "Monter"),
                                           ("descendre", lambda: self.deplacer_fusion(1), "Descendre"),
                                           ("supprimer", self.retirer_fusion, "Retirer de la liste")):
            theme.bouton(ligne, icone_nom=icone_nom, style="discret", commande=commande,
                         bulle=bulle).pack(side="left", padx=(4, 0))
        theme.bouton(ligne, "Vider", self.vider_fusion, style="discret").pack(side="right")
        self.bouton_action("Fusionner", self.lancer_fusion, icone_nom="fusion")
        self._rafraichir_fusion()

    def _rafraichir_fusion(self):
        for enfant in self.cadre_fusion.winfo_children():
            enfant.destroy()
        if not self.liste_fusion:
            ctk.CTkLabel(self.cadre_fusion, text="Aucun fichier pour l'instant.", font=theme.police(12),
                         text_color=theme.TEXTE_DISCRET).pack(padx=10, pady=16)
            return
        for i, chemin in enumerate(self.liste_fusion):
            choisi = i == self.selection_fusion
            ctk.CTkButton(
                self.cadre_fusion, text=f"{i + 1}.  {os.path.basename(chemin)}", anchor="w", height=30,
                corner_radius=6, font=theme.police(13), fg_color=theme.ACCENT_DOUX if choisi else "transparent",
                text_color=theme.TEXTE, hover_color=theme.SURFACE_3,
                command=lambda i=i: self._choisir_fusion(i),
            ).pack(fill="x", padx=4, pady=1)

    def _choisir_fusion(self, index: int):
        self.selection_fusion = index
        self._rafraichir_fusion()

    def ajouter_fusion(self):
        chemins = filedialog.askopenfilenames(initialdir=self.app.dernier_dossier, filetypes=[("PDF", "*.pdf")])
        if chemins:
            self.liste_fusion.extend(chemins)
            self.app.memoriser_dossier(chemins[0])
            self._rafraichir_fusion()

    def deplacer_fusion(self, sens: int):
        """Monte ou descend le fichier SÉLECTIONNÉ."""
        i = self.selection_fusion
        if i is None:
            return self.app.statut("Sélectionnez d'abord un fichier dans la liste.")
        j = i + sens
        if 0 <= j < len(self.liste_fusion):
            self.liste_fusion[i], self.liste_fusion[j] = self.liste_fusion[j], self.liste_fusion[i]
            self.selection_fusion = j
            self._rafraichir_fusion()

    def retirer_fusion(self):
        if self.selection_fusion is not None:
            del self.liste_fusion[self.selection_fusion]
            self.selection_fusion = None
            self._rafraichir_fusion()

    def vider_fusion(self):
        self.liste_fusion.clear()
        self.selection_fusion = None
        self._rafraichir_fusion()

    def lancer_fusion(self):
        fichiers = list(self.liste_fusion)
        if len(fichiers) < 2:
            return messagebox.showinfo(identite.NOM_AFFICHE, "Ajoutez au moins deux PDF à fusionner.")
        sortie = filedialog.asksaveasfilename(initialdir=self.app.dernier_dossier, initialfile="fusion.pdf",
                                              defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not sortie:
            return
        self.app.statut("Fusion en cours…")
        self.app.lancer(lambda p: core.merge_pdfs(fichiers, sortie, p),
                        fin=lambda _: self.app.proposer_ouverture(sortie, "Fusion terminée."))
