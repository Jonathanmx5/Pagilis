# Édition rapide : corriger et déplacer du texte, PDF et Word

Date : 2026-11-06 — statut : design validé, à planifier.

## Besoin

L'utilisateur veut ouvrir un PDF **ou un Word** et le modifier vite : corriger
le texte d'une ligne, déplacer un bloc de texte. Un Word aboutit à un **PDF**
(choix de l'utilisateur). Aujourd'hui, « Remplacer du texte » (rechercher /
remplacer) et « Déplacer du texte » existent mais sont deux onglets séparés,
qui écrivent chacun un nouveau fichier : trop lent pour des retouches.

Critères de réussite :
- un clic sur une ligne de l'aperçu permet de la corriger sur place ;
- un glisser déplace le bloc, sans changer de fonction ;
- les retouches s'accumulent, s'annulent (Ctrl+Z) et s'enregistrent une fois (Ctrl+S) ;
- un .docx/.doc/.rtf/.odt s'ouvre comme un PDF, avec la mise en page de Word.

Hors périmètre : enregistrer en Word ; ajouter du texte nouveau ; corriger un
scan sans OCR ; reprendre la police d'origine ; édition sur plusieurs lignes
à la fois (paragraphe complet).

## Vue d'ensemble

| Unité | Rôle | Dépend de |
|---|---|---|
| `conversion.py` (nouveau) | Word → PDF (Word puis LibreOffice) | PowerShell, `soffice` |
| `pdf_core.py` | `line_at`, `rewrite_line` (nouvelles), `move_text_block` (existante) | PyMuPDF |
| `edition.py` (nouveau) | Copie de travail : retouches, annulation, état « modifié », enregistrement | `pdf_core` |
| `pagilis.py` | Page « Modifier » : saisie sur place, glisser, raccourcis, alertes | les trois ci-dessus, `Apercu` |

`edition.py` et `conversion.py` n'ont aucune interface : testables sans écran.

## 1. Conversion Word → PDF (`conversion.py`)

```python
EXTENSIONS_WORD = (".docx", ".doc", ".rtf", ".odt")
def est_word(chemin: str) -> bool
def word_vers_pdf(source: str, dossier: str, delai: int = 120) -> str
```

- Retourne le chemin du PDF créé dans `dossier` (un dossier temporaire propre
  à la session, vidé à la fermeture).
- **Microsoft Word d'abord**, piloté par un script PowerShell (COM, même
  technique que les raccourcis de `installation.py`, aucune dépendance Python
  nouvelle) : `Word.Application` invisible, `DisplayAlerts = 0`,
  `Documents.Open(source, ReadOnly=True, AddToRecentFiles=False)`,
  `ExportAsFixedFormat(sortie, 17)` (PDF), fermeture sans enregistrer, `Quit`.
  Le script est lancé avec `CREATE_NO_WINDOW` et `delai` secondes au plus.
- **Sinon LibreOffice** s'il est trouvé (`Program Files[ (x86)]\LibreOffice\program\soffice.exe`) :
  `soffice --headless --convert-to pdf --outdir <dossier> <source>`.
- **Sinon** `PagilisError("Pour ouvrir un fichier Word, Microsoft Word ou LibreOffice doit être installé.")`.
- Un échec du convertisseur (code non nul, délai dépassé, PDF absent) lève
  `PagilisError` avec un message clair ; un Word protégé par mot de passe
  échoue proprement (pas de boîte de dialogue Word : `PasswordDocument` vide
  passé à `Open`) avec « Ce fichier Word est protégé : ouvrez-le dans Word
  pour retirer le mot de passe. »
- La détection Word = clé `HKCR\Word.Application\CurVer` (lecture du registre
  réel par l'exe ; voir la remarque MSIX : testée par simulation).

## 2. Logique PDF (`pdf_core.py`)

```python
def line_at(page, point) -> Optional[LineInfo]   # point en repère affiché
@dataclass
class LineInfo:
    rect: fitz.Rect      # repère affiché (pour poser la zone de saisie)
    text: str            # texte de la ligne, segments concaténés
    size: float          # taille dominante (pour la police de la zone de saisie)
    block_rect: fitz.Rect  # bloc (paragraphe) qui contient la ligne, repère affiché

def rewrite_line(doc, page_index, point, new_text, shrink_if_longer=True) -> bool
```

- `line_at` cherche la ligne horizontale (`_horizontal_line`) dont la bbox
  contient le point (tolérance 2 pt) ; `None` si aucune (vide, image, scan).
- `rewrite_line` efface la ligne entière (`_redact_rects`) puis écrit
  `new_text` à l'origine du premier segment, **au style du segment le plus
  long** (police, taille, couleur, gras/italique) via `_write_span`. Si le
  texte est plus large que l'ancien et `shrink_if_longer`, la taille est
  réduite pour tenir dans la largeur d'origine (comme `replace_text`). Un
  texte vide efface la ligne. Retourne Faux si aucune ligne au point.
- Une ligne inchangée n'est pas réécrite (pas de perte de police inutile).
- Le déplacement réutilise `move_text_block(doc, page, block_rect, dx, dy)`.
- Toutes les coordonnées d'entrée sont en repère affiché ; conversions par
  `derotation_matrix` comme les fonctions existantes (pages tournées 0/90/180/270).

## 3. Copie de travail (`edition.py`)

```python
class Edition:
    def __init__(self, doc, source: str, origine_word: bool, max_annulations=20)
    doc: fitz.Document; modifie: bool; peut_annuler: bool
    def corriger(self, page, point, texte) -> bool
    def deplacer(self, page, rect, dx, dy) -> int
    def annuler(self) -> fitz.Document   # nouveau doc à recharger dans l'aperçu
    def nom_propose(self) -> str         # <nom>.pdf (Word) / <nom>_modifie.pdf (PDF)
    def enregistrer(self, chemin) -> None  # save_atomic ; modifie = False
```

- Avant chaque retouche : instantané `doc.tobytes()` empilé (20 au plus, le plus
  ancien tombe). `annuler` rouvre le dernier instantané. Une retouche qui ne
  change rien (aucune ligne, 0 segment) ne crée pas d'instantané.
- Enregistrer sur le fichier d'origine est permis (écriture atomique) ; le
  dossier proposé est celui du fichier source (pour un Word : à côté du .docx).
- Un PDF protégé : le mot de passe déjà mémorisé (`remember_password`) sert à
  l'ouverture ; l'enregistrement produit un PDF non chiffré (limite annoncée).

## 4. Interface : page « Modifier » (`pagilis.py`)

- Premier élément de `FONCTIONS` : `("Modifier", "✎", "Corriger ou déplacer du texte, PDF ou Word")`.
  Les autres pages ne changent pas.
- Panneau : bouton **Ouvrir** (PDF + Word), boutons **Annuler** (Ctrl+Z) et
  **Enregistrer** (Ctrl+S), et un rappel d'usage : « Cliquez sur une ligne pour
  la corriger, faites glisser un bloc pour le déplacer. »
- Le filtre d'ouverture commun (`choisir_pdf`) accepte aussi les Word ; un Word
  est converti par `lancer()` (barre de progression indéterminée, message
  « Conversion du document Word… »), puis chargé.
- Gestes dans l'aperçu (page « Modifier » active) :
  - **appui** : on note le point et la ligne/le bloc sous la souris ;
  - **glisse** au-delà de 5 px écran : mode déplacement, fantôme du bloc
    (même rendu que « Déplacer du texte ») ;
  - **relâche** : en mode déplacement → `deplacer` ; sinon, si une ligne est
    sous le point → zone de saisie.
- **Zone de saisie** : `CTkEntry` placée sur le canevas (`create_window`) au
  `rect` de la ligne (`rect_canevas`), largeur ≥ ligne, police à la taille
  affichée de la ligne, texte actuel sélectionné. **Entrée** → `corriger` ;
  **Échap** ou clic ailleurs → abandon. Une seule zone à la fois ; changer de
  page, zoomer ou lancer un traitement la ferme sans appliquer.
- Après chaque retouche ou annulation : l'aperçu se redessine sur la même page
  et le même zoom ; le titre de la fenêtre affiche « • » si modifié.
- **Alertes** : fermer la fenêtre, ouvrir un autre fichier ou quitter la page
  avec des retouches non enregistrées → « Enregistrer les modifications ? »
  (Oui / Non / Annuler).
- Clic sur une page sans texte : statut « Aucun texte ici. Page scannée ?
  Utilisez l'OCR d'abord. »
- Première correction de la session : statut rappelant que la ligne est
  réécrite en Arial / Times / Courier.

## 5. Erreurs

- Conversion : `PagilisError` → boîte d'avertissement, rien n'est chargé.
- Retouche : exécutée dans le thread de l'interface (une ligne, rapide) ; toute
  exception est journalisée, l'instantané est restauré, message « Retouche
  impossible, le document n'a pas changé. »
- Enregistrement : via `lancer()` ; échec → message, `modifie` reste vrai.

## 6. Tests

- `tests/test_conversion.py` : choix du convertisseur et messages avec
  `subprocess.run`/détection simulés (Word présent, LibreOffice seul, aucun,
  délai dépassé, PDF absent) ; vraie conversion d'un .docx minimal **seulement
  si Word est installé** (`pytest.mark.skipif`) — sautée sur la CI GitHub.
  Le .docx de test est généré par le test (zip minimal), pas de fichier binaire versionné.
- `tests/test_core.py` : `line_at` et `rewrite_line` aux 4 rotations
  (position, texte relu par `get_text`, voisines intactes, texte vide, réduction).
- `tests/test_edition.py` : annulation (ordre, limite 20, retouche nulle sans
  instantané), `modifie`, `nom_propose`, `enregistrer`.
- `tests/test_interface.py` : scénario clic → saisie → Entrée → texte relu ;
  glisser → bloc déplacé ; Ctrl+Z ; alerte à la fermeture avec retouches.
- Couverture : le seuil de 80 % reste exigé.

## 7. Documentation

- `CHANGELOG.md` : section de la prochaine version (1.3.0).
- `README.md` : fonction « Modifier », ouverture des Word (Word ou LibreOffice
  requis), limites (police réécrite, scans, PDF protégé enregistré sans mot de passe).
