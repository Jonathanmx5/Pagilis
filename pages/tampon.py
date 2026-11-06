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
import theme
from pages.base import PageFonction


class PageTampon(PageFonction):
    nom = "Signature / Tampon"
    libelle = "Signer"
    groupe = "Éditer"
    icone = "signer"
    description = "Poser une signature ou un tampon sur les pages."

    def construire(self):
        self.image_tampon: str | None = None
        self.ratio_tampon = 0.5
        self._cache_tampon = (None, None)  # (clé, PhotoImage) de l'image en surimpression
        self._geste = None  # décalage du clic dans l'image pendant un glisser
        self.section("Image")
        ligne = self.ligne()
        theme.bouton(ligne, "Choisir une image…", self.choisir_tampon, icone_nom="ouvrir").pack(side="left")
        self.label_tampon = ctk.CTkLabel(self.cadre, text="PNG ou JPG : signature scannée, tampon…",
                                         anchor="w", font=theme.police(12), text_color=theme.TEXTE_2,
                                         wraplength=260, justify="left")
        self.label_tampon.pack(fill="x", padx=16, pady=(2, 2))
        self.blanc_transparent = ctk.BooleanVar(value=True)
        self.case(self.cadre, "Rendre le fond blanc transparent", self.blanc_transparent,
                  commande=self.apercu.redessiner)

        self.section("Placement")
        self.aide("Cliquez sur la page pour poser l'image, puis faites-la glisser.")
        self.largeur = ctk.DoubleVar(value=150)
        self.curseur("Taille", 40, 500, self.largeur, commande=self.apercu.redessiner)
        self.opacite = ctk.DoubleVar(value=100)
        self.curseur("Opacité", 10, 100, self.opacite, suffixe=" %")
        self.rotation_tampon = ctk.StringVar(value="0°")
        self.segments("Rotation", ["0°", "90°", "180°", "270°"], self.rotation_tampon,
                      commande=lambda _v: self.apercu.redessiner())

        self.section("Pages")
        self.portee_tampon = ctk.StringVar(value="page")
        for texte, valeur in (("Page affichée", "page"), ("Toutes les pages", "toutes"),
                              ("Ces pages :", "plage")):
            self.radio(self.cadre, texte, self.portee_tampon, valeur)
        self.entree_plage_tampon = self.champ("", "")
        self.entree_plage_tampon.configure(placeholder_text="1, 3-5")

        avance = self.options_avancees()
        self.aide("Position exacte du coin haut gauche, en points (1/72 de pouce).", parent=avance)
        self.entree_x = self.champ("Gauche", "72", parent=avance)
        self.entree_y = self.champ("Haut", "72", parent=avance)
        for entree in (self.entree_x, self.entree_y):
            entree.bind("<KeyRelease>", lambda _e: self.apercu.redessiner())
        self.bouton_action("Poser la signature", self.lancer_tampon, icone_nom="signer")

    def _rotation(self) -> int:
        return int(self.rotation_tampon.get().rstrip("°"))

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
        self.label_tampon.configure(text=os.path.basename(chemin), text_color=theme.TEXTE)
        self.apercu.redessiner()

    def _rect_tampon(self) -> fitz.Rect | None:
        """Rectangle du tampon dans le repère affiché, d'après les champs."""
        try:
            x, y = (float(e.get()) for e in (self.entree_x, self.entree_y))
            largeur = float(self.largeur.get())
        except ValueError:
            return None
        if self._rotation() in (90, 270):
            return fitz.Rect(x, y, x + largeur * self.ratio_tampon, y + largeur)
        return fitz.Rect(x, y, x + largeur, y + largeur * self.ratio_tampon)

    # ------------------------------------------------------- aperçu

    def dessiner(self, apercu):
        rect = self._rect_tampon()
        if not self.image_tampon or rect is None:
            return
        x0, y0, x1, y1 = apercu.rect_canevas(rect)
        taille = (max(1, int(x1 - x0)), max(1, int(y1 - y0)))
        cle = (self.image_tampon, taille, self._rotation(), self.blanc_transparent.get())
        if self._cache_tampon[0] != cle:
            image = Image.open(self.image_tampon).convert("RGBA")
            if self.blanc_transparent.get():
                image = Image.open(io.BytesIO(core._prepare_stamp_image(
                    self.image_tampon, core.StampOptions(0, 0, 1, white_transparent=True))))
            image = image.rotate(-self._rotation(), expand=True).resize(taille)
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
            largeur = float(self.largeur.get())
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
                width=float(self.largeur.get()),
                opacity=float(self.opacite.get()) / 100,
                rotation=self._rotation(),
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
            sortie, f"Signature posée sur {n} page(s)."))
