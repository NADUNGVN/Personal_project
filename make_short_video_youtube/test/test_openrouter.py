import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

data = {
    "model": "google/gemini-3.1-flash-image-preview",
    "messages": [
        {"role": "user", "content": "Draw a red apple"}
    ]
}

response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
with open("openrouter_response.json", "w", encoding="utf-8") as f:
    f.write(response.text)
print("Saved to openrouter_response.json")
