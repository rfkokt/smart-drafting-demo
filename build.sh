#!/bin/bash
# ============================================================
# Build Script - Smart Drafting Engine (macOS)
# Menghasilkan: dist/Smart Drafting Engine-{version}.dmg
#
# Prerequisites:
#   brew install tesseract poppler
#   pip install pyinstaller
#   npm install (di folder frontend/)
#
# Cara pakai:
#   chmod +x build.sh
#   ./build.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

OLLAMA_VERSION="0.3.14"
OLLAMA_MAC_URL="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}/ollama-darwin"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Smart Drafting Engine - Build Script (macOS)           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Cek prerequisites ───────────────────────────────────────
echo "[1/6] Checking prerequisites..."

if ! command -v tesseract &> /dev/null; then
    echo "  ❌ Tesseract not found. Install: brew install tesseract"
    exit 1
fi

if ! command -v pdftoppm &> /dev/null; then
    echo "  ❌ Poppler not found. Install: brew install poppler"
    exit 1
fi

if ! command -v pyinstaller &> /dev/null; then
    echo "  ❌ PyInstaller not found. Install: pip install pyinstaller"
    exit 1
fi

echo "  ✅ Prerequisites OK"

# ── 2. Download Ollama binary ──────────────────────────────────
echo "[2/6] Downloading Ollama binary (macOS)..."

mkdir -p ollama-bin/mac

if [ ! -f "ollama-bin/mac/ollama" ]; then
    echo "  Downloading from GitHub releases..."
    curl -L "$OLLAMA_MAC_URL" -o "ollama-bin/mac/ollama"
    chmod +x "ollama-bin/mac/ollama"
    echo "  ✅ Ollama binary downloaded"
else
    echo "  ✅ Ollama binary already exists (skip download)"
fi

# ── 3. Aktivasi venv & build Python backend ───────────────────
echo "[3/6] Building Python backend with PyInstaller..."

source venv/bin/activate
pyinstaller smart_drafting_backend.spec --noconfirm --clean

if [ ! -f "dist/smart_drafting_backend/smart_drafting_backend" ]; then
    echo "  ❌ PyInstaller build failed"
    exit 1
fi
echo "  ✅ Python backend built"

# ── 4. Bundle Tesseract + Poppler binaries ─────────────────────
echo "[4/6] Bundling Tesseract + Poppler binaries..."

BIN_DIR="dist/smart_drafting_backend/bin"
mkdir -p "$BIN_DIR"

TESS_BIN="$(which tesseract)"
TESS_DATA="/opt/homebrew/share/tessdata"
if [ ! -d "$TESS_DATA" ]; then
    TESS_DATA="/usr/local/share/tessdata"
fi

cp "$TESS_BIN" "$BIN_DIR/tesseract"
cp -r "$TESS_DATA" "$BIN_DIR/tessdata"
echo "  ✅ Tesseract bundled"

POPPLER_BIN_DIR="$(dirname $(which pdftoppm))"
for bin in pdftoppm pdfinfo; do
    if [ -f "$POPPLER_BIN_DIR/$bin" ]; then
        cp "$POPPLER_BIN_DIR/$bin" "$BIN_DIR/$bin"
    fi
done
echo "  ✅ Poppler bundled"

cp -r dist/smart_drafting_backend backend-dist

# ── 5. Install frontend deps & build Electron app ─────────────
echo "[5/6] Building Electron app..."

cd frontend
npm install
npm run build:mac
cd ..

echo "  ✅ Electron app built"

# ── 6. Cleanup ─────────────────────────────────────────────────
echo "[6/6] Cleaning up temp files..."
rm -rf backend-dist

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  ✅ Build complete!"
echo ""
echo "  Output: dist/Smart Drafting Engine-*.dmg"
echo ""
echo "  Distribusikan file .dmg tersebut ke user."
echo "  User cukup drag & drop ke Applications — tidak perlu"
echo "  install Python, Tesseract, Poppler, atau Ollama."
echo "  AI offline: default model ~1.9GB; user bisa pilih model lain."
echo "══════════════════════════════════════════════════════════"
echo ""
