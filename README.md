# Pagilis

Application Windows pour lire, assembler, découper, signer et modifier des PDF,
et rendre les scans cherchables (OCR).

## Télécharger

Dernière version : [Releases](https://github.com/Jonathanmx5/Pagilis/releases/latest).
L'application vérifie elle-même les mises à jour à chaque démarrage.

**Portable** : `Pagilis.exe` se lance tel quel, sans installation (clé USB,
dossier Téléchargements…).

**Installation** (facultative) : depuis la version portable, bouton
**Installer sur ce PC** en bas de la barre latérale. Sans droits
administrateur : copie dans `%LOCALAPPDATA%\Programs\Pagilis`, raccourcis
menu Démarrer et Bureau, Pagilis proposé dans « Ouvrir avec » pour les PDF.
Désinstallation depuis *Paramètres > Applications installées* ; les
préférences (`%LOCALAPPDATA%\Pagilis`) sont conservées.

**Anciennement PDF Studio** : jusqu'à la version 1.1.0, l'application
s'appelait PDF Studio. Une installation de PDF Studio qui reçoit la mise à jour
devient automatiquement Pagilis (nouveau dossier, raccourcis et entrée Windows ;
l'ancienne installation est retirée), et les préférences sont reprises.

## Modifier un PDF ou un Word

Fonction **Modifier** : ouvrir un PDF ou un document Word, puis dans l'aperçu
cliquer sur une ligne pour la corriger (Entrée pour valider, Échap pour
abandonner) ou faire glisser un bloc pour le déplacer. Ctrl+Z annule les 20
dernières retouches, Ctrl+S enregistre en PDF (pour un Word : `<nom>.pdf` à
côté du document). Un Word est converti avec Microsoft Word, ou LibreOffice
s'il n'y a pas Word ; sans l'un des deux, il ne peut pas être ouvert.

## Limites connues

- Remplacer / déplacer du texte : la police d'origine n'est pas réutilisée (les
  polices incorporées sont des sous-ensembles). Le texte est réécrit en Arial,
  Times New Roman ou Courier New selon son style.
- Pas de recherche à cheval sur deux lignes.
- Pas de détection des pages à l'envers ou couchées à 90°.
- Le redressement des pages penchées et le remplacement de texte sur un scan ne
  sont pas encore disponibles.
- Modifier : une ligne corrigée est réécrite d'un seul style (celui de son
  morceau le plus long) ; une page scannée doit d'abord passer à l'OCR ; un PDF
  protégé est enregistré sans mot de passe ; un Word protégé par mot de passe
  ne s'ouvre pas ; le résultat d'un Word est un PDF, pas un Word.
- Un .exe non signé peut être signalé par Windows Defender.
- Journal d'erreurs : `%LOCALAPPDATA%\Pagilis\pagilis.log`.

## Développer

```bat
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python pagilis.py
```

- `pdf_core.py` : toute la logique PDF, sans interface (testée).
- `pagilis.py`, `apercu.py` : l'interface.
- `updater.py` : vérification et installation des mises à jour.
- `installation.py` : installation sur le PC depuis la version portable.

Les versions des dépendances sont figées dans `requirements*.txt` : on les
met à jour volontairement, puis on relance les tests.

## Compiler

`build_exe.bat` installe les dépendances, récupère les fichiers de langue
Tesseract, analyse le code, lance les tests et produit `dist\Pagilis.exe`.

## Publier une version

1. Écrire les nouveautés dans `CHANGELOG.md`, section `## [1.2.0]` : elles
   s'affichent dans la fenêtre de mise à jour, et la CI refuse de publier une
   version sans notes.
2. Pousser un tag, la CI fait le reste (tests, exe, auto-vérification de l'exe,
   `version.json`, release) :

```bat
git tag v1.2.0-beta.1
git push origin v1.2.0-beta.1
```

Une **bêta** (`-beta.N`) est publiée comme pré-version GitHub : l'application
ne la propose jamais (seule la dernière version publiée pour tous l'est), on la
télécharge à la main pour l'essayer. Quand elle a fait ses preuves, publier
`v1.2.0` pour tous.

Numérotation : CORRECTIF (1.2.1) = corrections seulement ; MINEUR (1.3.0) =
nouveautés ; MAJEUR (2.0.0) = changements qui cassent des habitudes.

Pour un exe d'essai sans publication : onglet **Actions > Release > Run
workflow**, puis télécharger l'artefact.

## Sûreté des mises à jour

- Empreinte SHA-256 vérifiée après téléchargement.
- La nouvelle version doit réussir `Pagilis.exe --verifier` (PDF, OCR,
  interface) **avant** de remplacer l'ancienne ; sinon l'ancienne est conservée.
- La version remplacée est sauvegardée dans
  `%LOCALAPPDATA%\Pagilis\version-precedente`.
- Si le remplacement échoue (fichier verrouillé), il est abandonné après 30
  essais et l'ancienne version est restaurée.

## Licence

Pagilis est un logiciel libre sous licence
[GNU AGPL-3.0](LICENSE), comme la bibliothèque PyMuPDF qu'il utilise.
Toute copie distribuée, modifiée ou non, doit rester sous cette licence et
donner accès à son code source.
