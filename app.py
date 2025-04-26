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
import random

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = Flask(__name__)

# Excel catalog setup
CATALOG_PATH = "Data/nima_gear_catalog.xlsx"
try:
    catalog_df = pd.read_excel(CATALOG_PATH)
    all_categories = ", ".join(catalog_df["Category"].dropna().unique())
except Exception as e:
    print(f"Error loading catalog: {e}", flush=True)
    raise SystemExit("Critical error: Could not load product catalog")

# In-memory session
sessions = {}

# Conversation elements
GREETINGS = [
    "Assalamualaikum! 😊 Nima bol rahi hoon — The North Gear Kashmir se. Kya dhund rahe ho?",
    "Assalamualaikum! Nima here from The North Gear. Aaj kya adventure gear chahiye?",
    "Assalamualaikum! 🌄️ Nima from North Gear Kashmir. Batao, kya help chahiye?",
]

THINKING_PHRASES = [
    "Hmm, dekhti hoon...",
    "Ek minute, check kar rahi hoon...",
    "Aapke liye best options dhund rahi hoon...",
    "Let me find the perfect gear for you...",
]

NO_PRODUCTS_RESPONSES = [
    "Sorry, abhi wo items nahi hain humare pass — lekin ye zaroor dekhiye: " + all_categories,
    "Hmm, wo abhi stock mein nahi hai. Ye categories check karein: " + all_categories,
    "Maaf kijiye, wo product available nahi hai. Ye dekhiye: " + all_categories,
]

EMOJIS = ["🌽", "⛰️", "🏵️", "🏃‍♂️", "🏕️", "🌄️", "💼"]

# System prompt for Gemini
GEMINI_SYSTEM_PROMPT = """
You are Nima, a smart and warm-hearted assistant working for The North Gear Kashmir — a premium outdoor and winter gear store in Kashmir.
Your ONLY job is to help users with product-related queries.
"""

# Get personalized greeting for returning customers
def get_personalized_greeting(user, session):
    if session.get("products_viewed"):
        recent_product = session["products_viewed"][-1]
        return f"Wapas aaye {session.get('name', 'dost')}! Pichli baar {recent_product} dekha tha na? Kuch aur chahiye?"
    return random.choice(GREETINGS)

# Gemini intent parser
def query_gemini_intent(user_input):
    print("query_gemini_intent called with:", user_input, flush=True)

    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not set", flush=True)
        return {"intent": "unknown"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "parts": [
                {"text": GEMINI_SYSTEM_PROMPT},
                {"text": f"User: {user_input}"}
            ]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=5)
        print("Gemini raw output:", response.text, flush=True)

        if response.status_code != 200:
            print(f"Gemini API error: {response.status_code}", flush=True)
            return {"intent": "unknown"}

        json_output = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(json_output)

    except requests.exceptions.Timeout:
        print("Gemini API timeout", flush=True)
        return {"intent": "api_timeout"}

    except Exception as e:
        print("Gemini parsing error:", e, flush=True)
        return {"intent": "unknown"}


# Match products smartly
def match_products(category, subcategory=None, price_limit=None):
    if not category:
        return []
    try:
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
                "warranty": row.get("warranty", "N/A")
            })
        return results
    except Exception as e:
        print(f"Error matching products: {e}", flush=True)
        return []

# Format product
def format_product(idx, p):
    rent_line = f"💼 Rent: {p['rent_price']}" if p['rent_price'] else ""
    prefixes = [
        f"Ye {p['model']} bahut popular hai —\n",
        f"Aapko ye {p['model']} pasand aayega —\n",
        f"Check out this {p['model']} —\n",
        f"Customers love this {p['model']} —\n",
        ""
    ]
    return (
        f"{idx+1}. {random.choice(prefixes)}{p['model']} ({p['category']} - {p['type']})\n"
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
    sender = request.values.get("From", "")
    user = sender.replace("whatsapp:", "") if sender else "Unknown"

    print("Incoming WhatsApp Body:", incoming_msg, flush=True)

    resp = MessagingResponse()
    current_time = time.time()

    if user not in sessions or current_time - sessions[user].get("timestamp", 0) > 900:
        sessions[user] = {"matches": [], "page": 0, "timestamp": current_time, "products_viewed": [], "name": "dost"}
        resp.message(random.choice(GREETINGS))
        return str(resp)
    elif incoming_msg.lower() in ["hello", "hi", "salaam"]:
        sessions[user]["timestamp"] = current_time
        sessions[user]["matches"] = []
        sessions[user]["page"] = 0
        resp.message(get_personalized_greeting(user, sessions[user]))
        return str(resp)

    sessions[user]["timestamp"] = current_time
    session = sessions[user]

    time.sleep(random.uniform(0.5, 1.5))
    intent_data = query_gemini_intent(incoming_msg)
    intent = intent_data.get("intent", "unknown")

    if intent == "show_categories":
        categories_list = all_categories.split(", ")
        resp.message(f"Humare paas ye sab kuch hai, {session['name']} 📍:\n\n" + "\n".join([f"• {cat}" for cat in categories_list]))
        return str(resp)

    if intent == "discount_request":
        resp.message(f"Discount ke liye store visit karein ya call karein: +91-9876543210 {random.choice(EMOJIS)}")
        return str(resp)

    if intent == "store_info":
        resp.message("Store Srinagar mein hai — Dal Lake ke paas. Delivery available! Appointment ke liye call karein: +91-9876543210")
        return str(resp)

    if intent == "abuse":
        resp.message("Main sirf help karne ke liye hoon 😊 Gear chahiye toh zaroor poochiye.")
        return str(resp)

    if intent == "unknown":
        resp.message("Koi baat nahi! Ye categories available hai: " + all_categories)
        return str(resp)

    if incoming_msg.lower() == "more" and session["matches"]:
        resp.message(random.choice(THINKING_PHRASES))
        session["page"] += 1

    elif incoming_msg.isdigit() and session["matches"]:
        index = int(incoming_msg) - 1
        if 0 <= index < len(session["matches"]):
            item = session["matches"][index]
            if "model" in item:
                if "products_viewed" not in session:
                    session["products_viewed"] = []
                session["products_viewed"].append(item["model"])
            msg = resp.message(format_product(index, item))
            if item.get("image"):
                try:
                    msg.media(item["image"])
                except Exception as e:
                    print(f"Error adding media: {e}", flush=True)
            return str(resp)

    elif intent == "product_search":
        resp.message(random.choice(THINKING_PHRASES))
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
        resp.message(random.choice(NO_PRODUCTS_RESPONSES))
        return str(resp)

    if page_items and start == 0:
        intro_messages = [
            f"Dekhiye kuch best options, {session['name']}! {random.choice(EMOJIS)}",
            f"Aapke liye perfect options, {session['name']}!",
        ]
        resp.message(random.choice(intro_messages))

    for i, item in enumerate(page_items, start=start):
        msg = resp.message(format_product(i, item))
        if item.get("image"):
            try:
                msg.media(item["image"])
            except Exception as e:
                print(f"Error adding media: {e}", flush=True)

    if end < len(session["matches"]):
        resp.message("Aur options dekhne ke liye 'more' likhiye!")
    else:
        resp.message("Pasand aaye toh number bhejiye aur pura detail paayiye!")

    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
