@echo off
rem Construit dist\PDFStudio.exe : installe les dépendances, récupère les
rem fichiers de langue Tesseract si absents, lance les tests puis PyInstaller.
setlocal
cd /d "%~dp0"

echo [1/4] Installation des dependances...
python -m pip install -r requirements.txt || goto :erreur

echo [2/4] Fichiers de langue Tesseract (tessdata_fast)...
if not exist tessdata mkdir tessdata
set "BASE=https://github.com/tesseract-ocr/tessdata_fast/raw/main"
if not exist "tessdata\fra.traineddata" (
    curl -L -o "tessdata\fra.traineddata" "%BASE%/fra.traineddata" || goto :erreur
)
if not exist "tessdata\eng.traineddata" (
    curl -L -o "tessdata\eng.traineddata" "%BASE%/eng.traineddata" || goto :erreur
)

echo [3/4] Tests automatises...
python -m pytest tests -q || goto :erreur

echo [4/4] Compilation PyInstaller...
python -m PyInstaller --onefile --noconsole --name PDFStudio ^
    --collect-all customtkinter --add-data "tessdata;tessdata" pdf_studio.py || goto :erreur

echo.
echo Termine : dist\PDFStudio.exe
endlocal
exit /b 0

:erreur
echo.
echo ECHEC de la compilation. Voir les messages ci-dessus.
endlocal
exit /b 1
