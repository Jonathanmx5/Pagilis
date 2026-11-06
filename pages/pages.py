# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pages : pivoter, supprimer, réordonner, insérer et extraire des pages.

Les vignettes de toutes les pages s'affichent à gauche ; l'aperçu montre la
page cliquée. Les actions retouchent la copie de travail, comme « Modifier ».
"""

from __future__ import annotations

import logging
import os
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pymupdf as fitz
from PIL import Image

import pdf_core as core
from pages.copie import PageCopie

LARGEUR_VIGNETTE = 140  # pixels
COULEUR_CHOISIE = ("#3B8ED0", "#1F6AA5")


def _plages(indices: list[int]) -> str:
    """[0, 1, 2, 4] -> « 1-3,5 » (numéros de page affichés)."""
    morceaux, debut = [], None
    for k, i in enumerate(indices):
        if debut is None:
            debut = i
        if k + 1 == len(indices) or indices[k + 1] != i + 1:
            morceaux.append(f"{debut + 1}" if debut == i else f"{debut + 1}-{i + 1}")
            debut = None
    return ",".join(morceaux)


class PageGestionPages(PageCopie):
    nom = "Pages"
    libelle = "Pages"
    groupe = "Éditer"
    icone = "pages"
    description = "Pivoter, supprimer, réordonner, insérer ou extraire des pages."

    def construire(self):
        self.selection: set[int] = set()
        self._ancre: int | None = None   # point de départ d'une sélection avec Maj
        self.vignettes: list[ctk.CTkFrame] = []
        self._images: list[ctk.CTkImage] = []
        self._a_redessiner = True
        self.section("Pages sélectionnées")
        self.aide("Clic : choisir une page. Ctrl+clic : en ajouter. Maj+clic : une suite de pages.")
        ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        for texte, commande in (("↺", lambda: self.tourner(-90)), ("↻", lambda: self.tourner(90)),
                                ("▲", lambda: self.deplacer(-1)), ("▼", lambda: self.deplacer(1))):
            ctk.CTkButton(ligne, text=texte, width=44, command=commande).pack(side="left", padx=(0, 6))
        ctk.CTkButton(ligne, text="Supprimer", width=90, fg_color="#C92A2A", hover_color="#A61E1E",
                      command=self.supprimer).pack(side="left")
        ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=(6, 2))
        ctk.CTkButton(ligne, text="Insérer un PDF…", command=self.inserer).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(ligne, text="Extraire…", command=self.extraire).pack(side="left", fill="x", expand=True)
        self.section("Toutes les pages")
        self.grille = ctk.CTkFrame(self.cadre, fg_color="transparent")
        self.grille.pack(fill="x", padx=8, pady=(0, 12))

    # ------------------------------------------------------- vignettes

    def montree(self):
        if self._a_redessiner:
            self._dessiner_vignettes()

    def edition_changee(self):
        self._a_redessiner = True
        if self.app.page_active == self.nom:
            self._dessiner_vignettes()

    def document_charge(self):
        self.selection.clear()
        self._ancre = None
        super().document_charge()

    def _dessiner_vignettes(self):
        """Une vignette par page de la copie de travail, deux par ligne."""
        if self.app.travaux_en_cours:
            return  # PyMuPDF ne doit pas travailler sur deux threads ; on redessinera après
        for enfant in self.grille.winfo_children():
            enfant.destroy()
        self.vignettes, self._images = [], []
        self._a_redessiner = False
        doc = self.edition.doc if self.edition else None
        if doc is None:
            self.aide("Ouvrez un PDF pour voir ses pages.", parent=self.grille)
            return
        self.selection = {i for i in self.selection if i < doc.page_count}
        for i, page in enumerate(doc):
            echelle = LARGEUR_VIGNETTE / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(echelle, echelle), alpha=False)
            image = ctk.CTkImage(Image.frombytes("RGB", (pix.width, pix.height), pix.samples),
                                 size=(pix.width, pix.height))
            cellule = ctk.CTkFrame(self.grille, corner_radius=8, border_width=0)
            cellule.grid(row=i // 2, column=i % 2, padx=4, pady=4, sticky="n")
            vignette = ctk.CTkLabel(cellule, image=image, text="")
            vignette.pack(padx=6, pady=(6, 0))
            numero = ctk.CTkLabel(cellule, text=str(i + 1))
            numero.pack(pady=(0, 4))
            for widget in (vignette, numero):
                # état du clic : 0x4 = Ctrl, 0x1 = Maj
                widget.bind("<Button-1>", lambda e, i=i: self.cliquer(
                    i, ctrl=bool(e.state & 0x4), maj=bool(e.state & 0x1)))
            self.vignettes.append(cellule)
            self._images.append(image)
        self._marquer_selection()

    def _marquer_selection(self):
        for i, cellule in enumerate(self.vignettes):
            cellule.configure(fg_color=COULEUR_CHOISIE if i in self.selection else "transparent")

    def cliquer(self, index: int, ctrl: bool = False, maj: bool = False):
        """Sélection à la souris : simple, ajout (Ctrl) ou suite (Maj)."""
        if maj and self._ancre is not None:
            debut, fin = sorted((self._ancre, index))
            self.selection = set(range(debut, fin + 1))
        elif ctrl:
            self.selection ^= {index}
            self._ancre = index
        else:
            self.selection = {index}
            self._ancre = index
        self._marquer_selection()
        self.apercu.aller(index)

    def _choisies(self) -> list[int] | None:
        if self.edition is None:
            self.app.exiger_pdf()
            return None
        if not self.selection:
            self.app.statut("Sélectionnez d'abord une ou plusieurs pages.")
            return None
        return sorted(self.selection)

    # ------------------------------------------------------- actions

    def tourner(self, angle: int):
        pages = self._choisies()
        if pages and self.retoucher(lambda: self.edition.pivoter(pages, angle)):
            self.app.statut(f"{len(pages)} page(s) pivotée(s).")

    def supprimer(self):
        pages = self._choisies()
        if pages and self.retoucher(lambda: self.edition.supprimer(pages)):
            # On garde une page sélectionnée là où étaient les pages supprimées.
            reste = self.edition.doc.page_count
            self.selection = {min(pages[0], reste - 1)}
            self._ancre = None
            self._dessiner_vignettes()
            self.app.statut(f"{len(pages)} page(s) supprimée(s).")

    def deplacer(self, sens: int):
        pages = self._choisies()
        if not pages:
            return
        nouvelles = self.retoucher(lambda: self.edition.deplacer_pages(pages, sens))
        if nouvelles:
            self.selection = set(nouvelles)
            self._ancre = None
            self._marquer_selection()
            self.apercu.aller(nouvelles[0])

    def inserer(self):
        if self.edition is None:
            return self.app.exiger_pdf()
        chemin = filedialog.askopenfilename(initialdir=self.app.dernier_dossier, filetypes=[("PDF", "*.pdf")])
        if not chemin:
            return
        apres = max(self.selection) if self.selection else None
        while True:
            try:
                nouvelles = self.edition.inserer(chemin, apres)
                break
            except core.PasswordRequired:
                if not self.app.demander_mot_de_passe(chemin):
                    return self.app.statut("Insertion annulée : mot de passe requis.")
            except Exception:  # noqa: BLE001 - PDF illisible : la copie de travail est intacte
                logging.exception("Insertion impossible : %s", chemin)
                return messagebox.showerror("Pagilis", f"Impossible d'insérer « {os.path.basename(chemin)} ».")
        self.apercu.remplacer(self.edition.doc)
        self.selection = set(nouvelles)
        self._ancre = None
        self.maj_etat()
        self.apercu.aller(nouvelles[0])
        self.app.statut(f"{len(nouvelles)} page(s) insérée(s) depuis « {os.path.basename(chemin)} ».")

    def extraire(self):
        """Enregistre les pages sélectionnées dans un nouveau PDF ; le document ne change pas."""
        pages = self._choisies()
        if not pages:
            return
        base = os.path.splitext(os.path.basename(self.app.chemin_pdf or "document"))[0]
        sortie = filedialog.asksaveasfilename(
            initialdir=self.app.dernier_dossier, initialfile=f"{base}_pages_{_plages(pages)}.pdf",
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not sortie:
            return
        donnees = self.edition.doc.tobytes()  # lu ici : le traitement ne touche pas au document affiché

        def travail(_p):
            doc = fitz.open("pdf", donnees)
            try:
                return core.extract_pages(doc, pages, sortie)
            finally:
                doc.close()

        self.app.statut("Extraction…")
        self.app.lancer(travail, fin=lambda n: (self.app.statut(f"{n} page(s) extraite(s)."),
                                                  self.app.proposer_ouverture(sortie)))
