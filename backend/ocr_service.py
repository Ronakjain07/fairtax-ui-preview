from config import Config
import base64
import requests
from google.cloud import vision

_gcv_client = vision.ImageAnnotatorClient()


def _call_openrouter_image_ocr(file_bytes):
    if not getattr(Config, "OPENROUTER_API_KEY", None):
        raise Exception("OPENROUTER_API_KEY not configured")

    b64 = base64.b64encode(file_bytes).decode()
    messages = [
        {
            "role": "user",
            "content": (
                "Extract and return ONLY the plain textual content from the provided image. "
                "Do not add annotations, descriptions, or JSON — return the concatenated text exactly as it appears.\n\n"
                f"IMAGE_BASE64:\n{b64}"
            ),
        }
    ]

    payload = {
        "model": Config.OCR_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 5000,
    }

    headers = {
        "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    r = requests.post(Config.OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict) and data.get("choices"):
        choice = data["choices"][0]
        if isinstance(choice, dict):
            msg = choice.get("message")
            if msg and isinstance(msg, dict) and "content" in msg:
                return msg["content"]
            if "text" in choice:
                return choice["text"]

    if isinstance(data, dict) and "result" in data:
        out = data["result"].get("output")
        if isinstance(out, list) and out:
            for item in out:
                if isinstance(item, str):
                    return item
                if isinstance(item, dict) and item.get("content"):
                    return item["content"]

    raise Exception(f"Unexpected OpenRouter response for OCR: {data}")


def extract_text_from_image(file_bytes):
    # Only call the OpenRouter OCR model when OCR_USE_AI is enabled and an OCR_MODEL is configured
    if getattr(Config, "OCR_USE_AI", True) and getattr(Config, "OCR_MODEL", None):
        try:
            return _call_openrouter_image_ocr(file_bytes)
        except Exception as e:
            print(f"[OCR][OpenRouter] failed, falling back to Google Vision: {e}")

    image = vision.Image(content=file_bytes)
    response = _gcv_client.text_detection(image=image)

    if getattr(response, "error", None) and getattr(response.error, "message", None):
        raise Exception(response.error.message)

    texts = response.text_annotations
    return texts[0].description if texts else ""


def extract_text_from_pdf(file_bytes):
    # Use Google Vision for PDF/document OCR (keeps existing robust flow)
    client = vision.ImageAnnotatorClient()

    input_config = vision.InputConfig(
        content=file_bytes,
        mime_type="application/pdf",
    )

    feature = vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)

    request = vision.AnnotateFileRequest(
        input_config=input_config,
        features=[feature],
    )

    response = client.batch_annotate_files(requests=[request])

    text = ""
    for res in response.responses:
        for page in res.responses:
            if page.full_text_annotation:
                text += page.full_text_annotation.text

    return text