@echo off
REM First run creates a virtual environment and installs dependencies.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
    pip install -q -r requirements.txt
)
REM SEC asks for a contact e-mail in the User-Agent. Replace with your own:
set SEC_USER_AGENT=PersonalStockResearch your-email@example.com
REM Stage 3 (news analysis). You can also paste the keys in the app's sidebar instead.
REM set GEMINI_API_KEY=...
REM set ANTHROPIC_API_KEY=sk-ant-...
REM set FINNHUB_API_KEY=...
streamlit run app.py
