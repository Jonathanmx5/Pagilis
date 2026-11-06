# SPDX-License-Identifier: AGPL-3.0-or-later
"""Copie de travail de la page « Modifier ».

Les retouches (corriger une ligne, déplacer un bloc) s'appliquent au document
en mémoire ; chacune peut être annulée, et le tout s'enregistre en une fois.
Aucune interface ici : le module est testable sans écran.
"""

from __future__ import annotations

import os
from collections import deque

import pymupdf as fitz

import pdf_core as core


class Edition:
    """Document en cours de modification, avec sa pile d'annulations."""

    def __init__(self, doc: fitz.Document, source: str, origine_word: bool = False,
                 max_annulations: int = 20, max_octets: int = 300_000_000):
        self.doc = doc
        self.source = source            # fichier ouvert par l'utilisateur (PDF ou Word)
        self.origine_word = origine_word
        # Pile d'annulations : (copie du document, état qu'elle représente). Bornée en
        # nombre ET en taille : sur un gros fichier, on garde moins d'étapes plutôt
        # que d'épuiser la mémoire.
        self._annulations: deque[tuple[bytes, int]] = deque()
        self._max_annulations = max_annulations
        self._max_octets = max_octets
        self._octets = 0
        # Chaque état du document a un numéro : « modifié » = l'état courant n'est pas
        # celui du fichier enregistré (annuler jusqu'à lui efface donc le « • »).
        self._etat = 0
        self._prochain_etat = 1
        self._etat_enregistre = 0

    @property
    def modifie(self) -> bool:
        return self._etat != self._etat_enregistre

    @modifie.setter
    def modifie(self, valeur: bool) -> None:
        # Faux : l'état courant vient d'être enregistré. Vrai : il diffère de tout fichier.
        self._etat_enregistre = -1 if valeur else self._etat

    @property
    def peut_annuler(self) -> bool:
        return bool(self._annulations)

    def _retoucher(self, action):
        """Exécute `action()` ; garde un instantané si elle a changé le document.

        En cas d'erreur, le document est remis tel qu'avant puis l'erreur relancée.
        """
        instantane = self.doc.tobytes()
        try:
            resultat = action()
        except BaseException:
            self._recharger(instantane)
            raise
        if resultat:
            self._annulations.append((instantane, self._etat))
            self._octets += len(instantane)
            self._etat, self._prochain_etat = self._prochain_etat, self._prochain_etat + 1
            while len(self._annulations) > 1 and (len(self._annulations) > self._max_annulations
                                                  or self._octets > self._max_octets):
                self._octets -= len(self._annulations.popleft()[0])  # la plus ancienne tombe
        return resultat

    def _recharger(self, donnees: bytes) -> None:
        self.doc.close()
        self.doc = fitz.open("pdf", donnees)

    def corriger(self, page: int, point: fitz.Point, texte: str) -> bool:
        """Remplace la ligne sous `point` (repère affiché). Faux si rien n'a changé."""
        return self._retoucher(lambda: core.rewrite_line(self.doc, page, point, texte))

    def deplacer(self, page: int, rect: fitz.Rect, dx: float, dy: float) -> int:
        """Déplace les lignes de `rect` (repère affiché). Retourne le nombre de segments."""
        return self._retoucher(lambda: core.move_text_block(self.doc, page, rect, dx, dy))

    def remplacer(self, ancien: str, nouveau: str, casse: bool = False, progress=None) -> int:
        """Remplace partout `ancien` par `nouveau` ; retourne le nombre de remplacements.

        Peut tourner hors du thread de l'interface, pourvu que celle-ci ne touche
        pas au document pendant ce temps (voir Pagilis.lancer).
        """
        return self._retoucher(lambda: core.replace_text(self.doc, ancien, nouveau, range(self.doc.page_count),
                                                         casse, shrink_if_longer=True, progress=progress))

    # Gestion des pages (fonction « Pages »), annulable comme les retouches de texte.

    def pivoter(self, pages: list[int], angle: int) -> int:
        return self._retoucher(lambda: core.rotate_pages(self.doc, pages, angle))

    def supprimer(self, pages: list[int]) -> int:
        return self._retoucher(lambda: core.delete_pages(self.doc, pages))

    def deplacer_pages(self, pages: list[int], sens: int) -> list[int]:
        """Avance (-1) ou recule (1) les pages d'un cran ; retourne leurs nouveaux indices."""
        return self._retoucher(lambda: core.move_pages(self.doc, pages, sens))

    def inserer(self, chemin: str, apres: int | None = None) -> list[int]:
        """Insère un PDF après la page `apres` (à la fin si None) ; retourne les pages insérées."""
        return self._retoucher(lambda: core.insert_pdf(self.doc, chemin, apres))

    def annuler(self) -> fitz.Document:
        """Revient à l'état d'avant la dernière retouche. IndexError s'il n'y en a pas."""
        donnees, etat = self._annulations.pop()
        self._octets -= len(donnees)
        self._recharger(donnees)
        self._etat = etat
        return self.doc

    def nom_propose(self) -> str:
        """<nom>.pdf pour un Word, <nom>_modifie.pdf pour un PDF, dans le dossier source."""
        dossier, nom = os.path.split(self.source)
        base = os.path.splitext(nom)[0]
        return os.path.join(dossier, f"{base}.pdf" if self.origine_word else f"{base}_modifie.pdf")

    def enregistrer(self, chemin: str) -> None:
        ecrire_pdf(self.doc.tobytes(), chemin)
        self._etat_enregistre = self._etat


def ecrire_pdf(donnees: bytes, chemin: str) -> None:
    """Écrit un PDF à partir de ses octets (sûr depuis un autre thread).

    On enregistre une COPIE et jamais le document de travail : le nettoyage
    (garbage) de save_atomic renumérote les objets du document enregistré, et une
    police déjà insérée deviendrait illisible pour les retouches suivantes. Les
    octets sont pris dans le thread de l'interface ; ce thread-ci ne touche donc
    jamais au document affiché.
    """
    copie = fitz.open("pdf", donnees)
    try:
        core.save_atomic(copie, chemin)
    finally:
        copie.close()
