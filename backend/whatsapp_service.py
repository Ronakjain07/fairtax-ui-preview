import requests
import time
import logging
from config import Config

logger = logging.getLogger(__name__)


def _retry_with_backoff(func, max_retries=3, base_delay=1):
    """
    Retry a function with exponential backoff.

    Args:
        func: Callable that returns (success: bool, response: dict)
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds (doubles each retry)

    Returns:
        dict: Response from the function
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            success, response = func()

            if success:
                return response

            # Check if error is retryable
            if isinstance(response, dict):
                error = response.get('error', {})
                if isinstance(error, dict):
                    error_code = error.get('code')
                    # Retry on rate limit (429) and temporary errors (5xx)
                    if error_code not in (429, 500, 502, 503, 504):
                        return response  # Non-retryable error

            last_error = response

        except requests.exceptions.Timeout as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries + 1}: Timeout - {str(e)}")
            last_error = {'error': f'Timeout: {str(e)}'}

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries + 1}: Request error - {str(e)}")
            last_error = {'error': f'Request error: {str(e)}'}

        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{max_retries + 1}: Unexpected error - {str(e)}")
            return {'error': str(e)}

        # Calculate delay with exponential backoff
        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)  # 1, 2, 4 seconds
            logger.info(f"Retrying in {delay} seconds... (Attempt {attempt + 2}/{max_retries + 1})")
            time.sleep(delay)

    logger.error(f"All {max_retries + 1} retry attempts failed")
    return last_error or {'error': 'Unknown error after retries'}


def send_template(to_phone, template_name, params, button_url_param=None):
    """
    Send an approved WhatsApp template message with retry logic.

    Args:
        to_phone: '919876543210' (with country code, no +)
        template_name: Template name in WhatsApp Business Manager
        params: list of strings replacing {{1}}, {{2}}, ... in template
        button_url_param: optional string for URL button dynamic suffix

    Returns:
        dict: API response
    """
    url = Config.WHATSAPP_API_URL or f"https://graph.facebook.com/{Config.WHATSAPP_API_VERSION}/{Config.WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {Config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    # Basic config validation
    if not Config.WHATSAPP_TOKEN or (not Config.WHATSAPP_PHONE_ID and not Config.WHATSAPP_API_URL):
        logger.warning("[whatsapp_service] Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_ID/API_URL; skipping send")
        return {"error": "missing_whatsapp_config"}

    # Sanitize params
    sanitized_params = []
    for p in (params or []):
        val = str(p or "").strip()
        if not val:
            val = "Your filing"
        sanitized_params.append(val)

    components = [{
        "type": "body",
        "parameters": [{"type": "text", "text": p} for p in sanitized_params]
    }]

    if button_url_param:
        btn_val = str(button_url_param).strip()
        if btn_val:
            components.append({
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": btn_val}]
            })

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components
        }
    }

    def _send():
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=45)
            try:
                res_json = r.json()
            except Exception:
                res_json = {"raw_text": r.text}

            is_success = r.ok and not (isinstance(res_json, dict) and res_json.get("error"))

            if is_success:
                mid = None
                if isinstance(res_json, dict):
                    msgs = res_json.get('messages')
                    if isinstance(msgs, list) and len(msgs) > 0:
                        mid = msgs[0].get('id')
                logger.info(f"[whatsapp_service] Template sent: to={to_phone}, template={template_name}, id={mid}")

            else:
                logger.warning(f"[whatsapp_service] Failed to send template: "
                             f"status={r.status_code}, resp={res_json}")

            return is_success, res_json

        except Exception as e:
            logger.error(f"[whatsapp_service] Exception sending template: {str(e)}")
            raise

    return _retry_with_backoff(_send, max_retries=3, base_delay=2)


def send_text(to_phone, text):
    """
    Send a plain text WhatsApp message with retry logic.

    Args:
        to_phone: Phone number with country code (no +)
        text: Message body string

    Returns:
        dict: API response
    """
    url = Config.WHATSAPP_API_URL or f"https://graph.facebook.com/{Config.WHATSAPP_API_VERSION}/{Config.WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {Config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    if not Config.WHATSAPP_TOKEN or (not Config.WHATSAPP_PHONE_ID and not Config.WHATSAPP_API_URL):
        logger.warning("[whatsapp_service] Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_ID/API_URL; skipping send_text")
        return {"error": "missing_whatsapp_config"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": str(text)}
    }

    def _send():
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=45)
            try:
                res_json = r.json()
            except Exception:
                res_json = {"raw_text": r.text}

            is_success = r.ok and not (isinstance(res_json, dict) and res_json.get("error"))

            if is_success:
                logger.info(f"[whatsapp_service] Text sent: to={to_phone}")
            else:
                logger.warning(f"[whatsapp_service] Failed to send text: "
                             f"status={r.status_code}, resp={res_json}")

            return is_success, res_json

        except Exception as e:
            logger.error(f"[whatsapp_service] Exception sending text: {str(e)}")
            raise

    return _retry_with_backoff(_send, max_retries=3, base_delay=2)


def normalize_phone(p):
    """Normalize phone number to 91XXXXXXXXXX format."""
    p = str(p or "").replace(" ", "").replace("+", "").replace("-", "")
    if len(p) == 10:
        p = "91" + p
    return p
