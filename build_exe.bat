@echo off
rem Construit dist\Pagilis.exe : installe les dependances (versions figees),
rem recupere les fichiers de langue Tesseract si absents, verifie le code
rem (analyse + tests) puis lance PyInstaller. Utilise tel quel par la CI GitHub.
setlocal
cd /d "%~dp0"

echo [1/5] Installation des dependances...
python -m pip install -r requirements-dev.txt || goto :erreur

echo [2/5] Fichiers de langue Tesseract (tessdata_fast)...
if not exist tessdata mkdir tessdata
set "BASE=https://github.com/tesseract-ocr/tessdata_fast/raw/main"
if not exist "tessdata\fra.traineddata" (
    curl -L -o "tessdata\fra.traineddata" "%BASE%/fra.traineddata" || goto :erreur
)
if not exist "tessdata\eng.traineddata" (
    curl -L -o "tessdata\eng.traineddata" "%BASE%/eng.traineddata" || goto :erreur
)

echo [3/5] Analyse du code et tests automatises...
python -m pyflakes pdf_core.py pagilis.py apercu.py updater.py installation.py verification.py publication.py identite.py edition.py conversion.py fenetres.py theme.py outils pages tests || goto :erreur
python -m pytest tests -q || goto :erreur

echo [4/5] Compilation PyInstaller...
rem LICENSE est embarquee dans l'exe : l'AGPL impose de fournir la licence avec chaque copie.
rem Les --exclude-module retirent des dependances de PyMuPDF 2.x jamais chargees par
rem l'application (numpy, onnxruntime...) : l'exe s'allege, et --verifier le controle.
python -m PyInstaller --onefile --noconsole --noconfirm --name Pagilis ^
    --collect-all customtkinter --add-data "tessdata;tessdata" --add-data "LICENSE;." ^
    --icon "ressources\pagilis.ico" --add-data "ressources;ressources" ^
    --exclude-module numpy --exclude-module onnxruntime --exclude-module networkx ^
    --exclude-module pymupdf4llm --exclude-module pymupdf_layout --exclude-module yaml ^
    --exclude-module tabulate --exclude-module psutil ^
    pagilis.py || goto :erreur

echo.
echo [5/5] Auto-verification de l'exe compile...
rem "start /wait" rend le code de sortie de l'exe, mais seul "if errorlevel" le voit
rem (un "|| goto" ne se declencherait jamais : verifie).
start "" /wait dist\Pagilis.exe --verifier
if errorlevel 1 goto :erreur
echo Termine : dist\Pagilis.exe
endlocal
exit /b 0

:erreur
echo.
echo ECHEC de la compilation. Voir les messages ci-dessus.
endlocal
exit /b 1
