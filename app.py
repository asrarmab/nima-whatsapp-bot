from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import pandas as pd
import os
from dotenv import load_dotenv
import difflib
import re
import time
import json
import requests

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = Flask(__name__)

# Excel catalog setup
CATALOG_PATH = "Data/nima_gear_catalog.xlsx"
catalog_df = pd.read_excel(CATALOG_PATH)
all_categories = ", ".join(catalog_df["Category"].dropna().unique())

# In-memory session
sessions = {}

# System prompt for Gemini
GEMINI_SYSTEM_PROMPT = """
You are Nima, a smart and warm-hearted assistant working for The North Gear Kashmir — a premium outdoor and winter gear store in Kashmir.

Your ONLY job is to help users with product-related queries such as jackets, tents, boots, gloves, stoves, and similar gear.

If a user asks anything off-topic (like writing code, telling jokes, or anything not related to outdoor gear), politely say:
"I'm here to help you with adventure gear. Let me know what you're looking for 😊"

Always extract and respond with a structured summary of the user’s intent and key product preferences. For example:

Input: “Mujhe -10 wali jacket chahiye under 3000”
→ Output:
{
  "intent": "product_search",
  "category": "jacket",
  "subcategory": "-10",
  "price_limit": 3000,
  "language": "hindi"
}

Input: “What do you guys sell?”
→ Output:
{
  "intent": "show_categories"
}

Input: “Where is your store?”
→ Output:
{
  "intent": "store_info"
}

Input: “Any discount?”
→ Output:
{
  "intent": "discount_request"
}

Input: “chutye”, “you guys are scammers”
→ Output:
{
  "intent": "abuse"
}

If you are not sure, return:
{ "intent": "unknown" }

Always respond in pure JSON — no extra text, comments, or explanations.
"""

# Gemini intent parser
def query_gemini_intent(user_input):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "parts": [
                { "text": GEMINI_SYSTEM_PROMPT },
                { "text": f"User: {user_input}" }
            ]
        }]
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        json_output = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(json_output)
    except Exception as e:
        print("Gemini parsing error:", e)
        return { "intent": "unknown" }

# Match products
def match_products(category, subcategory=None, price_limit=None):
    if not category:
        return []

    filtered = catalog_df[catalog_df["Category"].str.lower() == category.lower()]
    if subcategory:
        filtered = filtered[filtered["Subcategory"].str.lower() == subcategory.lower()]

    if price_limit:
        price_filtered = filtered[filtered['Buy Price'] <= price_limit]
        if price_filtered.empty:
            tolerance = price_limit * 1.25
            filtered = filtered[filtered['Buy Price'] <= tolerance]
        else:
            filtered = price_filtered

    filtered = filtered.sort_values(by='Instock', ascending=False)

    results = []
    for _, row in filtered.iterrows():
        results.append({
            "model": row["Model"],
            "category": row["Category"],
            "type": row.get("Type", ""),
            "people": row.get("People/Size", ""),
            "price": row.get("Buy Price", "N/A"),
            "rent_price": row.get("Rent Price", None),
            "stock": row.get("Instock", "N/A"),
            "image": row.get("Image URL", None),
            "warranty": row.get("Warranty", "N/A")
        })
    return results
# Format product
def format_product(idx, p):
    rent_line = f"💼 Rent: {p['rent_price']}" if p['rent_price'] else ""
    return (
        f"{idx+1}. {p['model']} ({p['category']} - {p['type']})\n"
        f"👥 Size: {p['people']}\n"
        f"💸 Price: {p['price']}\n"
        f"🛠️ Warranty: {p['warranty']}\n"
        f"📦 Stock: {p['stock']}\n"
        f"{rent_line}"
    )
# WhatsApp webhook
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From")
    user = sender.replace("whatsapp:", "")
    resp = MessagingResponse()
    current_time = time.time()

    if user not in sessions or current_time - sessions[user].get("timestamp", 0) > 900 or incoming_msg.lower() in ["hello", "hi", "salaam"]:
        sessions[user] = {"matches": [], "page": 0, "timestamp": current_time}
        resp.message("Assalamualaikum! 😊 Nima bol rahi hoon — The North Gear Kashmir se. Jackets, tents, ya kuch aur chahiye ho toh bataiye!")
        return str(resp)

    sessions[user]["timestamp"] = current_time
    session = sessions[user]

    intent_data = query_gemini_intent(incoming_msg)
    intent = intent_data.get("intent", "unknown")

    if intent == "show_categories":
        resp.message("Here's what we offer: " + all_categories)
        return str(resp)

    if intent == "discount_request":
        resp.message("Discount ke liye aap hamare store pe visit karein ya iss number pe contact karein: +91-9876543210")
        return str(resp)

    if intent == "store_info":
        resp.message("Hamari location Srinagar mein hai — delivery available hai. Store visit by appointment hai. Contact karein: +91-9876543210")
        return str(resp)

    if intent == "abuse":
        resp.message("Main sirf help karne ke liye hoon 😊 Agar gear chahiye ho, toh zaroor batayein.")
        return str(resp)

    if incoming_msg.lower() == "more" and session["matches"]:
        session["page"] += 1
    elif incoming_msg.lower().isdigit() and session["matches"]:
        index = int(incoming_msg) - 1
        if 0 <= index < len(session["matches"]):
            item = session["matches"][index]
            msg = resp.message(format_product(index, item))
            if item.get("image"):
                msg.media(item["image"])
            return str(resp)
        else:
            resp.message("Invalid selection. Please reply with a valid number.")
            return str(resp)
    elif intent == "product_search":
        session["page"] = 0
        session["matches"] = match_products(
            category=intent_data.get("category"),
            subcategory=intent_data.get("subcategory"),
            price_limit=intent_data.get("price_limit")
        )

    page_size = 5
    start = session["page"] * page_size
    end = start + page_size
    page_items = session["matches"][start:end]

    if not page_items:
        resp.message("Sorry, we don’t have that — but we do offer: " + all_categories)
        return str(resp)

    for i, item in enumerate(page_items, start=start):
        msg = resp.message(format_product(i, item))
        if item.get("image"):
            msg.media(item["image"])

    if end < len(session["matches"]):
        resp.message("Reply with 'more' to see more options, or reply with a number (e.g. 1, 2) to select.")

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
