"""
AI Layer untuk Smart Drafting Engine
Hybrid: Groq (Cloud) + Ollama (Lokal)

Mode:
  cloud → Groq API (LLaMA 3.1 8B) — butuh internet + API key
  local → Ollama lokal (model selectable) — fully offline
  auto  → coba Groq, fallback Ollama kalau offline/no key
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path

DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
SUPPORTED_OLLAMA_MODELS = {
    "qwen2.5:1.5b": {"label": "Fast", "size": "~986MB"},
    "gemma2:2b": {"label": "Light", "size": "~1.6GB"},
    "qwen2.5:3b": {"label": "Recommended", "size": "~1.9GB"},
    "phi3.5:3.8b": {"label": "Reasoning", "size": "~2.2GB"},
    "qwen2.5:7b": {"label": "High Accuracy", "size": "~4.7GB"},
}
OLLAMA_DEFAULT_PORT = 11435


def check_ollama_available(port: int = OLLAMA_DEFAULT_PORT) -> bool:
    try:
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/tags", timeout=2
        )
        return req.status == 200
    except Exception:
        return False


def check_model_exists(port: int = OLLAMA_DEFAULT_PORT, model: str = DEFAULT_OLLAMA_MODEL) -> bool:
    try:
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/tags", timeout=2
        )
        data = json.loads(req.read())
        models = [m.get("name", "") for m in data.get("models", [])]
        return any(model in m for m in models)
    except Exception:
        return False


def _list_installed_models(port: int = OLLAMA_DEFAULT_PORT) -> list:
    try:
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/tags", timeout=2
        )
        data = json.loads(req.read())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _find_best_available_model(port: int = OLLAMA_DEFAULT_PORT, preferred: str = DEFAULT_OLLAMA_MODEL) -> str:
    """Auto-detect models. Use preferred if available, else fall back to any installed supported model."""
    installed = _list_installed_models(port)
    if preferred and any(preferred in m for m in installed):
        return preferred
    for supported in SUPPORTED_OLLAMA_MODELS:
        if any(supported in m for m in installed):
            return supported
    return DEFAULT_OLLAMA_MODEL


def _call_ollama(messages: list, port: int = OLLAMA_DEFAULT_PORT, max_tokens: int = 1500, model: str = DEFAULT_OLLAMA_MODEL) -> str:
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": max_tokens}
    }).encode()

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        return data["message"]["content"].strip()
    except Exception:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps({
                "model": model,
                "messages": messages,
                "stream": False,
                "temperature": 0.1,
                "max_tokens": max_tokens
            }).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()


def _call_groq(messages: list, api_key: str, max_tokens: int = 1500) -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.1,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content.strip()


def _parse_json_response(raw: str) -> any:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        return json.loads(raw.strip())
    brace_start = raw.find("[")
    brace_end = raw.rfind("]") + 1
    curly_start = raw.find("{")
    curly_end = raw.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        return json.loads(raw[brace_start:brace_end])
    if curly_start >= 0 and curly_end > curly_start:
        return json.loads(raw[curly_start:curly_end])
    return json.loads(raw)


def _get_field_spec(doc_type: str) -> list:
    specs = {
        "invoice": [
            "invoice_number", "invoice_date", "supplier_name", "consignee",
            "total_amount", "currency", "hs_code", "weight_kg",
            "quantity", "country_of_origin", "bl_number", "vessel_name",
            "port_of_loading", "port_of_discharge", "description_of_goods",
            "terms_of_payment", "incoterms"
        ],
        "bill_of_lading": [
            "bl_number", "shipper", "consignee", "notify_party",
            "vessel_name", "voyage_number", "port_of_loading", "port_of_discharge",
            "container_number", "total_packages", "gross_weight_kg",
            "measurement_cbm", "description_of_goods", "freight_status",
            "date_of_issue", "place_of_issue"
        ],
        "packing_list": [
            "invoice_number", "date", "shipper", "consignee",
            "total_packages", "total_gross_weight_kg", "total_net_weight_kg",
            "total_measurement_cbm", "marks_and_numbers", "description_of_goods"
        ]
    }
    return specs.get(doc_type, specs["invoice"])


def classify_document(raw_text: str, caller, mode_label: str) -> dict:
    prompt = f"""You are a customs document classifier. Based on the OCR text below, classify the document type.

Respond ONLY with a JSON object (no markdown, no explanation):
{{"type": "invoice" | "bill_of_lading" | "packing_list" | "unknown", "confidence": 0-100, "reason": "brief reason"}}

OCR Text (first 1500 chars):
{raw_text[:1500]}"""

    try:
        result = caller([{"role": "user", "content": prompt}], max_tokens=150)
        parsed = _parse_json_response(result)
        parsed["ai_enabled"] = True
        return parsed
    except Exception as e:
        return {"type": "unknown", "confidence": 0, "ai_enabled": False, "error": str(e)}


def extract_fields_ai(raw_text: str, doc_type: str, caller) -> list:
    fields = _get_field_spec(doc_type)

    prompt = f"""You are an AI assistant for customs document processing. Extract structured data from this OCR text of a {doc_type.replace('_', ' ')}.

Extract these fields: {', '.join(fields)}

Rules:
- Return ONLY a JSON array of objects
- Each object: {{"field": "field_name", "value": "extracted value", "confidence": 0-100}}
- If a field is not found, set value to null and confidence to 0
- Clean up OCR artifacts (fix obvious typos, remove garbage characters)
- For amounts, include currency symbol
- For HS codes, ensure 8-10 digits
- For dates, use format DD/MM/YYYY or as found in document
- No markdown, no explanation, ONLY the JSON array

OCR Text:
{raw_text[:3000]}"""

    try:
        result = caller([{"role": "user", "content": prompt}], max_tokens=1500)
        parsed = _parse_json_response(result)
        for field in parsed:
            field["source"] = "ai"
            conf = field.get("confidence", 0)
            field["status"] = (
                "auto_filled" if conf >= 90
                else "review" if conf >= 70
                else "manual"
            )
        return parsed
    except Exception as e:
        return [{"error": str(e), "source": "ai"}]


def validate_and_correct(fields: list, raw_text: str, caller) -> list:
    fields_json = json.dumps(fields, indent=2)

    prompt = f"""You are a customs document validation AI. Review these extracted fields and correct any errors.

Extracted fields:
{fields_json}

Original OCR text (first 2000 chars):
{raw_text[:2000]}

Rules:
- Return the SAME JSON array structure with corrections applied
- If a value looks wrong based on context, fix it and lower confidence to 75
- If a value is correct, keep confidence as-is or raise it
- Add "corrected": true if you changed a value, "corrected": false otherwise
- No markdown, no explanation, ONLY the JSON array

Return corrected JSON array:"""

    try:
        result = caller([{"role": "user", "content": prompt}], max_tokens=2000)
        return _parse_json_response(result)
    except Exception:
        return fields


def process_with_ai(
    raw_text: str,
    mode: str = "auto",
    api_key: str = "",
    ollama_port: int = OLLAMA_DEFAULT_PORT,
    ollama_model: str = DEFAULT_OLLAMA_MODEL
) -> dict:
    """
    Hybrid AI pipeline.
    mode: 'cloud' | 'local' | 'auto'
      auto → coba cloud (Groq), fallback local (Ollama)
    """

    if ollama_model not in SUPPORTED_OLLAMA_MODELS:
        ollama_model = DEFAULT_OLLAMA_MODEL

    groq_available = bool(api_key)
    ollama_available = check_ollama_available(ollama_port)

    if ollama_available and not check_model_exists(ollama_port, ollama_model):
        best_model = _find_best_available_model(ollama_port, ollama_model)
        if best_model != ollama_model:
            print(f"[AI] Model '{ollama_model}' tidak ditemukan, fallback ke '{best_model}'")
            ollama_model = best_model

    ollama_ready = ollama_available and check_model_exists(ollama_port, ollama_model)

    def groq_caller(messages, max_tokens=1500):
        return _call_groq(messages, api_key, max_tokens)

    def ollama_caller(messages, max_tokens=1500):
        return _call_ollama(messages, ollama_port, max_tokens, ollama_model)

    if mode == "cloud":
        if groq_available:
            caller = groq_caller
            model_label = "llama-3.1-8b-instant (Groq Cloud)"
            mode_used = "cloud"
        elif ollama_ready:
            caller = ollama_caller
            model_label = f"{ollama_model} (Ollama Lokal — fallback)"
            mode_used = "local_fallback"
        else:
            return {
                "ai_enabled": False,
                "message": "Mode Cloud: tidak ada internet/API key, dan Ollama belum tersedia.",
                "classification": None,
                "fields": []
            }

    elif mode == "local":
        if ollama_ready:
            caller = ollama_caller
            model_label = f"{ollama_model} (Ollama Lokal)"
            mode_used = "local"
        else:
            installed = _list_installed_models(ollama_port)
            hint = ""
            if check_ollama_available(ollama_port) and not installed:
                hint = " Jalankan: ollama pull qwen2.5:1.5b"
            elif not check_ollama_available(ollama_port):
                hint = " Pastikan Ollama sedang berjalan (ollama serve)."
            return {
                "ai_enabled": False,
                "message": f"Mode Lokal: Ollama belum siap atau model belum diunduh.{hint}",
                "classification": None,
                "fields": []
            }

    else:
        if groq_available:
            caller = groq_caller
            model_label = "llama-3.1-8b-instant (Groq Cloud)"
            mode_used = "cloud"
        elif ollama_ready:
            caller = ollama_caller
            model_label = f"{ollama_model} (Ollama Lokal)"
            mode_used = "local"
        else:
            return {
                "ai_enabled": False,
                "message": "AI tidak tersedia. Set Groq API Key atau unduh model Lokal.",
                "classification": None,
                "fields": []
            }

    try:
        classification = classify_document(raw_text, caller, mode_used)
        doc_type = classification.get("type", "invoice")

        fields = extract_fields_ai(raw_text, doc_type, caller)

        valid_fields = [f for f in fields if "error" not in f and f.get("value")]
        if valid_fields:
            fields = validate_and_correct(fields, raw_text, caller)

        return {
            "ai_enabled": True,
            "model": model_label,
            "mode": mode_used,
            "classification": classification,
            "fields": fields,
            "total_fields": len([f for f in fields if f.get("value")]),
        }

    except Exception as e:
        return {
            "ai_enabled": False,
            "error": str(e),
            "classification": None,
            "fields": []
        }
