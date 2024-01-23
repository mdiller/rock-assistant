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