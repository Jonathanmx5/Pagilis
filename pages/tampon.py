# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signature / Tampon : poser une image sur les pages, à la souris."""

from __future__ import annotations

import io
import os
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pymupdf as fitz
from PIL import Image, ImageTk

import pdf_core as core
from pages.base import PageFonction


class PageTampon(PageFonction):
    nom = "Signature / Tampon"
    icone = "✍"
    description = "Poser une signature ou un tampon image"

    def construire(self):
        self.image_tampon: str | None = None
        self.ratio_tampon = 0.5
        self._cache_tampon = (None, None)  # (clé, PhotoImage) de l'image en surimpression
        self._geste = None  # décalage du clic dans l'image pendant un glisser
        self.section("Image")
        ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkButton(ligne, text="Choisir…", width=90, command=self.choisir_tampon).pack(side="left")
        self.label_tampon = ctk.CTkLabel(ligne, text="Aucune image (PNG ou JPG)", anchor="w")
        self.label_tampon.pack(side="left", padx=8, fill="x", expand=True)
        self.blanc_transparent = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.cadre, text="Fond blanc transparent (signature scannée)",
                        variable=self.blanc_transparent).pack(anchor="w", padx=12, pady=4)

        self.section("Position sur la page")
        self.aide("Cliquez sur l'aperçu pour poser l'image, puis faites-la glisser. "
                  "Les valeurs sont en points (1/72 de pouce).")
        self.entree_x = self.champ("X (pt)", "72")
        self.entree_y = self.champ("Y (pt)", "72")
        self.entree_l = self.champ("Largeur (pt)", "150")
        for entree in (self.entree_x, self.entree_y, self.entree_l):
            entree.bind("<KeyRelease>", lambda _e: self.apercu.redessiner())
        self.entree_op = self.champ("Opacité (%)", "100")
        self.rotation_tampon = ctk.StringVar(value="0")
        ligne = ctk.CTkFrame(self.cadre, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text="Rotation (°)", width=130, anchor="w").pack(side="left")
        ctk.CTkSegmentedButton(ligne, values=["0", "90", "180", "270"], variable=self.rotation_tampon,
                               command=lambda _v: self.apercu.redessiner()).pack(side="left", fill="x", expand=True)

        self.section("Pages")
        self.portee_tampon = ctk.StringVar(value="page")
        for texte, valeur in (("Page affichée dans l'aperçu", "page"), ("Toutes les pages", "toutes"),
                              ("Plage :", "plage")):
            ctk.CTkRadioButton(self.cadre, text=texte, variable=self.portee_tampon,
                               value=valeur).pack(anchor="w", padx=12, pady=2)
        self.entree_plage_tampon = self.champ("", "")
        self.entree_plage_tampon.configure(placeholder_text="ex. 1, 3-5")
        self.continuer_tampon = self.case_continuer()
        self.bouton_action("Appliquer…", self.lancer_tampon)

    def choisir_tampon(self):
        chemin = filedialog.askopenfilename(initialdir=self.app.dernier_dossier,
                                            filetypes=[("Images", "*.png *.jpg *.jpeg")])
        if not chemin:
            return
        try:
            with Image.open(chemin) as im:
                self.ratio_tampon = im.height / im.width
        except OSError:
            return messagebox.showerror("Pagilis", "Image illisible.")
        self.image_tampon = chemin
        self.label_tampon.configure(text=os.path.basename(chemin))
        self.apercu.redessiner()

    def _rect_tampon(self) -> fitz.Rect | None:
        """Rectangle du tampon dans le repère affiché, d'après les champs."""
        try:
            x, y, largeur = (float(e.get()) for e in (self.entree_x, self.entree_y, self.entree_l))
        except ValueError:
            return None
        if self.rotation_tampon.get() in ("90", "270"):
            return fitz.Rect(x, y, x + largeur * self.ratio_tampon, y + largeur)
        return fitz.Rect(x, y, x + largeur, y + largeur * self.ratio_tampon)

    # ------------------------------------------------------- aperçu

    def dessiner(self, apercu):
        rect = self._rect_tampon()
        if not self.image_tampon or rect is None:
            return
        x0, y0, x1, y1 = apercu.rect_canevas(rect)
        taille = (max(1, int(x1 - x0)), max(1, int(y1 - y0)))
        cle = (self.image_tampon, taille, self.rotation_tampon.get(), self.blanc_transparent.get())
        if self._cache_tampon[0] != cle:
            image = Image.open(self.image_tampon).convert("RGBA")
            if self.blanc_transparent.get():
                image = Image.open(io.BytesIO(core._prepare_stamp_image(
                    self.image_tampon, core.StampOptions(0, 0, 1, white_transparent=True))))
            image = image.rotate(-int(self.rotation_tampon.get()), expand=True).resize(taille)
            self._cache_tampon = (cle, ImageTk.PhotoImage(image))
        apercu.canevas.create_image(x0, y0, image=self._cache_tampon[1], anchor="nw", tags="superposition")
        apercu.canevas.create_rectangle(x0, y0, x1, y1, outline="#1F6AA5", width=2, dash=(4, 2),
                                        tags="superposition")

    def appui(self, point):
        self._geste = None
        if not self.image_tampon:
            return self.app.statut("Choisissez d'abord une image.")
        rect = self._rect_tampon()
        if rect is None or not rect.contains(point):
            # Clic hors de l'image : on la centre sur le clic.
            largeur = float(self.entree_l.get() or 150)
            rect = self._rect_tampon() or fitz.Rect(0, 0, largeur, largeur * self.ratio_tampon)
            self.remplir(self.entree_x, max(0, point.x - rect.width / 2))
            self.remplir(self.entree_y, max(0, point.y - rect.height / 2))
            rect = self._rect_tampon()
        self._geste = point - rect.tl
        self.apercu.redessiner()

    def glisse(self, point):
        if self._geste is None:
            return
        self.remplir(self.entree_x, max(0, point.x - self._geste.x))
        self.remplir(self.entree_y, max(0, point.y - self._geste.y))
        self.apercu.redessiner()

    def relache(self, point):
        self._geste = None

    # ------------------------------------------------------- traitement

    def lancer_tampon(self):
        if not self.app.exiger_pdf():
            return
        if not self.image_tampon:
            return messagebox.showinfo("Pagilis", "Choisissez d'abord une image.")
        try:
            opts = core.StampOptions(
                x=float(self.entree_x.get()),
                y=float(self.entree_y.get()),
                width=float(self.entree_l.get()),
                opacity=float(self.entree_op.get()) / 100,
                rotation=int(self.rotation_tampon.get()),
                white_transparent=self.blanc_transparent.get(),
            )
        except ValueError:
            return messagebox.showwarning("Pagilis", "Vérifiez les valeurs numériques.")
        source = self.app.chemin_pdf
        image = self.image_tampon
        portee = self.portee_tampon.get()
        plage = self.entree_plage_tampon.get().strip()
        page_affichee = self.apercu.index
        if portee == "plage" and not plage:
            return messagebox.showwarning("Pagilis", "Indiquez la plage de pages.")
        sortie = self.app.enregistrer_sous("signe")
        if not sortie:
            return

        def travail(p):
            doc = core.open_pdf(source)
            try:
                if portee == "plage":
                    pages = core.parse_page_ranges(plage, doc.page_count)
                elif portee == "toutes":
                    pages = list(range(doc.page_count))
                else:
                    pages = [page_affichee]
                core.add_stamp(doc, image, pages, opts, p)
                core.save_atomic(doc, sortie)
                return len(pages)
            finally:
                doc.close()

        self.app.statut("Application du tampon…")
        self.app.lancer(travail, fin=lambda n: self.app.apres_sauvegarde(
            sortie, self.continuer_tampon, f"Tampon posé sur {n} page(s)."))
