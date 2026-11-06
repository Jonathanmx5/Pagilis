@echo off
rem Construit dist\PDFStudio.exe : installe les dependances (versions figees),
rem recupere les fichiers de langue Tesseract si absents, verifie le code
rem (analyse + tests) puis lance PyInstaller. Utilise tel quel par la CI GitHub.
setlocal
cd /d "%~dp0"

echo [1/4] Installation des dependances...
python -m pip install -r requirements-dev.txt || goto :erreur

echo [2/4] Fichiers de langue Tesseract (tessdata_fast)...
if not exist tessdata mkdir tessdata
set "BASE=https://github.com/tesseract-ocr/tessdata_fast/raw/main"
if not exist "tessdata\fra.traineddata" (
    curl -L -o "tessdata\fra.traineddata" "%BASE%/fra.traineddata" || goto :erreur
)
if not exist "tessdata\eng.traineddata" (
    curl -L -o "tessdata\eng.traineddata" "%BASE%/eng.traineddata" || goto :erreur
)

echo [3/4] Analyse du code et tests automatises...
python -m pyflakes pdf_core.py pdf_studio.py apercu.py updater.py tests || goto :erreur
python -m pytest tests -q || goto :erreur

echo [4/4] Compilation PyInstaller...
rem LICENSE est embarquee dans l'exe : l'AGPL impose de fournir la licence avec chaque copie.
python -m PyInstaller --onefile --noconsole --noconfirm --name PDFStudio ^
    --collect-all customtkinter --add-data "tessdata;tessdata" --add-data "LICENSE;." ^
    pdf_studio.py || goto :erreur

echo.
echo Termine : dist\PDFStudio.exe
endlocal
exit /b 0

:erreur
echo.
echo ECHEC de la compilation. Voir les messages ci-dessus.
endlocal
exit /b 1
