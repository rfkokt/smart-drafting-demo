"""
Smart Drafting Engine - Web Demo (All-in-One)
Beauty Contest — 26 Mei 2026

Jalankan: python3 run_web.py
Buka: http://localhost:8500
"""

import os
import sys
import json
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
from app import SmartDraftingEngine

# Try AI engine
try:
    os.chdir(os.path.join(os.path.dirname(__file__), 'backend'))
    from ai_engine import process_with_ai, check_ollama_available, check_model_exists, OLLAMA_DEFAULT_PORT
    AI_AVAILABLE = True
    os.chdir(os.path.dirname(__file__))
except Exception:
    AI_AVAILABLE = False
    os.chdir(os.path.dirname(__file__))

# Flask app
app = Flask(__name__, static_folder='web')
CORS(app)

engine = SmartDraftingEngine()

# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    return send_from_directory('web', 'index.html')

@app.route('/health')
def health():
    ollama_ready = False
    model_ready = False
    if AI_AVAILABLE:
        ollama_port = int(os.environ.get("OLLAMA_PORT", OLLAMA_DEFAULT_PORT))
        ollama_ready = check_ollama_available(ollama_port)
        if ollama_ready:
            model_ready = check_model_exists(ollama_port)
    return jsonify({
        "status": "ok",
        "service": "Smart Drafting Engine",
        "version": "1.0.0-poc",
        "ai": AI_AVAILABLE,
        "ollama": ollama_ready,
        "model_ready": model_ready
    })

@app.route('/extract', methods=['POST'])
def extract():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    ai_mode = request.headers.get('X-AI-Mode', 'auto').strip()
    api_key = request.headers.get('X-Groq-API-Key', '').strip()
    ollama_port = int(request.headers.get('X-Ollama-Port', str(OLLAMA_DEFAULT_PORT)))
    ollama_model = request.headers.get('X-Ollama-Model', 'qwen2.5:3b').strip()

    suffix = Path(file.filename).suffix or '.pdf'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = engine.process_document(tmp_path)

        if AI_AVAILABLE and result.get("raw_text_preview"):
            try:
                from pdf2image import convert_from_path
                from PIL import Image
                import app as _app_module
                file_path = Path(tmp_path)
                if file_path.suffix.lower() == '.pdf':
                    pdf_kwargs = {'dpi': 300}
                    _poppler = getattr(_app_module, 'BUNDLED_POPPLER_PATH', None)
                    if _poppler:
                        pdf_kwargs['poppler_path'] = _poppler
                    images = convert_from_path(str(file_path), **pdf_kwargs)
                    if len(images) > 3:
                        images = images[:3]
                else:
                    images = [Image.open(str(file_path))]
                full_text = ""
                for img in images:
                    full_text += engine.extract_text(img) + "\n"
                ai_result = process_with_ai(
                    full_text,
                    mode=ai_mode,
                    api_key=api_key,
                    ollama_port=ollama_port,
                    ollama_model=ollama_model
                )
            except Exception as e:
                ai_result = {"ai_enabled": False, "error": str(e)}
            result["ai"] = ai_result
        else:
            result["ai"] = {"ai_enabled": False, "message": "AI engine tidak tersedia."}

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp_path)

    return jsonify(result)


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    port = 8500
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  Smart Drafting Engine - Web Demo                      ║
║  Beauty Contest — 26 Mei 2026                           ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  🌐 Open in browser: http://localhost:{port}             ║
║                                                          ║
║  AI Engine: {'✅ Ready (Hybrid: Cloud + Lokal)' if AI_AVAILABLE else '❌ Tidak tersedia'}
║  OCR: Tesseract 5 + OpenCV                              ║
║                                                          ║
║  Press Ctrl+C to stop                                    ║
╚══════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=port, debug=False)
