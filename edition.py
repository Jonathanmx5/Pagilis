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
                 max_annulations: int = 20):
        self.doc = doc
        self.source = source            # fichier ouvert par l'utilisateur (PDF ou Word)
        self.origine_word = origine_word
        self.modifie = False
        self._annulations: deque[bytes] = deque(maxlen=max_annulations)

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
            self._annulations.append(instantane)
            self.modifie = True
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

    def annuler(self) -> fitz.Document:
        """Revient à l'état d'avant la dernière retouche. IndexError s'il n'y en a pas."""
        self._recharger(self._annulations.pop())
        self.modifie = True
        return self.doc

    def nom_propose(self) -> str:
        """<nom>.pdf pour un Word, <nom>_modifie.pdf pour un PDF, dans le dossier source."""
        dossier, nom = os.path.split(self.source)
        base = os.path.splitext(nom)[0]
        return os.path.join(dossier, f"{base}.pdf" if self.origine_word else f"{base}_modifie.pdf")

    def enregistrer(self, chemin: str) -> None:
        ecrire_pdf(self.doc.tobytes(), chemin)
        self.modifie = False


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
