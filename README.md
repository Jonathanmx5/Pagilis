# PDF Studio

Application Windows pour lire, assembler, découper, signer et modifier des PDF,
et rendre les scans cherchables (OCR).

## Télécharger

Dernière version : [Releases](https://github.com/Jonathanmx5/PDFStudio/releases/latest).
L'application vérifie elle-même les mises à jour à chaque démarrage.

**Portable** : `PDFStudio.exe` se lance tel quel, sans installation (clé USB,
dossier Téléchargements…).

**Installation** (facultative) : depuis la version portable, bouton
**Installer sur ce PC** en bas de la barre latérale. Sans droits
administrateur : copie dans `%LOCALAPPDATA%\Programs\PDF Studio`, raccourcis
menu Démarrer et Bureau, PDF Studio proposé dans « Ouvrir avec » pour les PDF.
Désinstallation depuis *Paramètres > Applications installées* ; les
préférences (`%LOCALAPPDATA%\PDFStudio`) sont conservées.

## Développer

```bat
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python pdf_studio.py
```

- `pdf_core.py` : toute la logique PDF, sans interface (testée).
- `pdf_studio.py`, `apercu.py` : l'interface.
- `updater.py` : vérification et installation des mises à jour.
- `installation.py` : installation sur le PC depuis la version portable.

Les versions des dépendances sont figées dans `requirements*.txt` : on les
met à jour volontairement, puis on relance les tests.

## Compiler

`build_exe.bat` installe les dépendances, récupère les fichiers de langue
Tesseract, analyse le code, lance les tests et produit `dist\PDFStudio.exe`.

## Publier une version

Pousser un tag suffit, la CI fait le reste (tests, exe, `version.json`, release) :

```bat
git tag v1.0.2
git push origin v1.0.2
```

Le numéro vient du tag. Pour un exe d'essai sans publication : onglet
**Actions > Release > Run workflow**, puis télécharger l'artefact.

## Licence

PDF Studio est un logiciel libre sous licence
[GNU AGPL-3.0](LICENSE), comme la bibliothèque PyMuPDF qu'il utilise.
Toute copie distribuée, modifiée ou non, doit rester sous cette licence et
donner accès à son code source.
