import requests
import json

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
   'Authorization': 'Bearer ARK_API_KEY_REDACTED',
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)