#AshishSecDev
from collections import defaultdict

from flask import Flask, request, jsonify
import requests
import os
import re
import time
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-<--Add your bot token-->")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
BOT_USER_ID = os.getenv("BOT_USER_ID", "<@<--App_User_ID-->")

processed_events = {}          
thread_cache = defaultdict(list) 

@app.route('/', methods=['GET'])
def home():
    return "Ollama Slack Bot is running."

@app.route('/slack/events', methods=['POST'])
def slack_events():
    slack_data = request.json

    if slack_data.get("type") == "url_verification":
        return jsonify({"challenge": slack_data["challenge"]})

    if 'event' in slack_data:
        event = slack_data['event']
        event_id = slack_data.get('event_id')

        if event_id in processed_events:
            return jsonify({'status': 'duplicate ignored'}), 200
        processed_events[event_id] = time.time()
        # Cleanup old events important as Bot might keep sending you old responses.
        for key in list(processed_events):
            if time.time() - processed_events[key] > 60:
                del processed_events[key]

        if event.get('bot_id'):
            return jsonify({'status': 'ignored'}), 200

        if event['type'] == 'message':
            channel = event['channel']
            text = event.get('text', '')
            parent_ts = event.get('thread_ts') or event.get('ts')

            # Direct message to Bot
            if event.get('channel_type') == 'im':
                response = get_ollama_response(text)
                send_slack_message(response, channel)

            # Mention in thread
            elif is_bot_mentioned(text) and parent_ts:
                # Fetch thread messages (cached)
                messages = get_thread_messages_cached(channel, parent_ts)
                cleaned_text = clean_thread_messages(messages)

                # Change here for prefixed prompts
                prompt = f"""You are a helpful assistant. Answer the following question based on this Slack thread:

Thread messages:
{cleaned_text}

User question: {text}
"""
  
                response = get_ollama_response(prompt)
                send_slack_message(response, channel, parent_ts)

    return jsonify({'status': 'ok'}), 200


def is_bot_mentioned(text):
    return BOT_USER_ID in text if text else False

def get_thread_messages_cached(channel, thread_ts):
    """Fetch thread messages with caching"""
    cache_key = f"{channel}-{thread_ts}"
    if cache_key in thread_cache:
        return thread_cache[cache_key]

    messages = fetch_thread_messages(channel, thread_ts)
    thread_cache[cache_key] = messages
    return messages

def fetch_thread_messages(channel, thread_ts):
    """Fetch all messages in a Slack thread (paginated)"""
    headers = {'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
    params = {'channel': channel, 'ts': thread_ts, 'limit': 200}
    all_messages = []
    cursor = None

    try:
        while True:
            if cursor:
                params['cursor'] = cursor
            response = requests.get(
                'https://slack.com/api/conversations.replies',
                headers=headers,
                params=params
            )
            data = response.json()
            if not data.get("ok"):
                print("Slack API error:", data)
                break
            all_messages.extend(data.get("messages", []))
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:
        print(f"Error fetching thread messages: {e}")

    return all_messages

def clean_thread_messages(messages):
    """Strip bot mentions and empty messages"""
    cleaned = []
    for msg in messages:
        if 'text' in msg and not msg.get('bot_id'):
            txt = re.sub(r"<@[\w]+>", "", msg['text']).strip()
            if txt:
                cleaned.append(txt)
    return "\n".join(cleaned)

def get_ollama_response(prompt):
    headers = {'Content-Type': 'application/json'}
    payload = {"model": "llama3.1:8b", "prompt": prompt, "stream": False} #Change Model here in Ollama, I am currently using llama3.1 8b parameter

    try:
        start = time.time()
        response = requests.post(OLLAMA_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_text = response.json().get("response", "")
        print(f"Ollama generation took {time.time() - start:.2f}s")
    except Exception as e:
        print(f"Error calling Ollama API: {e}")
        return "There was an error processing your request."


    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
    return response_text.strip() if response_text else "Sorry, I couldn't generate a response."

def send_slack_message(text, channel, thread_ts=None):
    """Send message back to Slack"""
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {SLACK_BOT_TOKEN}'}
    payload = {'channel': channel, 'text': text}
    if thread_ts:
        payload['thread_ts'] = thread_ts
    try:
        requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload) #Posting responses via Slack API
    except Exception as e:
        print(f"Error sending message: {e}")


if __name__ == '__main__':
    app.run(port=5000, debug=True)
