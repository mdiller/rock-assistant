'''''
prompt: ok add a web request to send "hello there" as a discord message to this discord webhook: https://discord.com/api/webhooks/1196368250649456730/Z3vCm3tEItwE3jKChQf1tjT3fCe9DD7PAjIXqdlsuXLTL556ED-ckrImnkjkSB7ItF1I
[- Used So Far: 0.2003¢ | 1377 tokens -]
'''''
import requests

with open(__file__, "r") as file:
    contents = file.read()
    print(contents)

# Send a webhook request
webhook_url = "https://discord.com/api/webhooks/1196368250649456730/Z3vCm3tEItwE3jKChQf1tjT3fCe9DD7PAjIXqdlsuXLTL556ED-ckrImnkjkSB7ItF1I"
message = "hello there"

payload = {
    "content": message
}

response = requests.post(webhook_url, json=payload)

if response.status_code == 204:
    print("Webhook request sent successfully")
else:
    print("Failed to send webhook request")

print("badaboom")