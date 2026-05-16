import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_URL = "https://api.openai.com/v1/chat/completions"
    OCR_MODEL = os.getenv("OCR_MODEL", "baidu/qianfan-ocr-fast:free")
    OCR_USE_AI = os.getenv("OCR_USE_AI", "1").lower() in ("1", "true", "yes")
    EXTRACTION_USE_AI = os.getenv("EXTRACTION_USE_AI", "1").lower() in ("1", "true", "yes")

    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
    SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")

    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v18.0")
    # Optional full API URL (overrides version+phone id construction)
    WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "")
    # Verify token used when registering the webhook with Meta/Facebook
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

    FLASK_SECRET = os.getenv("FLASK_SECRET", "dev")
    USE_AI = os.getenv("USE_AI", "1").lower() in ("1", "true", "yes")
    APPS_SCRIPT_WEBHOOK_URL = os.getenv("APPS_SCRIPT_WEBHOOK_URL", "")
    PAYMENT_UPI_ID = os.getenv("PAYMENT_UPI_ID", "fairtaxadvisors@upi")