# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conversion des documents Word en PDF, pour les modifier dans Pagilis.

Microsoft Word d'abord (mise en page identique), piloté par un script
PowerShell : aucune dépendance Python de plus. Sinon LibreOffice s'il est
installé. Sinon, un message clair. Aucune interface ici.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from pdf_core import PagilisError

EXTENSIONS_WORD = (".docx", ".doc", ".rtf", ".odt")

AUCUN_CONVERTISSEUR = "Pour ouvrir un fichier Word, Microsoft Word ou LibreOffice doit être installé."
WORD_PROTEGE = "Ce fichier Word est protégé : ouvrez-le dans Word pour retirer le mot de passe."
MARQUEUR_MOT_DE_PASSE = "MOT_DE_PASSE"

# Chemins lus dans $args : jamais insérés dans le texte du script (apostrophes,
# accents, espaces). Un mot de passe factice fait ÉCHOUER l'ouverture d'un
# document protégé au lieu d'afficher une boîte de dialogue invisible.
SCRIPT_WORD = r"""
$ErrorActionPreference = 'Stop'
$word = $null; $doc = $null
try {
    # Word lancé par COM n'est pas un enfant de ce script : on note son PID
    # ($args[2]) pour pouvoir l'arrêter si le délai est dépassé.
    $avant = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $word = New-Object -ComObject Word.Application
    $nouveaux = @(Get-Process WINWORD -ErrorAction SilentlyContinue |
                  Where-Object { $avant -notcontains $_.Id } | ForEach-Object { $_.Id })
    Set-Content -LiteralPath $args[2] -Value $nouveaux -Encoding ascii
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {
        $doc = $word.Documents.Open($args[0], $false, $true, $false, 'pagilis-sans-mot-de-passe')
    } catch {
        if ($_.Exception.Message -match 'mot de passe|password') { [Console]::Error.WriteLine('MOT_DE_PASSE'); exit 2 }
        throw
    }
    $doc.ExportAsFixedFormat($args[1], 17)
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message); exit 1
} finally {
    if ($doc) { $doc.Close(0) }
    # Word déjà ouvert par l'utilisateur et réutilisé : on ne ferme pas ses documents.
    if ($word -and $word.Documents.Count -eq 0) { $word.Quit() }
}
"""


def est_word(chemin: str) -> bool:
    return os.path.splitext(chemin)[1].lower() in EXTENSIONS_WORD


def word_installe() -> bool:
    """Vrai si Microsoft Word est installé (objet COM Word.Application enregistré)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CurVer"):
            return True
    except OSError:
        return False


def chemin_libreoffice() -> Optional[str]:
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        racine = os.environ.get(variable)
        if racine:
            chemin = os.path.join(racine, "LibreOffice", "program", "soffice.exe")
            if os.path.exists(chemin):
                return chemin
    return None


def _tuer(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _tuer_word_lance(fichier_pid: Optional[str]) -> None:
    """Arrête le Word lancé par le script (délai dépassé : boîte de dialogue invisible…)."""
    if not fichier_pid or not os.path.exists(fichier_pid):
        return
    with open(fichier_pid, encoding="ascii", errors="ignore") as fh:
        for ligne in fh:
            if ligne.strip().isdigit():
                _tuer(int(ligne))


def _executer(commande: list[str], delai: int) -> subprocess.CompletedProcess:
    return subprocess.run(commande, capture_output=True, text=True, errors="replace", timeout=delai,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def word_vers_pdf(source: str, dossier: str, delai: int = 120) -> str:
    """Convertit `source` en PDF dans `dossier` et retourne le chemin du PDF.

    Lève PagilisError avec un message pour l'utilisateur en cas d'échec.
    """
    os.makedirs(dossier, exist_ok=True)
    source = os.path.abspath(source)
    sortie = os.path.join(dossier, os.path.splitext(os.path.basename(source))[0] + ".pdf")
    fichier_pid = None
    if word_installe():
        script = os.path.join(dossier, "pagilis_word_vers_pdf.ps1")
        fichier_pid = os.path.join(dossier, "pagilis_word.pid")
        if os.path.exists(fichier_pid):
            os.remove(fichier_pid)
        with open(script, "w", encoding="utf-8-sig") as fh:
            fh.write(SCRIPT_WORD)
        commande = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", script, source, sortie, fichier_pid]
        nom = "Microsoft Word"
    else:
        soffice = chemin_libreoffice()
        if not soffice:
            raise PagilisError(AUCUN_CONVERTISSEUR)
        commande = [soffice, "--headless", "--convert-to", "pdf", "--outdir", dossier, source]
        nom = "LibreOffice"
    if os.path.exists(sortie):
        os.remove(sortie)  # un ancien PDF ne doit pas passer pour le résultat
    try:
        resultat = _executer(commande, delai)
    except subprocess.TimeoutExpired:
        _tuer_word_lance(fichier_pid)
        raise PagilisError(f"{nom} n'a pas converti le document en {delai} secondes.") from None
    except OSError as exc:
        raise PagilisError(f"Impossible de lancer {nom} : {exc}") from None
    if MARQUEUR_MOT_DE_PASSE in (resultat.stderr or ""):
        raise PagilisError(WORD_PROTEGE)
    if resultat.returncode != 0 or not os.path.exists(sortie):
        detail = (resultat.stderr or "").strip().splitlines()
        raise PagilisError(f"{nom} n'a pas pu convertir « {os.path.basename(source)} »."
                           + (f"\n{detail[-1]}" if detail else ""))
    return sortie
