from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Get your Gemini API key from .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Function to call Gemini API
def get_gemini_response(user_message):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + GEMINI_API_KEY
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [
            {
                "parts": [
                    {"text": user_message}
                ]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=data)

    # Debug full Gemini response
    print("\n--- Gemini Full API Response ---")
    print("Status Code:", response.status_code)
    print(response.text)
    print("--- End Response ---\n")

    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print("Error parsing Gemini response:", e)
        return "Oops! Couldn't get a smart reply. Try again later."

# WhatsApp webhook endpoint
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    reply = resp.message()

    if incoming_msg:
        bot_response = get_gemini_response(incoming_msg)
        reply.body(bot_response)
    else:
        reply.body("Hi! I'm Nima, your AI assistant. How can I help you today?")

    return str(resp)

# Start Flask app
if __name__ == "__main__":
    app.run(debug=True)
