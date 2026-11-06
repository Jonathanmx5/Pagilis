# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pages qui retouchent la copie de travail (« Modifier », « Pages »).

Elles partagent la même copie (app.edition) : mêmes annulations (Ctrl+Z), un
seul enregistrement (Ctrl+S), et on passe de l'une à l'autre sans rien
enregistrer. Les autres fonctions lisent le fichier enregistré : les quitter
avec des retouches en cours propose de les enregistrer.
"""

from __future__ import annotations

import logging
import os
from tkinter import filedialog, messagebox

from edition import Edition, ecrire_pdf
from pages.base import PageFonction


class PageCopie(PageFonction):
    """Socle des pages qui retouchent la copie de travail."""

    utilise_copie = True

    @property
    def edition(self) -> Edition | None:
        return self.app.edition

    # ------------------------------------------------------- à redéfinir

    def interrompre(self) -> None:
        """Abandonne une saisie en cours avant une annulation ou un enregistrement."""

    def edition_changee(self) -> None:
        """La copie de travail a changé (retouche, annulation, nouveau document)."""

    def raccourcis_permis(self) -> bool:
        return True

    # ------------------------------------------------------- crochets communs

    def document_charge(self):
        self.maj_etat()

    def peut_quitter(self, vers: PageFonction) -> bool:
        if getattr(vers, "utilise_copie", False) or self.edition is None:
            return True  # même copie de travail : rien à enregistrer pour changer de page
        if self.app.occupe():
            return False
        self.interrompre()
        return self.confirmer_abandon(abandonner=True)

    def touche_annuler(self):
        self._raccourci(self.annuler_retouche)

    def touche_enregistrer(self):
        self._raccourci(self.enregistrer_edition)

    def _raccourci(self, action):
        if self.raccourcis_permis() and not self.app.travaux_en_cours:
            action()

    # ------------------------------------------------------- retouches

    def retoucher(self, action):
        """Applique une retouche de la copie de travail et rafraîchit l'aperçu."""
        try:
            resultat = action()
        except Exception as exc:  # noqa: BLE001 - la copie de travail est déjà restaurée
            from pdf_core import PagilisError
            if isinstance(exc, PagilisError):
                messagebox.showwarning("Pagilis", str(exc))
            else:
                logging.exception("Retouche impossible")
                messagebox.showerror("Pagilis", "Retouche impossible, le document n'a pas changé.")
            resultat = None
        self.apercu.remplacer(self.edition.doc)
        self.maj_etat()
        return resultat

    def maj_etat(self):
        """Annuler / Enregistrer de la barre du haut, pastille et titre (« • » = non enregistré)."""
        ed = self.edition
        self.app.bouton_annuler.configure(state="normal" if ed and ed.peut_annuler else "disabled")
        self.app.bouton_enregistrer.configure(state="normal" if ed and ed.modifie else "disabled")
        self.app.afficher_non_enregistre(bool(ed and ed.modifie))
        for page in self.app.fonctions.values():
            if isinstance(page, PageCopie):
                page.edition_changee()
        if ed and ed.modifie:
            self.app.title(f"Pagilis • {os.path.basename(ed.source)}")
        else:
            self.app.title("Pagilis")

    def annuler_retouche(self):
        if self.edition is None or not self.edition.peut_annuler or self.app.travaux_en_cours:
            return
        self.interrompre()
        self.retoucher(self.edition.annuler)
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
        self.interrompre()
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
