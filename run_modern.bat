@echo off
cd /d "%~dp0"
echo ==========================================
echo   CloudExam - Modern Online Examination
echo ==========================================
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
echo Installing/checking required packages...
python -m pip install -r requirements.txt
echo.
echo Starting CloudExam...
echo Open http://127.0.0.1:5000 in your browser.
echo Keep this window open while using the website.
echo.
python app.py
pause
