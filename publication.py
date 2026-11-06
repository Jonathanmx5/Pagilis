# SPDX-License-Identifier: AGPL-3.0-or-later
"""Préparation d'une publication, appelée par la CI (.github/workflows/release.yml).

    python publication.py <version> <dépôt> <exe> <dossier de sortie>

Écrit dans le dossier de sortie :
- notes.md : la section de CHANGELOG.md pour cette version (notes de la release) ;
- version.json : le fichier lu par les applications installées.

Échoue (code 1) si CHANGELOG.md n'a pas de section pour cette version : on ne
publie pas une version sans dire ce qu'elle change.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


def notes_de_version(changelog: str, version: str) -> str:
    """Section « ## [version] » du changelog ; une bêta reprend celle de sa version."""
    candidats = [version]
    if "-" in version:
        candidats.append(version.split("-", 1)[0])  # 1.2.0-beta.1 -> 1.2.0
    for candidat in candidats:
        motif = rf"^## \[{re.escape(candidat)}\][^\n]*\n(.*?)(?=^## \[|\Z)"
        trouve = re.search(motif, changelog, re.MULTILINE | re.DOTALL)
        if trouve and trouve.group(1).strip():
            return trouve.group(1).strip()
    raise ValueError(f"CHANGELOG.md n'a pas de section « ## [{version}] »")


def manifeste(version: str, depot: str, exe: Path, notes: str) -> dict:
    return {
        "version": version,
        "url": f"https://github.com/{depot}/releases/download/v{version}/PDFStudio.exe",
        "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "notes": notes,
        "prerelease": "-" in version,
    }


def main(arguments: list[str]) -> int:
    version, depot, exe, sortie = arguments[0], arguments[1], Path(arguments[2]), Path(arguments[3])
    try:
        notes = notes_de_version(Path("CHANGELOG.md").read_text(encoding="utf-8"), version)
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "notes.md").write_text(notes + "\n", encoding="utf-8")
    contenu = manifeste(version, depot, exe, notes)
    (sortie / "version.json").write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**contenu, "notes": f"{len(notes)} caractères"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
