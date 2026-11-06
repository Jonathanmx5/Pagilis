# SPDX-License-Identifier: AGPL-3.0-or-later
"""Déplacer du texte : sélectionner un bloc dans l'aperçu et le faire glisser."""

from __future__ import annotations

from tkinter import messagebox

import pymupdf as fitz

import pdf_core as core
from pages.base import PageFonction


class PageDeplacer(PageFonction):
    nom = "Déplacer du texte"
    icone = "✥"
    description = "Déplacer un bloc de texte sur la page"

    def construire(self):
        self.selection: fitz.Rect | None = None
        self._geste = None  # ("deplacer", origine) ou ("selection", départ)
        self.section("Sélection")
        self.aide("Dans l'aperçu : cliquez sur un bloc encadré ou tracez un rectangle, "
                  "puis faites glisser la sélection vers sa nouvelle place.")
        self.entree_zone = self.champ("Zone x0,y0,x1,y1", "")
        self.section("Décalage")
        self.entree_dx = self.champ("dX (pt)", "0")
        self.entree_dy = self.champ("dY (pt)", "0")
        for entree in (self.entree_zone, self.entree_dx, self.entree_dy):
            entree.bind("<KeyRelease>", lambda _e: self._lire_zone_saisie())
        self.continuer_dep = self.case_continuer()
        self.bouton_action("Déplacer…", self.lancer_deplacement)

    def _lire_zone_saisie(self):
        """Une zone tapée à la main remplace la sélection faite à la souris."""
        try:
            x0, y0, x1, y1 = (float(v) for v in self.entree_zone.get().split(","))
            self.selection = fitz.Rect(x0, y0, x1, y1)
        except ValueError:
            pass
        self.apercu.redessiner()

    def _decalage(self) -> tuple[float, float]:
        try:
            return float(self.entree_dx.get()), float(self.entree_dy.get())
        except ValueError:
            return 0.0, 0.0

    def _maj_champs(self, dx: float = 0.0, dy: float = 0.0):
        if self.selection is not None:
            r = self.selection
            self.remplir(self.entree_zone, f"{r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f}")
        else:
            self.remplir(self.entree_zone, "")
        self.remplir(self.entree_dx, dx)
        self.remplir(self.entree_dy, dy)

    # ------------------------------------------------------- crochets

    def page_changee(self):
        """Changement de page (pas de zoom) : la sélection n'a plus de sens."""
        self.selection = None
        self._maj_champs()

    def document_charge(self):
        self.selection = None

    def dessiner(self, apercu):
        canevas = apercu.canevas
        for rect in core.text_blocks(apercu.page):
            canevas.create_rectangle(*apercu.rect_canevas(rect), outline="#8a8a8a", dash=(2, 3),
                                     tags="superposition")
        if self.selection is not None:
            canevas.create_rectangle(*apercu.rect_canevas(self.selection), outline="#1F6AA5", width=2,
                                     tags="superposition")
            dx, dy = self._decalage()
            if dx or dy:
                fantome = fitz.Rect(self.selection) + (dx, dy, dx, dy)
                canevas.create_rectangle(*apercu.rect_canevas(fantome), outline="#E8590C", width=2,
                                         dash=(6, 3), tags="superposition")

    def appui(self, point):
        dx, dy = self._decalage()
        if self.selection is not None and (fitz.Rect(self.selection) + (dx, dy, dx, dy)).contains(point):
            self._geste = ("deplacer", point - fitz.Point(dx, dy))
        else:
            self._geste = ("selection", point)

    def glisse(self, point):
        if not self._geste:
            return
        nature, valeur = self._geste
        if nature == "deplacer":
            ecart = point - valeur
            self._maj_champs(round(ecart.x), round(ecart.y))
        else:
            self.selection = fitz.Rect(valeur, point)
            self.selection.normalize()
            self._maj_champs()
        self.apercu.redessiner()

    def relache(self, point):
        if self._geste and self._geste[0] == "selection" and (
                self.selection is None or self.selection.width < 3 or self.selection.height < 3):
            # Simple clic : on sélectionne le bloc de texte situé sous la souris.
            blocs = [] if self.app.travaux_en_cours else core.text_blocks(self.apercu.page)
            self.selection = next((fitz.Rect(b) for b in blocs if b.contains(point)), None)
            self._maj_champs()
            self.apercu.redessiner()
        self._geste = None

    # ------------------------------------------------------- traitement

    def lancer_deplacement(self):
        if not self.app.exiger_pdf():
            return
        if self.selection is None:
            return messagebox.showinfo("Pagilis", "Sélectionnez d'abord un bloc de texte dans l'aperçu.")
        zone = fitz.Rect(self.selection)
        dx, dy = self._decalage()
        if dx == 0 and dy == 0:
            return messagebox.showinfo("Pagilis", "Faites glisser la sélection ou indiquez un décalage.")
        page = self.apercu.index
        source = self.app.chemin_pdf
        sortie = self.app.enregistrer_sous("deplace")
        if not sortie:
            return

        def travail(_p):
            doc = core.open_pdf(source)
            try:
                n = core.move_text_block(doc, page, zone, dx, dy)
                if n:
                    core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.app.statut("Déplacement en cours…")
        self.app.lancer(travail, fin=lambda n: self._fin_deplacement(n, sortie))

    def _fin_deplacement(self, n: int, sortie: str):
        if n == 0:
            self.app.statut("Aucun texte dans la zone sélectionnée.")
            return messagebox.showinfo("Pagilis", "La zone sélectionnée ne contient pas de texte lisible "
                                                     "horizontalement. Rien n'a été enregistré.")
        self.selection = None
        self._maj_champs()
        self.app.apres_sauvegarde(sortie, self.continuer_dep, f"{n} segment(s) déplacé(s).")
