'''''
PROMPT:
ok add a web request to send "hello there" as a discord message to a discord message url when they pass one in as an argument in the command line
[- Used So Far: 0.0743¢ | 422 tokens -]
'''''
import requests
import sys

def send_discord_message(message_url, content):
    payload = {
        'content': content
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.post(message_url, json=payload, headers=headers)
    if response.status_code == 200:
        print("Message sent successfully")
    else:
        print("Message sending failed")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <message_url>")
        sys.exit(1)

    message_url = sys.argv[1]
    content = "Hello there"

    send_discord_message(message_url, content)