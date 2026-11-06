"""Publie dist\\PDFStudio.exe comme nouvelle release GitHub.

Étapes :
1. augmenter APP_VERSION dans updater.py ;
2. lancer build_exe.bat ;
3. commiter et pousser (git push) ;
4. lancer : python release.py

Le script calcule l'empreinte SHA-256, écrit dist\\version.json puis crée la
release v<version> avec l'exe et version.json (outil `gh` requis, connecté).
Les applications installées verront la mise à jour à leur prochain démarrage.
"""

import hashlib
import json
import os
import subprocess
import sys

import updater

DOSSIER = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(DOSSIER, "dist", "PDFStudio.exe")
MANIFESTE = os.path.join(DOSSIER, "dist", "version.json")


def main() -> int:
    version = updater.APP_VERSION
    if not os.path.exists(EXE):
        print("dist\\PDFStudio.exe introuvable : lancez d'abord build_exe.bat.")
        return 1
    with open(EXE, "rb") as fh:
        empreinte = hashlib.sha256(fh.read()).hexdigest()
    tag = f"v{version}"
    manifeste = {
        "version": version,
        "url": f"https://github.com/{updater.GITHUB_REPO}/releases/download/{tag}/PDFStudio.exe",
        "sha256": empreinte,
    }
    with open(MANIFESTE, "w", encoding="utf-8") as fh:
        json.dump(manifeste, fh, indent=2)
    # La release doit pointer sur le commit compilé : il doit être poussé sur GitHub.
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=DOSSIER).stdout.strip()
    non_pousse = subprocess.run(["git", "log", "--oneline", "@{u}..HEAD"], capture_output=True,
                                text=True, cwd=DOSSIER).stdout.strip()
    if not commit or non_pousse:
        print("Commitez et poussez (git push) le code compilé avant de publier.")
        return 1
    print(f"Publication de {tag} ({commit[:7]}) sur {updater.GITHUB_REPO}…")
    resultat = subprocess.run(
        ["gh", "release", "create", tag, EXE, MANIFESTE,
         "--repo", updater.GITHUB_REPO, "--target", commit,
         "--title", f"PDF Studio {version}",
         "--notes", f"PDF Studio version {version}."],
    )
    return resultat.returncode


if __name__ == "__main__":
    sys.exit(main())
