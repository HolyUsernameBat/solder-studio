@echo off
cd /d "%~dp0"
where uv >nul 2>&1
if %errorlevel% equ 0 (
  set "UV=uv"
) else if exist "%USERPROFILE%\.local\bin\uv.exe" (
  set "UV=%USERPROFILE%\.local\bin\uv.exe"
) else (
  echo uv was not found on PATH or in %%USERPROFILE%%\.local\bin\uv.exe
  echo Installing uv...
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
echo First run downloads dependencies and may take 2-3 minutes; later launches take about 5 seconds.
set "CODEX=%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe"
if not exist "%CODEX%" set "CODEX=codex"
"%CODEX%" login status | findstr /C:"Logged in using ChatGPT" >nul
if errorlevel 1 (
  echo A browser window will open. Sign in with your ChatGPT subscription.
  "%CODEX%" login
  if errorlevel 1 (
    echo Login did not finish.
    pause
    exit /b 1
  )
)
"%UV%" run streamlit run solder_studio.py
pause