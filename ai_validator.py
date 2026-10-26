import os
import base64
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def validate_proof_image(image_path: str, ngo_name: str, amount: float, note: str) -> str:
    """
    Sends the uploaded proof image and claim details to Claude to verify 
    if the visual evidence matches the claimed relief expenditure.
    """
    if not os.path.exists(image_path):
        return "VERDICT: ERROR\nCONFIDENCE: Low\nREASONING: Image file not found on disk."

    with open(image_path, "rb") as img_file:
        image_data = base64.b64encode(img_file.read()).decode("utf-8")

    ext = image_path.lower().split('.')[-1]
    media_type = "image/png" if ext == "png" else "image/jpeg"

    prompt = f"""
    You are an AI auditor for a flood relief tracking system. 
    Analyze this uploaded proof image and determine if it validly supports the following claim:
    - NGO Name: {ngo_name}
    - Claimed Amount: ${amount}
    - Description/Note: {note}

    Check for:
    1. Visual signs of flood relief activity, distribution, or receipts matching the details.
    2. Any obvious signs of tampering, mismatched branding, or irrelevant stock photos.

    Respond strictly in the following format:
    VERDICT: [MATCH / SUSPICIOUS / REJECT]
    CONFIDENCE: [High / Medium / Low]
    REASONING: [1-2 concise sentences explaining why]
    """

    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ],
                }
            ],
        )
        return message.content[0].text
    except Exception as e:
        return f"VERDICT: ERROR\nCONFIDENCE: Low\nREASONING: {str(e)}"