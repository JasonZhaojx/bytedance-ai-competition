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
   'Authorization': 'Bearer ark-4126af52-1fda-4c17-8561-8db89e066502-95563',
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)