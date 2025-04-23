from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Get Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Load Excel catalog
def load_gear_catalog():
    return pd.read_excel("data/nima_gear_catalog.xlsx")

# Match product based on user message
def match_product(user_input, df):
    message = user_input.lower()
    show_rent = any(word in message for word in ["rent", "borrow", "kiraye"])

    filtered = df[df.apply(
        lambda row: (
            row['Category'].lower() in message or
            str(row['Subcategory']).lower() in message or
            str(row['Type']).lower() in message
        ), axis=1)]

    if not filtered.empty:
        product = filtered.iloc[0]
        return {
            "model": product["Model"],
            "category": product["Category"],
            "type": product["Type"],
            "people": product.get("People/Size", ""),
            "price": product["Buy Price"],
            "rent_price": product["Rent Price"] if show_rent else None,
            "stock": product["Instock"],
            "image": product.get("Image URL", None)
        }
    return None

# Gemini context prompt
context = """
You are Nima, a warm, friendly assistant for The North Gear Kashmir — a premium outdoor and adventure gear store in Kashmir.

Your job is to help users by:
- Recommending products based on their queries and what’s available in the Excel catalog.
- Showing buy prices by default, but mentioning rent prices only if the user clearly asks (e.g., rent, borrow, kiraye).
- Using product details like category, subcategory, model, size or people count, and price to tailor suggestions.
- Checking the Instock column to confirm availability before recommending.
- Speaking naturally like a helpful shop assistant — short replies, friendly tone, and Hinglish if needed.
- Never sounding robotic. Be precise, proactive, and pleasant.

Store info:
- Open Mon–Sat, 9 AM–7 PM
- Delivery in Srinagar available
- Payments: UPI, cash, bank transfer
"""

# Combine context + product
def build_prompt(user_message, matched_product):
    if matched_product:
        product_text = f"""
        Product match:
        - Model: {matched_product['model']}
        - Category: {matched_product['category']}
        - Type: {matched_product['type']}
        - People/Size: {matched_product['people']}
        - Price: {matched_product['price']}
        {'- Rent Price: ' + matched_product['rent_price'] if matched_product['rent_price'] else ''}
        - Stock: {matched_product['stock']}
        """
        return f"{context}\n\n{product_text}\n\nCustomer: {user_message}"
    else:
        return f"{context}\n\nCustomer: {user_message}"

# Call Gemini
def get_gemini_response(user_message):
    print("📨 User message received by Gemini function:", user_message)
    print("🔑 Gemini API Key in use:", GEMINI_API_KEY)
    
    df = load_gear_catalog()
    match = match_product(user_message, df)
    prompt = build_prompt(user_message, match)

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + GEMINI_API_KEY
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=data)

    print("\n--- Gemini Full API Response ---")
    print("Status Code:", response.status_code)
    print(response.text)
    print("--- End Response ---\n")

    try:
        gemini_reply = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return gemini_reply, match
    except Exception as e:
        print("Error parsing Gemini response:", e)
        return "Oops! Couldn't get a smart reply. Try again later.", None


# WhatsApp webhook
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    print("✅ WhatsApp message received")  
    incoming_msg = request.values.get("Body", "").strip()
    resp = MessagingResponse()
    reply = resp.message()

    if incoming_msg:
        bot_response, match = get_gemini_response(incoming_msg)
        reply.body(bot_response)

        if match and match['image']:
            reply.media(match['image'])
    else:
        reply.body("Hi! I'm Nima, your AI assistant. How can I help you today?")

    return str(resp)

# Run the Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)

