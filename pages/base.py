# SPDX-License-Identifier: AGPL-3.0-or-later
"""Socle commun des fonctions de la barre latérale.

Chaque fonction (Modifier, Fusion…) est une page : un formulaire à gauche,
et ses propres gestes de souris et dessins sur l'aperçu partagé. La fenêtre
principale (pagilis.Pagilis) appelle les méthodes « crochets » ci-dessous
sur la page affichée, ou sur toutes les pages pour les événements communs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk
import pymupdf as fitz

if TYPE_CHECKING:  # pragma: no cover
    from apercu import Apercu
    from pagilis import Pagilis


class PageFonction:
    """Une fonction de la barre latérale : son formulaire et ses gestes dans l'aperçu."""

    nom = ""          # libellé de la barre latérale (clé unique)
    icone = ""
    description = ""  # sous-titre affiché en haut de la page

    def __init__(self, app: "Pagilis", cadre: ctk.CTkScrollableFrame):
        self.app = app
        self.cadre = cadre
        self.construire()

    @property
    def apercu(self) -> "Apercu":
        return self.app.apercu

    # --------------------------------------------------------------- crochets

    def construire(self) -> None:
        """Crée le formulaire dans self.cadre."""

    def dessiner(self, apercu: "Apercu") -> None:
        """Superpositions sur l'aperçu (page affichée seulement, hors traitement)."""

    def appui(self, point: fitz.Point) -> None:
        """Gestes souris dans l'aperçu, point en repère affiché (page affichée seulement)."""

    def glisse(self, point: fitz.Point) -> None:
        pass

    def relache(self, point: fitz.Point) -> None:
        pass

    def page_changee(self) -> None:
        """L'aperçu a changé de page (toutes les pages sont prévenues)."""

    def document_charge(self) -> None:
        """Un nouveau document est ouvert (toutes les pages sont prévenues)."""

    def avant_traitement(self) -> None:
        """Un traitement en arrière-plan démarre (toutes les pages sont prévenues)."""

    def peut_quitter(self) -> bool:
        """On passe à une autre fonction : Faux pour rester sur celle-ci."""
        return True

    # -------------------------------------------------- éléments de formulaire

    def section(self, titre: str, parent=None):
        """Petit titre de section dans un formulaire."""
        ctk.CTkLabel(parent or self.cadre, text=titre.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray45", "gray55"), anchor="w").pack(fill="x", padx=12, pady=(14, 4))

    def aide(self, texte: str, parent=None):
        """Texte explicatif discret, sur plusieurs lignes."""
        ctk.CTkLabel(parent or self.cadre, text=texte, wraplength=340, justify="left", anchor="w",
                     text_color=("gray35", "gray65")).pack(fill="x", padx=12, pady=(0, 6))

    def champ(self, libelle: str, defaut: str) -> ctk.CTkEntry:
        ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text=libelle, width=130, anchor="w").pack(side="left")
        entree = ctk.CTkEntry(ligne)
        entree.insert(0, defaut)
        entree.pack(side="left", fill="x", expand=True)
        return entree

    @staticmethod
    def remplir(entree: ctk.CTkEntry, valeur):
        entree.delete(0, "end")
        entree.insert(0, valeur if isinstance(valeur, str) else f"{valeur:.1f}".rstrip("0").rstrip("."))

    def case_continuer(self) -> ctk.BooleanVar:
        var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.cadre, text="Continuer sur le fichier résultat", variable=var).pack(
            anchor="w", padx=12, pady=(10, 2))
        return var

    def bouton_action(self, texte: str, commande):
        ctk.CTkButton(self.cadre, text=texte, height=36, font=ctk.CTkFont(size=14, weight="bold"),
                      command=commande).pack(fill="x", padx=12, pady=(10, 12))
