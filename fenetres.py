# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fenêtres annexes : mise à jour proposée, installation sur le PC, désinstallation."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

import identite
import installation
import updater

if TYPE_CHECKING:  # pragma: no cover
    from pagilis import Pagilis


# ---------------------------------------------------------- installation sur le PC


def proposer_installation(app: "Pagilis"):
    """Fenêtre « Installer sur ce PC » (version portable uniquement)."""
    deja = installation.est_installe()
    fenetre = ctk.CTkToplevel(app)
    fenetre.title("Installer Pagilis")
    fenetre.geometry("480x330")
    fenetre.resizable(False, False)
    fenetre.transient(app)
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
    ctk.CTkCheckBox(fenetre, text="Créer un raccourci sur le Bureau", variable=bureau).pack(
        anchor="w", padx=24, pady=(14, 4))
    ctk.CTkCheckBox(fenetre, text="Proposer Pagilis dans « Ouvrir avec » pour les PDF",
                    variable=ouvrir_avec).pack(anchor="w", padx=24, pady=4)
    boutons = ctk.CTkFrame(fenetre, fg_color="transparent")
    boutons.pack(fill="x", side="bottom", padx=24, pady=20)
    ctk.CTkButton(boutons, text="Annuler", width=100, fg_color="gray50", hover_color="gray40",
                  command=fenetre.destroy).pack(side="right")
    ctk.CTkButton(boutons, text="Installer", width=120,
                  command=lambda: _installer(app, fenetre, bureau.get(), ouvrir_avec.get())).pack(
        side="right", padx=8)


def _installer(app: "Pagilis", fenetre, bureau: bool, ouvrir_avec: bool):
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
        app._fermer()


# ------------------------------------------------------------------ mise à jour


def popup_mise_a_jour(app: "Pagilis", mise_a_jour: updater.Update):
    """Popup facultatif : « Plus tard » ou la croix ferment le popup sans rien installer."""
    popup = ctk.CTkToplevel(app)
    popup.title("Mise à jour disponible")
    popup.geometry("460x440" if mise_a_jour.notes else "420x260")
    popup.resizable(False, False)
    popup.transient(app)
    ne_plus_proposer = ctk.BooleanVar(value=False)

    def plus_tard():
        if ne_plus_proposer.get():
            app.config_data["version_ignoree"] = mise_a_jour.version
            app.sauver_preferences()
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

    def echec(exc):
        etat.configure(text=f"Échec : {exc}. Réessayez.")
        bouton_maj.configure(state="normal")
        bouton_quitter.configure(state="normal")

    def installer():
        bouton_maj.configure(state="disabled")
        bouton_quitter.configure(state="disabled")
        etat.configure(text="Téléchargement…")
        barre.pack(fill="x", padx=20, before=etat)
        destination = os.path.join(app.dossier_donnees, "Pagilis_new.exe")

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
                # Fermeture sans écrire la configuration : l'installation prend le relais.
                popup.after(0, app.destroy)
            except Exception as exc:  # noqa: BLE001 - on affiche l'erreur et on propose de réessayer
                logging.exception("Échec de la mise à jour")
                # exc=exc : Python efface `exc` à la sortie du except, avant que le lambda ne s'exécute.
                popup.after(0, lambda exc=exc: echec(exc))

        threading.Thread(target=travail, daemon=True).start()

    bouton_maj.configure(command=installer)

    def surveiller():
        """Grise « Mettre à jour » tant qu'un traitement tourne (l'installation ferme l'application)."""
        if not popup.winfo_exists():
            return
        if bouton_quitter.cget("state") == "disabled":
            pass  # téléchargement en cours : on ne touche à rien
        elif app.travaux_en_cours:
            bouton_maj.configure(state="disabled")
            etat.configure(text="Un traitement est en cours : patientez avant de mettre à jour.")
        elif etat.cget("text").startswith("Un traitement"):
            bouton_maj.configure(state="normal")
            etat.configure(text="")
        popup.after(500, surveiller)

    surveiller()


# --------------------------------------------------------------- désinstallation


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
