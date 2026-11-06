# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fenêtre principale de Pagilis (CustomTkinter).

Elle porte la barre latérale, le document ouvert, l'aperçu partagé, la barre
d'état et les traitements en arrière-plan. Chaque fonction de la barre
latérale est une page du dossier pages/ ; la logique PDF est dans pdf_core.
"""

from __future__ import annotations

import json
import logging
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
logging.basicConfig(
    filename=os.path.join(DOSSIER_DONNEES, "pagilis.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)


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


# Fonctions affichées dans la barre latérale : (nom, icône, description).
FONCTIONS = [(p.nom, p.icone, p.description) for p in PAGES]


class Pagilis(ctk.CTk):
    """Fenêtre principale : fonctions dans une barre à gauche, page de travail à droite."""

    def __init__(self):
        # Apparence sombre, fixe (pas de choix ; un ancien réglage « apparence » est ignoré).
        ctk.set_appearance_mode("dark")
        super().__init__()
        self.title("Pagilis")
        self.geometry("1280x780")
        self.minsize(1080, 640)
        self.config_data = charger_config()
        self.dossier_donnees = DOSSIER_DONNEES
        self.dernier_dossier = self.config_data.get("dernier_dossier", os.path.expanduser("~"))
        self.chemin_pdf: str | None = None
        # Copie de travail du document affiché (retouches de la page « Modifier »).
        self.edition: Edition | None = None
        # PDF issus des conversions Word de la session ; dossier supprimé à la fermeture.
        self.dossier_conversions = tempfile.mkdtemp(prefix="pagilis-word-")
        self.page_active = FONCTIONS[0][0]
        # Nombre de traitements en cours : la mise à jour est bloquée tant qu'il est > 0,
        # et l'aperçu ne rend rien (PyMuPDF n'est pas thread-safe).
        self.travaux_en_cours = 0

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._construire_barre_laterale()

        # Zone principale : en-tête, formulaire à gauche + aperçu à droite, barre d'état.
        principal = ctk.CTkFrame(self, fg_color="transparent")
        principal.grid(row=0, column=1, sticky="nsew", padx=20, pady=16)
        principal.grid_columnconfigure(1, weight=1)
        principal.grid_rowconfigure(1, weight=1)

        entete = ctk.CTkFrame(principal, fg_color="transparent")
        entete.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        entete.grid_columnconfigure(0, weight=1)
        self.titre_page = ctk.CTkLabel(entete, text="", font=ctk.CTkFont(size=24, weight="bold"), anchor="w")
        self.titre_page.grid(row=0, column=0, sticky="w")
        self.sous_titre_page = ctk.CTkLabel(entete, text="", text_color=("gray40", "gray65"), anchor="w")
        self.sous_titre_page.grid(row=1, column=0, sticky="w")
        fichier = ctk.CTkFrame(entete)
        fichier.grid(row=0, column=1, rowspan=2, sticky="e")
        self.label_fichier = ctk.CTkLabel(fichier, text="Aucun fichier ouvert", text_color=("gray40", "gray65"))
        self.label_fichier.pack(side="left", padx=(12, 8), pady=8)
        ctk.CTkButton(fichier, text="Ouvrir…", width=110, command=self.choisir_pdf).pack(side="left", padx=(0, 8), pady=8)

        # Aperçu partagé par toutes les fonctions.
        self.apercu = Apercu(principal, occupe=lambda: self.travaux_en_cours > 0, corner_radius=10)
        self.apercu.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        self.apercu.on_page = self._page_changee
        self.apercu.on_dessin = self._dessiner_superpositions
        self.apercu.on_appui = self._souris_appui
        self.apercu.on_glisse = self._souris_glisse
        self.apercu.on_relache = self._souris_relache

        # Une page (défilante) par fonction ; une seule est visible à la fois.
        self.pages: dict[str, ctk.CTkScrollableFrame] = {}
        self.fonctions: dict[str, PageFonction] = {}
        for classe in PAGES:
            cadre = ctk.CTkScrollableFrame(principal, corner_radius=10, width=380)
            cadre.grid_columnconfigure(0, weight=1)
            self.pages[classe.nom] = cadre
            self.fonctions[classe.nom] = classe(self, cadre)
        self.modifier = self.fonctions["Modifier"]

        etat = ctk.CTkFrame(principal, fg_color="transparent")
        etat.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        etat.grid_columnconfigure(0, weight=1)
        self.etat = ctk.CTkLabel(etat, text="Prêt", anchor="w")
        self.etat.grid(row=0, column=0, sticky="w")
        self.barre = ctk.CTkProgressBar(etat, width=220)
        self.barre.set(0)
        self.barre.grid(row=0, column=1, sticky="e")
        self.barre.grid_remove()  # réapparaît pendant les traitements

        derniere = self.config_data.get("derniere_page")
        self.afficher_page(derniere if derniere in self.pages else FONCTIONS[0][0])
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        # Ctrl+Z / Ctrl+S pour la page affichée (minuscule et majuscule : verrouillage).
        for touche in ("<Control-z>", "<Control-Z>"):
            self.bind(touche, lambda _e: self.fonctions[self.page_active].touche_annuler())
        for touche in ("<Control-s>", "<Control-S>"):
            self.bind(touche, lambda _e: self.fonctions[self.page_active].touche_enregistrer())
        # Vérification au démarrage, hors thread de l'interface : rien ne se passe si à jour.
        # La version ignorée est lue ici, dans le thread de l'interface.
        # Seules les versions publiées pour tous sont proposées, jamais les bêtas
        # (un ancien réglage « canal_beta » est ignoré).
        version_ignoree = self.config_data.get("version_ignoree")
        threading.Thread(target=self._chercher_mise_a_jour, args=(version_ignoree,), daemon=True).start()

    # ------------------------------------------------- barre latérale

    def _construire_barre_laterale(self):
        barre = ctk.CTkFrame(self, width=240, corner_radius=0)
        barre.grid(row=0, column=0, sticky="nsw")
        barre.grid_propagate(False)
        barre.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(barre, text="Pagilis", font=ctk.CTkFont(size=22, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 0))
        ctk.CTkLabel(barre, text=f"Version {updater.APP_VERSION}", text_color=("gray40", "gray60"),
                     anchor="w").grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        ctk.CTkLabel(barre, text="FONCTIONS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray45", "gray55"), anchor="w").grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 6))

        self.boutons_nav: dict[str, ctk.CTkButton] = {}
        for i, (nom, icone, _description) in enumerate(FONCTIONS):
            bouton = ctk.CTkButton(
                barre, text=f"{icone}   {nom}", anchor="w", height=40, corner_radius=8,
                font=ctk.CTkFont(size=14), fg_color="transparent",
                text_color=("gray10", "gray90"), hover_color=("gray75", "gray30"),
                command=lambda n=nom: self.afficher_page(n),
            )
            bouton.grid(row=3 + i, column=0, sticky="ew", padx=12, pady=2)
            self.boutons_nav[nom] = bouton

        # Pousse le bouton d'installation tout en bas de la barre.
        bas = 4 + len(FONCTIONS)
        barre.grid_rowconfigure(bas - 1, weight=1)
        # Version portable lancée : on propose de l'installer sur le PC.
        if installation.exe_courant() and not installation.tourne_depuis_installation():
            texte = "Réinstaller sur ce PC" if installation.est_installe() else "⬇  Installer sur ce PC"
            ctk.CTkButton(barre, text=texte, height=34, fg_color=("#2F9E44", "#2B8A3E"),
                          hover_color=("#2B8A3E", "#237032"), command=self.proposer_installation).grid(
                row=bas, column=0, sticky="ew", padx=20, pady=(0, 20))

    def proposer_installation(self):
        fenetres.proposer_installation(self)

    def afficher_page(self, nom: str):
        """Affiche la page d'une fonction et met en évidence son bouton."""
        if nom != self.page_active and not self.fonctions[self.page_active].peut_quitter(self.fonctions[nom]):
            return
        for autre, page in self.pages.items():
            if autre != nom:
                page.grid_forget()
        self.pages[nom].grid(row=1, column=0, sticky="nsew")
        self.page_active = nom
        self.apercu.redessiner()
        for autre, bouton in self.boutons_nav.items():
            choisi = autre == nom
            bouton.configure(
                fg_color=("#3B8ED0", "#1F6AA5") if choisi else "transparent",
                text_color=("white", "white") if choisi else ("gray10", "gray90"),
            )
        self.titre_page.configure(text=nom)
        self.sous_titre_page.configure(text=self.fonctions[nom].description)
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
            self.charger_fichier(chemin)
            return
        dossier = self.dossier_conversions

        def fin(pdf: str):
            if self.charger_fichier(pdf):
                self.edition = Edition(self.apercu.doc, chemin, origine_word=True)
                self.label_fichier.configure(text=os.path.basename(chemin))

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
                messagebox.showerror("Pagilis", f"Impossible d'ouvrir « {os.path.basename(chemin)} ».")
                return False
        self.chemin_pdf = chemin
        self.label_fichier.configure(text=os.path.basename(chemin))
        self.apercu.charger(doc)
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
            messagebox.showinfo("Pagilis", "Ouvrez d'abord un PDF (bouton en haut à droite).")
            return False
        return True

    # ------------------------------------------------- traitements en arrière-plan

    def lancer(self, travail, fin=None):
        """Exécute `travail(progress)` dans un thread ; la barre suit la progression.

        Les variables Tk doivent être lues AVANT l'appel, dans le thread de l'interface.
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
                self.after(0, lambda: messagebox.showwarning("Pagilis", message))
                self.after(0, lambda: self.statut(message))
            except Exception:  # noqa: BLE001 - tout doit finir dans le journal
                logging.error(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror(
                    "Pagilis", "Erreur inattendue. Détails dans pagilis.log."))
            finally:
                self.after(0, lambda: self.barre.set(0))
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

    def proposer_ouverture(self, chemin: str):
        if messagebox.askyesno("Pagilis", "Ouvrir le résultat ?"):
            os.startfile(chemin)  # noqa: S606 - Windows uniquement

    def apres_sauvegarde(self, sortie: str, continuer: ctk.BooleanVar, message: str = "Terminé."):
        """Après un traitement : statut, « Continuer sur le fichier résultat », ouvrir le résultat."""
        self.statut(message)
        if continuer.get():
            page = self.apercu.index
            self.charger_fichier(sortie)
            self.apercu.aller(page)  # reste sur la page où l'on travaillait
        self.proposer_ouverture(sortie)

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
    ctk.set_default_color_theme("blue")
    app = Pagilis()
    if installation.tourne_depuis_installation():
        # Après une mise à jour automatique, la version affichée par Windows doit suivre.
        installation.mettre_a_jour_version(updater.APP_VERSION)
    if "--renomme" in arguments:
        app.after(800, lambda: messagebox.showinfo(
            identite.NOM, f"{identite.ANCIEN_NOM} s'appelle désormais {identite.NOM}.\n\n"
                          "Vos préférences sont conservées ; les raccourcis et l'entrée dans "
                          "« Applications installées » portent le nouveau nom."))
    # « Ouvrir avec Pagilis » ou PDF glissé sur l'exe : le chemin arrive en argument.
    fichiers = [a for a in arguments if a.lower().endswith(".pdf") and os.path.isfile(a)]
    if fichiers:
        app.after(200, lambda: app.ouvrir_document(os.path.abspath(fichiers[0])))
    app.mainloop()


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
