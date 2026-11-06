# SPDX-License-Identifier: AGPL-3.0-or-later
"""Les fonctions de la barre latérale, dans l'ordre d'affichage.

Ajouter une fonction : un fichier ici avec une sous-classe de PageFonction,
puis l'ajouter à PAGES.
"""

from pages.division import PageDivision
from pages.fusion import PageFusion
from pages.modifier import PageModifier
from pages.ocr import PageOcr
from pages.pages import PageGestionPages
from pages.tampon import PageTampon

PAGES = [PageModifier, PageGestionPages, PageTampon, PageFusion, PageDivision, PageOcr]
