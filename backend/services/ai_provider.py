import os
import json
import base64
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
AI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

_client = None

def _get_client():
    """Initialize OpenAI API client."""
    global _client
    if _client is not None:
        print(f"[AI_PROVIDER] Returning cached client")
        return _client
    api_key = os.getenv("OPENAI_API_KEY")
    print(f"[AI_PROVIDER] _get_client() called. API key: {'SET' if api_key else 'NOT SET'}")
    try:
        if api_key:
            print(f"[AI_PROVIDER] Initializing OpenAI with API key...")
            _client = OpenAI(api_key=api_key)
        else:
            print(f"[AI_PROVIDER] Initializing OpenAI from environment...")
            _client = OpenAI()  # Uses OPENAI_API_KEY from env
        print(f"[AI_PROVIDER] OpenAI client initialized successfully")
    except Exception as e:
        print(f"[AI_PROVIDER] Could not initialize OpenAI client: {str(e)}")
        import traceback
        traceback.print_exc()
        _client = None
    return _client

def generate_ai_response(prompt):
    """Call text/reasoning model with text prompt using OpenAI."""
    try:
        if AI_PROVIDER == "openai":
            client = _get_client()
            if not client:
                raise ValueError("OpenAI client not initialized")

            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # FIXED: Changed from 0.7 to 0.0 for deterministic extraction
                max_tokens=2000
            )

            return response.choices[0].message.content

        raise ValueError(f"Unsupported AI provider: {AI_PROVIDER}")

    except Exception as e:
        print(f"[AI_PROVIDER] Text generation error: {str(e)}")
        raise


def call_vision_model(image_bytes, prompt):
    """Call OpenAI Vision model (GPT-4o) with image bytes + text prompt."""
    try:
        if AI_PROVIDER != "openai":
            raise ValueError(f"Unsupported AI provider for Vision: {AI_PROVIDER}")

        client = _get_client()
        if not client:
            raise ValueError("OpenAI client not initialized")

        # Encode image to base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Call OpenAI Vision API with GPT-4o
        response = client.chat.completions.create(
            model="gpt-4o",  # GPT-4o has vision capabilities
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,
            temperature=0.0  # FIXED: Changed from 0.7 to 0.0 for deterministic document extraction
        )

        result = response.choices[0].message.content
        if not result:
            raise ValueError("No response from Vision model")

        return result

    except Exception as e:
        print(f"[AI_PROVIDER] Vision extraction failed: {str(e)}")
        raise


def call_reasoning_model(text_prompt, json_data):
    """Call text model with structured JSON data for tax reasoning using OpenAI."""
    try:
        combined_prompt = f"{text_prompt}\n\nStructured Data:\n{json.dumps(json_data, indent=2)}"
        return generate_ai_response(combined_prompt)

    except Exception as e:
        print(f"[AI_PROVIDER] Reasoning call failed: {str(e)}")
        raise
