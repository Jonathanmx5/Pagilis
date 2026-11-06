# Édition rapide (PDF et Word) — plan de réalisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une page « Modifier » où l'on ouvre un PDF ou un Word, corrige une ligne d'un clic et déplace un bloc d'un glisser, avec annulation et un seul enregistrement.

**Architecture :** trois unités sans interface (`pdf_core.line_at`/`rewrite_line`, `edition.Edition` pour la copie de travail, `conversion.word_vers_pdf`), puis la page dans `pagilis.py` qui les relie à l'aperçu existant (`Apercu`, gestes `on_appui/on_glisse/on_relache`).

**Tech Stack :** Python 3.10+, PyMuPDF 2.1, CustomTkinter 6.0, PowerShell (COM Word), pytest 9.

**Spec :** `docs/superpowers/specs/2026-11-06-edition-rapide-design.md` — à lire avant chaque tâche.

## Global Constraints

- Aucune dépendance Python nouvelle (Word piloté par PowerShell, comme `installation._creer_raccourci`).
- Commentaires, messages et noms en français ; en-tête `# SPDX-License-Identifier: AGPL-3.0-or-later` sur tout nouveau fichier.
- Entrées des fonctions PDF en **repère affiché** ; texte et caviardage en repère non tourné (`derotation_matrix`) ; tests aux rotations 0/90/180/270.
- Messages exacts : `"Pour ouvrir un fichier Word, Microsoft Word ou LibreOffice doit être installé."` ; `"Ce fichier Word est protégé : ouvrez-le dans Word pour retirer le mot de passe."` ; `"Aucun texte ici. Page scannée ? Utilisez l'OCR d'abord."` ; `"Retouche impossible, le document n'a pas changé."` ; `"Enregistrer les modifications ?"` ; rappel d'usage `"Cliquez sur une ligne pour la corriger, faites glisser un bloc pour le déplacer."`.
- Annulations : 20 au plus. Seuil glisser : 5 px écran. Délai conversion : 120 s. Tolérance `line_at` : 2 pt.
- Tout nouveau module `.py` ajouté à la liste pyflakes de `build_exe.bat` (ASCII + CRLF : éditer en Python, pas `sed`) et de `.github/workflows/ci.yml`.
- Couverture ≥ 80 % (`.coveragerc`) ; `python -m pytest` vert à chaque commit.
- Commits terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Ligne aux segments de styles mixtes (mot en gras au milieu) → la ligne est réécrite au style du segment le plus long, et rien d'autre de la page ne bouge. *(test Tâche 1)*
2. Zone de saisie ouverte puis zoom / changement de page / traitement lancé → la zone disparaît sans rien appliquer. *(test Tâche 5)*
3. Nom de Word contenant espaces, accents ou apostrophe (`L'été 2026.docx`) → conversion correcte (chemins passés au script PowerShell sans interpolation). *(test Tâche 3)*
4. Plus de 20 retouches puis annulations répétées → 20 annulations, puis le bouton s'éteint ; aucune exception. *(test Tâche 2)*
5. Fermer la fenêtre avec retouches et répondre « Annuler » → la fenêtre reste ouverte, le document est intact. *(test Tâche 6)*

---

### Task 1 : Trouver et réécrire une ligne (`pdf_core.py`)

**Files :**
- Modify : `pdf_core.py` (après `move_text_block`)
- Test : `tests/test_core.py`

**Interfaces :**
- Consumes : `iter_lines`, `_horizontal_line`, `_spans_of_line`, `_redact_rects`, `_write_span`, `to_displayed`, `text_blocks` (existants).
- Produces :
  - `@dataclass LineInfo(rect: fitz.Rect, text: str, size: float, block_rect: fitz.Rect)` — rects en repère affiché.
  - `line_at(page: fitz.Page, point: fitz.Point) -> Optional[LineInfo]`
  - `rewrite_line(doc: fitz.Document, page_index: int, point: fitz.Point, new_text: str, shrink_if_longer: bool = True) -> bool`

- [ ] **Step 1 : tests qui échouent**, paramétrés `rotation in (0, 90, 180, 270)` sur un PDF de 3 lignes (« Le client accepte le devis. », « Montant total : 1 200 euros. », « Le client signe ci-dessous. ») construit comme la fixture `contrat` de `tests/test_interface.py` :
  - `test_line_at_finds_displayed_line` : point au centre affiché de la ligne 2 → `info.text == "Montant total : 1 200 euros."`, `info.rect` contient le point, `info.block_rect` contient `info.rect`, `info.size ≈ 12`.
  - `test_line_at_outside_text_is_none` : point (5, 5) → `None` ; page sans texte → `None`.
  - `test_rewrite_line_replaces_only_that_line` : `rewrite_line(..., "Montant total : 950 euros.")` → `True` ; `get_text()` contient le nouveau texte, plus l'ancien ; lignes 1 et 3 intactes ; position affichée du premier mot à < 2 pt de l'ancienne.
  - `test_rewrite_line_empty_text_erases` : `""` → ligne absente, les autres présentes.
  - `test_rewrite_line_shrinks_longer_text` : texte 2× plus long → largeur affichée de la nouvelle ligne ≤ ancienne largeur + 1 pt.
  - `test_rewrite_line_mixed_styles_uses_longest_span` *(Review Focus 1)* : ligne « Total **TTC** à payer maintenant » (segment gras court au milieu) → après réécriture, un seul style relu (`flags` du segment le plus long), autres lignes intactes.
  - `test_rewrite_line_unchanged_text_is_noop` : même texte → `False`, contenu de la page (`page.read_contents()`) inchangé.
  - `test_rewrite_line_no_line_returns_false`.
- [ ] **Step 2 :** `python -m pytest tests/test_core.py -k "line_at or rewrite_line" -q` → FAIL (`AttributeError: line_at`).
- [ ] **Step 3 : implémenter** `LineInfo`, `line_at`, `rewrite_line`. Point affiché → non tourné par `* page.derotation_matrix` ; recherche dans `iter_lines` limitée aux lignes `_horizontal_line`, bbox `+ (-2, -2, 2, 2)`. `block_rect` = le rect de `text_blocks(page)` qui contient `rect`. Réécriture : `_redact_rects` sur les bbox des segments, puis un `TextSpan` copié du segment le plus long (`len(text)`) avec `text=new_text`, écrit à l'`origin` du premier segment ; réduction = ancienne largeur / nouvelle (`fitz.get_text_length`, `helv`) comme `replace_text`.
- [ ] **Step 4 :** même commande → PASS ; puis `python -m pytest -q` → tout vert.
- [ ] **Step 5 : commit** `Edition : trouver et reecrire une ligne de texte`.

### Task 2 : Copie de travail avec annulation (`edition.py`)

**Files :**
- Create : `edition.py`
- Test : `tests/test_edition.py`
- Modify : `build_exe.bat`, `.github/workflows/ci.yml` (liste pyflakes)

**Interfaces :**
- Consumes : `pdf_core.rewrite_line`, `pdf_core.move_text_block`, `pdf_core.save_atomic` (Tâche 1 / existants).
- Produces : `class Edition` —
  `__init__(self, doc: fitz.Document, source: str, origine_word: bool = False, max_annulations: int = 20)` ;
  attributs `doc`, `source`, `origine_word`, `modifie: bool` ; propriété `peut_annuler: bool` ;
  `corriger(page: int, point: fitz.Point, texte: str) -> bool` ;
  `deplacer(page: int, rect: fitz.Rect, dx: float, dy: float) -> int` ;
  `annuler() -> fitz.Document` (le nouveau `self.doc`) ;
  `nom_propose() -> str` (chemin complet) ;
  `enregistrer(chemin: str) -> None`.

- [ ] **Step 1 : tests qui échouent** (`tests/test_edition.py`, PDF de 3 lignes généré dans `tmp_path`) :
  - `test_correction_marks_modified_and_can_undo` : `corriger` → `True`, `modifie`, `peut_annuler` ; `annuler()` → texte d'origine relu, `peut_annuler` faux.
  - `test_noop_edit_creates_no_snapshot` : `corriger` sur un point vide → `False`, `peut_annuler` faux, `modifie` faux ; `deplacer` d'une zone vide → `0`, idem.
  - `test_undo_limit_is_twenty` *(Review Focus 4)* : 25 corrections successives (`f"Ligne {i}"`) → exactement 20 `annuler()` possibles, texte final == celui après la 5e correction, puis `peut_annuler` faux ; un 21e `annuler()` lève `IndexError` (l'interface consulte `peut_annuler` avant).
  - `test_nom_propose` : PDF `C:/x/contrat.pdf` → `C:/x/contrat_modifie.pdf` ; Word `C:/x/Lettre.docx` → `C:/x/Lettre.pdf` (chemins via `os.path.join`).
  - `test_enregistrer_writes_and_clears_modified` : fichier écrit, relu avec la correction, `modifie` faux ; enregistrer sur `source` lui-même fonctionne.
  - `test_failed_edit_restores_document` : `monkeypatch` de `pdf_core.rewrite_line` qui lève `RuntimeError` après avoir caviardé → `corriger` relève l'exception, mais `doc` relu == avant, `peut_annuler` faux.
- [ ] **Step 2 :** `python -m pytest tests/test_edition.py -q` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3 : implémenter.** Instantané `doc.tobytes()` pris avant la retouche, empilé seulement si elle a changé quelque chose (pile `collections.deque(maxlen=max_annulations)`) ; en cas d'exception, `self.doc = fitz.open("pdf", instantané)` puis relance. `annuler` ferme l'ancien doc et rouvre le dernier instantané (pile vide → `IndexError`). `modifie = True` après toute retouche effective ou annulation, `False` après `enregistrer`. Ajouter `edition.py` aux deux listes pyflakes.
- [ ] **Step 4 :** même commande → PASS ; `python -m pyflakes edition.py tests` sans sortie ; `python -m pytest -q` vert.
- [ ] **Step 5 : commit** `Edition : copie de travail avec annulation`.

### Task 3 : Conversion Word → PDF (`conversion.py`)

**Files :**
- Create : `conversion.py`
- Test : `tests/test_conversion.py`
- Modify : `build_exe.bat`, `.github/workflows/ci.yml` (liste pyflakes)

**Interfaces :**
- Consumes : `pdf_core.PagilisError`.
- Produces :
  `EXTENSIONS_WORD = (".docx", ".doc", ".rtf", ".odt")` ;
  `est_word(chemin: str) -> bool` (insensible à la casse) ;
  `word_vers_pdf(source: str, dossier: str, delai: int = 120) -> str` ;
  points d'injection pour les tests : `word_installe() -> bool`, `chemin_libreoffice() -> Optional[str]`, et l'appel `subprocess.run` du module.

- [ ] **Step 1 : tests qui échouent** :
  - `test_est_word` : `.docx/.DOC/.rtf/.odt` vrais ; `.pdf`, `.txt` faux.
  - `test_uses_word_when_installed` : `word_installe → True`, faux `subprocess.run` qui crée le PDF attendu et note la commande → retourne `dossier/<nom>.pdf` ; la commande est `powershell` avec `-File` ; source et sortie passées en **arguments** (pas dans le texte du script).
  - `test_falls_back_to_libreoffice` : Word absent, `chemin_libreoffice → "C:/LO/soffice.exe"` → commande `[soffice, "--headless", "--convert-to", "pdf", "--outdir", dossier, source]`.
  - `test_no_converter_raises_clear_message` : les deux absents → `PagilisError` au message exact de la spec.
  - `test_converter_failure_or_timeout_raises` : code de retour 1 → `PagilisError` ; `subprocess.TimeoutExpired` → `PagilisError` ; code 0 mais PDF absent → `PagilisError`.
  - `test_protected_word_message` : sortie d'erreur du script contenant `MOT_DE_PASSE` (marqueur écrit par le script) → message exact « Ce fichier Word est protégé… ».
  - `test_real_word_conversion` *(Review Focus 3)*, `@pytest.mark.skipif(not conversion.word_installe(), reason="Word absent")` : .docx minimal généré par `zipfile` (`[Content_Types].xml`, `_rels/.rels`, `word/document.xml` avec « Bonjour Pagilis ») nommé `L'été 2026.docx` → PDF ouvert par PyMuPDF, texte « Bonjour Pagilis » présent.
- [ ] **Step 2 :** `python -m pytest tests/test_conversion.py -q` → FAIL.
- [ ] **Step 3 : implémenter.** Script PowerShell écrit dans `dossier` (UTF-8 avec BOM), lit `$args[0]` / `$args[1]` ; `Word.Application` invisible, `DisplayAlerts = 0`, `Documents.Open($args[0], $false, $true, $false, "x")` (mot de passe factice : un document protégé échoue au lieu d'ouvrir une boîte ; dans le `catch`, écrire `MOT_DE_PASSE` sur stderr si le message d'erreur parle de mot de passe, `exit 2`), `ExportAsFixedFormat($args[1], 17)`, `Close(0)`, `Quit()` dans un `finally`. Lancement `["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, source, sortie]`, `timeout=delai`, `creationflags=CREATE_NO_WINDOW`, `capture_output=True`. `word_installe` lit `HKEY_CLASSES_ROOT\Word.Application\CurVer` avec `winreg` (exception → `False`). Ajouter `conversion.py` aux listes pyflakes.
- [ ] **Step 4 :** même commande → PASS (le test réel passe ici, Word étant installé) ; `python -m pytest -q` vert.
- [ ] **Step 5 : commit** `Conversion des documents Word en PDF`.

### Task 4 : Page « Modifier » et ouverture PDF/Word (`pagilis.py`)

**Files :**
- Modify : `pagilis.py` (`FONCTIONS`, construction des pages, `choisir_pdf`, `charger_fichier`, nouvelle méthode `_construire_page_modifier`)
- Test : `tests/test_interface.py`

**Interfaces :**
- Consumes : `Edition` (Tâche 2), `conversion.est_word`, `conversion.word_vers_pdf` (Tâche 3).
- Produces (utilisés par les Tâches 5–6) : `self.edition: Optional[Edition]` ; `ouvrir_document(chemin: str) -> None` ; `self.dossier_conversions` (`tempfile.mkdtemp`, supprimé dans `_fermer`).

- [ ] **Step 1 : tests qui échouent** :
  - `test_modifier_is_first_function` : premier bouton de `app.boutons_nav` == « Modifier » ; le panneau contient le rappel d'usage exact.
  - `test_open_pdf_creates_working_copy` : `app.ouvrir_document(contrat)` sur la page « Modifier » → `app.edition.source == str(contrat)`, `app.apercu.doc is app.edition.doc`.
  - `test_open_word_converts_then_loads` : `monkeypatch` de `conversion.word_vers_pdf` qui copie `contrat` vers `dossier/lettre.pdf` → après `yield TRAVAUX`, `app.edition.origine_word`, `app.edition.source` se termine par `lettre.docx`, aperçu chargé.
  - `test_word_conversion_error_is_shown` : `word_vers_pdf` lève `PagilisError("…installé.")` → message d'avertissement affiché, `app.edition is None`.
- [ ] **Step 2 :** `python -m pytest tests/test_interface.py -k "modifier or open_" -q` → FAIL.
- [ ] **Step 3 : implémenter.** `("Modifier", "✎", "Corriger ou déplacer du texte, PDF ou Word")` en tête de `FONCTIONS`. Filtres d'ouverture : `[("PDF et Word", "*.pdf *.docx *.doc *.rtf *.odt"), ("PDF", "*.pdf")]`. `choisir_pdf` appelle `ouvrir_document`, qui : pour un Word, `statut("Conversion du document Word…")` puis `lancer(lambda p: conversion.word_vers_pdf(chemin, self.dossier_conversions), fin=…)` ; ensuite `charger_fichier(pdf)` et `self.edition = Edition(self.apercu.doc, chemin, origine_word=True)` ; pour un PDF, `charger_fichier` puis `Edition(..., origine_word=False)`. `self.chemin_pdf` reste le PDF (converti pour un Word) pour les autres fonctions. Panneau : Ouvrir, Annuler (désactivé), Enregistrer (désactivé), rappel d'usage.
- [ ] **Step 4 :** même commande → PASS ; `python -m pytest -q` vert.
- [ ] **Step 5 : commit** `Page Modifier : ouverture des PDF et des Word`.

### Task 5 : Clic pour corriger, glisser pour déplacer

**Files :**
- Modify : `pagilis.py` (`_souris_appui/_souris_glisse/_souris_relache`, `_dessiner_superpositions`, `_page_changee`, nouvelles `_ouvrir_saisie`, `_fermer_saisie`, `_valider_saisie`)
- Test : `tests/test_interface.py`

**Interfaces :**
- Consumes : `self.edition` (Tâche 4), `pdf_core.line_at` / `LineInfo` (Tâche 1), `Apercu.rect_canevas`, `Apercu.vers_canevas`.
- Produces : `self.saisie: Optional[ctk.CTkEntry]` (zone ouverte), `self._ligne_saisie: Optional[LineInfo]`.

- [ ] **Step 1 : tests qui échouent** (page « Modifier », `contrat` ouvert, page 2 tournée à 90°) :
  - `test_click_line_opens_entry_with_its_text` : appui + relâche au centre de « Montant total… » → `app.saisie` visible, `app.saisie.get() == "Montant total : 1 200 euros."`.
  - `test_enter_applies_correction` : remplacer le texte, `app.saisie.event_generate("<Return>")` → `app.saisie is None`, `app.edition.modifie`, texte relu sur `app.apercu.page`, même page affichée.
  - `test_escape_cancels` : `<Escape>` → zone fermée, `modifie` faux.
  - `test_entry_closes_on_zoom_page_change_or_job` *(Review Focus 2)* : zone ouverte puis `apercu.zoomer(1.25)` → fermée sans appliquer ; idem `apercu.aller(0)` ; idem `app.lancer(lambda p: None)`.
  - `test_drag_moves_block_with_ghost` : appui sur le bloc, glisse +100 pt en y (au-delà de 5 px écran) → une superposition « fantôme » existe ; relâche → mot « signe » déplacé de 100 pt (± 3), aucune zone de saisie ouverte.
  - `test_small_jitter_is_a_click` : appui puis glisse de 1 pt puis relâche → zone de saisie ouverte, aucun déplacement.
  - `test_click_on_scan_suggests_ocr` : page sans texte → statut exact « Aucun texte ici… », pas de zone.
- [ ] **Step 2 :** `python -m pytest tests/test_interface.py -k "click or enter_ or escape or entry_closes or drag or jitter" -q` → FAIL.
- [ ] **Step 3 : implémenter.** Branche `self.page_active == "Modifier"` dans les trois gestes : l'appui mémorise point et `line_at` ; la glisse passe en mode déplacement quand la distance **canevas** (`vers_canevas` des deux points) dépasse 5 px et dessine le fantôme de `block_rect` ; la relâche appelle `edition.deplacer(...)` ou `_ouvrir_saisie(info)`. Zone : `CTkEntry` posée par `canevas.create_window` au coin haut-gauche de `rect_canevas(info.rect)`, largeur max(ligne, 200 px), police à `info.size × zoom`, texte sélectionné, focus ; `<Return>` → `_valider_saisie`, `<Escape>`/`<FocusOut>` → `_fermer_saisie`. `_page_changee`, le zoom (`Apercu` rappelle `on_dessin`, fermer si l'échelle a changé) et `lancer()` ferment la zone. Retouche dans le thread de l'interface ; exception → journal + message exact « Retouche impossible… ». Après retouche : `apercu.charger(edition.doc)` puis `apercu.aller(index)` (même page, même zoom). Statut à la première correction : rappel Arial / Times / Courier.
- [ ] **Step 4 :** même commande → PASS ; `python -m pytest -q` vert.
- [ ] **Step 5 : commit** `Page Modifier : corriger d'un clic, deplacer d'un glisser`.

### Task 6 : Annuler, enregistrer, alertes ; documentation

**Files :**
- Modify : `pagilis.py` (boutons, raccourcis `<Control-z>` / `<Control-s>`, titre « • », `_fermer`, `afficher_page`, `ouvrir_document`), `tests/test_interface.py` (fixture `ui` : `askyesnocancel` simulé par `d.oui_non_annuler`), `CHANGELOG.md` (section `## [1.3.0]`), `README.md`, `updater.py` (`APP_VERSION = "1.3.0"`)
- Test : `tests/test_interface.py`

**Interfaces :**
- Consumes : `Edition.annuler/enregistrer/nom_propose/modifie/peut_annuler` (Tâche 2), `self.edition` (Tâche 4).
- Produces : `annuler_retouche() -> None`, `enregistrer_edition() -> None`, `_confirmer_abandon() -> bool` (Vrai = on peut continuer).

- [ ] **Step 1 : tests qui échouent** :
  - `test_ctrl_z_undoes_and_disables_button` : correction puis `annuler_retouche()` → texte d'origine, bouton Annuler désactivé.
  - `test_ctrl_s_saves_proposed_name` : correction, `d.enregistrer_sous = str(tmp_path / "out.pdf")`, `enregistrer_edition()` + `yield TRAVAUX` → fichier relu avec la correction, titre sans « • », `modifie` faux ; `initialfile` passé au dialogue == `contrat_modifie.pdf` (Word : `lettre.pdf`, `initialdir` = dossier du .docx).
  - `test_title_marks_unsaved_changes` : après correction, `"•" in app.title()`.
  - `test_close_with_changes_cancel_keeps_window` *(Review Focus 5)* : correction, `d.oui_non_annuler = None`, `app._fermer()` → fenêtre toujours là (`app.winfo_exists()`), `modifie` vrai.
  - `test_close_with_changes_no_discards` : `False` → fenêtre détruite, aucun fichier écrit.
  - `test_close_with_changes_yes_saves_first` : `True` + `d.enregistrer_sous` → fichier écrit puis fermeture.
  - `test_leave_page_or_open_other_file_asks` : correction puis `afficher_page("Fusion")` avec `None` → reste sur « Modifier » ; `ouvrir_document(autre)` avec `None` → document inchangé.
- [ ] **Step 2 :** `python -m pytest tests/test_interface.py -k "ctrl_ or title_marks or close_with or leave_page" -q` → FAIL.
- [ ] **Step 3 : implémenter.** `_confirmer_abandon` : rien à faire si pas de retouche ; sinon `messagebox.askyesnocancel("Pagilis", "Enregistrer les modifications ?")` → `None` : Faux ; `False` : Vrai ; `True` : enregistrement **synchrone** (`edition.enregistrer`) puis Vrai, Faux si le dialogue de nom est annulé. Appelé par `_fermer`, `afficher_page` (en quittant « Modifier ») et `ouvrir_document`. Enregistrement par le bouton : `lancer()` avec `edition.enregistrer`. Raccourcis liés sur la fenêtre, actifs seulement sur « Modifier » et hors zone de saisie. `APP_VERSION = "1.3.0"` ; CHANGELOG 1.3.0 : fonction Modifier, ouverture des Word (Word ou LibreOffice requis) ; README : section fonction + limites (police réécrite, scans, PDF protégé enregistré sans mot de passe).
- [ ] **Step 4 :** même commande → PASS ; `python -m pyflakes pdf_core.py pagilis.py apercu.py updater.py installation.py verification.py publication.py identite.py edition.py conversion.py tests` sans sortie ; `python -m coverage run -m pytest -q && python -m coverage report` → total ≥ 80 %.
- [ ] **Step 5 : vérification réelle.** `build_exe.bat` → `dist\Pagilis.exe --verifier` code 0 ; lancer l'exe, ouvrir un vrai .docx, corriger une ligne, déplacer un bloc, Ctrl+Z, Ctrl+S, ouvrir le PDF obtenu.
- [ ] **Step 6 : commit** `Page Modifier : annuler, enregistrer, alertes (1.3.0)` (pas de tag : la publication reste une décision de l'utilisateur).
