import os
import re
import json
from dotenv import load_dotenv
from google import genai


def run_test():
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in .env")

    client = genai.Client(api_key=api_key)

    prompt = """
You are a product feedback analyst.

Return ONLY valid JSON.

Classify this feedback:
"App crashes every time I open it after the latest update"

Return this exact schema:
{
  "category": ["bug", "crash"],
  "sentiment": -0.9,
  "urgency": 5,
  "summary": "App crashes on launch after update",
  "entities": ["latest update"]
}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    raw_text = response.text
    if not raw_text or not raw_text.strip():
        print("❌ Empty response from Gemini API")
        return

    output = raw_text.strip()
    # Strip code fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", output)
    if match:
        output = match.group(1).strip()

    print("RAW OUTPUT:\n")
    print(output)

    print("\nPARSED JSON:\n")
    try:
        parsed = json.loads(output)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse JSON: {e}")
        print(f"Raw output was:\n{output}")


if __name__ == "__main__":
    run_test()
