import json
import os

import requests


API_KEY = os.getenv("ARK_API_KEY") or os.getenv("LLM_API_KEY") or "<token>"
URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL = os.getenv("LLM_MODEL", "Doubao-Seed-2.0-lite")

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": "你好",
        }
    ],
}
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

response = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=120)
response.raise_for_status()
data = response.json()

print(data["choices"][0]["message"]["content"])
