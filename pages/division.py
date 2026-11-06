# SPDX-License-Identifier: AGPL-3.0-or-later
"""Division : découper un PDF en plusieurs fichiers."""

from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

import pdf_core as core
from pages.base import PageFonction


class PageDivision(PageFonction):
    nom = "Division"
    libelle = "Découper"
    groupe = "Assembler"
    icone = "decouper"
    description = "Découper un PDF en plusieurs fichiers."

    def construire(self):
        self.section("Découper")
        self.mode_division = ctk.StringVar(value="page")
        for valeur, texte in [("page", "Une page par fichier"),
                              ("n", "Toutes les N pages"),
                              ("plages", "Selon des plages de pages")]:
            self.radio(self.cadre, texte, self.mode_division, valeur)
        self.section("Réglages")
        self.entree_n = self.champ("N pages", "2")
        self.entree_plages = self.champ("Plages", "")
        self.entree_plages.configure(placeholder_text="1-3, 5, 8-")
        self.aide("Chaque plage donne un fichier. Les fichiers sont créés dans le dossier que vous choisirez.")
        self.bouton_action("Découper", self.lancer_division, icone_nom="decouper")

    def lancer_division(self):
        if not self.app.exiger_pdf():
            return
        source = self.app.chemin_pdf
        mode = self.mode_division.get()
        n = self.entree_n.get().strip()
        plages = self.entree_plages.get().strip()
        if mode == "n" and not n.isdigit():
            return messagebox.showwarning("Pagilis", "Indiquez un nombre entier pour N.")
        if mode == "plages" and not plages:
            return messagebox.showwarning("Pagilis", "Indiquez les plages, par exemple « 1-3, 5, 8- ».")
        dossier = filedialog.askdirectory(initialdir=self.app.dernier_dossier)
        if not dossier:
            return

        def travail(p):
            if mode == "page":
                return core.split_by_page(source, dossier, p)
            if mode == "n":
                return core.split_every_n(source, dossier, int(n), p)
            return core.split_by_ranges(source, dossier, plages, p)

        self.app.statut("Division en cours…")
        self.app.lancer(travail, fin=lambda fichiers: self.app.statut(
            f"{len(fichiers)} fichier(s) créé(s) dans {dossier}."))
