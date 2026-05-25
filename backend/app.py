"""
Smart Drafting Engine - Backend OCR Service
POC Demo untuk Beauty Contest

Pipeline:
1. Terima file (PDF/Image) via REST API
2. Pre-processing (enhance image quality)
3. OCR extraction (Tesseract)
4. Post-processing (regex + field mapping)
5. Return structured JSON dengan confidence score
"""

import os
import re
import json
import tempfile
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import sys
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from pdf2image import convert_from_path
import numpy as np
import cv2


def _get_bundled_bin_dir() -> Path:
    """Return path to bundled binaries dir when running as PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'bin'
    return None


def _setup_bundled_paths():
    """Configure Tesseract and Poppler paths when running as bundled app."""
    bin_dir = _get_bundled_bin_dir()
    if bin_dir is None:
        return None

    if sys.platform == 'win32':
        tesseract_bin = bin_dir / 'tesseract.exe'
        tessdata_dir = bin_dir / 'tessdata'
    else:
        tesseract_bin = bin_dir / 'tesseract'
        tessdata_dir = bin_dir / 'tessdata'

    if tesseract_bin.exists():
        pytesseract.pytesseract.tesseract_cmd = str(tesseract_bin)
        os.environ['TESSDATA_PREFIX'] = str(tessdata_dir)

    return str(bin_dir) if bin_dir.exists() else None


BUNDLED_POPPLER_PATH = _setup_bundled_paths()

# AI Engine
try:
    from ai_engine import process_with_ai, check_ollama_available, check_model_exists, OLLAMA_DEFAULT_PORT
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


# ============================================================
# OCR ENGINE
# ============================================================

class SmartDraftingEngine:
    """
    Smart Drafting Engine - OCR + AI Field Extraction
    
    Pipeline:
    Upload → Pre-process → OCR → Post-process (NER/Regex) → Structured Output
    """

    # Template field patterns untuk dokumen kepabeanan
    FIELD_PATTERNS = {
        "invoice_number": {
            "patterns": [
                r"(?:invoice\s*(?:no|number|#|num)[\s.:]*)\s*([A-Z0-9\-/]+)",
                r"(?:inv[\s.\-:]*(?:no|#)?[\s.:]*)\s*([A-Z0-9\-/]+)",
                r"(?:no\.?\s*invoice[\s.:]*)\s*([A-Z0-9\-/]+)",
                r"(?:faktur[\s.:]*(?:no)?[\s.:]*)\s*([A-Z0-9\-/]+)",
            ],
            "label": "Invoice Number",
            "type": "string"
        },
        "invoice_date": {
            "patterns": [
                r"(?:invoice\s*date|date\s*of\s*invoice|tanggal\s*faktur)[\s.:]*\s*(\d{1,2}[\s/\-\.]\w{3,9}[\s/\-\.]\d{2,4})",
                r"(?:invoice\s*date|date\s*of\s*invoice|tanggal\s*faktur)[\s.:]*\s*(\d{1,2}[\s/\-\.]\d{1,2}[\s/\-\.]\d{2,4})",
                r"(?:date)[\s.:]*\s*(\d{1,2}[\s/\-\.]\w{3,9}[\s/\-\.]\d{2,4})",
            ],
            "label": "Invoice Date",
            "type": "date"
        },
        "supplier_name": {
            "patterns": [
                r"(?:shipper|exporter|seller|supplier|pengirim)[\s/:]*\s*\n?\s*([A-Z][A-Za-z\s&.,]+(?:Ltd|Inc|Corp|Co|PT|CV|LLC|GmbH|Pte|LTD|CO\.?)?[.,]?)",
                r"(?:company|perusahaan)[\s.:]*\s*([A-Z][A-Za-z\s&.,]+(?:Ltd|Inc|Corp|Co|PT|CV|LLC|GmbH|Pte)?[.,]?)",
            ],
            "label": "Supplier / Shipper",
            "type": "string"
        },
        "consignee": {
            "patterns": [
                r"(?:consignee|buyer|pembeli|importer|to)[\s.:]*\s*([A-Za-z\s&.,]+(?:Ltd|Inc|Corp|Co|PT|CV|LLC|GmbH|Pte)?\.?)",
            ],
            "label": "Consignee / Buyer",
            "type": "string"
        },
        "total_amount": {
            "patterns": [
                r"(?:total\s*amount|grand\s*total|total\s*value|total\s*invoice|amount\s*due)[\s.:]*\s*(?:USD|US\$|\$|EUR|€)?\s*([\d,]+\.?\d*)",
                r"(?:total)[\s.:]*\s*(?:USD|US\$|\$|EUR|€)\s*([\d,]+\.?\d*)",
                r"(?:USD|US\$|\$)\s*([\d,]+\.?\d*)\s*(?:total|amount)",
            ],
            "label": "Total Amount",
            "type": "currency"
        },
        "currency": {
            "patterns": [
                r"(?:currency|mata\s*uang)[\s.:]*\s*(USD|EUR|GBP|JPY|CNY|SGD|IDR)",
                r"(USD|EUR|GBP|JPY|CNY|SGD)\s*[\d,]+\.?\d*",
            ],
            "label": "Currency",
            "type": "string"
        },
        "hs_code": {
            "patterns": [
                r"(?:hs\s*code|tariff\s*(?:code|no)|kode\s*hs|pos\s*tarif)[\s.:]*\s*(\d{4}[\s.]?\d{2}[\s.]?\d{2,4})",
                r"(\d{4}\.\d{2}\.\d{2,4})",
                r"(\d{8,10})(?=\s)",
            ],
            "label": "HS Code",
            "type": "hs_code"
        },
        "weight": {
            "patterns": [
                r"(?:gross\s*weight|berat\s*kotor|total\s*weight|g\.?w\.?)[\s.:]*\s*([\d,]+\.?\d*)\s*(?:kg|kgs|KG|KGS)?",
                r"(?:net\s*weight|berat\s*bersih|n\.?w\.?)[\s.:]*\s*([\d,]+\.?\d*)\s*(?:kg|kgs|KG|KGS)?",
                r"([\d,]+\.?\d*)\s*(?:KGS|KG|kgs|kg)",
            ],
            "label": "Weight (KG)",
            "type": "number"
        },
        "quantity": {
            "patterns": [
                r"(?:quantity|qty|jumlah\s*barang|total\s*qty)[\s.:]*\s*([\d,]+)\s*(?:pcs|units|ctns|cartons|boxes|sets)?",
                r"([\d,]+)\s*(?:PCS|UNITS|CTNS|CARTONS|BOXES|SETS|pcs|units)",
            ],
            "label": "Quantity",
            "type": "number"
        },
        "country_origin": {
            "patterns": [
                r"(?:country\s*of\s*origin|negara\s*asal|origin|made\s*in)[\s.:]*\s*([A-Za-z\s]+)",
                r"(?:port\s*of\s*loading|pol|pelabuhan\s*muat)[\s.:]*\s*([A-Za-z\s,]+)",
            ],
            "label": "Country of Origin",
            "type": "string"
        },
        "bl_number": {
            "patterns": [
                r"(?:b/?l\s*(?:no|number|#)|bill\s*of\s*lading\s*(?:no|number))[\s.:]*\s*([A-Z0-9\-/]+)",
                r"(?:no\.?\s*b/?l)[\s.:]*\s*([A-Z0-9\-/]+)",
            ],
            "label": "B/L Number",
            "type": "string"
        },
        "vessel_name": {
            "patterns": [
                r"(?:vessel|ship|kapal|nama\s*kapal|ocean\s*vessel)[\s.:]*\s*([A-Za-z\s\d]+)",
                r"(?:m/?v|mv\.)[\s.:]*\s*([A-Za-z\s\d]+)",
            ],
            "label": "Vessel Name",
            "type": "string"
        },
        "port_of_loading": {
            "patterns": [
                r"(?:port\s*of\s*loading|pol|pelabuhan\s*muat)[\s.:]*\s*([A-Za-z\s,]+)",
            ],
            "label": "Port of Loading",
            "type": "string"
        },
        "port_of_discharge": {
            "patterns": [
                r"(?:port\s*of\s*discharge|pod|pelabuhan\s*bongkar|port\s*of\s*destination)[\s.:]*\s*([A-Za-z\s,]+)",
            ],
            "label": "Port of Discharge",
            "type": "string"
        },
    }

    def __init__(self):
        self.tesseract_config = '--oem 3 --psm 6'

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Pre-processing untuk meningkatkan kualitas OCR:
        1. Convert to grayscale
        2. Enhance contrast
        3. Denoise
        4. Adaptive threshold
        """
        # Convert PIL to OpenCV
        img_array = np.array(image)

        # Convert to grayscale if needed
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

        # Enhance contrast (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # Adaptive threshold for better text detection
        # Use binary for cleaner OCR
        thresh = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # Convert back to PIL
        return Image.fromarray(thresh)

    def extract_text(self, image: Image.Image) -> str:
        """Extract raw text from image using Tesseract OCR"""
        processed = self.preprocess_image(image)
        text = pytesseract.image_to_string(processed, config=self.tesseract_config)
        return text

    def extract_text_with_confidence(self, image: Image.Image) -> dict:
        """Extract text with per-word confidence scores"""
        processed = self.preprocess_image(image)
        data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT)
        
        words_with_conf = []
        for i, word in enumerate(data['text']):
            if word.strip():
                words_with_conf.append({
                    'text': word,
                    'confidence': int(data['conf'][i]),
                    'x': data['left'][i],
                    'y': data['top'][i],
                    'width': data['width'][i],
                    'height': data['height'][i]
                })
        
        # Calculate overall confidence
        confidences = [w['confidence'] for w in words_with_conf if w['confidence'] > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        return {
            'words': words_with_conf,
            'avg_confidence': round(avg_confidence, 1),
            'total_words': len(words_with_conf)
        }

    def extract_fields(self, raw_text: str) -> list:
        """
        Post-processing: Extract structured fields from raw OCR text
        using regex patterns + confidence scoring
        """
        results = []
        text_upper = raw_text.upper()
        text_original = raw_text

        for field_key, field_config in self.FIELD_PATTERNS.items():
            best_match = None
            best_confidence = 0

            for pattern in field_config["patterns"]:
                matches = re.finditer(pattern, text_original, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    value = match.group(1).strip()
                    if value:
                        # Calculate confidence based on pattern specificity & value quality
                        confidence = self._calculate_field_confidence(
                            field_key, field_config, value, pattern
                        )
                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_match = value

            if best_match:
                # Clean up extracted value
                cleaned_value = self._clean_value(field_key, field_config, best_match)
                results.append({
                    "field": field_key,
                    "label": field_config["label"],
                    "value": cleaned_value,
                    "raw_value": best_match,
                    "confidence": round(best_confidence, 1),
                    "status": self._get_status(best_confidence),
                    "type": field_config["type"]
                })

        return results

    def _calculate_field_confidence(self, field_key: str, config: dict, value: str, pattern: str) -> float:
        """Calculate confidence score for extracted field (0-100)"""
        base_confidence = 75.0  # Base confidence if pattern matches

        # Bonus for longer, more specific patterns
        if len(pattern) > 50:
            base_confidence += 5

        # Validate by type
        field_type = config["type"]

        if field_type == "hs_code":
            # HS code should be 8-10 digits
            digits = re.sub(r'[^\d]', '', value)
            if len(digits) == 10:
                base_confidence += 20
            elif len(digits) == 8:
                base_confidence += 15
            elif len(digits) >= 6:
                base_confidence += 5
            else:
                base_confidence -= 20

        elif field_type == "currency":
            if value.upper() in ['USD', 'EUR', 'GBP', 'JPY', 'CNY', 'SGD', 'IDR']:
                base_confidence += 20

        elif field_type == "number":
            try:
                float(value.replace(',', ''))
                base_confidence += 15
            except ValueError:
                base_confidence -= 20

        elif field_type == "date":
            if re.match(r'\d{1,2}[\s/\-\.]\w+[\s/\-\.]\d{2,4}', value):
                base_confidence += 15

        elif field_type == "string":
            if len(value) > 3 and not value.isdigit():
                base_confidence += 10

        # Cap at 99
        return min(99.0, max(10.0, base_confidence))

    def _get_status(self, confidence: float) -> str:
        """Determine status based on confidence"""
        if confidence >= 90:
            return "auto_filled"
        elif confidence >= 70:
            return "review"
        else:
            return "manual"

    def _clean_value(self, field_key: str, config: dict, value: str) -> str:
        """Clean extracted value based on field type"""
        value = value.strip().rstrip('.,;:')

        if config["type"] == "hs_code":
            digits = re.sub(r'[^\d]', '', value)
            if len(digits) >= 8:
                return digits[:10]  # Max 10 digits
            return digits

        elif config["type"] == "number":
            # Remove non-numeric except comma and dot
            cleaned = re.sub(r'[^\d.,]', '', value)
            return cleaned

        elif config["type"] == "currency":
            # Remove currency symbols, keep number
            cleaned = re.sub(r'[^\d.,]', '', value)
            return cleaned

        elif config["type"] == "string":
            # Remove trailing garbage and known field labels that got captured
            cleaned = re.sub(r'\s+', ' ', value)
            # Cut at known boundary words that indicate next field
            boundary_words = [
                r'Port of', r'Country of', r'Invoice', r'Date', r'Currency',
                r'Consignee', r'Shipper', r'Vessel', r'B/L', r'Voyage',
                r'Place of', r'Notify', r'No\.?\s', r'Jl\.', r'JI\.',
                r'Tel:', r'Fax:', r'NPWP'
            ]
            for bw in boundary_words:
                match = re.search(bw, cleaned)
                if match and match.start() > 5:
                    cleaned = cleaned[:match.start()].strip().rstrip('.,;:')
                    break
            return cleaned[:100]  # Max 100 chars

        elif config["type"] == "date":
            # Clean date - remove trailing text
            cleaned = re.sub(r'\s+', ' ', value)
            return cleaned.strip()

        return value

    def process_document(self, file_path: str) -> dict:
        """
        Main entry point: Process a document (PDF or Image)
        Returns structured extraction result
        """
        file_path = Path(file_path)
        images = []

        # Convert PDF to images, or load image directly
        if file_path.suffix.lower() == '.pdf':
            pdf_kwargs = {'dpi': 300}
            if BUNDLED_POPPLER_PATH:
                pdf_kwargs['poppler_path'] = BUNDLED_POPPLER_PATH
            images = convert_from_path(str(file_path), **pdf_kwargs)
            # Limit to first 3 pages for performance
            if len(images) > 3:
                images = images[:3]
        elif file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            images = [Image.open(str(file_path))]
        else:
            return {"error": f"Unsupported file format: {file_path.suffix}"}

        # Process each page
        all_text = ""
        page_results = []
        total_confidence = 0

        for i, image in enumerate(images):
            # Extract text with confidence
            ocr_result = self.extract_text_with_confidence(image)
            raw_text = self.extract_text(image)
            all_text += raw_text + "\n"

            page_results.append({
                "page": i + 1,
                "avg_confidence": ocr_result["avg_confidence"],
                "total_words": ocr_result["total_words"]
            })
            total_confidence += ocr_result["avg_confidence"]

        # Extract structured fields from combined text
        fields = self.extract_fields(all_text)

        # AI-powered extraction (if available)
        ai_result = None
        if AI_AVAILABLE:
            try:
                ai_result = process_with_ai(all_text)
            except Exception as e:
                ai_result = {"ai_enabled": False, "error": str(e)}

        # Calculate overall document confidence
        ocr_confidence = total_confidence / len(images) if images else 0
        field_confidences = [f["confidence"] for f in fields]
        avg_field_confidence = sum(field_confidences) / len(field_confidences) if field_confidences else 0

        # Summary stats
        auto_filled = len([f for f in fields if f["status"] == "auto_filled"])
        review_needed = len([f for f in fields if f["status"] == "review"])
        manual_needed = len([f for f in fields if f["status"] == "manual"])

        return {
            "success": True,
            "file_name": file_path.name,
            "pages_processed": len(images),
            "ocr_confidence": round(ocr_confidence, 1),
            "extraction_confidence": round(avg_field_confidence, 1),
            "fields_extracted": len(fields),
            "summary": {
                "auto_filled": auto_filled,
                "review_needed": review_needed,
                "manual_needed": manual_needed,
                "total_fields": len(fields)
            },
            "fields": fields,
            "ai": ai_result,
            "raw_text_preview": all_text[:500] + "..." if len(all_text) > 500 else all_text,
            "page_details": page_results
        }


# ============================================================
# REST API SERVER
# ============================================================

class SmartDraftingAPI(BaseHTTPRequestHandler):
    """Simple REST API for Smart Drafting Engine"""

    engine = SmartDraftingEngine()

    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Health check endpoint"""
        if self.path == '/health':
            self.send_json({"status": "ok", "service": "Smart Drafting Engine", "version": "1.0.0-poc"})
        elif self.path == '/':
            self.send_json({
                "service": "Smart Drafting Engine",
                "version": "1.0.0-poc",
                "description": "OCR-based document extraction for customs documents",
                "endpoints": {
                    "POST /extract": "Upload document for OCR extraction",
                    "GET /health": "Health check"
                },
                "supported_formats": ["PDF", "PNG", "JPG", "JPEG", "TIFF"],
                "supported_documents": ["Invoice", "Bill of Lading", "Packing List"]
            })
        else:
            self.send_error(404)

    def do_POST(self):
        """Handle document upload and extraction"""
        if self.path == '/extract':
            self.handle_extract()
        else:
            self.send_error(404)

    def handle_extract(self):
        """Process uploaded document"""
        try:
            content_type = self.headers.get('Content-Type', '')

            if 'multipart/form-data' in content_type:
                # Parse boundary from content-type
                boundary = None
                for part in content_type.split(';'):
                    part = part.strip()
                    if part.startswith('boundary='):
                        boundary = part.split('=', 1)[1].strip('"')
                        break

                if not boundary:
                    self.send_json({"error": "No boundary in Content-Type"}, status=400)
                    return

                # Read body
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)

                # Parse multipart manually
                boundary_bytes = boundary.encode()
                parts = body.split(b'--' + boundary_bytes)

                file_data = None
                file_name = 'upload.pdf'

                for part in parts:
                    if b'Content-Disposition' in part:
                        # Extract filename
                        header_end = part.find(b'\r\n\r\n')
                        if header_end == -1:
                            continue
                        header_section = part[:header_end].decode('utf-8', errors='ignore')
                        file_content = part[header_end + 4:]
                        # Remove trailing \r\n
                        if file_content.endswith(b'\r\n'):
                            file_content = file_content[:-2]

                        # Get filename from header
                        if 'filename="' in header_section:
                            fn_start = header_section.index('filename="') + 10
                            fn_end = header_section.index('"', fn_start)
                            file_name = header_section[fn_start:fn_end]

                        if file_content:
                            file_data = file_content

                if file_data:
                    # Save to temp file
                    suffix = Path(file_name).suffix or '.pdf'
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(file_data)
                        tmp_path = tmp.name

                    # Process document
                    result = self.engine.process_document(tmp_path)

                    # Cleanup
                    os.unlink(tmp_path)

                    self.send_json(result)
                else:
                    self.send_json({"error": "No file uploaded"}, status=400)
            else:
                self.send_json({"error": "Content-Type must be multipart/form-data"}, status=400)

        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        """Custom log format"""
        print(f"[Smart Drafting API] {args[0]}")


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    PORT = 8500

    # Use ThreadingHTTPServer so OCR processing doesn't block health checks
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('0.0.0.0', PORT), SmartDraftingAPI)
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  Smart Drafting Engine - POC Demo                      ║
║  Backend OCR Service                                    ║
╠══════════════════════════════════════════════════════════╣
║  Server running on http://localhost:{PORT}               ║
║                                                          ║
║  Endpoints:                                              ║
║    GET  /         → Service info                         ║
║    GET  /health   → Health check                         ║
║    POST /extract  → Upload & extract document            ║
║                                                          ║
║  Supported: PDF, PNG, JPG, TIFF                          ║
║  OCR Engine: Tesseract 5 + OpenCV pre-processing         ║
║  Mode: Multi-threaded (non-blocking)                     ║
╚══════════════════════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()
