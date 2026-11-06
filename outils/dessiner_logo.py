# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dessine le logo de Pagilis : une page bleue au coin plié, avec « Pdf » en blanc.

Usage : python outils/dessiner_logo.py
Produit ressources/pagilis.ico (toutes les tailles de Windows) et
ressources/logo.png (512 px). Chaque taille est dessinée à part, en grand puis
réduite : en dessous de 32 px, le dessin est simplifié (P seul et épais, sans
pli ni « df ») pour rester net dans la barre des tâches.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

FOND = (31, 41, 55, 255)       # #1f2937
PAGE = (61, 123, 245, 255)     # #3d7bf5, l'accent de l'interface
PLI = (157, 188, 251, 255)     # #9dbcfb
LETTRE = (255, 255, 255, 255)
POLICE_TEXTE = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeuib.ttf")  # Segoe UI gras
TAILLES_ICO = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
DOSSIER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ressources")


def _p(d, u, k, x, y0, y1, droite_boucle, bas_boucle, e):
    """Le P en formes pleines : jambage, boucle en anneau, coin haut gauche anguleux."""
    d.rounded_rectangle(u(x - e / 2, y0 - e / 2, x + e / 2, y1 + e / 2), radius=e / 2 * k, fill=LETTRE)
    exterieur = (x - e / 2, y0 - e / 2, droite_boucle + e / 2, bas_boucle + e / 2)
    d.rounded_rectangle(u(*exterieur), radius=(exterieur[3] - exterieur[1]) / 2 * k, fill=LETTRE)
    d.rectangle(u(x - e / 2, y0 - e / 2, x + e / 2, bas_boucle), fill=LETTRE)
    interieur = (x + e / 2, y0 + e / 2, droite_boucle - e / 2, bas_boucle - e / 2)
    if interieur[2] > interieur[0] and interieur[3] > interieur[1]:
        d.rounded_rectangle(u(*interieur), radius=(interieur[3] - interieur[1]) / 2 * k, fill=PAGE)


def dessiner(taille: int) -> Image.Image:
    """Logo carré de `taille` pixels (grille de 64 unités, dessinée 8 fois plus grand)."""
    simple = taille < 32
    k = taille * 8 / 64  # pixels par unité, en grand
    grand = Image.new("RGBA", (taille * 8, taille * 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(grand)

    def u(*valeurs):
        return [v * k for v in valeurs]

    # Fond : carré arrondi sombre.
    d.rounded_rectangle(u(2, 2, 62, 62), radius=14 * k, fill=FOND)
    # Page : coin haut droit coupé en biais (le pli).
    gauche, haut, droite, bas, pli = 12, 9, 52, 55, 11
    d.rounded_rectangle(u(gauche, haut, droite, bas), radius=3 * k, fill=PAGE)
    if simple:
        d.polygon(u(droite - pli + 2, haut, droite + 1, haut, droite + 1, haut + pli - 2), fill=FOND)
    else:
        d.polygon(u(droite - pli, haut - 1, droite + 1, haut - 1, droite + 1, haut + pli), fill=FOND)
        d.polygon(u(droite - pli, haut, droite - pli, haut + pli, droite, haut + pli), fill=PLI)

    if simple:
        # Petites tailles : le P seul, épais, centré (un « df » serait illisible).
        _p(d, u, k, x=24.5, y0=20, y1=47, droite_boucle=40, bas_boucle=34, e=8)
    else:
        # « Pdf » : un grand P et un petit « df » posé sur la même ligne de base.
        _p(d, u, k, x=19.5, y0=19.5, y1=47, droite_boucle=32.5, bas_boucle=32.5, e=5)
        fonte = ImageFont.truetype(POLICE_TEXTE, round(15 * k))
        x0, _y0, _x1, y1 = d.textbbox((0, 0), "df", font=fonte, anchor="ls")
        d.text((36 * k - x0, 49.5 * k), "df", font=fonte, fill=LETTRE, anchor="ls")
    return grand.resize((taille, taille), Image.LANCZOS)


def main():
    os.makedirs(DOSSIER, exist_ok=True)
    images = [dessiner(t) for t in TAILLES_ICO]
    images[-1].save(os.path.join(DOSSIER, "pagilis.ico"), sizes=[(t, t) for t in TAILLES_ICO],
                    append_images=images[:-1])
    dessiner(512).save(os.path.join(DOSSIER, "logo.png"))
    print("ressources/pagilis.ico et ressources/logo.png écrits.")


if __name__ == "__main__":
    main()
