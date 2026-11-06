# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modifier : corriger une ligne d'un clic, déplacer un bloc d'un glisser.

Les retouches s'appliquent à la copie de travail (app.edition, voir
edition.py), s'annulent et s'enregistrent en une fois.
"""

from __future__ import annotations

import customtkinter as ctk
import pymupdf as fitz

import pdf_core as core
from pages.copie import PageCopie

# Au-delà de ce déplacement de la souris (pixels écran), un appui devient un
# glisser (déplacer le bloc) au lieu d'un clic (corriger la ligne).
SEUIL_GLISSER = 5

# Statut après une correction, selon la police utilisée pour réécrire la ligne.
MESSAGES_POLICE = {
    core.POLICE_ORIGINE: "Ligne corrigée, police d'origine conservée.",
    core.POLICE_INSTALLEE: "Ligne corrigée avec la police d'origine, installée sur ce PC.",
    core.POLICE_REMPLACEMENT: "Ligne corrigée. Police d'origine indisponible pour ces caractères : "
                              "réécrite en Arial, Times ou Courier.",
    core.LIGNE_EFFACEE: "Ligne effacée.",
}


class PageModifier(PageCopie):
    nom = "Modifier"
    icone = "✎"
    description = "Corriger ou déplacer du texte, PDF ou Word"

    def construire(self):
        self.saisie: ctk.CTkEntry | None = None  # zone de correction posée sur l'aperçu
        self._ligne_saisie: core.LineInfo | None = None
        self._contexte_saisie = None  # (page, zoom, décalage) à l'ouverture de la zone
        self._fenetre_saisie = None   # élément du canevas qui porte la zone
        # (départ, ligne sous la souris, bloc, point courant si glisser)
        self._geste = None
        self.section("Document")
        self.aide("Ouvrez un PDF ou un document Word (converti en PDF ; Microsoft Word "
                  "ou LibreOffice requis).")
        ctk.CTkButton(self.cadre, text="Ouvrir…", command=self.app.choisir_pdf).pack(
            fill="x", padx=12, pady=(4, 4))
        self.section("Retoucher")
        self.aide("Cliquez sur une ligne pour la corriger, faites glisser un bloc pour le déplacer.")
        self.boutons_copie()

    # ------------------------------------------------------- crochets

    def page_changee(self):
        self._fermer_saisie()

    def avant_traitement(self):
        self._fermer_saisie()  # le document va être lu par un autre thread

    def interrompre(self):
        self._fermer_saisie()

    def raccourcis_permis(self) -> bool:
        return self.saisie is None  # dans la zone de saisie, Ctrl+Z / Ctrl+S ne retouchent pas

    def dessiner(self, apercu):
        canevas = apercu.canevas
        if self.saisie is not None:
            if self._contexte_saisie != (apercu.index, apercu.zoom, apercu.decalage):
                self._fermer_saisie()  # zoom ou page changés : la zone n'est plus à sa place
            elif self._fenetre_saisie is None or not canevas.type(self._fenetre_saisie):
                self._poser_saisie()   # rendu complet : l'élément du canevas a été effacé
        if self._geste and self._geste[3] is not None:
            depart, _ligne, bloc, courant = self._geste
            dx, dy = courant.x - depart.x, courant.y - depart.y
            canevas.create_rectangle(*apercu.rect_canevas(bloc), outline="#1F6AA5", width=2,
                                     tags="superposition")
            canevas.create_rectangle(*apercu.rect_canevas(bloc + (dx, dy, dx, dy)), outline="#E8590C",
                                     width=2, dash=(6, 3), tags="superposition")

    def appui(self, point):
        self._geste = None
        self._fermer_saisie()
        if self.edition is None or self.app.travaux_en_cours:
            return
        page = self.apercu.page
        ligne = core.line_at(page, point)
        bloc = ligne.block_rect if ligne else next(
            (fitz.Rect(b) for b in core.text_blocks(page) if b.contains(point)), None)
        self._geste = (point, ligne, bloc, None)

    def glisse(self, point):
        if not self._geste:
            return
        depart, ligne, bloc, courant = self._geste
        x0, y0 = self.apercu.vers_canevas(depart.x, depart.y)
        x1, y1 = self.apercu.vers_canevas(point.x, point.y)
        # Au-delà de SEUIL_GLISSER pixels à l'écran, c'est un déplacement, pas un clic.
        if bloc is not None and (courant is not None or abs(x1 - x0) + abs(y1 - y0) > SEUIL_GLISSER):
            self._geste = (depart, ligne, bloc, point)
            self.apercu.redessiner()

    def relache(self, point):
        if not self._geste:
            return
        depart, ligne, bloc, courant = self._geste
        self._geste = None
        if courant is not None:
            index = self.apercu.index
            self.retoucher(lambda: self.edition.deplacer(index, bloc, point.x - depart.x,
                                                          point.y - depart.y))
        elif ligne is not None:
            self._ouvrir_saisie(ligne)
        elif not core.has_text(self.apercu.page):
            self.app.statut("Aucun texte ici. Page scannée ? Utilisez l'OCR d'abord.")
        self.apercu.redessiner()

    # ------------------------------------------------------- zone de saisie

    def _ouvrir_saisie(self, ligne: core.LineInfo):
        """Pose une zone de saisie sur la ligne, avec son texte actuel sélectionné."""
        self._fermer_saisie()
        taille = max(9, round(ligne.size * self.apercu.zoom * 0.9))
        x0, y0, x1, y1 = self.apercu.rect_canevas(ligne.rect)
        self.saisie = ctk.CTkEntry(self.apercu.canevas, width=max(int(x1 - x0) + 24, 200),
                                   height=max(int(y1 - y0) + 10, 28), font=ctk.CTkFont(size=taille))
        self.saisie.insert(0, ligne.text)
        self.saisie.select_range(0, "end")
        self.saisie.bind("<Return>", lambda _e: self._valider_saisie())
        self.saisie.bind("<KP_Enter>", lambda _e: self._valider_saisie())
        self.saisie.bind("<Escape>", lambda _e: self._fermer_saisie())
        self._ligne_saisie = ligne
        self._contexte_saisie = (self.apercu.index, self.apercu.zoom, self.apercu.decalage)
        self._poser_saisie()
        self.saisie.focus_set()

    def _poser_saisie(self):
        x0, y0, _x1, y1 = self.apercu.rect_canevas(self._ligne_saisie.rect)
        hauteur = max(int(y1 - y0) + 10, 28)
        self._fenetre_saisie = self.apercu.canevas.create_window(
            x0 - 6, (y0 + y1) / 2 - hauteur / 2, anchor="nw", window=self.saisie)

    def _fermer_saisie(self):
        """Ferme la zone de saisie sans rien appliquer."""
        if self.saisie is not None:
            if self._fenetre_saisie is not None:
                self.apercu.canevas.delete(self._fenetre_saisie)
            self.saisie.destroy()
        self.saisie = self._ligne_saisie = self._contexte_saisie = self._fenetre_saisie = None

    def _valider_saisie(self):
        ligne, index, texte = self._ligne_saisie, self.apercu.index, self.saisie.get()
        self._fermer_saisie()
        centre = fitz.Point((ligne.rect.x0 + ligne.rect.x1) / 2, (ligne.rect.y0 + ligne.rect.y1) / 2)
        niveau = self.retoucher(lambda: self.edition.corriger(index, centre, texte))
        message = MESSAGES_POLICE.get(niveau)
        if message:
            self.app.statut(message)
