# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modifier : corriger une ligne d'un clic, déplacer un bloc d'un glisser.

Les retouches s'appliquent à la copie de travail (app.edition, voir
edition.py), s'annulent et s'enregistrent en une fois.
"""

from __future__ import annotations

import logging
import os
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pymupdf as fitz

import pdf_core as core
from edition import Edition, ecrire_pdf
from pages.base import PageFonction

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


class PageModifier(PageFonction):
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
        boutons = ctk.CTkFrame(self.cadre, fg_color="transparent")
        boutons.pack(fill="x", padx=12, pady=(10, 12))
        self.bouton_annuler = ctk.CTkButton(boutons, text="Annuler (Ctrl+Z)", state="disabled",
                                            command=lambda: self.annuler_retouche())
        self.bouton_annuler.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.bouton_enregistrer = ctk.CTkButton(boutons, text="Enregistrer (Ctrl+S)", state="disabled",
                                                command=lambda: self.enregistrer_edition())
        self.bouton_enregistrer.pack(side="left", fill="x", expand=True)

    @property
    def edition(self) -> Edition | None:
        return self.app.edition

    # ------------------------------------------------------- crochets

    def page_changee(self):
        self._fermer_saisie()

    def avant_traitement(self):
        self._fermer_saisie()  # le document va être lu par un autre thread

    def document_charge(self):
        self.maj_etat()

    def peut_quitter(self) -> bool:
        # Les autres fonctions lisent le fichier enregistré, pas la copie de travail.
        if self.edition is None:
            return True
        if self.app.occupe():
            return False
        self._fermer_saisie()
        return self.confirmer_abandon(abandonner=True)

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
            self._retoucher(lambda: self.edition.deplacer(index, bloc, point.x - depart.x,
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
        niveau = self._retoucher(lambda: self.edition.corriger(index, centre, texte))
        message = MESSAGES_POLICE.get(niveau)
        if message:
            self.app.statut(message)

    # ------------------------------------------------------- retouches

    def _retoucher(self, action):
        """Applique une retouche de la copie de travail et rafraîchit l'aperçu."""
        try:
            resultat = action()
        except Exception:  # noqa: BLE001 - la copie de travail est déjà restaurée
            logging.exception("Retouche impossible")
            messagebox.showerror("Pagilis", "Retouche impossible, le document n'a pas changé.")
            resultat = None
        self.apercu.remplacer(self.edition.doc)
        self.maj_etat()
        return resultat

    def maj_etat(self):
        """Boutons Annuler / Enregistrer et titre de la fenêtre (« • » = non enregistré)."""
        ed = self.edition
        self.bouton_annuler.configure(state="normal" if ed and ed.peut_annuler else "disabled")
        self.bouton_enregistrer.configure(state="normal" if ed and ed.modifie else "disabled")
        if ed and ed.modifie:
            self.app.title(f"Pagilis • {os.path.basename(ed.source)}")
        else:
            self.app.title("Pagilis")

    def raccourci(self, action):
        """Ctrl+Z / Ctrl+S : seulement sur « Modifier », hors zone de saisie."""
        if self.app.page_active == self.nom and self.saisie is None and not self.app.travaux_en_cours:
            action()

    def annuler_retouche(self):
        if self.edition is None or not self.edition.peut_annuler or self.app.travaux_en_cours:
            return
        self._fermer_saisie()
        self._retoucher(self.edition.annuler)
        self.app.statut("Dernière retouche annulée.")

    def _demander_chemin(self) -> str | None:
        propose = self.edition.nom_propose()
        return filedialog.asksaveasfilename(
            initialdir=os.path.dirname(propose), initialfile=os.path.basename(propose),
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]) or None

    def enregistrer_edition(self):
        """Enregistre la copie de travail (en arrière-plan)."""
        if self.edition is None or self.app.travaux_en_cours:
            return
        self._fermer_saisie()
        chemin = self._demander_chemin()
        if not chemin:
            return
        edition = self.edition
        donnees = edition.doc.tobytes()  # ici, dans le thread de l'interface

        def fin(_resultat):
            edition.modifie = False
            self._apres_enregistrement(chemin)

        self.app.lancer(lambda _p: ecrire_pdf(donnees, chemin), fin=fin)

    def _apres_enregistrement(self, chemin: str):
        """Le fichier enregistré devient le fichier ouvert : les autres fonctions le liront."""
        self.app.chemin_pdf = chemin
        self.app.label_fichier.configure(text=os.path.basename(chemin))
        self.app.memoriser_dossier(chemin)
        self.maj_etat()
        self.app.statut(f"Enregistré : {os.path.basename(chemin)}")

    def confirmer_abandon(self, abandonner: bool = False) -> bool:
        """Retouches non enregistrées : propose de les enregistrer. Vrai = on peut continuer.

        abandonner : sur « Non », la copie de travail revient au fichier ouvert.
        """
        ed = self.edition
        if ed is None or not ed.modifie:
            return True
        reponse = messagebox.askyesnocancel("Pagilis", "Enregistrer les modifications ?")
        if reponse is None:
            return False
        if reponse:
            chemin = self._demander_chemin()
            if not chemin:
                return False
            try:
                ed.enregistrer(chemin)
            except Exception:  # noqa: BLE001 - on reste sur place, rien n'est perdu
                logging.exception("Enregistrement impossible : %s", chemin)
                messagebox.showerror("Pagilis", f"Impossible d'enregistrer « {os.path.basename(chemin)} ».")
                return False
            self._apres_enregistrement(chemin)
        elif abandonner:
            # Retouches abandonnées : on repart du document tel qu'il a été ouvert.
            source, word = ed.source, ed.origine_word
            if self.app.charger_fichier(self.app.chemin_pdf):
                self.app.edition = Edition(self.apercu.doc, source, origine_word=word)
                self.app.label_fichier.configure(text=os.path.basename(source))
        else:
            ed.modifie = False
        self.maj_etat()
        return True
