# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interface de Pagilis (CustomTkinter). Toute la logique est dans pdf_core."""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import shutil
import sys
import tempfile
import threading
import traceback
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
import pymupdf as fitz
from PIL import Image, ImageTk

import conversion
import identite
import installation
import pdf_core as core
import updater
from apercu import Apercu
from edition import Edition, ecrire_pdf

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


# Page « Modifier » : au-delà de ce déplacement de la souris (pixels écran), un appui
# devient un glisser (déplacer le bloc) au lieu d'un clic (corriger la ligne).
SEUIL_GLISSER = 5

# Statut après une correction, selon la police utilisée pour réécrire la ligne.
MESSAGES_POLICE = {
    core.POLICE_ORIGINE: "Ligne corrigée, police d'origine conservée.",
    core.POLICE_INSTALLEE: "Ligne corrigée avec la police d'origine, installée sur ce PC.",
    core.POLICE_REMPLACEMENT: "Ligne corrigée. Police d'origine indisponible pour ces caractères : "
                              "réécrite en Arial, Times ou Courier.",
    core.LIGNE_EFFACEE: "Ligne effacée.",
}

# Fonctions affichées dans la barre latérale : (nom, icône, description).
FONCTIONS = [
    ("Modifier", "✎", "Corriger ou déplacer du texte, PDF ou Word"),
    ("Fusion", "⧉", "Assembler plusieurs PDF dans l'ordre choisi"),
    ("Division", "✂", "Découper un PDF en plusieurs fichiers"),
    ("Signature / Tampon", "✍", "Poser une signature ou un tampon image"),
    ("Remplacer du texte", "⇄", "Rechercher et remplacer du texte"),
    ("Déplacer du texte", "✥", "Déplacer un bloc de texte sur la page"),
    ("OCR (scans)", "◎", "Rendre un PDF scanné cherchable"),
]


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
        self.dernier_dossier = self.config_data.get("dernier_dossier", os.path.expanduser("~"))
        self.chemin_pdf: str | None = None
        # Copie de travail de la page « Modifier » (document affiché dans l'aperçu).
        self.edition: Edition | None = None
        self.saisie: ctk.CTkEntry | None = None  # zone de correction posée sur l'aperçu
        self._ligne_saisie: core.LineInfo | None = None
        self._contexte_saisie = None  # (page, zoom, décalage) à l'ouverture de la zone
        self._fenetre_saisie = None   # élément du canevas qui porte la zone
        # PDF issus des conversions Word de la session ; dossier supprimé à la fermeture.
        self.dossier_conversions = tempfile.mkdtemp(prefix="pagilis-word-")
        self.page_active = FONCTIONS[0][0]
        self._geste = None  # geste souris en cours dans l'aperçu
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

        # Une page (défilante) par fonction ; une seule est visible à la fois.
        self.pages: dict[str, ctk.CTkScrollableFrame] = {}
        for nom, _icone, _description in FONCTIONS:
            page = ctk.CTkScrollableFrame(principal, corner_radius=10, width=380)
            page.grid_columnconfigure(0, weight=1)
            self.pages[nom] = page

        # Aperçu partagé par toutes les fonctions.
        self.apercu = Apercu(principal, occupe=lambda: self.travaux_en_cours > 0, corner_radius=10)
        self.apercu.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        self.apercu.on_page = self._page_changee
        self.apercu.on_dessin = self._dessiner_superpositions
        self.apercu.on_appui = self._souris_appui
        self.apercu.on_glisse = self._souris_glisse
        self.apercu.on_relache = self._souris_relache

        self._construire_modifier()
        self._construire_fusion()
        self._construire_division()
        self._construire_tampon()
        self._construire_remplacement()
        self._construire_deplacement()
        self._construire_ocr()

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
        # Raccourcis de la page « Modifier » (minuscule et majuscule : verrouillage).
        for touche in ("<Control-z>", "<Control-Z>"):
            self.bind(touche, lambda _e: self._raccourci(self.annuler_retouche))
        for touche in ("<Control-s>", "<Control-S>"):
            self.bind(touche, lambda _e: self._raccourci(self.enregistrer_edition))
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

    # ------------------------------------------------- installation sur le PC

    def proposer_installation(self):
        """Fenêtre « Installer sur ce PC » (version portable uniquement)."""
        deja = installation.est_installe()
        fenetre = ctk.CTkToplevel(self)
        fenetre.title("Installer Pagilis")
        fenetre.geometry("480x330")
        fenetre.resizable(False, False)
        fenetre.transient(self)
        fenetre.grab_set()
        ctk.CTkLabel(fenetre, text="Installer Pagilis sur ce PC",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=24, pady=(22, 6))
        explication = (
            "Pagilis sera copié dans votre dossier utilisateur et ajouté au menu Démarrer. "
            "Aucun droit administrateur n'est nécessaire, et vous pourrez le désinstaller depuis "
            "« Paramètres > Applications installées ».\n\n"
            f"Emplacement : {installation.Emplacements().dossier}"
        )
        if deja:
            explication += "\n\nPagilis est déjà installé : la copie installée sera remplacée par celle-ci."
        ctk.CTkLabel(fenetre, text=explication, wraplength=430, justify="left",
                     text_color=("gray30", "gray70")).pack(anchor="w", padx=24)
        bureau = ctk.BooleanVar(value=True)
        ouvrir_avec = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(fenetre, text="Créer un raccourci sur le Bureau", variable=bureau).pack(anchor="w", padx=24, pady=(14, 4))
        ctk.CTkCheckBox(fenetre, text="Proposer Pagilis dans « Ouvrir avec » pour les PDF",
                        variable=ouvrir_avec).pack(anchor="w", padx=24, pady=4)
        boutons = ctk.CTkFrame(fenetre, fg_color="transparent")
        boutons.pack(fill="x", side="bottom", padx=24, pady=20)
        ctk.CTkButton(boutons, text="Annuler", width=100, fg_color="gray50", hover_color="gray40",
                      command=fenetre.destroy).pack(side="right")
        ctk.CTkButton(boutons, text="Installer", width=120,
                      command=lambda: self._installer(fenetre, bureau.get(), ouvrir_avec.get())).pack(side="right", padx=8)

    def _installer(self, fenetre, bureau: bool, ouvrir_avec: bool):
        try:
            installe = installation.installer(installation.exe_courant(), updater.APP_VERSION,
                                              raccourci_bureau=bureau, ouvrir_avec=ouvrir_avec)
        except PermissionError:
            return messagebox.showerror("Pagilis", "La version installée est ouverte. "
                                                      "Fermez-la, puis recommencez.", parent=fenetre)
        except OSError as exc:
            logging.exception("Installation impossible")
            return messagebox.showerror("Pagilis", f"Installation impossible :\n{exc}", parent=fenetre)
        fenetre.destroy()
        logging.info("Installé dans %s", installe)
        # Une installation de PDF Studio (nom d'avant) ferait doublon : on la retire.
        ancienne = installation.ancienne_installation()
        if ancienne.exe.exists():
            installation.desinstaller(ancienne)
            logging.info("Ancienne installation %s retirée", identite.ANCIEN_NOM)
        if messagebox.askyesno("Pagilis", "Pagilis est installé.\n\n"
                                             "Fermer cette version portable et ouvrir la version installée ?"):
            subprocess.Popen([str(installe)], env=updater.environnement_lancement(), close_fds=True)
            self._fermer()

    def afficher_page(self, nom: str):
        """Affiche la page d'une fonction et met en évidence son bouton."""
        if self.page_active == "Modifier" and nom != "Modifier" and self.edition is not None:
            # Les autres fonctions lisent le fichier enregistré, pas la copie de travail.
            if self._occupe():
                return
            self._fermer_saisie()
            if not self._confirmer_abandon(abandonner=True):
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
        description = next(d for n, _i, d in FONCTIONS if n == nom)
        self.titre_page.configure(text=nom)
        self.sous_titre_page.configure(text=description)
        self.config_data["derniere_page"] = nom

    # ------------------------------------------------------ mises à jour

    def _chercher_mise_a_jour(self, version_ignoree: str | None):
        mise_a_jour = updater.check_for_update()
        # « Ne plus me proposer cette version » : on se tait pour CETTE version seulement.
        if mise_a_jour and mise_a_jour.version != version_ignoree:
            self.after(0, lambda: self._popup_mise_a_jour(mise_a_jour))

    def _popup_mise_a_jour(self, mise_a_jour: updater.Update):
        """Popup facultatif : « Plus tard » ou la croix ferment le popup sans rien installer."""
        popup = ctk.CTkToplevel(self)
        popup.title("Mise à jour disponible")
        popup.geometry("460x440" if mise_a_jour.notes else "420x260")
        popup.resizable(False, False)
        popup.transient(self)
        ne_plus_proposer = ctk.BooleanVar(value=False)

        def plus_tard():
            if ne_plus_proposer.get():
                self.config_data["version_ignoree"] = mise_a_jour.version
                sauver_config(self.config_data)
            popup.destroy()

        popup.protocol("WM_DELETE_WINDOW", plus_tard)
        ctk.CTkLabel(
            popup,
            text=f"Une mise à jour est disponible (version {mise_a_jour.version}).\n"
                 f"Voulez-vous l'installer maintenant ?",
            wraplength=380,
        ).pack(padx=20, pady=(24, 12))
        if mise_a_jour.notes:
            # Les nouveautés : sans elles, l'utilisateur ne sait pas ce qu'il installe.
            notes = ctk.CTkTextbox(popup, height=170, wrap="word")
            notes.insert("1.0", updater.notes_lisibles(mise_a_jour.notes))
            notes.configure(state="disabled")
            notes.pack(fill="x", padx=20, pady=(0, 10))
        # Barre affichée seulement pendant le téléchargement (vide, elle montre un point parasite).
        barre = ctk.CTkProgressBar(popup)
        barre.set(0)
        etat = ctk.CTkLabel(popup, text="")
        etat.pack(pady=6)
        bouton_maj = ctk.CTkButton(popup, text="Mettre à jour")
        bouton_maj.pack(pady=4)
        bouton_quitter = ctk.CTkButton(popup, text="Plus tard", fg_color="gray", command=plus_tard)
        bouton_quitter.pack(pady=4)
        ctk.CTkCheckBox(popup, text="Ne plus me proposer cette version", variable=ne_plus_proposer).pack(pady=(4, 12))

        def installer():
            bouton_maj.configure(state="disabled")
            bouton_quitter.configure(state="disabled")
            etat.configure(text="Téléchargement…")
            barre.pack(fill="x", padx=20, before=etat)
            destination = os.path.join(DOSSIER_DONNEES, "Pagilis_new.exe")

            def progression(lu, total):
                if total:
                    popup.after(0, lambda: barre.set(lu / total))

            def travail():
                try:
                    updater.download(mise_a_jour, destination, progression)
                    # La nouvelle version doit prouver qu'elle fonctionne AVANT de remplacer celle-ci.
                    popup.after(0, lambda: etat.configure(text="Vérification de la nouvelle version…"))
                    if not updater.verifier_exe(destination):
                        os.remove(destination)
                        raise RuntimeError("la nouvelle version n'a pas passé son auto-vérification ; "
                                           "votre version actuelle est conservée")
                    popup.after(0, lambda: etat.configure(text="Installation…"))
                    updater.install_and_restart(destination)
                    popup.after(0, self._quitter_sans_sauver)
                except Exception as exc:  # noqa: BLE001 - on affiche l'erreur et on propose de réessayer
                    logging.exception("Échec de la mise à jour")
                    # exc=exc : Python efface `exc` à la sortie du except, avant que le lambda ne s'exécute.
                    popup.after(0, lambda exc=exc: self._echec_mise_a_jour(popup, etat, bouton_maj, bouton_quitter, exc))

            threading.Thread(target=travail, daemon=True).start()

        bouton_maj.configure(command=installer)

        def surveiller():
            """Grise « Mettre à jour » tant qu'un traitement tourne (l'installation ferme l'application)."""
            if not popup.winfo_exists():
                return
            if bouton_quitter.cget("state") == "disabled":
                pass  # téléchargement en cours : on ne touche à rien
            elif self.travaux_en_cours:
                bouton_maj.configure(state="disabled")
                etat.configure(text="Un traitement est en cours : patientez avant de mettre à jour.")
            elif etat.cget("text").startswith("Un traitement"):
                bouton_maj.configure(state="normal")
                etat.configure(text="")
            popup.after(500, surveiller)

        surveiller()

    def _echec_mise_a_jour(self, popup, etat, bouton_maj, bouton_quitter, exc):
        etat.configure(text=f"Échec : {exc}. Réessayez.")
        bouton_maj.configure(state="normal")
        bouton_quitter.configure(state="normal")

    def _quitter_sans_sauver(self):
        """Quitte l'application sans écrire la configuration (utilisé par le popup obligatoire)."""
        self.destroy()

    # ------------------------------------------------------ utilitaires

    def _occupe(self) -> bool:
        """Vrai (et le dit) si un traitement tourne : le document ne doit pas changer."""
        if self.travaux_en_cours:
            self.statut("Traitement en cours, patientez…")
            return True
        return False

    def _fermer(self):
        if self._occupe() or not self._confirmer_abandon():
            return
        self.config_data["dernier_dossier"] = self.dernier_dossier
        sauver_config(self.config_data)
        shutil.rmtree(self.dossier_conversions, ignore_errors=True)
        self.destroy()

    def _memoriser_dossier(self, chemin: str):
        self.dernier_dossier = os.path.dirname(chemin)

    def choisir_pdf(self):
        chemin = filedialog.askopenfilename(
            initialdir=self.dernier_dossier,
            filetypes=[("PDF et Word", "*.pdf *.docx *.doc *.rtf *.odt"), ("PDF", "*.pdf")],
        )
        if chemin:
            self._memoriser_dossier(chemin)
            self.ouvrir_document(chemin)

    def ouvrir_document(self, chemin: str):
        """Ouvre un PDF, ou convertit d'abord un Word en PDF (en arrière-plan)."""
        if self._occupe() or not self._confirmer_abandon():
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
        self.selection = None
        self.resultats_recherche = {}
        self.apercu.charger(doc)
        # Nouvelle copie de travail (page « Modifier ») sur le document affiché.
        self.edition = Edition(doc, chemin)
        if hasattr(self, "bouton_annuler"):
            self._maj_etat_edition()
        self.statut(f"Fichier ouvert : {os.path.basename(chemin)} ({doc.page_count} page(s))")
        return True

    def statut(self, texte: str):
        self.etat.configure(text=texte)
        logging.info(texte)

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

        self._fermer_saisie()  # le document va être lu par un autre thread
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

    def _continuer_sur_resultat(self, var: ctk.BooleanVar, chemin: str):
        """Case « Continuer sur le fichier résultat » : le résultat devient le fichier courant."""
        if var.get():
            page = self.apercu.index
            self.charger_fichier(chemin)
            self.apercu.aller(page)  # reste sur la page où l'on travaillait

    # ----------------------------------------------- éléments de formulaire

    def _section(self, parent, titre: str):
        """Petit titre de section dans un formulaire."""
        ctk.CTkLabel(parent, text=titre.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray45", "gray55"), anchor="w").pack(fill="x", padx=12, pady=(14, 4))

    def _aide(self, parent, texte: str):
        """Texte explicatif discret, sur plusieurs lignes."""
        ctk.CTkLabel(parent, text=texte, wraplength=340, justify="left", anchor="w",
                     text_color=("gray35", "gray65")).pack(fill="x", padx=12, pady=(0, 6))

    def _champ(self, parent, libelle: str, defaut: str) -> ctk.CTkEntry:
        ligne = ctk.CTkFrame(parent, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text=libelle, width=130, anchor="w").pack(side="left")
        entree = ctk.CTkEntry(ligne)
        entree.insert(0, defaut)
        entree.pack(side="left", fill="x", expand=True)
        return entree

    def _remplir(self, entree: ctk.CTkEntry, valeur):
        entree.delete(0, "end")
        entree.insert(0, valeur if isinstance(valeur, str) else f"{valeur:.1f}".rstrip("0").rstrip("."))

    def _case_continuer(self, parent) -> ctk.BooleanVar:
        var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(parent, text="Continuer sur le fichier résultat", variable=var).pack(anchor="w", padx=12, pady=(10, 2))
        return var

    def _bouton_action(self, parent, texte: str, commande):
        ctk.CTkButton(parent, text=texte, height=36, font=ctk.CTkFont(size=14, weight="bold"),
                      command=commande).pack(fill="x", padx=12, pady=(10, 12))

    def _exiger_pdf(self) -> bool:
        if not self.chemin_pdf:
            messagebox.showinfo("Pagilis", "Ouvrez d'abord un PDF (bouton en haut à droite).")
            return False
        return True

    # ---------------------------------------------------------- Modifier

    def _construire_modifier(self):
        onglet = self.pages["Modifier"]
        self._section(onglet, "Document")
        self._aide(onglet, "Ouvrez un PDF ou un document Word (converti en PDF ; Microsoft Word "
                           "ou LibreOffice requis).")
        ctk.CTkButton(onglet, text="Ouvrir…", command=self.choisir_pdf).pack(fill="x", padx=12, pady=(4, 4))
        self._section(onglet, "Retoucher")
        self._aide(onglet, "Cliquez sur une ligne pour la corriger, faites glisser un bloc pour le déplacer.")
        boutons = ctk.CTkFrame(onglet, fg_color="transparent")
        boutons.pack(fill="x", padx=12, pady=(10, 12))
        self.bouton_annuler = ctk.CTkButton(boutons, text="Annuler (Ctrl+Z)", state="disabled",
                                            command=lambda: self.annuler_retouche())
        self.bouton_annuler.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.bouton_enregistrer = ctk.CTkButton(boutons, text="Enregistrer (Ctrl+S)", state="disabled",
                                                command=lambda: self.enregistrer_edition())
        self.bouton_enregistrer.pack(side="left", fill="x", expand=True)

    # ---------------------------------------------------------- Fusion

    def _construire_fusion(self):
        onglet = self.pages["Fusion"]
        self.liste_fusion: list[str] = []
        self.selection_fusion: int | None = None
        self._section(onglet, "Fichiers à fusionner")
        self._aide(onglet, "Cliquez sur un fichier pour le sélectionner, puis changez sa place. "
                           "Chaque fichier devient un signet ; ses signets d'origine sont conservés.")
        self.cadre_fusion = ctk.CTkFrame(onglet)
        self.cadre_fusion.pack(fill="x", padx=12, pady=4)
        boutons = ctk.CTkFrame(onglet, fg_color="transparent")
        boutons.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(boutons, text="Ajouter…", width=80, command=self.ajouter_fusion).pack(side="left")
        for texte, commande in [("▲", lambda: self.deplacer_fusion(-1)), ("▼", lambda: self.deplacer_fusion(1)),
                                ("Retirer", self.retirer_fusion), ("Vider", self.vider_fusion)]:
            ctk.CTkButton(boutons, text=texte, width=36 if len(texte) == 1 else 70, fg_color="gray50",
                          hover_color="gray40", command=commande).pack(side="left", padx=(6, 0))
        self._bouton_action(onglet, "Fusionner…", self.lancer_fusion)
        self._rafraichir_fusion()

    def _rafraichir_fusion(self):
        for enfant in self.cadre_fusion.winfo_children():
            enfant.destroy()
        if not self.liste_fusion:
            ctk.CTkLabel(self.cadre_fusion, text="Aucun fichier. Cliquez sur « Ajouter… ».",
                         text_color=("gray40", "gray60")).pack(padx=10, pady=14)
            return
        for i, chemin in enumerate(self.liste_fusion):
            choisi = i == self.selection_fusion
            ctk.CTkButton(
                self.cadre_fusion, text=f"{i + 1}.  {os.path.basename(chemin)}", anchor="w", height=30,
                fg_color=("#3B8ED0", "#1F6AA5") if choisi else "transparent",
                text_color=("white", "white") if choisi else ("gray10", "gray90"),
                hover_color=("gray75", "gray30"),
                command=lambda i=i: self._choisir_fusion(i),
            ).pack(fill="x", padx=4, pady=1)

    def _choisir_fusion(self, index: int):
        self.selection_fusion = index
        self._rafraichir_fusion()

    def ajouter_fusion(self):
        chemins = filedialog.askopenfilenames(initialdir=self.dernier_dossier, filetypes=[("PDF", "*.pdf")])
        if chemins:
            self.liste_fusion.extend(chemins)
            self._memoriser_dossier(chemins[0])
            self._rafraichir_fusion()

    def deplacer_fusion(self, sens: int):
        """Monte ou descend le fichier SÉLECTIONNÉ."""
        i = self.selection_fusion
        if i is None:
            return self.statut("Sélectionnez d'abord un fichier dans la liste.")
        j = i + sens
        if 0 <= j < len(self.liste_fusion):
            self.liste_fusion[i], self.liste_fusion[j] = self.liste_fusion[j], self.liste_fusion[i]
            self.selection_fusion = j
            self._rafraichir_fusion()

    def retirer_fusion(self):
        if self.selection_fusion is not None:
            del self.liste_fusion[self.selection_fusion]
            self.selection_fusion = None
            self._rafraichir_fusion()

    def vider_fusion(self):
        self.liste_fusion.clear()
        self.selection_fusion = None
        self._rafraichir_fusion()

    def lancer_fusion(self):
        fichiers = list(self.liste_fusion)
        if len(fichiers) < 2:
            return messagebox.showinfo("Pagilis", "Ajoutez au moins deux PDF à fusionner.")
        sortie = filedialog.asksaveasfilename(initialdir=self.dernier_dossier, initialfile="fusion.pdf",
                                              defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not sortie:
            return
        self.statut("Fusion en cours…")
        self.lancer(lambda p: core.merge_pdfs(fichiers, sortie, p),
                    fin=lambda _: self.proposer_ouverture(sortie))

    # -------------------------------------------------------- Division

    def _construire_division(self):
        onglet = self.pages["Division"]
        self._section(onglet, "Mode de découpe")
        self.mode_division = ctk.StringVar(value="page")
        for valeur, texte in [("page", "Une page par fichier"),
                              ("n", "Toutes les N pages"),
                              ("plages", "Par plages (une plage = un fichier)")]:
            ctk.CTkRadioButton(onglet, text=texte, variable=self.mode_division, value=valeur).pack(anchor="w", padx=12, pady=4)
        self._section(onglet, "Paramètres")
        self.entree_n = self._champ(onglet, "N pages", "2")
        self.entree_plages = self._champ(onglet, "Plages", "")
        self.entree_plages.configure(placeholder_text="ex. 1-3, 5, 8-")
        self._aide(onglet, "Les fichiers sont créés dans le dossier que vous choisirez.")
        self._bouton_action(onglet, "Diviser…", self.lancer_division)

    def lancer_division(self):
        if not self._exiger_pdf():
            return
        source = self.chemin_pdf
        mode = self.mode_division.get()
        n = self.entree_n.get().strip()
        plages = self.entree_plages.get().strip()
        if mode == "n" and not n.isdigit():
            return messagebox.showwarning("Pagilis", "Indiquez un nombre entier pour N.")
        if mode == "plages" and not plages:
            return messagebox.showwarning("Pagilis", "Indiquez les plages, par exemple « 1-3, 5, 8- ».")
        dossier = filedialog.askdirectory(initialdir=self.dernier_dossier)
        if not dossier:
            return

        def travail(p):
            if mode == "page":
                return core.split_by_page(source, dossier, p)
            if mode == "n":
                return core.split_every_n(source, dossier, int(n), p)
            return core.split_by_ranges(source, dossier, plages, p)

        self.statut("Division en cours…")
        self.lancer(travail, fin=lambda fichiers: self.statut(f"{len(fichiers)} fichier(s) créé(s) dans {dossier}."))

    # ---------------------------------------------- Signature / Tampon

    def _construire_tampon(self):
        onglet = self.pages["Signature / Tampon"]
        self.image_tampon: str | None = None
        self.ratio_tampon = 0.5
        self._cache_tampon = (None, None)  # (clé, PhotoImage) de l'image en surimpression
        self._section(onglet, "Image")
        ligne = ctk.CTkFrame(onglet, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkButton(ligne, text="Choisir…", width=90, command=self.choisir_tampon).pack(side="left")
        self.label_tampon = ctk.CTkLabel(ligne, text="Aucune image (PNG ou JPG)", anchor="w")
        self.label_tampon.pack(side="left", padx=8, fill="x", expand=True)
        self.blanc_transparent = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(onglet, text="Fond blanc transparent (signature scannée)", variable=self.blanc_transparent).pack(anchor="w", padx=12, pady=4)

        self._section(onglet, "Position sur la page")
        self._aide(onglet, "Cliquez sur l'aperçu pour poser l'image, puis faites-la glisser. "
                           "Les valeurs sont en points (1/72 de pouce).")
        self.entree_x = self._champ(onglet, "X (pt)", "72")
        self.entree_y = self._champ(onglet, "Y (pt)", "72")
        self.entree_l = self._champ(onglet, "Largeur (pt)", "150")
        for entree in (self.entree_x, self.entree_y, self.entree_l):
            entree.bind("<KeyRelease>", lambda _e: self.apercu.redessiner())
        self.entree_op = self._champ(onglet, "Opacité (%)", "100")
        self.rotation_tampon = ctk.StringVar(value="0")
        ligne = ctk.CTkFrame(onglet, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text="Rotation (°)", width=130, anchor="w").pack(side="left")
        ctk.CTkSegmentedButton(ligne, values=["0", "90", "180", "270"], variable=self.rotation_tampon,
                               command=lambda _v: self.apercu.redessiner()).pack(side="left", fill="x", expand=True)

        self._section(onglet, "Pages")
        self.portee_tampon = ctk.StringVar(value="page")
        ctk.CTkRadioButton(onglet, text="Page affichée dans l'aperçu", variable=self.portee_tampon, value="page").pack(anchor="w", padx=12, pady=2)
        ctk.CTkRadioButton(onglet, text="Toutes les pages", variable=self.portee_tampon, value="toutes").pack(anchor="w", padx=12, pady=2)
        ctk.CTkRadioButton(onglet, text="Plage :", variable=self.portee_tampon, value="plage").pack(anchor="w", padx=12, pady=2)
        self.entree_plage_tampon = self._champ(onglet, "", "")
        self.entree_plage_tampon.configure(placeholder_text="ex. 1, 3-5")
        self.continuer_tampon = self._case_continuer(onglet)
        self._bouton_action(onglet, "Appliquer…", self.lancer_tampon)

    def choisir_tampon(self):
        chemin = filedialog.askopenfilename(initialdir=self.dernier_dossier,
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

    def _dessiner_tampon(self, apercu: Apercu):
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
        apercu.canevas.create_rectangle(x0, y0, x1, y1, outline="#1F6AA5", width=2, dash=(4, 2), tags="superposition")

    def lancer_tampon(self):
        if not self._exiger_pdf():
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
        source = self.chemin_pdf
        image = self.image_tampon
        portee = self.portee_tampon.get()
        plage = self.entree_plage_tampon.get().strip()
        page_affichee = self.apercu.index
        if portee == "plage" and not plage:
            return messagebox.showwarning("Pagilis", "Indiquez la plage de pages.")
        sortie = self.enregistrer_sous("signe")
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

        self.statut("Application du tampon…")
        self.lancer(travail, fin=lambda n: self._apres_sauvegarde(sortie, self.continuer_tampon,
                                                                   f"Tampon posé sur {n} page(s)."))

    def _apres_sauvegarde(self, sortie: str, continuer: ctk.BooleanVar, message: str = "Terminé."):
        self.statut(message)
        self._continuer_sur_resultat(continuer, sortie)
        self.proposer_ouverture(sortie)

    # ----------------------------------------------- Remplacer du texte

    def _construire_remplacement(self):
        onglet = self.pages["Remplacer du texte"]
        self.resultats_recherche: dict[int, list[fitz.Rect]] = {}
        self._section(onglet, "Texte")
        self.entree_ancien = self._champ(onglet, "Rechercher", "")
        self.entree_nouveau = self._champ(onglet, "Remplacer par", "")
        self.entree_nouveau.configure(placeholder_text="vide = effacer")
        self.entree_plage_rempl = self._champ(onglet, "Pages", "")
        self.entree_plage_rempl.configure(placeholder_text="vide = toutes")
        self.casse = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Respecter la casse", variable=self.casse).pack(anchor="w", padx=12, pady=(8, 2))
        self.reduire = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Réduire la taille si le texte est plus long", variable=self.reduire).pack(anchor="w", padx=12, pady=2)
        ctk.CTkButton(onglet, text="Rechercher (aperçu)", fg_color="gray50", hover_color="gray40",
                      command=self.rechercher_texte).pack(fill="x", padx=12, pady=(10, 4))
        self.entree_ancien.bind("<Return>", lambda _e: self.rechercher_texte())
        self.cadre_resultats = ctk.CTkFrame(onglet, fg_color="transparent")
        self.cadre_resultats.pack(fill="x", padx=12)
        self.continuer_rempl = self._case_continuer(onglet)
        self._bouton_action(onglet, "Remplacer…", self.lancer_remplacement)

    def rechercher_texte(self):
        if not self._exiger_pdf():
            return
        needle = self.entree_ancien.get()
        if not needle:
            return self.statut("Saisissez le texte à rechercher.")
        casse = self.casse.get()
        source = self.chemin_pdf

        def travail(p):
            doc = core.open_pdf(source)
            try:
                return core.find_text_rects(doc, needle, casse, p)
            finally:
                doc.close()

        self.statut("Recherche…")
        self.lancer(travail, fin=self._afficher_resultats)

    def _afficher_resultats(self, resultats: dict[int, list[fitz.Rect]]):
        self.resultats_recherche = resultats
        for enfant in self.cadre_resultats.winfo_children():
            enfant.destroy()
        if not resultats:
            self._aide(self.cadre_resultats, "Aucune occurrence. Si ce PDF est un scan, le texte n'est "
                                             "qu'une image : passez d'abord par « OCR (scans) ».")
            self.statut("Aucune occurrence.")
        else:
            total = sum(len(r) for r in resultats.values())
            self.statut(f"{total} occurrence(s) sur {len(resultats)} page(s).")
            pages = sorted(resultats)
            for page in pages[:30]:
                ctk.CTkButton(self.cadre_resultats, text=f"Page {page + 1} — {len(resultats[page])} occurrence(s)",
                              anchor="w", height=26, fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray75", "gray30"),
                              command=lambda page=page: self.apercu.aller(page)).pack(fill="x")
            if len(pages) > 30:
                self._aide(self.cadre_resultats, f"… et {len(pages) - 30} autre(s) page(s).")
            if self.apercu.index not in resultats:
                self.apercu.aller(pages[0])
        self.apercu.redessiner()

    def lancer_remplacement(self):
        if not self._exiger_pdf():
            return
        ancien = self.entree_ancien.get()
        if not ancien:
            return messagebox.showinfo("Pagilis", "Saisissez le texte à remplacer.")
        nouveau = self.entree_nouveau.get()
        casse = self.casse.get()
        reduire = self.reduire.get()
        plage = self.entree_plage_rempl.get().strip()
        source = self.chemin_pdf
        sortie = self.enregistrer_sous("remplace")
        if not sortie:
            return

        def travail(p):
            doc = core.open_pdf(source)
            try:
                pages = core.parse_page_ranges(plage, doc.page_count) if plage else list(range(doc.page_count))
                n = core.replace_text(doc, ancien, nouveau, pages, casse, reduire, p)
                core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.statut("Remplacement en cours…")
        self.lancer(travail, fin=lambda n: self._fin_remplacement(n, sortie))

    def _fin_remplacement(self, n: int, sortie: str):
        self.resultats_recherche = {}
        if n == 0:
            self.statut("Aucune occurrence remplacée.")
            return messagebox.showinfo("Pagilis", "Aucune occurrence trouvée : le fichier créé est identique.\n"
                                                     "Si c'est un scan, passez d'abord par « OCR (scans) ».")
        self._apres_sauvegarde(sortie, self.continuer_rempl, f"{n} remplacement(s).")

    # ----------------------------------------------- Déplacer du texte

    def _construire_deplacement(self):
        onglet = self.pages["Déplacer du texte"]
        self.selection: fitz.Rect | None = None
        self._section(onglet, "Sélection")
        self._aide(onglet, "Dans l'aperçu : cliquez sur un bloc encadré ou tracez un rectangle, "
                           "puis faites glisser la sélection vers sa nouvelle place.")
        self.entree_zone = self._champ(onglet, "Zone x0,y0,x1,y1", "")
        self._section(onglet, "Décalage")
        self.entree_dx = self._champ(onglet, "dX (pt)", "0")
        self.entree_dy = self._champ(onglet, "dY (pt)", "0")
        for entree in (self.entree_zone, self.entree_dx, self.entree_dy):
            entree.bind("<KeyRelease>", lambda _e: self._lire_zone_saisie())
        self.continuer_dep = self._case_continuer(onglet)
        self._bouton_action(onglet, "Déplacer…", self.lancer_deplacement)

    def _lire_zone_saisie(self):
        """Une zone tapée à la main remplace la sélection faite à la souris."""
        try:
            x0, y0, x1, y1 = (float(v) for v in self.entree_zone.get().split(","))
            self.selection = fitz.Rect(x0, y0, x1, y1)
        except ValueError:
            pass
        self.apercu.redessiner()

    def _decalage(self) -> tuple[float, float]:
        try:
            return float(self.entree_dx.get()), float(self.entree_dy.get())
        except ValueError:
            return 0.0, 0.0

    def _maj_champs_deplacement(self, dx: float = 0.0, dy: float = 0.0):
        if self.selection is not None:
            r = self.selection
            self._remplir(self.entree_zone, f"{r.x0:.0f},{r.y0:.0f},{r.x1:.0f},{r.y1:.0f}")
        else:
            self._remplir(self.entree_zone, "")
        self._remplir(self.entree_dx, dx)
        self._remplir(self.entree_dy, dy)

    def lancer_deplacement(self):
        if not self._exiger_pdf():
            return
        if self.selection is None:
            return messagebox.showinfo("Pagilis", "Sélectionnez d'abord un bloc de texte dans l'aperçu.")
        zone = fitz.Rect(self.selection)
        dx, dy = self._decalage()
        if dx == 0 and dy == 0:
            return messagebox.showinfo("Pagilis", "Faites glisser la sélection ou indiquez un décalage.")
        page = self.apercu.index
        source = self.chemin_pdf
        sortie = self.enregistrer_sous("deplace")
        if not sortie:
            return

        def travail(_p):
            doc = core.open_pdf(source)
            try:
                n = core.move_text_block(doc, page, zone, dx, dy)
                if n:
                    core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.statut("Déplacement en cours…")
        self.lancer(travail, fin=lambda n: self._fin_deplacement(n, sortie))

    def _fin_deplacement(self, n: int, sortie: str):
        if n == 0:
            self.statut("Aucun texte dans la zone sélectionnée.")
            return messagebox.showinfo("Pagilis", "La zone sélectionnée ne contient pas de texte lisible "
                                                     "horizontalement. Rien n'a été enregistré.")
        self.selection = None
        self._maj_champs_deplacement()
        self._apres_sauvegarde(sortie, self.continuer_dep, f"{n} segment(s) déplacé(s).")

    # ----------------------------------------------------------- OCR

    def _construire_ocr(self):
        onglet = self.pages["OCR (scans)"]
        self._section(onglet, "Langues")
        langues = ["fra", "eng", "deu", "spa", "ita"]
        self.langue_ocr = ctk.StringVar(value=self.config_data.get("langue_ocr", "fra"))
        self.langue2_ocr = ctk.StringVar(value=self.config_data.get("langue2_ocr", "aucune"))
        for libelle, var, valeurs in [("Langue", self.langue_ocr, langues),
                                      ("2ᵉ langue", self.langue2_ocr, ["aucune"] + langues)]:
            ligne = ctk.CTkFrame(onglet, fg_color="transparent")
            ligne.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(ligne, text=libelle, width=130, anchor="w").pack(side="left")
            ctk.CTkOptionMenu(ligne, values=valeurs, variable=var).pack(side="left", fill="x", expand=True)
        self._section(onglet, "Options")
        self.dpi_ocr = ctk.StringVar(value="300")
        ligne = ctk.CTkFrame(onglet, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text="Résolution (dpi)", width=130, anchor="w").pack(side="left")
        ctk.CTkSegmentedButton(ligne, values=["200", "300", "400"], variable=self.dpi_ocr).pack(side="left", fill="x", expand=True)
        self.entree_pages_ocr = self._champ(onglet, "Pages", "")
        self.entree_pages_ocr.configure(placeholder_text="vide = toutes")
        self.ignorer_texte = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(onglet, text="Ignorer les pages qui ont déjà du texte", variable=self.ignorer_texte).pack(anchor="w", padx=12, pady=(8, 2))
        self.encadrer_mots = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Encadrer les mots reconnus dans l'aperçu", variable=self.encadrer_mots,
                        command=self.apercu.redessiner).pack(anchor="w", padx=12, pady=2)
        self._section(onglet, "Fichiers de langue")
        self.entree_tessdata = self._champ(onglet, "Dossier tessdata", self.config_data.get("tessdata", ""))
        self.entree_tessdata.configure(placeholder_text="automatique")
        self.continuer_ocr = self._case_continuer(onglet)
        self._bouton_action(onglet, "Lancer l'OCR…", self.lancer_ocr)

    def lancer_ocr(self):
        if not self._exiger_pdf():
            return
        langue = self.langue_ocr.get()
        if self.langue2_ocr.get() not in ("aucune", langue):
            langue += "+" + self.langue2_ocr.get()
        dpi = int(self.dpi_ocr.get())
        plage = self.entree_pages_ocr.get().strip()
        tessdata = self.entree_tessdata.get().strip() or None
        ignorer = self.ignorer_texte.get()
        # Préférences mémorisées pour les prochaines fois.
        self.config_data.update(langue_ocr=self.langue_ocr.get(), langue2_ocr=self.langue2_ocr.get(),
                                tessdata=tessdata or "")
        if core.find_tessdata(tessdata) is None:
            return messagebox.showwarning("Pagilis", "Fichiers de langue Tesseract (.traineddata) introuvables.\n"
                                                        "Indiquez le dossier « tessdata » qui les contient.")
        source = self.chemin_pdf
        sortie = self.enregistrer_sous("ocr")
        if not sortie:
            return

        def travail(p):
            doc = core.open_pdf(source)
            try:
                pages = core.parse_page_ranges(plage, doc.page_count) if plage else list(range(doc.page_count))
                n = core.ocr_pages(doc, pages, langue, dpi, tessdata, ignorer, p)
                core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.statut("OCR en cours (peut être long)…")
        self.lancer(travail, fin=lambda n: self._fin_ocr(n, sortie))

    def _fin_ocr(self, n: int, sortie: str):
        if n == 0:
            self.statut("Aucune page traitée.")
            return messagebox.showinfo("Pagilis", "Aucune page à traiter : toutes contiennent déjà du texte.\n"
                                                     "Décochez « Ignorer les pages qui ont déjà du texte » pour forcer.")
        self.encadrer_mots.set(True)
        self._apres_sauvegarde(sortie, self.continuer_ocr, f"OCR terminé sur {n} page(s).")

    # ------------------------------------------- aperçu : dessin et souris

    def _page_changee(self, _index: int):
        """Changement de page (pas de zoom) : la sélection de texte n'a plus de sens."""
        self._fermer_saisie()
        self.selection = None
        self._maj_champs_deplacement()

    def _dessiner_superpositions(self, apercu: Apercu):
        if self.travaux_en_cours:
            return  # lire la page pendant un traitement ferait travailler PyMuPDF sur deux threads
        canevas = apercu.canevas
        if self.page_active == "Signature / Tampon":
            self._dessiner_tampon(apercu)
        elif self.page_active == "Remplacer du texte":
            for rect in self.resultats_recherche.get(apercu.index, []):
                canevas.create_rectangle(*apercu.rect_canevas(rect), outline="#E0A800", width=2,
                                         fill="#FFD43B", stipple="gray25", tags="superposition")
        elif self.page_active == "Déplacer du texte":
            for rect in core.text_blocks(apercu.page):
                canevas.create_rectangle(*apercu.rect_canevas(rect), outline="#8a8a8a", dash=(2, 3),
                                         tags="superposition")
            if self.selection is not None:
                canevas.create_rectangle(*apercu.rect_canevas(self.selection), outline="#1F6AA5", width=2,
                                         tags="superposition")
                dx, dy = self._decalage()
                if dx or dy:
                    fantome = fitz.Rect(self.selection) + (dx, dy, dx, dy)
                    canevas.create_rectangle(*apercu.rect_canevas(fantome), outline="#E8590C", width=2,
                                             dash=(6, 3), tags="superposition")
        elif self.page_active == "Modifier":
            self._dessiner_modifier(apercu)
        elif self.page_active == "OCR (scans)" and self.encadrer_mots.get():
            for rect in core.word_rects(apercu.page):
                canevas.create_rectangle(*apercu.rect_canevas(rect), outline="#2F9E44", tags="superposition")

    def _souris_appui(self, point: fitz.Point):
        self._geste = None
        if self.page_active == "Modifier":
            self._fermer_saisie()
            if self.edition is None or self.travaux_en_cours:
                return
            page = self.apercu.page
            ligne = core.line_at(page, point)
            bloc = ligne.block_rect if ligne else next(
                (fitz.Rect(b) for b in core.text_blocks(page) if b.contains(point)), None)
            # (nature, départ, ligne sous la souris, bloc, point courant si glisser)
            self._geste = ("modifier", point, ligne, bloc, None)
        elif self.page_active == "Signature / Tampon":
            if not self.image_tampon:
                return self.statut("Choisissez d'abord une image.")
            rect = self._rect_tampon()
            if rect is None or not rect.contains(point):
                # Clic hors de l'image : on la centre sur le clic.
                largeur = float(self.entree_l.get() or 150)
                rect = self._rect_tampon() or fitz.Rect(0, 0, largeur, largeur * self.ratio_tampon)
                self._remplir(self.entree_x, max(0, point.x - rect.width / 2))
                self._remplir(self.entree_y, max(0, point.y - rect.height / 2))
                rect = self._rect_tampon()
            self._geste = ("tampon", point - rect.tl)
            self.apercu.redessiner()
        elif self.page_active == "Déplacer du texte":
            dx, dy = self._decalage()
            if self.selection is not None and (fitz.Rect(self.selection) + (dx, dy, dx, dy)).contains(point):
                self._geste = ("deplacer", point - fitz.Point(dx, dy))
            else:
                self._geste = ("selection", point)

    def _souris_glisse(self, point: fitz.Point):
        if not self._geste:
            return
        if self._geste[0] == "modifier":
            _n, depart, ligne, bloc, courant = self._geste
            x0, y0 = self.apercu.vers_canevas(depart.x, depart.y)
            x1, y1 = self.apercu.vers_canevas(point.x, point.y)
            # Au-delà de SEUIL_GLISSER pixels à l'écran, c'est un déplacement, pas un clic.
            if bloc is not None and (courant is not None or abs(x1 - x0) + abs(y1 - y0) > SEUIL_GLISSER):
                self._geste = ("modifier", depart, ligne, bloc, point)
                self.apercu.redessiner()
            return
        nature, valeur = self._geste
        if nature == "tampon":
            self._remplir(self.entree_x, max(0, point.x - valeur.x))
            self._remplir(self.entree_y, max(0, point.y - valeur.y))
        elif nature == "deplacer":
            ecart = point - valeur
            self._maj_champs_deplacement(round(ecart.x), round(ecart.y))
        elif nature == "selection":
            self.selection = fitz.Rect(valeur, point)
            self.selection.normalize()
            self._maj_champs_deplacement()
        self.apercu.redessiner()

    def _souris_relache(self, point: fitz.Point):
        if self._geste and self._geste[0] == "modifier":
            _n, depart, ligne, bloc, courant = self._geste
            self._geste = None
            if courant is not None:
                index = self.apercu.index
                self._retoucher(lambda: self.edition.deplacer(index, bloc, point.x - depart.x,
                                                              point.y - depart.y))
            elif ligne is not None:
                self._ouvrir_saisie(ligne)
            elif not core.has_text(self.apercu.page):
                self.statut("Aucun texte ici. Page scannée ? Utilisez l'OCR d'abord.")
            self.apercu.redessiner()
            return
        if self._geste and self._geste[0] == "selection" and (self.selection is None or
                                                              self.selection.width < 3 or self.selection.height < 3):
            # Simple clic : on sélectionne le bloc de texte situé sous la souris.
            blocs = [] if self.travaux_en_cours else core.text_blocks(self.apercu.page)
            self.selection = next((fitz.Rect(b) for b in blocs if b.contains(point)), None)
            self._maj_champs_deplacement()
            self.apercu.redessiner()
        self._geste = None


    # ------------------------------------------- page « Modifier » : retouches

    def _dessiner_modifier(self, apercu: Apercu):
        canevas = apercu.canevas
        if self.saisie is not None:
            if self._contexte_saisie != (apercu.index, apercu.zoom, apercu.decalage):
                self._fermer_saisie()  # zoom ou page changés : la zone n'est plus à sa place
            elif self._fenetre_saisie is None or not canevas.type(self._fenetre_saisie):
                self._poser_saisie()   # rendu complet : l'élément du canevas a été effacé
        geste = self._geste
        if geste and geste[0] == "modifier" and geste[4] is not None:
            _n, depart, _ligne, bloc, courant = geste
            dx, dy = courant.x - depart.x, courant.y - depart.y
            canevas.create_rectangle(*apercu.rect_canevas(bloc), outline="#1F6AA5", width=2,
                                     tags="superposition")
            canevas.create_rectangle(*apercu.rect_canevas(bloc + (dx, dy, dx, dy)), outline="#E8590C",
                                     width=2, dash=(6, 3), tags="superposition")

    def _ouvrir_saisie(self, ligne: core.LineInfo):
        """Pose une zone de saisie sur la ligne, avec son texte actuel sélectionné."""
        self._fermer_saisie()
        taille = max(9, round(ligne.size * self.apercu.zoom * 0.9))
        x0, y0, x1, y1 = self.apercu.rect_canevas(ligne.rect)
        self.saisie = ctk.CTkEntry(self.apercu.canevas, width=max(int(x1 - x0) + 24, 200),
                                   height=max(int(y1 - y0) + 10, 28), font=ctk.CTkFont(size=taille))
        self.saisie.insert(0, ligne.text)
        self.saisie.select_range(0, "end")
        self.saisie.bind("<Return>", lambda _e: self._valider_saisie())
        self.saisie.bind("<KP_Enter>", lambda _e: self._valider_saisie())
        self.saisie.bind("<Escape>", lambda _e: self._fermer_saisie())
        self._ligne_saisie = ligne
        self._contexte_saisie = (self.apercu.index, self.apercu.zoom, self.apercu.decalage)
        self._poser_saisie()
        self.saisie.focus_set()

    def _poser_saisie(self):
        x0, y0, _x1, y1 = self.apercu.rect_canevas(self._ligne_saisie.rect)
        hauteur = max(int(y1 - y0) + 10, 28)
        self._fenetre_saisie = self.apercu.canevas.create_window(
            x0 - 6, (y0 + y1) / 2 - hauteur / 2, anchor="nw", window=self.saisie)

    def _fermer_saisie(self):
        """Ferme la zone de saisie sans rien appliquer."""
        if self.saisie is not None:
            if self._fenetre_saisie is not None:
                self.apercu.canevas.delete(self._fenetre_saisie)
            self.saisie.destroy()
        self.saisie = self._ligne_saisie = self._contexte_saisie = self._fenetre_saisie = None

    def _valider_saisie(self):
        ligne, index, texte = self._ligne_saisie, self.apercu.index, self.saisie.get()
        self._fermer_saisie()
        centre = fitz.Point((ligne.rect.x0 + ligne.rect.x1) / 2, (ligne.rect.y0 + ligne.rect.y1) / 2)
        niveau = self._retoucher(lambda: self.edition.corriger(index, centre, texte))
        message = MESSAGES_POLICE.get(niveau)
        if message:
            self.statut(message)

    def _retoucher(self, action):
        """Applique une retouche de la copie de travail et rafraîchit l'aperçu."""
        try:
            resultat = action()
        except Exception:  # noqa: BLE001 - la copie de travail est déjà restaurée
            logging.exception("Retouche impossible")
            messagebox.showerror("Pagilis", "Retouche impossible, le document n'a pas changé.")
            resultat = None
        self.apercu.remplacer(self.edition.doc)
        self._maj_etat_edition()
        return resultat

    def _maj_etat_edition(self):
        """Boutons Annuler / Enregistrer et titre de la fenêtre (« • » = non enregistré)."""
        ed = self.edition
        self.bouton_annuler.configure(state="normal" if ed and ed.peut_annuler else "disabled")
        self.bouton_enregistrer.configure(state="normal" if ed and ed.modifie else "disabled")
        if ed and ed.modifie:
            self.title(f"Pagilis • {os.path.basename(ed.source)}")
        else:
            self.title("Pagilis")

    def _raccourci(self, action):
        """Ctrl+Z / Ctrl+S : seulement sur « Modifier », hors zone de saisie."""
        if self.page_active == "Modifier" and self.saisie is None and not self.travaux_en_cours:
            action()

    def annuler_retouche(self):
        if self.edition is None or not self.edition.peut_annuler or self.travaux_en_cours:
            return
        self._fermer_saisie()
        self._retoucher(self.edition.annuler)
        self.statut("Dernière retouche annulée.")

    def _demander_chemin_edition(self) -> str | None:
        propose = self.edition.nom_propose()
        return filedialog.asksaveasfilename(
            initialdir=os.path.dirname(propose), initialfile=os.path.basename(propose),
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]) or None

    def enregistrer_edition(self):
        """Enregistre la copie de travail (en arrière-plan)."""
        if self.edition is None or self.travaux_en_cours:
            return
        self._fermer_saisie()
        chemin = self._demander_chemin_edition()
        if not chemin:
            return
        edition = self.edition
        donnees = edition.doc.tobytes()  # ici, dans le thread de l'interface

        def fin(_resultat):
            edition.modifie = False
            self._apres_enregistrement_edition(chemin)

        self.lancer(lambda _p: ecrire_pdf(donnees, chemin), fin=fin)

    def _apres_enregistrement_edition(self, chemin: str):
        """Le fichier enregistré devient le fichier ouvert : les autres fonctions le liront."""
        self.chemin_pdf = chemin
        self.label_fichier.configure(text=os.path.basename(chemin))
        self._memoriser_dossier(chemin)
        self._maj_etat_edition()
        self.statut(f"Enregistré : {os.path.basename(chemin)}")

    def _confirmer_abandon(self, abandonner: bool = False) -> bool:
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
            chemin = self._demander_chemin_edition()
            if not chemin:
                return False
            try:
                ed.enregistrer(chemin)
            except Exception:  # noqa: BLE001 - on reste sur place, rien n'est perdu
                logging.exception("Enregistrement impossible : %s", chemin)
                messagebox.showerror("Pagilis", f"Impossible d'enregistrer « {os.path.basename(chemin)} ».")
                return False
            self._apres_enregistrement_edition(chemin)
        elif abandonner:
            # Retouches abandonnées : on repart du document tel qu'il a été ouvert.
            source, word = ed.source, ed.origine_word
            if self.charger_fichier(self.chemin_pdf):
                self.edition = Edition(self.apercu.doc, source, origine_word=word)
                self.label_fichier.configure(text=os.path.basename(source))
        else:
            ed.modifie = False
        self._maj_etat_edition()
        return True


def desinstaller_avec_confirmation() -> None:
    """« Pagilis.exe --desinstaller », lancé par Windows (Applications installées)."""
    racine = ctk.CTk()
    racine.withdraw()
    if messagebox.askyesno("Désinstaller Pagilis",
                           "Désinstaller Pagilis de ce PC ?\n\n"
                           "Vos documents ne sont pas touchés. Vos préférences sont conservées.",
                           parent=racine):
        # Lancé depuis l'exe installé : son dossier n'est supprimé qu'après notre fermeture.
        depuis_installation = installation.tourne_depuis_installation()
        installation.desinstaller(attendre_pid=os.getpid() if depuis_installation else None)
        messagebox.showinfo("Pagilis", "Pagilis a été désinstallé.", parent=racine)
    racine.destroy()


def main() -> None:
    arguments = sys.argv[1:]
    if "--verifier" in arguments:
        # Auto-vérification sans fenêtre (CI, et nouvelle version avant installation).
        import verification
        echecs = verification.verifier()
        logging.info("Auto-vérification %s : %s", updater.APP_VERSION, "OK" if not echecs else echecs)
        sys.exit(1 if echecs else 0)
    if "--desinstaller" in arguments:
        return desinstaller_avec_confirmation()
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
