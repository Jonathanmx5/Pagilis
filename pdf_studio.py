"""Interface de PDF Studio (CustomTkinter). Toute la logique est dans pdf_core."""

from __future__ import annotations

import json
import logging
import os
import threading
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pymupdf as fitz

import pdf_core as core
import updater

# Dossier de configuration et journal, indispensables avec --noconsole.
DOSSIER_DONNEES = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PDFStudio")
os.makedirs(DOSSIER_DONNEES, exist_ok=True)
CONFIG = os.path.join(DOSSIER_DONNEES, "config.json")
logging.basicConfig(
    filename=os.path.join(DOSSIER_DONNEES, "pdfstudio.log"),
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


class PDFStudio(ctk.CTk):
    """Fenêtre principale : un onglet par fonctionnalité."""

    def __init__(self):
        super().__init__()
        self.title("PDF Studio")
        self.geometry("760x620")
        self.config_data = charger_config()
        self.dernier_dossier = self.config_data.get("dernier_dossier", os.path.expanduser("~"))
        self.chemin_pdf: str | None = None
        # Nombre de traitements en cours : la mise à jour est bloquée tant qu'il est > 0.
        self.travaux_en_cours = 0

        # Barre de fichier courant commune à tous les onglets.
        haut = ctk.CTkFrame(self)
        haut.pack(fill="x", padx=12, pady=(12, 0))
        ctk.CTkButton(haut, text="Ouvrir un PDF…", command=self.choisir_pdf).pack(side="left", padx=8, pady=8)
        self.label_fichier = ctk.CTkLabel(haut, text="Aucun fichier")
        self.label_fichier.pack(side="left", padx=8)

        self.onglets = ctk.CTkTabview(self)
        self.onglets.pack(fill="both", expand=True, padx=12, pady=12)
        for nom in ["Fusion", "Division", "Signature / Tampon", "Remplacer du texte",
                    "Déplacer du texte", "OCR (scans)"]:
            self.onglets.add(nom)
        self._construire_fusion()
        self._construire_division()
        self._construire_tampon()
        self._construire_remplacement()
        self._construire_deplacement()
        self._construire_ocr()

        self.barre = ctk.CTkProgressBar(self)
        self.barre.set(0)
        self.barre.pack(fill="x", padx=12)
        self.etat = ctk.CTkLabel(self, text="Prêt", anchor="w")
        self.etat.pack(fill="x", padx=12, pady=(4, 8))
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        # Vérification au démarrage, hors thread de l'interface : rien ne se passe si à jour.
        # La version ignorée est lue ici, dans le thread de l'interface.
        version_ignoree = self.config_data.get("version_ignoree")
        threading.Thread(target=self._chercher_mise_a_jour, args=(version_ignoree,), daemon=True).start()

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
        popup.geometry("420x260")
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
        barre = ctk.CTkProgressBar(popup)
        barre.set(0)
        barre.pack(fill="x", padx=20)
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
            destination = os.path.join(DOSSIER_DONNEES, "PDFStudio_new.exe")

            def progression(lu, total):
                if total:
                    popup.after(0, lambda: barre.set(lu / total))

            def travail():
                try:
                    updater.download(mise_a_jour, destination, progression)
                    popup.after(0, lambda: etat.configure(text="Installation…"))
                    updater.install_and_restart(destination)
                    popup.after(0, self._quitter_sans_sauver)
                except Exception as exc:  # noqa: BLE001 - on affiche l'erreur et on propose de réessayer
                    logging.exception("Échec de la mise à jour")
                    popup.after(0, lambda: self._echec_mise_a_jour(popup, etat, bouton_maj, bouton_quitter, exc))

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

    def _fermer(self):
        self.config_data["dernier_dossier"] = self.dernier_dossier
        sauver_config(self.config_data)
        self.destroy()

    def _memoriser_dossier(self, chemin: str):
        self.dernier_dossier = os.path.dirname(chemin)

    def choisir_pdf(self):
        chemin = filedialog.askopenfilename(
            initialdir=self.dernier_dossier, filetypes=[("PDF", "*.pdf")]
        )
        if chemin:
            self.chemin_pdf = chemin
            self._memoriser_dossier(chemin)
            self.label_fichier.configure(text=os.path.basename(chemin))
            self.statut(f"Fichier ouvert : {os.path.basename(chemin)}")

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
            except core.PasswordRequired:
                self.after(0, lambda: self.statut("Ce PDF est protégé par un mot de passe."))
            except core.PdfStudioError as exc:
                self.after(0, lambda: messagebox.showwarning("PDF Studio", str(exc)))
                self.after(0, lambda: self.statut(str(exc)))
            except Exception:  # noqa: BLE001 - tout doit finir dans le journal
                logging.error(traceback.format_exc())
                self.after(0, lambda: messagebox.showerror(
                    "PDF Studio", "Erreur inattendue. Détails dans pdfstudio.log."))
            finally:
                self.after(0, lambda: self.barre.set(0))
                self.after(0, self._fin_travail)

        self.travaux_en_cours += 1
        threading.Thread(target=cible, daemon=True).start()

    def _fin_travail(self):
        self.travaux_en_cours -= 1

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
        if messagebox.askyesno("PDF Studio", "Ouvrir le résultat ?"):
            os.startfile(chemin)  # noqa: S606 - Windows uniquement

    def _continuer_sur_resultat(self, var: ctk.BooleanVar, chemin: str):
        """Case « Continuer sur le fichier résultat » : le résultat devient le fichier courant."""
        if var.get():
            self.chemin_pdf = chemin
            self.label_fichier.configure(text=os.path.basename(chemin))

    # ---------------------------------------------------------- Fusion

    def _construire_fusion(self):
        onglet = self.onglets.tab("Fusion")
        self.liste_fusion: list[str] = []
        self.zone_fusion = ctk.CTkTextbox(onglet, height=300)
        self.zone_fusion.pack(fill="both", expand=True, padx=8, pady=8)
        self.zone_fusion.configure(state="disabled")
        cadre = ctk.CTkFrame(onglet, fg_color="transparent")
        cadre.pack(fill="x", padx=8)
        ctk.CTkButton(cadre, text="Ajouter des PDF…", command=self.ajouter_fusion).pack(side="left", padx=4)
        ctk.CTkButton(cadre, text="Monter", width=80, command=lambda: self.deplacer_fusion(-1)).pack(side="left", padx=4)
        ctk.CTkButton(cadre, text="Descendre", width=80, command=lambda: self.deplacer_fusion(1)).pack(side="left", padx=4)
        ctk.CTkButton(cadre, text="Vider", width=80, command=self.vider_fusion).pack(side="left", padx=4)
        ctk.CTkButton(cadre, text="Fusionner", command=self.lancer_fusion).pack(side="right", padx=4)

    def _rafraichir_fusion(self):
        self.zone_fusion.configure(state="normal")
        self.zone_fusion.delete("1.0", "end")
        for i, p in enumerate(self.liste_fusion, 1):
            self.zone_fusion.insert("end", f"{i}. {os.path.basename(p)}\n")
        self.zone_fusion.configure(state="disabled")

    def ajouter_fusion(self):
        chemins = filedialog.askopenfilenames(initialdir=self.dernier_dossier, filetypes=[("PDF", "*.pdf")])
        if chemins:
            self.liste_fusion.extend(chemins)
            self._memoriser_dossier(chemins[0])
            self._rafraichir_fusion()

    def deplacer_fusion(self, sens: int):
        # Ici la liste sert de modèle : on déplace le DERNIER fichier ajouté, faute de sélection.
        if len(self.liste_fusion) > 1:
            i = len(self.liste_fusion) - 1 if sens < 0 else 0
            j = i + sens
            if 0 <= j < len(self.liste_fusion):
                self.liste_fusion[i], self.liste_fusion[j] = self.liste_fusion[j], self.liste_fusion[i]
            self._rafraichir_fusion()

    def vider_fusion(self):
        self.liste_fusion.clear()
        self._rafraichir_fusion()

    def lancer_fusion(self):
        fichiers = list(self.liste_fusion)
        sortie = filedialog.asksaveasfilename(initialdir=self.dernier_dossier, initialfile="fusion.pdf",
                                              defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not sortie:
            return
        self.statut("Fusion en cours…")
        self.lancer(lambda p: core.merge_pdfs(fichiers, sortie, p),
                    fin=lambda _: self.proposer_ouverture(sortie))

    # -------------------------------------------------------- Division

    def _construire_division(self):
        onglet = self.onglets.tab("Division")
        self.mode_division = ctk.StringVar(value="page")
        for valeur, texte in [("page", "Une page par fichier"),
                              ("n", "Toutes les N pages"),
                              ("plages", "Par plages (ex. 1-3, 5, 8-)")]:
            ctk.CTkRadioButton(onglet, text=texte, variable=self.mode_division, value=valeur).pack(anchor="w", padx=12, pady=4)
        self.entree_n = ctk.CTkEntry(onglet, placeholder_text="N (pour le mode « toutes les N pages »)")
        self.entree_n.pack(fill="x", padx=12, pady=4)
        self.entree_plages = ctk.CTkEntry(onglet, placeholder_text="Plages, ex. 1-3, 5, 8-")
        self.entree_plages.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(onglet, text="Diviser", command=self.lancer_division).pack(padx=12, pady=12, anchor="e")

    def lancer_division(self):
        if not self.chemin_pdf:
            return messagebox.showinfo("PDF Studio", "Ouvrez d'abord un PDF.")
        dossier = filedialog.askdirectory(initialdir=self.dernier_dossier)
        if not dossier:
            return
        source = self.chemin_pdf
        mode = self.mode_division.get()
        n = self.entree_n.get().strip()
        plages = self.entree_plages.get().strip()

        def travail(p):
            if mode == "page":
                return core.split_by_page(source, dossier, p)
            if mode == "n":
                if not n.isdigit():
                    raise core.PdfStudioError("Indiquez un nombre entier pour N.")
                return core.split_every_n(source, dossier, int(n), p)
            return core.split_by_ranges(source, dossier, plages, p)

        self.statut("Division en cours…")
        self.lancer(travail, fin=lambda fichiers: self.statut(f"{len(fichiers)} fichier(s) créé(s)."))

    # ---------------------------------------------- Signature / Tampon

    def _construire_tampon(self):
        onglet = self.onglets.tab("Signature / Tampon")
        self.image_tampon: str | None = None
        ctk.CTkButton(onglet, text="Choisir l'image (PNG/JPG)…", command=self.choisir_tampon).pack(anchor="w", padx=12, pady=6)
        self.label_tampon = ctk.CTkLabel(onglet, text="Aucune image")
        self.label_tampon.pack(anchor="w", padx=12)
        self.entree_x = self._champ(onglet, "X (pt)", "72")
        self.entree_y = self._champ(onglet, "Y (pt)", "72")
        self.entree_l = self._champ(onglet, "Largeur (pt)", "120")
        self.entree_op = self._champ(onglet, "Opacité (%)", "100")
        self.rotation_tampon = ctk.StringVar(value="0")
        ctk.CTkOptionMenu(onglet, values=["0", "90", "180", "270"], variable=self.rotation_tampon).pack(anchor="w", padx=12, pady=4)
        self.blanc_transparent = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(onglet, text="Fond blanc transparent (signature scannée)", variable=self.blanc_transparent).pack(anchor="w", padx=12, pady=4)
        self.portee_tampon = ctk.StringVar(value="page")
        ctk.CTkRadioButton(onglet, text="Page affichée (1)", variable=self.portee_tampon, value="page").pack(anchor="w", padx=12)
        ctk.CTkRadioButton(onglet, text="Toutes les pages", variable=self.portee_tampon, value="toutes").pack(anchor="w", padx=12)
        self.entree_plage_tampon = self._champ(onglet, "Ou plage de pages", "")
        self.continuer_tampon = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Continuer sur le fichier résultat", variable=self.continuer_tampon).pack(anchor="w", padx=12, pady=4)
        ctk.CTkButton(onglet, text="Appliquer…", command=self.lancer_tampon).pack(anchor="e", padx=12, pady=8)

    def _champ(self, parent, libelle: str, defaut: str) -> ctk.CTkEntry:
        ligne = ctk.CTkFrame(parent, fg_color="transparent")
        ligne.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(ligne, text=libelle, width=140, anchor="w").pack(side="left")
        entree = ctk.CTkEntry(ligne)
        entree.insert(0, defaut)
        entree.pack(side="left", fill="x", expand=True)
        return entree

    def choisir_tampon(self):
        chemin = filedialog.askopenfilename(initialdir=self.dernier_dossier,
                                            filetypes=[("Images", "*.png *.jpg *.jpeg")])
        if chemin:
            self.image_tampon = chemin
            self.label_tampon.configure(text=os.path.basename(chemin))

    def lancer_tampon(self):
        if not (self.chemin_pdf and self.image_tampon):
            return messagebox.showinfo("PDF Studio", "Ouvrez un PDF et choisissez une image.")
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
            return messagebox.showwarning("PDF Studio", "Vérifiez les valeurs numériques.")
        source = self.chemin_pdf
        image = self.image_tampon
        portee = self.portee_tampon.get()
        plage = self.entree_plage_tampon.get().strip()
        sortie = self.enregistrer_sous("signe")
        if not sortie:
            return

        def travail(p):
            doc = core.open_pdf(source)
            try:
                if plage:
                    pages = core.parse_page_ranges(plage, doc.page_count)
                elif portee == "toutes":
                    pages = list(range(doc.page_count))
                else:
                    pages = [0]
                core.add_stamp(doc, image, pages, opts, p)
                core.save_atomic(doc, sortie)
            finally:
                doc.close()

        self.statut("Application du tampon…")
        self.lancer(travail, fin=lambda _: self._apres_sauvegarde(sortie, self.continuer_tampon))

    def _apres_sauvegarde(self, sortie: str, continuer: ctk.BooleanVar):
        self._continuer_sur_resultat(continuer, sortie)
        self.proposer_ouverture(sortie)

    # ----------------------------------------------- Remplacer du texte

    def _construire_remplacement(self):
        onglet = self.onglets.tab("Remplacer du texte")
        self.entree_ancien = self._champ(onglet, "Texte à remplacer", "")
        self.entree_nouveau = self._champ(onglet, "Nouveau texte (vide = effacer)", "")
        self.entree_plage_rempl = self._champ(onglet, "Pages (vide = toutes)", "")
        self.casse = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Respecter la casse", variable=self.casse).pack(anchor="w", padx=12, pady=2)
        self.reduire = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Réduire la taille si le nouveau texte est plus long", variable=self.reduire).pack(anchor="w", padx=12, pady=2)
        self.continuer_rempl = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Continuer sur le fichier résultat", variable=self.continuer_rempl).pack(anchor="w", padx=12, pady=2)
        cadre = ctk.CTkFrame(onglet, fg_color="transparent")
        cadre.pack(fill="x", padx=12, pady=8)
        ctk.CTkButton(cadre, text="Rechercher (aperçu)", command=self.rechercher_texte).pack(side="left", padx=4)
        ctk.CTkButton(cadre, text="Remplacer…", command=self.lancer_remplacement).pack(side="right", padx=4)
        self.zone_resultats = ctk.CTkTextbox(onglet, height=160)
        self.zone_resultats.pack(fill="both", expand=True, padx=12, pady=6)

    def rechercher_texte(self):
        if not self.chemin_pdf:
            return messagebox.showinfo("PDF Studio", "Ouvrez d'abord un PDF.")
        needle = self.entree_ancien.get()
        casse = self.casse.get()
        source = self.chemin_pdf

        def travail(_p):
            doc = core.open_pdf(source)
            try:
                return core.find_text(doc, needle, casse)
            finally:
                doc.close()

        def fin(resultat):
            self.zone_resultats.delete("1.0", "end")
            if not resultat:
                self.zone_resultats.insert("end", "Aucune occurrence.\nSi c'est un scan, passez par l'onglet OCR.\n")
            for page, n in sorted(resultat.items()):
                self.zone_resultats.insert("end", f"Page {page + 1} : {n} occurrence(s)\n")

        self.lancer(travail, fin=fin)

    def lancer_remplacement(self):
        if not self.chemin_pdf:
            return messagebox.showinfo("PDF Studio", "Ouvrez d'abord un PDF.")
        ancien = self.entree_ancien.get()
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
        self.statut(f"{n} remplacement(s).")
        self._continuer_sur_resultat(self.continuer_rempl, sortie)
        self.proposer_ouverture(sortie)

    # ----------------------------------------------- Déplacer du texte

    def _construire_deplacement(self):
        onglet = self.onglets.tab("Déplacer du texte")
        ctk.CTkLabel(onglet, text="Zone à déplacer (points, repère affiché) : page, x0, y0, x1, y1").pack(anchor="w", padx=12, pady=4)
        self.entree_page_dep = self._champ(onglet, "Page", "1")
        self.entree_zone = self._champ(onglet, "Zone x0,y0,x1,y1", "0,0,300,100")
        self.entree_dx = self._champ(onglet, "Décalage dX (pt)", "0")
        self.entree_dy = self._champ(onglet, "Décalage dY (pt)", "0")
        self.continuer_dep = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Continuer sur le fichier résultat", variable=self.continuer_dep).pack(anchor="w", padx=12, pady=4)
        ctk.CTkButton(onglet, text="Déplacer…", command=self.lancer_deplacement).pack(anchor="e", padx=12, pady=8)

    def lancer_deplacement(self):
        if not self.chemin_pdf:
            return messagebox.showinfo("PDF Studio", "Ouvrez d'abord un PDF.")
        try:
            page = int(self.entree_page_dep.get()) - 1
            x0, y0, x1, y1 = (float(v) for v in self.entree_zone.get().split(","))
            dx = float(self.entree_dx.get())
            dy = float(self.entree_dy.get())
        except ValueError:
            return messagebox.showwarning("PDF Studio", "Vérifiez la page, la zone et les décalages.")
        source = self.chemin_pdf
        sortie = self.enregistrer_sous("deplace")
        if not sortie:
            return

        def travail(_p):
            doc = core.open_pdf(source)
            try:
                if not 0 <= page < doc.page_count:
                    raise core.PdfStudioError("Numéro de page hors du document.")
                n = core.move_text_block(doc, page, fitz.Rect(x0, y0, x1, y1), dx, dy)
                core.save_atomic(doc, sortie)
                return n
            finally:
                doc.close()

        self.statut("Déplacement en cours…")
        self.lancer(travail, fin=lambda n: self._apres_sauvegarde_dep(n, sortie))

    def _apres_sauvegarde_dep(self, n: int, sortie: str):
        self.statut(f"{n} segment(s) déplacé(s).")
        self._continuer_sur_resultat(self.continuer_dep, sortie)
        self.proposer_ouverture(sortie)

    # ----------------------------------------------------------- OCR

    def _construire_ocr(self):
        onglet = self.onglets.tab("OCR (scans)")
        self.entree_langue = self._champ(onglet, "Langue (ex. fra, eng)", "fra")
        self.entree_dpi = self._champ(onglet, "Résolution (200/300/400)", "300")
        self.entree_pages_ocr = self._champ(onglet, "Pages (vide = toutes)", "")
        self.entree_tessdata = self._champ(onglet, "Dossier tessdata (optionnel)", "")
        self.ignorer_texte = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(onglet, text="Ignorer les pages qui ont déjà du texte", variable=self.ignorer_texte).pack(anchor="w", padx=12, pady=2)
        self.continuer_ocr = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(onglet, text="Continuer sur le fichier résultat", variable=self.continuer_ocr).pack(anchor="w", padx=12, pady=2)
        ctk.CTkButton(onglet, text="Lancer l'OCR…", command=self.lancer_ocr).pack(anchor="e", padx=12, pady=8)

    def lancer_ocr(self):
        if not self.chemin_pdf:
            return messagebox.showinfo("PDF Studio", "Ouvrez d'abord un PDF.")
        try:
            dpi = int(self.entree_dpi.get())
        except ValueError:
            return messagebox.showwarning("PDF Studio", "La résolution doit être un nombre.")
        langue = self.entree_langue.get().strip() or "fra"
        plage = self.entree_pages_ocr.get().strip()
        tessdata = self.entree_tessdata.get().strip() or None
        ignorer = self.ignorer_texte.get()
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
        self.statut(f"OCR terminé sur {n} page(s).")
        self._continuer_sur_resultat(self.continuer_ocr, sortie)
        self.proposer_ouverture(sortie)


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    PDFStudio().mainloop()


if __name__ == "__main__":
    main()
