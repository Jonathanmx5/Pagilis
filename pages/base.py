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

import theme

if TYPE_CHECKING:  # pragma: no cover
    from apercu import Apercu
    from pagilis import Pagilis


class PageFonction:
    """Une fonction de la barre latérale : son formulaire et ses gestes dans l'aperçu."""

    nom = ""          # clé unique (préférences, tests)
    libelle = ""      # nom affiché dans la barre latérale et en tête du panneau
    groupe = ""       # rubrique de la barre latérale
    icone = ""        # clé d'icône du thème (theme.ICONES)
    description = ""  # une phrase sous le titre du panneau

    def __init__(self, app: "Pagilis", cadre: ctk.CTkScrollableFrame):
        self.app = app
        self.cadre = cadre
        ctk.CTkLabel(cadre, text=self.libelle or self.nom, font=theme.police(18, gras=True),
                     text_color=theme.TEXTE, anchor="w").pack(fill="x", padx=16, pady=(16, 0))
        ctk.CTkLabel(cadre, text=self.description, font=theme.police(12), text_color=theme.TEXTE_2,
                     anchor="w", justify="left", wraplength=260).pack(fill="x", padx=16, pady=(2, 4))
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

    def peut_quitter(self, vers: "PageFonction") -> bool:
        """On passe à la fonction `vers` : Faux pour rester sur celle-ci."""
        return True

    def touche_annuler(self) -> None:
        """Ctrl+Z, quand cette page est affichée."""

    def touche_enregistrer(self) -> None:
        """Ctrl+S, quand cette page est affichée."""

    def montree(self) -> None:
        """La page vient d'être affichée."""

    # -------------------------------------------------- éléments de formulaire

    def section(self, titre: str, parent=None):
        """Titre de section dans un formulaire."""
        ctk.CTkLabel(parent or self.cadre, text=titre, font=theme.police(13, gras=True),
                     text_color=theme.TEXTE, anchor="w").pack(fill="x", padx=16, pady=(18, 6))

    def aide(self, texte: str, parent=None):
        """Texte explicatif, sur plusieurs lignes."""
        ctk.CTkLabel(parent or self.cadre, text=texte, wraplength=260, justify="left", anchor="w",
                     font=theme.police(12), text_color=theme.TEXTE_2).pack(fill="x", padx=16, pady=(0, 6))

    def ligne(self, parent=None) -> ctk.CTkFrame:
        """Rangée horizontale (boutons, réglages côte à côte)."""
        cadre = ctk.CTkFrame(parent or self.cadre, fg_color="transparent")
        cadre.pack(fill="x", padx=16, pady=3)
        return cadre

    def champ(self, libelle: str, defaut: str, parent=None) -> ctk.CTkEntry:
        ligne = self.ligne(parent)
        if libelle:
            ctk.CTkLabel(ligne, text=libelle, width=96, anchor="w", font=theme.police(13),
                         text_color=theme.TEXTE_2).pack(side="left")
        entree = theme.champ(ligne)
        entree.insert(0, defaut)
        entree.pack(side="left", fill="x", expand=True)
        return entree

    @staticmethod
    def remplir(entree: ctk.CTkEntry, valeur):
        entree.delete(0, "end")
        entree.insert(0, valeur if isinstance(valeur, str) else f"{valeur:.1f}".rstrip("0").rstrip("."))

    @staticmethod
    def radio(parent, texte: str, variable, valeur) -> ctk.CTkRadioButton:
        bouton = ctk.CTkRadioButton(parent, text=texte, variable=variable, value=valeur, font=theme.police(13),
                                    text_color=theme.TEXTE, fg_color=theme.ACCENT, hover_color=theme.ACCENT_SURVOL,
                                    border_color=theme.BORDURE, radiobutton_width=18, radiobutton_height=18)
        bouton.pack(anchor="w", padx=16, pady=4)
        return bouton

    def segments(self, libelle: str, valeurs: list[str], variable, commande=None) -> ctk.CTkSegmentedButton:
        ligne = self.ligne()
        ctk.CTkLabel(ligne, text=libelle, width=96, anchor="w", font=theme.police(13),
                     text_color=theme.TEXTE_2).pack(side="left")
        choix = ctk.CTkSegmentedButton(ligne, values=valeurs, variable=variable, command=commande,
                                       font=theme.police(12), fg_color=theme.SURFACE_2,
                                       selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_SURVOL,
                                       unselected_color=theme.SURFACE_2, unselected_hover_color=theme.SURFACE_3,
                                       text_color=theme.TEXTE)
        choix.pack(side="left", fill="x", expand=True)
        return choix

    def curseur(self, libelle: str, debut: float, fin: float, variable, suffixe: str = "",
                commande=None) -> ctk.CTkSlider:
        """Réglage à la souris, avec sa valeur affichée à droite."""
        ligne = self.ligne()
        ctk.CTkLabel(ligne, text=libelle, width=96, anchor="w", font=theme.police(13),
                     text_color=theme.TEXTE_2).pack(side="left")
        valeur = ctk.CTkLabel(ligne, width=48, anchor="e", font=theme.police(12), text_color=theme.TEXTE_2)
        valeur.pack(side="right")

        def changer(_v=None):
            valeur.configure(text=f"{round(variable.get())}{suffixe}")
            if commande:
                commande()

        glissiere = ctk.CTkSlider(ligne, from_=debut, to=fin, variable=variable, command=changer,
                                  progress_color=theme.ACCENT, button_color=theme.TEXTE,
                                  button_hover_color="#ffffff", fg_color=theme.SURFACE_3, height=16)
        glissiere.pack(side="left", fill="x", expand=True, padx=(0, 6))
        changer()
        return glissiere

    def options_avancees(self) -> ctk.CTkFrame:
        """Réglages techniques, repliés tant qu'on ne les demande pas."""
        cadre = ctk.CTkFrame(self.cadre, fg_color="transparent")
        bascule = theme.bouton(self.cadre, "Options avancées", style="discret", hauteur=28, anchor="w",
                               icone_nom="descendre")
        bascule.pack(fill="x", padx=10, pady=(12, 0))

        def basculer():
            if cadre.winfo_ismapped():
                cadre.pack_forget()
                bascule.configure(image=theme.icone("descendre", 16))
            else:
                cadre.pack(fill="x", after=bascule)
                bascule.configure(image=theme.icone("monter", 16))

        bascule.configure(command=basculer)
        self.basculer_options = basculer
        return cadre

    @staticmethod
    def case(parent, texte: str, variable, commande=None) -> ctk.CTkCheckBox:
        boite = ctk.CTkCheckBox(parent, text=texte, variable=variable, command=commande, font=theme.police(13),
                                text_color=theme.TEXTE, fg_color=theme.ACCENT, hover_color=theme.ACCENT_SURVOL,
                                border_color=theme.BORDURE, checkbox_width=18, checkbox_height=18, corner_radius=4)
        boite.pack(anchor="w", padx=16, pady=4)
        return boite

    def bouton_action(self, texte: str, commande, icone_nom: str | None = None):
        """L'action principale de la page (une seule, en couleur d'accent)."""
        theme.bouton(self.cadre, texte, commande, style="principal", icone_nom=icone_nom, hauteur=38).pack(
            fill="x", padx=16, pady=(18, 16))
