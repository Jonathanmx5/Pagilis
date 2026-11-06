# Nouveautés de Pagilis (anciennement PDF Studio)

Chaque version publiée a sa section ci-dessous : la CI refuse de publier une
version qui n'en a pas, et son contenu s'affiche dans la fenêtre de mise à jour.

Numérotation : MAJEUR.MINEUR.CORRECTIF.
- CORRECTIF (1.1.1) : corrections uniquement ;
- MINEUR (1.2.0) : nouveautés compatibles ;
- MAJEUR (2.0.0) : changements qui cassent des habitudes.

Une bêta (tag `v1.2.0-beta.1`) reprend les notes de sa version (`1.2.0`) si
elle n'a pas de section propre.

## [1.7.0]

- Nouveau logo : une page bleue au coin plié, avec « Pdf ». Il apparaît dans
  la barre des tâches, sur l'exe, les raccourcis, la barre du haut et l'accueil.

## [1.6.0]

- Nouvelle présentation, plus claire et plus professionnelle : police et icônes
  de Windows, une seule couleur pour l'action principale, et le document au
  centre de la fenêtre.
- Barre du haut : le document ouvert, une pastille « Non enregistré » et les
  boutons Ouvrir, Annuler et Enregistrer (Ctrl+O, Ctrl+Z, Ctrl+S).
- Fonctions regroupées : Éditer (Modifier le texte, Pages, Signer), Assembler
  (Fusionner, Découper), Outils (Reconnaître le texte).
- « Remplacer du texte » et « Déplacer du texte » rejoignent « Modifier le
  texte » : rechercher et remplacer dans tout le document, annulable.
- Écran d'accueil avec les fichiers récents ; numéro de page à taper sous
  l'aperçu ; bulles d'aide sur les boutons à icône.
- Réglages en mots simples (langue « Français », précision « Standard »…) ;
  les réglages techniques sont rangés dans « Options avancées ».
- Plus de fenêtre « Ouvrir le résultat ? » après chaque traitement : la barre
  d'état propose « Ouvrir » ou « Continuer dessus ».

## [1.5.0]

- Nouvelle fonction « Pages » : les vignettes de toutes les pages, pour
  pivoter, supprimer, monter ou descendre des pages, insérer un autre PDF et
  extraire une sélection dans un nouveau fichier. Sélection au clic,
  Ctrl+clic et Maj+clic.
- « Modifier » et « Pages » travaillent sur le même document : les retouches
  de texte et de pages s'annulent (Ctrl+Z) et s'enregistrent (Ctrl+S)
  ensemble.

## [1.4.0]

- Une ligne corrigée garde sa police d'origine : celle du PDF quand elle
  contient tous les caractères du nouveau texte, sinon la même police
  installée sur le PC (Aptos, Calibri, Garamond…). Arial, Times ou Courier ne
  servent plus qu'en dernier recours, et la barre d'état indique la police
  utilisée. Vaut aussi pour « Remplacer du texte » et « Déplacer du texte ».
- Un texte plus long que l'original est réduit selon la largeur réelle de sa
  police.

## [1.3.0]

- Nouvelle fonction « Modifier » : cliquez sur une ligne pour corriger son
  texte sur place, faites glisser un bloc pour le déplacer. Les retouches
  s'annulent (Ctrl+Z) et s'enregistrent en une fois (Ctrl+S).
- Les documents Word (.docx, .doc, .rtf, .odt) s'ouvrent : ils sont convertis
  en PDF avec Microsoft Word, ou LibreOffice s'il n'y a pas Word.
- Pagilis prévient avant de fermer ou d'ouvrir un autre fichier si des
  retouches ne sont pas enregistrées.
- Apparence sombre pour tous ; le choix « Apparence » est retiré de la barre
  latérale.

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
