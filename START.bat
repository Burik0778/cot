@echo off
chcp 866 >nul
cd /d "%~dp0"
title COT - sostoyanie rynka

echo.
echo   Obnovlyayu dannye CFTC i sobirayu sayt...
echo.

python -c "import pandas" 2>nul
if errorlevel 1 (
    echo   Pervyy zapusk: ustanavlivayu biblioteki. Eto zaymet paru minut.
    echo.
    python -m pip install -r requirements.txt
    echo.
)

if not exist "data\cot_research.db" (
    echo   Zagruzhayu istoriyu CFTC. Eto zaymet 1-2 minuty.
    echo.
    python scripts\init_db.py --live --currencies EUR GBP JPY AUD CAD CHF MXN
) else (
    python scripts\refresh_data.py --currencies EUR GBP JPY AUD CAD CHF MXN
)

echo.
python scripts\build_site.py
echo.

start "" "site\index.html"

echo   Sayt otkryt v brauzere.
echo   Fayl: site\index.html - mozhno dobavit v zakladki.
echo.
pause
