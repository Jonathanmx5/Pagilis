# Nouveautés de Pagilis (anciennement PDF Studio)

Chaque version publiée a sa section ci-dessous : la CI refuse de publier une
version qui n'en a pas, et son contenu s'affiche dans la fenêtre de mise à jour.

Numérotation : MAJEUR.MINEUR.CORRECTIF.
- CORRECTIF (1.1.1) : corrections uniquement ;
- MINEUR (1.2.0) : nouveautés compatibles ;
- MAJEUR (2.0.0) : changements qui cassent des habitudes.

Une bêta (tag `v1.2.0-beta.1`) reprend les notes de sa version (`1.2.0`) si
elle n'a pas de section propre.

## [1.3.0]

- Nouvelle fonction « Modifier » : cliquez sur une ligne pour corriger son
  texte sur place, faites glisser un bloc pour le déplacer. Les retouches
  s'annulent (Ctrl+Z) et s'enregistrent en une fois (Ctrl+S).
- Les documents Word (.docx, .doc, .rtf, .odt) s'ouvrent : ils sont convertis
  en PDF avec Microsoft Word, ou LibreOffice s'il n'y a pas Word.
- Pagilis prévient avant de fermer ou d'ouvrir un autre fichier si des
  retouches ne sont pas enregistrées.

## [1.2.0]

- PDF Studio s'appelle désormais Pagilis.
- Si PDF Studio est installé sur votre PC, il devient automatiquement Pagilis :
  nouveaux raccourcis et nouvelle entrée dans « Applications installées »,
  l'ancienne installation est retirée. Vos préférences sont conservées.
- L'option « Versions bêta » est retirée : seules les versions publiées pour
  tous sont proposées.
- Le bouton « Aide et limites » est retiré de la barre latérale.

## [1.1.0]

- Versions bêta : activez « Versions bêta » dans la barre latérale pour recevoir
  les versions de test avant tout le monde.
- La fenêtre de mise à jour affiche les nouveautés de la version proposée.
- Plus sûr : une nouvelle version est d'abord vérifiée sur votre PC ; si elle
  ne fonctionne pas, votre version actuelle est conservée. La version remplacée
  est gardée en sauvegarde.
- Exe plus léger (environ 10 Mo de moins).
- Corrections : l'aperçu ne laisse plus de rendu en attente à la fermeture ;
  la vérification des mises à jour pouvait ignorer la configuration.

## [1.0.2]

- Aperçu de page avec navigation et zoom ; signature posée et déplacée à la
  souris ; blocs de texte sélectionnés et déplacés à la souris ; occurrences
  surlignées ; mots reconnus par l'OCR encadrés.
- Les PDF protégés demandent leur mot de passe.
- Application portable, installable sur le PC sans droits administrateur.
- Fusion : la liste se réordonne fichier par fichier.
- Corrections : gras et police serif conservés au remplacement ; messages
  d'erreur qui faisaient planter l'application ; scripts de mise à jour.

## [1.0.1]

- Fonctions dans une barre latérale à gauche, thème clair ou sombre.
- Mises à jour proposées au démarrage, avec « Ne plus me proposer cette version ».

## [1.0.0]

- Première version : fusion, division, signature/tampon, remplacement et
  déplacement de texte, OCR des PDF scannés.
