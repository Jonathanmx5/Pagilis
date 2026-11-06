# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aperçu de page partagé : rendu, navigation, zoom et interactions souris.

Les coordonnées échangées avec le reste de l'application sont des points PDF
dans le repère de la page AFFICHÉE (rotation /Rotate prise en compte) : le
rendu PyMuPDF est déjà orienté comme à l'écran, donc la conversion se réduit à
un facteur de zoom et au décalage du dessin dans le canevas.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk
import pymupdf as fitz
from PIL import Image, ImageTk

ZOOM_MIN, ZOOM_MAX = 0.2, 5.0
MARGE = 16  # marge autour de la page dans le canevas, en pixels


class Apercu(ctk.CTkFrame):
    """Affiche une page d'un document et transmet les gestes de la souris.

    Rappels (tous facultatifs) :
    - on_page(index) : la page affichée a changé (PAS appelé pour un zoom) ;
    - on_dessin(apercu) : dessiner les superpositions après chaque rendu ;
    - on_appui / on_glisse / on_relache(point) : gestes souris, point en repère affiché.
    """

    def __init__(self, master, occupe: Callable[[], bool] = lambda: False, **kwargs):
        super().__init__(master, **kwargs)
        self.occupe = occupe  # vrai pendant un traitement : PyMuPDF n'est pas thread-safe
        self.doc: Optional[fitz.Document] = None
        self.index = 0
        self.zoom = 1.0
        self.ajuster = True  # reste actif au redimensionnement
        self.decalage = (MARGE, MARGE)
        self._image_tk = None
        self._rendu_prevu = None
        self.on_page: Optional[Callable[[int], None]] = None
        self.on_dessin: Optional[Callable[["Apercu"], None]] = None
        self.on_appui = self.on_glisse = self.on_relache = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        barre = ctk.CTkFrame(self, fg_color="transparent")
        barre.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        self.bouton_prec = ctk.CTkButton(barre, text="◀", width=36, command=lambda: self.aller(self.index - 1))
        self.bouton_prec.pack(side="left")
        self.label_page = ctk.CTkLabel(barre, text="Aucun document", width=130)
        self.label_page.pack(side="left", padx=6)
        self.bouton_suiv = ctk.CTkButton(barre, text="▶", width=36, command=lambda: self.aller(self.index + 1))
        self.bouton_suiv.pack(side="left")
        ctk.CTkButton(barre, text="Ajuster", width=70, command=self.activer_ajuster).pack(side="right")
        ctk.CTkButton(barre, text="+", width=36, command=lambda: self.zoomer(1.25)).pack(side="right", padx=(4, 8))
        self.label_zoom = ctk.CTkLabel(barre, text="", width=52)
        self.label_zoom.pack(side="right")
        ctk.CTkButton(barre, text="−", width=36, command=lambda: self.zoomer(0.8)).pack(side="right", padx=4)

        self.canevas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.canevas.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        defil_v = ctk.CTkScrollbar(self, command=self.canevas.yview)
        defil_v.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        defil_h = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canevas.xview)
        defil_h.grid(row=2, column=0, sticky="ew", padx=(8, 0))
        self.canevas.configure(yscrollcommand=defil_v.set, xscrollcommand=defil_h.set)

        self.canevas.bind("<Configure>", lambda _e: self._planifier_rendu())
        self.canevas.bind("<Control-MouseWheel>", self._molette_zoom)
        self.canevas.bind("<MouseWheel>", lambda e: self.canevas.yview_scroll(-e.delta // 120, "units"))
        self.canevas.bind("<ButtonPress-1>", lambda e: self._souris(self.on_appui, e))
        self.canevas.bind("<B1-Motion>", lambda e: self._souris(self.on_glisse, e))
        self.canevas.bind("<ButtonRelease-1>", lambda e: self._souris(self.on_relache, e))
        self._appliquer_couleurs()
        self._mettre_a_jour_barre()

    # -------------------------------------------------------- document

    def charger(self, doc: Optional[fitz.Document]):
        """Affiche un nouveau document (ou rien), à la première page."""
        if self.doc is not None and self.doc is not doc:
            self.doc.close()
        self.doc = doc
        self.index = 0
        self.ajuster = True
        self._planifier_rendu()
        if self.on_page:
            self.on_page(self.index)

    @property
    def page(self) -> Optional[fitz.Page]:
        return self.doc[self.index] if self.doc is not None else None

    def aller(self, index: int):
        """Change de page (efface donc la sélection côté application via on_page)."""
        if self.doc is None or not 0 <= index < self.doc.page_count or index == self.index:
            return
        self.index = index
        self._planifier_rendu()
        if self.on_page:
            self.on_page(index)

    # ------------------------------------------------------------- zoom

    def zoomer(self, facteur: float):
        self.ajuster = False
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, self.zoom * facteur))
        self._planifier_rendu()

    def activer_ajuster(self):
        self.ajuster = True
        self._planifier_rendu()

    def _molette_zoom(self, event):
        self.zoomer(1.1 if event.delta > 0 else 1 / 1.1)

    # ------------------------------------------------------- conversions

    def vers_canevas(self, x: float, y: float) -> tuple[float, float]:
        """Point PDF (repère affiché) -> coordonnées du canevas."""
        return self.decalage[0] + x * self.zoom, self.decalage[1] + y * self.zoom

    def rect_canevas(self, rect) -> tuple[float, float, float, float]:
        r = fitz.Rect(rect)
        x0, y0 = self.vers_canevas(r.x0, r.y0)
        x1, y1 = self.vers_canevas(r.x1, r.y1)
        return x0, y0, x1, y1

    def vers_pdf(self, cx: float, cy: float) -> fitz.Point:
        """Coordonnées du canevas -> point PDF (repère affiché)."""
        return fitz.Point((cx - self.decalage[0]) / self.zoom, (cy - self.decalage[1]) / self.zoom)

    def _souris(self, rappel, event):
        if rappel and self.doc is not None:
            rappel(self.vers_pdf(self.canevas.canvasx(event.x), self.canevas.canvasy(event.y)))

    # ------------------------------------------------------------- rendu

    def _planifier_rendu(self):
        """Regroupe les demandes de rendu (redimensionnement continu, zoom rapide)."""
        if self._rendu_prevu is not None:
            self.after_cancel(self._rendu_prevu)
        self._rendu_prevu = self.after(40, self._rendre)

    def redessiner(self):
        """Redessine les superpositions sans refaire le rendu de la page."""
        self.canevas.delete("superposition")
        if self.on_dessin and self.doc is not None:
            self.on_dessin(self)

    def _rendre(self):
        self._rendu_prevu = None
        if self.occupe():
            # Un traitement tourne dans un autre thread : on réessaie plus tard.
            self._rendu_prevu = self.after(300, self._rendre)
            return
        self.canevas.delete("all")
        self._mettre_a_jour_barre()
        if self.doc is None:
            self.canevas.create_text(
                self.canevas.winfo_width() // 2, self.canevas.winfo_height() // 2,
                text="Ouvrez un PDF pour afficher l'aperçu", fill="gray55", font=("Segoe UI", 12))
            return
        largeur, hauteur = self.canevas.winfo_width(), self.canevas.winfo_height()
        if largeur < 20 or hauteur < 20:
            return  # onglet caché ou fenêtre en cours d'affichage : largeur de 1 px
        page = self.page
        if self.ajuster:
            self.zoom = max(ZOOM_MIN, min((largeur - 2 * MARGE) / page.rect.width,
                                          (hauteur - 2 * MARGE) / page.rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self._image_tk = ImageTk.PhotoImage(image)
        # Page centrée quand elle est plus petite que la zone visible.
        ox = max(MARGE, (largeur - pix.width) // 2)
        oy = max(MARGE, (hauteur - pix.height) // 2)
        self.decalage = (ox, oy)
        # Ombre légère sous la page.
        ombre = "#0d0d0d" if ctk.get_appearance_mode() == "Dark" else "#a8a8a8"
        self.canevas.create_rectangle(ox + 3, oy + 3, ox + pix.width + 3, oy + pix.height + 3,
                                      fill=ombre, outline="")
        self.canevas.create_image(ox, oy, image=self._image_tk, anchor="nw")
        self.canevas.configure(scrollregion=(0, 0, ox + pix.width + MARGE, oy + pix.height + MARGE))
        self.label_zoom.configure(text=f"{round(self.zoom * 100)} %")
        self.redessiner()

    def _mettre_a_jour_barre(self):
        if self.doc is None:
            self.label_page.configure(text="Aucun document")
            self.label_zoom.configure(text="")
        else:
            self.label_page.configure(text=f"Page {self.index + 1} / {self.doc.page_count}")
        n = self.doc.page_count if self.doc is not None else 0
        self.bouton_prec.configure(state="normal" if self.index > 0 else "disabled")
        self.bouton_suiv.configure(state="normal" if self.index < n - 1 else "disabled")

    def _appliquer_couleurs(self):
        """Fond du canevas accordé au thème clair / sombre."""
        sombre = ctk.get_appearance_mode() == "Dark"
        self.canevas.configure(bg="#1e1e1e" if sombre else "#d4d4d4")

    def changer_theme(self):
        self._appliquer_couleurs()
        self._planifier_rendu()
