# SPDX-License-Identifier: AGPL-3.0-or-later
"""Système visuel de Pagilis : couleurs, polices, icônes et boutons.

Une seule source pour l'apparence : les pages n'écrivent jamais une couleur ou
une police en dur, elles passent par ici. Polices et icônes sont celles de
Windows (Segoe UI, Segoe MDL2 Assets) : rien à installer ni à embarquer.
"""

from __future__ import annotations

import functools
import os

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ couleurs
# Apparence sombre fixe. Une seule couleur d'accent, réservée à l'action
# principale et à l'élément sélectionné.
FOND = "#1c1d20"          # fond de la fenêtre
SURFACE = "#24252a"       # barre latérale, panneaux, barre du haut
SURFACE_2 = "#2d2e34"     # champs, survol, cellules
SURFACE_3 = "#36373e"     # survol d'un élément déjà en relief
BORDURE = "#3a3c43"
DOCUMENT = "#16171a"      # fond derrière les pages
TEXTE = "#ececef"
TEXTE_2 = "#b2b4bb"       # texte d'appui (contraste suffisant sur SURFACE)
TEXTE_DISCRET = "#80838c"
ACCENT = "#3d7bf5"
ACCENT_SURVOL = "#2f66d6"
ACCENT_DOUX = "#253552"   # élément sélectionné (navigation, vignette)
DANGER = "#d64848"
DANGER_SURVOL = "#b83a3a"
ALERTE_FOND = "#4a3d16"
ALERTE_TEXTE = "#f3cf6b"
SUCCES = "#4caf7a"

# ------------------------------------------------------------------ polices
POLICE = "Segoe UI"
_POLICE_ICONES = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segmdl2.ttf")


def chemin_ressource(nom: str) -> str:
    """Fichier du dossier ressources/, dans les sources comme dans l'exe compilé."""
    import sys
    racine = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(racine, "ressources", nom)


ICONE_APPLICATION = chemin_ressource("pagilis.ico")


def logo(taille: int) -> ctk.CTkImage | None:
    """Le logo (page bleue et « Pdf »), à afficher dans l'interface."""
    chemin = chemin_ressource("logo.png")
    if not os.path.exists(chemin):
        return None
    image = Image.open(chemin)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(taille, taille))


def poser_icone(fenetre):
    """Icône de fenêtre (barre de titre, barre des tâches).

    CustomTkinter impose la sienne environ 200 ms après la création de la
    fenêtre : on repasse derrière.
    """
    if not os.path.exists(ICONE_APPLICATION):
        return

    def poser():
        try:
            fenetre.iconbitmap(ICONE_APPLICATION)
        except Exception:  # noqa: BLE001 - fenêtre déjà fermée : sans importance
            pass

    poser()
    fenetre.after(300, poser)


def police(taille: int = 13, gras: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=POLICE, size=taille, weight="bold" if gras else "normal")


# ------------------------------------------------------------------ icônes
# Glyphes de Segoe MDL2 Assets (présente sur Windows 10 et 11).
ICONES = {
    "modifier": "\uE70F", "pages": "\uE8C8", "signer": "\uEE56", "fusion": "\uEA3C",
    "decouper": "\uE8C6", "ocr": "\uEE6F", "ouvrir": "\uE8E5", "enregistrer": "\uE74E",
    "annuler": "\uE7A7", "document": "\uE8A5", "precedent": "\uE76B", "suivant": "\uE76C",
    "zoom_plus": "\uE710", "zoom_moins": "\uE738", "ajuster": "\uE740", "pivoter": "\uE7AD",
    "supprimer": "\uE74D", "monter": "\uE70E", "descendre": "\uE70D", "ajouter": "\uE710",
    "retirer": "\uE738", "extraire": "\uE896", "inserer": "\uE8F4", "rechercher": "\uE721",
    "info": "\uE946", "fermer": "\uE711", "valider": "\uE8FB",
}


@functools.lru_cache(maxsize=None)
def _dessin_icone(nom: str, taille: int, couleur: str, miroir: bool) -> Image.Image | None:
    """Glyphe dessiné en image (gardé en mémoire : indépendant de la fenêtre Tk)."""
    if not os.path.exists(_POLICE_ICONES):
        return None
    cote = taille * 2  # double résolution : net sur les écrans à 150 %
    image = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    fonte = ImageFont.truetype(_POLICE_ICONES, int(cote * 0.86))
    dessin = ImageDraw.Draw(image)
    x0, y0, x1, y1 = dessin.textbbox((0, 0), ICONES[nom], font=fonte)
    dessin.text(((cote - (x1 - x0)) / 2 - x0, (cote - (y1 - y0)) / 2 - y0), ICONES[nom], font=fonte, fill=couleur)
    return image.transpose(Image.FLIP_LEFT_RIGHT) if miroir else image


def icone(nom: str, taille: int = 16, couleur: str = TEXTE, miroir: bool = False) -> ctk.CTkImage | None:
    """Icône `nom` (None si la police d'icônes de Windows est absente).

    Un CTkImage neuf à chaque appel : il est lié à la fenêtre Tk qui l'affiche.
    """
    image = _dessin_icone(nom, taille, couleur, miroir)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(taille, taille)) if image else None


# ------------------------------------------------------------------ boutons
_STYLES = {
    # fond, survol, texte, bordure
    "principal": (ACCENT, ACCENT_SURVOL, "#ffffff", None),
    "secondaire": (SURFACE_2, SURFACE_3, TEXTE, BORDURE),
    "discret": ("transparent", SURFACE_2, TEXTE, None),
    "danger": ("transparent", "#3a2224", "#ff8a8a", "#6b2f33"),
}


def bouton(parent, texte: str = "", commande=None, style: str = "secondaire", icone_nom: str | None = None,
           largeur: int = 0, hauteur: int = 32, miroir: bool = False, bulle: str | None = None,
           **options) -> ctk.CTkButton:
    """Bouton aux couleurs du thème.

    principal : l'action principale de l'écran (une seule) ; secondaire : les
    autres actions ; discret : barres d'outils ; danger : action destructive.
    """
    fond, survol, couleur, bordure = _STYLES[style]
    image = icone(icone_nom, 16, couleur, miroir) if icone_nom else None
    widget = ctk.CTkButton(
        parent, text=texte, command=commande, image=image, compound="left",
        width=largeur or (hauteur if not texte else 0), height=hauteur, corner_radius=6,
        fg_color=fond, hover_color=survol, text_color=couleur, text_color_disabled=TEXTE_DISCRET,
        border_width=1 if bordure else 0, border_color=bordure or SURFACE,
        font=police(13, gras=style == "principal"), **options)
    if bulle:
        infobulle(widget, bulle)
    return widget


def infobulle(widget, texte: str):
    """Petite bulle d'explication au survol (indispensable pour un bouton à icône seule)."""
    etat = {"bulle": None, "attente": None}

    def montrer():
        etat["attente"] = None
        if etat["bulle"] is not None or not widget.winfo_exists():
            return
        bulle = ctk.CTkToplevel(widget)
        bulle.overrideredirect(True)
        bulle.attributes("-topmost", True)
        ctk.CTkLabel(bulle, text=texte, font=police(12), text_color=TEXTE, fg_color=SURFACE_3,
                     corner_radius=4, padx=8, pady=3).pack()
        bulle.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
        etat["bulle"] = bulle

    def cacher(_e=None):
        if etat["attente"] is not None:
            widget.after_cancel(etat["attente"])
            etat["attente"] = None
        if etat["bulle"] is not None:
            etat["bulle"].destroy()
            etat["bulle"] = None

    def entrer(_e=None):
        if etat["attente"] is None:
            etat["attente"] = widget.after(500, montrer)

    widget.bind("<Enter>", entrer, add="+")
    widget.bind("<Leave>", cacher, add="+")
    widget.bind("<ButtonPress>", cacher, add="+")


def activer(bouton: ctk.CTkButton, actif: bool, style: str = "secondaire"):
    """Active ou désactive un bouton ; désactivé, il perd sa couleur pour ne pas sembler cliquable."""
    fond, survol, couleur, _bordure = _STYLES[style]
    bouton.configure(state="normal" if actif else "disabled",
                     fg_color=fond if actif else ("transparent" if fond == "transparent" else SURFACE_2))


def champ(parent, **options) -> ctk.CTkEntry:
    return ctk.CTkEntry(parent, height=32, corner_radius=6, fg_color=SURFACE_2, border_color=BORDURE,
                        border_width=1, text_color=TEXTE, placeholder_text_color=TEXTE_DISCRET,
                        font=police(13), **options)


def appliquer():
    """Réglages globaux de CustomTkinter, avant la création de la fenêtre."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
