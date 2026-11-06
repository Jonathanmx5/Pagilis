# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identité de l'application : le nom, à un seul endroit.

L'application s'appelait « PDF Studio » jusqu'à la version 1.1.0. Les anciens
noms restent ici pour reconnaître et migrer ce que ces versions ont laissé sur
le PC (installation, préférences).
"""

NOM = "Pagilis"
NOM_EXE = "Pagilis.exe"
DEPOT_GITHUB = "Jonathanmx5/Pagilis"
EDITEUR = "Jonathanmx5"
PROGID_PDF = "Pagilis.pdf"            # « Ouvrir avec » pour les PDF
CLE_REGISTRE = "Pagilis"              # entrée dans « Applications installées »
DOSSIER_DONNEES = "Pagilis"           # sous %LOCALAPPDATA% : préférences, journal

# Avant le renommage (jusqu'à la 1.1.0).
ANCIEN_NOM = "PDF Studio"
ANCIEN_NOM_EXE = "PDFStudio.exe"
ANCIEN_PROGID_PDF = "PDFStudio.pdf"
ANCIENNE_CLE_REGISTRE = "PDFStudio"
ANCIEN_DOSSIER_DONNEES = "PDFStudio"
