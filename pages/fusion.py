# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fusion : assembler plusieurs PDF dans l'ordre choisi."""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

import pdf_core as core
from pages.base import PageFonction


class PageFusion(PageFonction):
    nom = "Fusion"
    icone = "⧉"
    description = "Assembler plusieurs PDF dans l'ordre choisi"

    def construire(self):
        self.liste_fusion: list[str] = []
        self.selection_fusion: int | None = None
        self.section("Fichiers à fusionner")
        self.aide("Cliquez sur un fichier pour le sélectionner, puis changez sa place. "
                  "Chaque fichier devient un signet ; ses signets d'origine sont conservés.")
        self.cadre_fusion = ctk.CTkFrame(self.cadre)
        self.cadre_fusion.pack(fill="x", padx=12, pady=4)
        boutons = ctk.CTkFrame(self.cadre, fg_color="transparent")
        boutons.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(boutons, text="Ajouter…", width=80, command=self.ajouter_fusion).pack(side="left")
        for texte, commande in [("▲", lambda: self.deplacer_fusion(-1)), ("▼", lambda: self.deplacer_fusion(1)),
                                ("Retirer", self.retirer_fusion), ("Vider", self.vider_fusion)]:
            ctk.CTkButton(boutons, text=texte, width=36 if len(texte) == 1 else 70, fg_color="gray50",
                          hover_color="gray40", command=commande).pack(side="left", padx=(6, 0))
        self.bouton_action("Fusionner…", self.lancer_fusion)
        self._rafraichir_fusion()

    def _rafraichir_fusion(self):
        for enfant in self.cadre_fusion.winfo_children():
            enfant.destroy()
        if not self.liste_fusion:
            ctk.CTkLabel(self.cadre_fusion, text="Aucun fichier. Cliquez sur « Ajouter… ».",
                         text_color=("gray40", "gray60")).pack(padx=10, pady=14)
            return
        for i, chemin in enumerate(self.liste_fusion):
            choisi = i == self.selection_fusion
            ctk.CTkButton(
                self.cadre_fusion, text=f"{i + 1}.  {os.path.basename(chemin)}", anchor="w", height=30,
                fg_color=("#3B8ED0", "#1F6AA5") if choisi else "transparent",
                text_color=("white", "white") if choisi else ("gray10", "gray90"),
                hover_color=("gray75", "gray30"),
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
            return messagebox.showinfo("Pagilis", "Ajoutez au moins deux PDF à fusionner.")
        sortie = filedialog.asksaveasfilename(initialdir=self.app.dernier_dossier, initialfile="fusion.pdf",
                                              defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not sortie:
            return
        self.app.statut("Fusion en cours…")
        self.app.lancer(lambda p: core.merge_pdfs(fichiers, sortie, p),
                        fin=lambda _: self.app.proposer_ouverture(sortie))
