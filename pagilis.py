# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fenêtre principale de Pagilis (CustomTkinter).

Elle porte la barre latérale, le document ouvert, l'aperçu partagé, la barre
d'état et les traitements en arrière-plan. Chaque fonction de la barre
latérale est une page du dossier pages/ ; la logique PDF est dans pdf_core.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
import pymupdf as fitz

import conversion
import fenetres
import identite
import installation
import pdf_core as core
import theme
import updater
from apercu import Apercu
from edition import Edition
from pages import PAGES
from pages.base import PageFonction

# Dossier de configuration et journal, indispensables avec --noconsole.
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
DOSSIER_DONNEES = os.path.join(_LOCALAPPDATA, identite.DOSSIER_DONNEES)
os.makedirs(DOSSIER_DONNEES, exist_ok=True)
CONFIG = os.path.join(DOSSIER_DONNEES, "config.json")
JOURNAL = os.path.join(DOSSIER_DONNEES, "pagilis.log")


def _installer_journal() -> None:
    """Journal limité à 3 fichiers de 1 Mo (pagilis.log, .1, .2, .3) : il ne grossit pas sans fin."""
    racine = logging.getLogger()
    if any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == os.path.abspath(JOURNAL)
           for h in racine.handlers):
        return
    fichier = logging.handlers.RotatingFileHandler(JOURNAL, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fichier.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    racine.addHandler(fichier)
    racine.setLevel(logging.INFO)


_installer_journal()


def charger_config() -> dict:
    """Lit les préférences ; retourne des valeurs par défaut si absentes."""
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def sauver_config(config: dict) -> None:
    """Écrit les préférences sans jamais faire planter l'application."""
    try:
        with open(CONFIG, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)
    except OSError:
        logging.exception("Impossible d'écrire la configuration")


# Fonctions de la barre latérale : (clé, libellé, description).
FONCTIONS = [(p.nom, p.libelle, p.description) for p in PAGES]


class Pagilis(ctk.CTk):
    """Fenêtre principale : fonctions dans une barre à gauche, page de travail à droite."""

    def __init__(self):
        theme.appliquer()  # apparence sombre fixe ; un ancien réglage « apparence » est ignoré
        super().__init__(fg_color=theme.FOND)
        self.title(identite.NOM_AFFICHE)
        theme.poser_icone(self)
        # Une erreur imprévue dans un clic ou un bouton : journalisée et signalée,
        # au lieu de se perdre (l'exe n'a pas de console).
        self.report_callback_exception = self._erreur_interface
        self.geometry("1280x780")
        self.minsize(1080, 640)
        self.config_data = charger_config()
        self.dossier_donnees = DOSSIER_DONNEES
        self.dernier_dossier = self.config_data.get("dernier_dossier", os.path.expanduser("~"))
        self.chemin_pdf: str | None = None
        # Copie de travail du document affiché (retouches de « Modifier » et « Pages »).
        self.edition: Edition | None = None
        # PDF issus des conversions Word de la session ; dossier supprimé à la fermeture.
        self.dossier_conversions = tempfile.mkdtemp(prefix="pagilis-word-")
        self.page_active = FONCTIONS[0][0]
        # Nombre de traitements en cours : la mise à jour est bloquée tant qu'il est > 0,
        # et l'aperçu ne rend rien (PyMuPDF n'est pas thread-safe).
        self.travaux_en_cours = 0

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._construire_barre_haut()
        self._construire_barre_laterale()

        # Zone de travail : panneau de la fonction à gauche, document à droite.
        principal = ctk.CTkFrame(self, fg_color=theme.FOND, corner_radius=0)
        principal.grid(row=1, column=1, sticky="nsew")
        principal.grid_columnconfigure(1, weight=1)
        principal.grid_rowconfigure(0, weight=1)

        # Aperçu partagé par toutes les fonctions.
        self.apercu = Apercu(principal, occupe=lambda: self.travaux_en_cours > 0, corner_radius=0,
                             fg_color=theme.DOCUMENT)
        self.apercu.grid(row=0, column=1, sticky="nsew")
        self.apercu.on_page = self._page_changee
        self.apercu.on_dessin = self._dessiner_superpositions
        self.apercu.on_appui = self._souris_appui
        self.apercu.on_glisse = self._souris_glisse
        self.apercu.on_relache = self._souris_relache
        # Écran d'accueil, à la place du document tant qu'aucun n'est ouvert.
        self.accueil = ctk.CTkFrame(principal, fg_color=theme.DOCUMENT, corner_radius=0)
        self.accueil.grid(row=0, column=1, sticky="nsew")
        self.boutons_recents: list[str] = []

        # Un panneau (défilant) par fonction ; un seul est visible à la fois.
        self.pages: dict[str, ctk.CTkScrollableFrame] = {}
        self.fonctions: dict[str, PageFonction] = {}
        for classe in PAGES:
            cadre = ctk.CTkScrollableFrame(principal, corner_radius=0, width=300, fg_color=theme.SURFACE,
                                           scrollbar_button_color=theme.SURFACE_3,
                                           scrollbar_button_hover_color=theme.BORDURE)
            cadre.grid_columnconfigure(0, weight=1)
            self.pages[classe.nom] = cadre
            self.fonctions[classe.nom] = classe(self, cadre)
        self.modifier = self.fonctions["Modifier"]

        # Barre d'état : message, progression.
        etat = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, height=30)
        etat.grid(row=2, column=0, columnspan=2, sticky="ew")
        etat.grid_columnconfigure(0, weight=1)
        self.etat = ctk.CTkLabel(etat, text="Prêt", anchor="w", font=theme.police(12), text_color=theme.TEXTE_2)
        self.etat.grid(row=0, column=0, sticky="w", padx=14, pady=4)
        self.zone_actions = ctk.CTkFrame(etat, fg_color="transparent", height=26, width=1)
        self.zone_actions.grid(row=0, column=1, sticky="e")
        self.actions_notification = {}
        self.barre = ctk.CTkProgressBar(etat, width=200, height=6, progress_color=theme.ACCENT,
                                        fg_color=theme.SURFACE_2)
        self.barre.set(0)
        self.barre.grid(row=0, column=2, sticky="e", padx=14)
        self.barre.grid_remove()  # réapparaît pendant les traitements

        self.afficher_accueil()
        derniere = self.config_data.get("derniere_page")
        self.afficher_page(derniere if derniere in self.pages else FONCTIONS[0][0])
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        # Ctrl+Z / Ctrl+S pour la page affichée (minuscule et majuscule : verrouillage).
        for touche in ("<Control-z>", "<Control-Z>"):
            self.bind(touche, lambda _e: self.fonctions[self.page_active].touche_annuler())
        for touche in ("<Control-s>", "<Control-S>"):
            self.bind(touche, lambda _e: self.fonctions[self.page_active].touche_enregistrer())
        for touche in ("<Control-o>", "<Control-O>"):
            self.bind(touche, lambda _e: self.choisir_pdf())
        # Vérification au démarrage, hors thread de l'interface : rien ne se passe si à jour.
        # La version ignorée est lue ici, dans le thread de l'interface.
        # Seules les versions publiées pour tous sont proposées, jamais les bêtas
        # (un ancien réglage « canal_beta » est ignoré).
        version_ignoree = self.config_data.get("version_ignoree")
        threading.Thread(target=self._chercher_mise_a_jour, args=(version_ignoree,), daemon=True).start()

    # ------------------------------------------------- barre du haut

    def _construire_barre_haut(self):
        """Nom de l'application, document ouvert et actions sur le document."""
        barre = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, height=52)
        barre.grid(row=0, column=0, columnspan=2, sticky="ew")
        barre.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(barre, text=f"  {identite.NOM_AFFICHE}", image=theme.logo(26), compound="left",
                     font=theme.police(16, gras=True), text_color=theme.TEXTE).grid(row=0, column=0, padx=(16, 18), pady=10)
        ctk.CTkFrame(barre, width=1, height=22, fg_color=theme.BORDURE).grid(row=0, column=1)
        ctk.CTkLabel(barre, text="", image=theme.icone("document", 16, theme.TEXTE_2)).grid(
            row=0, column=2, padx=(16, 6))
        fichier = ctk.CTkFrame(barre, fg_color="transparent")
        fichier.grid(row=0, column=3, sticky="w")
        self.label_fichier = ctk.CTkLabel(fichier, text="Aucun fichier ouvert", font=theme.police(13),
                                          text_color=theme.TEXTE)
        self.label_fichier.pack(side="left")
        # Pastille affichée tant que des retouches ne sont pas enregistrées.
        self.pastille = ctk.CTkLabel(fichier, text="Non enregistré", font=theme.police(11, gras=True),
                                     fg_color=theme.ALERTE_FOND, text_color=theme.ALERTE_TEXTE,
                                     corner_radius=6, height=22, padx=8)
        self.bouton_annuler = theme.bouton(barre, icone_nom="annuler", style="discret", state="disabled",
                                           bulle="Annuler la dernière retouche (Ctrl+Z)",
                                           commande=lambda: self.modifier.annuler_retouche())
        self.bouton_annuler.grid(row=0, column=4, padx=4)
        theme.bouton(barre, "Ouvrir", self.choisir_pdf, style="secondaire", icone_nom="ouvrir",
                     bulle="Ouvrir un PDF ou un document Word (Ctrl+O)").grid(
            row=0, column=5, padx=4)
        self.bouton_enregistrer = theme.bouton(barre, "Enregistrer", style="principal", icone_nom="enregistrer",
                                               bulle="Enregistrer les retouches (Ctrl+S)",
                                               state="disabled", commande=lambda: self.modifier.enregistrer_edition())
        self.bouton_enregistrer.grid(row=0, column=6, padx=(4, 16))
        theme.activer(self.bouton_enregistrer, False, "principal")

    def afficher_non_enregistre(self, oui: bool):
        if oui:
            self.pastille.pack(side="left", padx=(10, 0))
        else:
            self.pastille.pack_forget()

    # ------------------------------------------------- barre latérale

    def _construire_barre_laterale(self):
        barre = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color=theme.SURFACE)
        barre.grid(row=1, column=0, sticky="nsw")
        barre.grid_propagate(False)
        barre.grid_columnconfigure(0, weight=1)
        # Séparation discrète avec la zone de travail.
        ctk.CTkFrame(self, width=1, fg_color=theme.BORDURE, corner_radius=0).grid(row=1, column=0, sticky="nse")

        self.boutons_nav: dict[str, ctk.CTkButton] = {}
        rang, groupe = 0, None
        for classe in PAGES:
            if classe.groupe != groupe:
                groupe = classe.groupe
                ctk.CTkLabel(barre, text=groupe, font=theme.police(11, gras=True), text_color=theme.TEXTE_DISCRET,
                             anchor="w").grid(row=rang, column=0, sticky="ew", padx=22, pady=(18 if rang else 14, 4))
                rang += 1
            bouton = ctk.CTkButton(
                barre, text=classe.libelle, anchor="w", height=36, corner_radius=6, font=theme.police(13),
                image=theme.icone(classe.icone, 16, theme.TEXTE_2), compound="left",
                fg_color="transparent", text_color=theme.TEXTE, hover_color=theme.SURFACE_2,
                command=lambda n=classe.nom: self.afficher_page(n),
            )
            bouton.grid(row=rang, column=0, sticky="ew", padx=10, pady=1)
            self.boutons_nav[classe.nom] = bouton
            rang += 1

        # Pousse le bas de la barre (installation, version) tout en bas.
        barre.grid_rowconfigure(rang, weight=1)
        # Version portable lancée : on propose de l'installer sur le PC.
        if installation.exe_courant() and not installation.tourne_depuis_installation():
            texte = "Réinstaller sur ce PC" if installation.est_installe() else "Installer sur ce PC"
            theme.bouton(barre, texte, self.proposer_installation, style="secondaire").grid(
                row=rang + 1, column=0, sticky="ew", padx=14, pady=(0, 8))
        ctk.CTkLabel(barre, text=f"Version {updater.APP_VERSION}", font=theme.police(11),
                     text_color=theme.TEXTE_DISCRET, anchor="w").grid(row=rang + 2, column=0, sticky="ew",
                                                                      padx=22, pady=(0, 12))

    def proposer_installation(self):
        fenetres.proposer_installation(self)

    # ------------------------------------------------- accueil

    def afficher_accueil(self):
        """Invitation à ouvrir un document, et les derniers fichiers ouverts."""
        for enfant in self.accueil.winfo_children():
            enfant.destroy()
        centre = ctk.CTkFrame(self.accueil, fg_color="transparent")
        centre.place(relx=0.5, rely=0.42, anchor="center")
        ctk.CTkLabel(centre, text="", image=theme.logo(84)).pack(pady=(0, 16))
        ctk.CTkLabel(centre, text="Ouvrez un document pour commencer", font=theme.police(20, gras=True),
                     text_color=theme.TEXTE).pack()
        ctk.CTkLabel(centre, text="Un PDF ou un document Word. Raccourci : Ctrl+O.", font=theme.police(13),
                     text_color=theme.TEXTE_2).pack(pady=(4, 18))
        theme.bouton(centre, "Ouvrir un fichier", self.choisir_pdf, style="principal", icone_nom="ouvrir",
                     hauteur=40, largeur=220).pack()
        self.boutons_recents = [c for c in self.config_data.get("recents", []) if os.path.isfile(c)][:6]
        if self.boutons_recents:
            ctk.CTkLabel(centre, text="Récents", font=theme.police(13, gras=True), text_color=theme.TEXTE,
                         anchor="w").pack(fill="x", pady=(28, 6))
            for chemin in self.boutons_recents:
                ligne = ctk.CTkButton(
                    centre, text=f"{os.path.basename(chemin)}    {os.path.dirname(chemin)}", anchor="w",
                    width=420, height=34, corner_radius=6, font=theme.police(13), fg_color="transparent",
                    hover_color=theme.SURFACE_2, text_color=theme.TEXTE,
                    image=theme.icone("document", 16, theme.TEXTE_2), compound="left",
                    command=lambda c=chemin: self.ouvrir_document(c))
                ligne.pack(fill="x")
        self.accueil.grid()
        self.accueil.tkraise()

    def _retenir_recent(self, chemin: str):
        recents = [c for c in self.config_data.get("recents", []) if os.path.normcase(c) != os.path.normcase(chemin)]
        self.config_data["recents"] = [chemin] + recents[:9]

    def afficher_page(self, nom: str):
        """Affiche le panneau d'une fonction et met en évidence son bouton."""
        if nom != self.page_active and not self.fonctions[self.page_active].peut_quitter(self.fonctions[nom]):
            return
        for autre, page in self.pages.items():
            if autre != nom:
                page.grid_forget()
        self.pages[nom].grid(row=0, column=0, sticky="nsew")
        self.page_active = nom
        self.apercu.redessiner()
        for autre, bouton in self.boutons_nav.items():
            choisi = autre == nom
            classe = type(self.fonctions[autre])
            bouton.configure(
                fg_color=theme.ACCENT_DOUX if choisi else "transparent",
                image=theme.icone(classe.icone, 16, theme.TEXTE if choisi else theme.TEXTE_2),
                font=theme.police(13, gras=choisi),
            )
        self.config_data["derniere_page"] = nom
        self.fonctions[nom].montree()

    # ------------------------------------------------------ mises à jour

    def _chercher_mise_a_jour(self, version_ignoree: str | None):
        mise_a_jour = updater.check_for_update()
        # « Ne plus me proposer cette version » : on se tait pour CETTE version seulement.
        if mise_a_jour and mise_a_jour.version != version_ignoree:
            self.after(0, lambda: self._popup_mise_a_jour(mise_a_jour))

    def _popup_mise_a_jour(self, mise_a_jour: updater.Update):
        fenetres.popup_mise_a_jour(self, mise_a_jour)

    def _erreur_interface(self, type_erreur, erreur, trace):
        logging.error("Erreur inattendue dans l'interface", exc_info=(type_erreur, erreur, trace))
        try:
            messagebox.showerror(identite.NOM_AFFICHE, "Une erreur inattendue s'est produite : la dernière "
                                 "action n'a peut-être pas abouti. Détails dans pagilis.log.")
        except Exception:  # noqa: BLE001 - la fenêtre peut être en train de se fermer
            pass

    def sauver_preferences(self):
        sauver_config(self.config_data)

    # ------------------------------------------------------ document ouvert

    def occupe(self) -> bool:
        """Vrai (et le dit) si un traitement tourne : le document ne doit pas changer."""
        if self.travaux_en_cours:
            self.statut("Traitement en cours, patientez…")
            return True
        return False

    def _fermer(self):
        if self.occupe() or not self.modifier.confirmer_abandon():
            return
        self.config_data["dernier_dossier"] = self.dernier_dossier
        sauver_config(self.config_data)
        shutil.rmtree(self.dossier_conversions, ignore_errors=True)
        self.destroy()

    def memoriser_dossier(self, chemin: str):
        self.dernier_dossier = os.path.dirname(chemin)

    def choisir_pdf(self):
        chemin = filedialog.askopenfilename(
            initialdir=self.dernier_dossier,
            filetypes=[("PDF et Word", "*.pdf *.docx *.doc *.rtf *.odt"), ("PDF", "*.pdf")],
        )
        if chemin:
            self.memoriser_dossier(chemin)
            self.ouvrir_document(chemin)

    def ouvrir_document(self, chemin: str):
        """Ouvre un PDF, ou convertit d'abord un Word en PDF (en arrière-plan)."""
        if self.occupe() or not self.modifier.confirmer_abandon():
            return
        if not conversion.est_word(chemin):
            if self.charger_fichier(chemin):
                self._retenir_recent(chemin)
            return
        dossier = self.dossier_conversions

        def fin(pdf: str):
            if self.charger_fichier(pdf):
                self.edition = Edition(self.apercu.doc, chemin, origine_word=True)
                self.label_fichier.configure(text=os.path.basename(chemin))
                self._retenir_recent(chemin)

        self.statut("Conversion du document Word…")
        self.lancer(lambda _p: conversion.word_vers_pdf(chemin, dossier), fin=fin)

    def demander_mot_de_passe(self, chemin: str) -> bool:
        """Demande le mot de passe d'un PDF chiffré et le mémorise. Faux si annulé."""
        mot_de_passe = simpledialog.askstring(
            "PDF protégé", f"« {os.path.basename(chemin)} » est protégé.\nMot de passe :",
            show="•", parent=self)
        if not mot_de_passe:
            return False
        core.remember_password(chemin, mot_de_passe)
        return True

    def charger_fichier(self, chemin: str) -> bool:
        """Ouvre un PDF dans l'aperçu ; demande le mot de passe s'il est chiffré. Vrai si ouvert."""
        while True:
            try:
                doc = core.open_pdf(chemin)
                break
            except core.PasswordRequired:
                if not self.demander_mot_de_passe(chemin):
                    self.statut("Ouverture annulée : mot de passe requis.")
                    return False
                # Un mot de passe faux relève PasswordRequired : on redemande.
            except Exception:  # noqa: BLE001 - fichier illisible, on le dit sans planter
                logging.exception("Ouverture impossible : %s", chemin)
                messagebox.showerror(identite.NOM_AFFICHE, f"Impossible d'ouvrir « {os.path.basename(chemin)} ».")
                return False
        self.chemin_pdf = chemin
        self.label_fichier.configure(text=os.path.basename(chemin))
        self.apercu.charger(doc)
        self.accueil.grid_remove()
        self._effacer_actions()
        # Nouvelle copie de travail (page « Modifier ») sur le document affiché.
        self.edition = Edition(doc, chemin)
        for page in self.fonctions.values():
            page.document_charge()
        self.statut(f"Fichier ouvert : {os.path.basename(chemin)} ({doc.page_count} page(s))")
        return True

    def statut(self, texte: str):
        self.etat.configure(text=texte)
        logging.info(texte)

    def exiger_pdf(self) -> bool:
        if not self.chemin_pdf:
            messagebox.showinfo(identite.NOM_AFFICHE, "Ouvrez d'abord un PDF (bouton en haut à droite).")
            return False
        return True

    # ------------------------------------------------- traitements en arrière-plan

    def lancer(self, travail, fin=None, toujours=None):
        """Exécute `travail(progress)` dans un thread ; la barre suit la progression.

        `fin(resultat)` suit un succès ; `toujours()` suit le traitement, réussi ou
        non (les deux dans le thread de l'interface). Les variables Tk doivent être
        lues AVANT l'appel, dans le thread de l'interface.
        """

        def progress(i, n):
            self.after(0, lambda: self.barre.set(i / n if n else 1))

        def cible():
            try:
                resultat = travail(progress)
                self.after(0, lambda: self._fin_ok(resultat, fin))
            # Les messages sont lus ICI : Python efface `exc` à la sortie du except,
            # avant que les lambdas ne s'exécutent dans le thread de l'interface.
            except core.PasswordRequired as exc:
                # Demande le mot de passe dans le thread de l'interface, puis relance.
                chemin = exc.path
                self.after(0, lambda: self._relancer_avec_mot_de_passe(chemin, travail, fin))
            except core.PagilisError as exc:
                message = str(exc)
                self.after(0, lambda: messagebox.showwarning(identite.NOM_AFFICHE, message))
                self.after(0, lambda: self.statut(message))
            except Exception:  # noqa: BLE001 - tout doit finir dans le journal
                logging.error(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror(
                    identite.NOM_AFFICHE, "Erreur inattendue. Détails dans pagilis.log."))
            finally:
                self.after(0, lambda: self.barre.set(0))
                if toujours:
                    self.after(0, toujours)
                self.after(0, self._fin_travail)

        for page in self.fonctions.values():
            page.avant_traitement()
        self.travaux_en_cours += 1
        self.barre.set(0)
        self.barre.grid()  # visible uniquement pendant un traitement
        threading.Thread(target=cible, daemon=True).start()

    def _relancer_avec_mot_de_passe(self, chemin: str, travail, fin):
        if self.demander_mot_de_passe(chemin):
            self.lancer(travail, fin)
        else:
            self.statut("Traitement annulé : mot de passe requis.")

    def _fin_travail(self):
        self.travaux_en_cours -= 1
        if not self.travaux_en_cours:
            self.barre.grid_remove()
            # Les superpositions sont sautées pendant un traitement : on les rattrape.
            self.apercu.redessiner()

    def _fin_ok(self, resultat, fin):
        self.statut("Terminé.")
        if fin:
            fin(resultat)

    # ------------------------------------------------- résultats enregistrés

    def enregistrer_sous(self, suffixe: str) -> str | None:
        """Propose un nom du type <nom>_<suffixe>.pdf et retourne le choix."""
        base = os.path.splitext(os.path.basename(self.chemin_pdf or "document"))[0]
        return filedialog.asksaveasfilename(
            initialdir=self.dernier_dossier,
            initialfile=f"{base}_{suffixe}.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        ) or None

    # ------------------------------------------------- notification

    def notifier(self, message: str, actions: list[tuple[str, object]] = ()):
        """Message dans la barre d'état, avec des actions facultatives (sans bloquer le travail)."""
        self.statut(message)
        self._effacer_actions()
        for libelle, action in actions:
            self.actions_notification[libelle] = action
            theme.bouton(self.zone_actions, libelle, lambda libelle=libelle: self.action_notification(libelle),
                         style="secondaire", hauteur=24).pack(side="left", padx=(0, 6))

    def action_notification(self, libelle: str):
        action = self.actions_notification.get(libelle)
        self._effacer_actions()
        if action:
            action()

    def _effacer_actions(self):
        self.actions_notification: dict[str, object] = {}
        for enfant in self.zone_actions.winfo_children():
            enfant.destroy()

    def proposer_ouverture(self, chemin: str, message: str = "Terminé."):
        """Résultat enregistré : « Ouvrir » l'affiche dans le lecteur PDF de Windows."""
        self.notifier(message, [("Ouvrir", lambda: os.startfile(chemin))])  # noqa: S606 - Windows

    def apres_sauvegarde(self, sortie: str, message: str = "Terminé."):
        """Après un traitement : ouvrir le résultat, ou continuer à travailler dessus."""
        self.notifier(message, [("Ouvrir", lambda: os.startfile(sortie)),  # noqa: S606 - Windows
                                ("Continuer dessus", lambda: self.continuer_sur(sortie))])

    def continuer_sur(self, chemin: str):
        """Le résultat devient le document ouvert, à la même page."""
        page = self.apercu.index
        if self.charger_fichier(chemin):
            self.apercu.aller(page)

    # ------------------------------------------------- aperçu : répartition vers les pages

    def _page_changee(self, _index: int):
        for page in self.fonctions.values():
            page.page_changee()

    def _dessiner_superpositions(self, apercu: Apercu):
        if self.travaux_en_cours:
            return  # lire la page pendant un traitement ferait travailler PyMuPDF sur deux threads
        self.fonctions[self.page_active].dessiner(apercu)

    def _souris_appui(self, point: fitz.Point):
        self.fonctions[self.page_active].appui(point)

    def _souris_glisse(self, point: fitz.Point):
        self.fonctions[self.page_active].glisse(point)

    def _souris_relache(self, point: fitz.Point):
        self.fonctions[self.page_active].relache(point)


def main() -> None:
    arguments = sys.argv[1:]
    if "--verifier" in arguments:
        # Auto-vérification sans fenêtre (CI, et nouvelle version avant installation).
        import verification
        echecs = verification.verifier()
        logging.info("Auto-vérification %s : %s", updater.APP_VERSION, "OK" if not echecs else echecs)
        sys.exit(1 if echecs else 0)
    if "--desinstaller" in arguments:
        return fenetres.desinstaller_avec_confirmation()
    # Préférences de PDF Studio (nom d'avant la 1.2.0) reprises au premier lancement.
    # Ici et non à l'import : importer le module (tests) ne doit pas toucher aux vraies données.
    installation.reprendre_preferences(os.path.join(_LOCALAPPDATA, identite.ANCIEN_DOSSIER_DONNEES),
                                       DOSSIER_DONNEES)
    if migrer_installation_pdf_studio(arguments):
        return  # la version installée sous le nouveau nom a pris le relais
    app = Pagilis()
    if installation.tourne_depuis_installation():
        # Après une mise à jour automatique, la version affichée par Windows doit suivre.
        installation.mettre_a_jour_version(updater.APP_VERSION)
    if "--renomme" in arguments:
        app.after(800, lambda: messagebox.showinfo(
            identite.NOM_AFFICHE, f"{identite.ANCIEN_NOM} s'appelle désormais {identite.NOM_AFFICHE}.\n\n"
                          "Vos préférences sont conservées ; les raccourcis et l'entrée dans "
                          "« Applications installées » portent le nouveau nom."))
    # « Ouvrir avec Pagilis PDF » ou fichier glissé sur l'exe : le chemin arrive en argument.
    fichiers = fichiers_a_ouvrir(arguments)
    if fichiers:
        app.after(200, lambda: app.ouvrir_document(os.path.abspath(fichiers[0])))
    app.mainloop()


def fichiers_a_ouvrir(arguments: list[str], existe=os.path.isfile) -> list[str]:
    """PDF et documents Word passés en argument (les options sont ignorées)."""
    return [a for a in arguments if (a.lower().endswith(".pdf") or conversion.est_word(a)) and existe(a)]


def migrer_installation_pdf_studio(arguments: list[str]) -> bool:
    """Installation de PDF Studio tout juste mise à jour : elle devient Pagilis.

    L'exe mis à jour tourne encore depuis l'ancien dossier, sous l'ancien nom.
    Il s'installe sous Pagilis (mêmes choix de raccourcis), retire l'ancienne
    installation (dossier effacé après sa fermeture), puis lance la nouvelle
    copie. Vrai si la migration a eu lieu ; en cas d'échec, l'application
    démarre normalement depuis l'ancien emplacement et réessaiera au prochain
    lancement.
    """
    if not installation.tourne_depuis_installation(installation.ancienne_installation()):
        return False
    try:
        nouvel_exe = installation.migrer_depuis_pdf_studio(
            updater.APP_VERSION, source=installation.exe_courant(), attendre_pid=os.getpid())
        logging.info("Installation de %s migrée vers %s", identite.ANCIEN_NOM, nouvel_exe)
        relance = [str(nouvel_exe), "--renomme"] + [a for a in arguments if a.lower().endswith(".pdf")]
        subprocess.Popen(relance, env=updater.environnement_lancement(), close_fds=True)
        return True
    except Exception:  # noqa: BLE001 - une migration ratée ne doit pas empêcher de travailler
        logging.exception("Migration de l'installation %s impossible", identite.ANCIEN_NOM)
        return False


if __name__ == "__main__":
    main()
