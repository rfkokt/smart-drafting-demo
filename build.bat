@echo off
REM ============================================================
REM Build Script - Smart Drafting Engine (Windows)
REM Menghasilkan: dist\Smart Drafting Engine Setup-{version}.exe
REM
REM Prerequisites:
REM   - Python 3.10+ di PATH
REM   - Tesseract dari UB-Mannheim: https://github.com/UB-Mannheim/tesseract/wiki
REM   - Poppler: https://github.com/osber/poppler-windows/releases
REM   - pip install pyinstaller
REM   - npm install (di folder frontend\)
REM   - curl (built-in di Windows 10+)
REM
REM Cara pakai:
REM   build.bat
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set OLLAMA_VERSION=0.3.14
set OLLAMA_WIN_URL=https://github.com/ollama/ollama/releases/download/v%OLLAMA_VERSION%/ollama-windows-amd64.exe

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║  Smart Drafting Engine - Build Script (Windows)         ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM ── 1. Cek prerequisites ──────────────────────────────────────
echo [1/6] Checking prerequisites...

where tesseract >nul 2>&1
if errorlevel 1 (
    echo   ❌ Tesseract not found.
    echo      Install dari: https://github.com/UB-Mannheim/tesseract/wiki
    echo      Lalu tambahkan ke PATH: C:\Program Files\Tesseract-OCR
    exit /b 1
)

where pdftoppm >nul 2>&1
if errorlevel 1 (
    echo   ❌ Poppler not found.
    echo      Download dari: https://github.com/osber/poppler-windows/releases
    echo      Extract dan tambahkan folder bin\ ke PATH
    exit /b 1
)

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo   ❌ PyInstaller not found. Install: pip install pyinstaller
    exit /b 1
)

echo   ✅ Prerequisites OK

REM ── 2. Download Ollama binary (Windows) ───────────────────────
echo [2/6] Downloading Ollama binary (Windows)...

mkdir "ollama-bin\win" 2>nul

if not exist "ollama-bin\win\ollama.exe" (
    echo   Downloading from GitHub releases...
    curl -L "%OLLAMA_WIN_URL%" -o "ollama-bin\win\ollama.exe"
    echo   ✅ Ollama binary downloaded
) else (
    echo   ✅ Ollama binary already exists (skip download)
)

REM ── 3. Aktivasi venv & build Python backend ──────────────────
echo [3/6] Building Python backend with PyInstaller...

call venv\Scripts\activate.bat
pyinstaller smart_drafting_backend.spec --noconfirm --clean

if not exist "dist\smart_drafting_backend\smart_drafting_backend.exe" (
    echo   ❌ PyInstaller build failed
    exit /b 1
)
echo   ✅ Python backend built

REM ── 4. Bundle Tesseract + Poppler binaries ───────────────────
echo [4/6] Bundling Tesseract + Poppler binaries...

set BIN_DIR=dist\smart_drafting_backend\bin
mkdir "%BIN_DIR%" 2>nul

REM Tesseract
set TESS_DIR=C:\Program Files\Tesseract-OCR
if exist "%TESS_DIR%\tesseract.exe" (
    copy "%TESS_DIR%\tesseract.exe" "%BIN_DIR%\" >nul
    xcopy "%TESS_DIR%\tessdata" "%BIN_DIR%\tessdata\" /E /I /Q >nul
    echo   ✅ Tesseract bundled
) else (
    echo   ⚠️  Tesseract not found at %TESS_DIR% — skip bundling
)

REM Poppler
for /f "tokens=*" %%i in ('where pdftoppm') do set POPPLER_BIN=%%i
for %%i in ("%POPPLER_BIN%") do set POPPLER_DIR=%%~dpi
copy "%POPPLER_DIR%pdftoppm.exe" "%BIN_DIR%\" >nul 2>&1
copy "%POPPLER_DIR%pdfinfo.exe" "%BIN_DIR%\" >nul 2>&1
copy "%POPPLER_DIR%*.dll" "%BIN_DIR%\" >nul 2>&1
echo   ✅ Poppler bundled

xcopy "dist\smart_drafting_backend" "backend-dist\" /E /I /Q >nul

REM ── 5. Install frontend deps & build Electron app ────────────
echo [5/6] Building Electron app...

cd frontend
call npm install
call npm run build:win
cd ..

echo   ✅ Electron app built

REM ── 6. Cleanup ───────────────────────────────────────────────
echo [6/6] Cleaning up temp files...
rmdir /s /q backend-dist 2>nul

echo.
echo ══════════════════════════════════════════════════════════
echo   ✅ Build complete!
echo.
echo   Output: dist\Smart Drafting Engine Setup-*.exe
echo.
echo   Distribusikan file Setup .exe tersebut ke user.
echo   User cukup jalankan installer — tidak perlu
echo   install Python, Tesseract, Poppler, atau Ollama.
echo   AI offline: default model ~1.9GB; user bisa pilih model lain.
echo ══════════════════════════════════════════════════════════
echo.
