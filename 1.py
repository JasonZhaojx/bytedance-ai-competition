import requests
import json
import os

url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

payload = json.dumps({
   "model": "ep-20260514111325-xjmj7",
   "messages": [
      {
         "role": "system",
         "content": "You are a helpful assistant."
      },
      {
         "role": "user",
         "content": "Hello!"
      }
   ]
})
headers = {
   'Authorization': 'Bearer ' + (os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY") or os.getenv("LLM_API_KEY") or ""),
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
