from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import pandas as pd
import os
from dotenv import load_dotenv
import difflib
import re
import time

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = Flask(__name__)

# Load Excel catalog
CATALOG_PATH = "Data/nima_gear_catalog.xlsx"
catalog_df = pd.read_excel(CATALOG_PATH)
all_categories = ", ".join(catalog_df["Category"].dropna().unique())

# Session store
sessions = {}

# Synonyms (excluding raincoat <-> jacket)
synonyms = {
    "joote": "boots",
    "shoes": "boots",
    "shooz": "boots",
    "shose": "boots",
    "thermal": "jacket",
    "coat": "jacket",
    "gloves": "accessory",
    "mittens": "gloves",
    "tandoor": "stove",
    "burner": "stove",
    "backpack": "bag",
    "rucksack": "bag",
    "tent house": "tent",
    "camper": "tent",
    "bagpack": "bag",
    "bottle": "accessory"
}

def normalize_message(msg):
    words = msg.split()
    final_words = []
    for word in words:
        if word in synonyms:
            final_words.append(synonyms[word])
        else:
            close = difflib.get_close_matches(word, synonyms.keys(), n=1, cutoff=0.85)
            if close:
                final_words.append(synonyms[close[0]])
            else:
                final_words.append(word)
    return " ".join(final_words)

def match_products(user_input):
    message = normalize_message(user_input.lower())
    show_rent = any(word in message for word in ["rent", "borrow", "kiraye"])
    price_matches = re.findall(r"\d{3,5}", message)
    price_limit = int(price_matches[0]) if price_matches else None

    filtered = catalog_df[catalog_df.apply(
        lambda row: (
            row['Category'].lower() in message or
            str(row['Subcategory']).lower() in message or
            str(row['Type']).lower() in message
        ), axis=1)]

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
            "type": row["Type"],
            "people": row.get("People/Size", ""),
            "price": row["Buy Price"],
            "rent_price": row["Rent Price"] if show_rent else None,
            "stock": row["Instock"],
            "image": row.get("Image URL", None)
        })

    return results

def format_product(idx, p):
    return f"""{idx+1}. {p['model']} ({p['category']} - {p['type']})
👥 Size: {p['people']}
💸 Price: {p['price']}
{f'💼 Rent: {p["rent_price"]}' if p["rent_price"] else ''}
📦 Stock: {p['stock']}"""

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From")
    user = sender.replace("whatsapp:", "")
    resp = MessagingResponse()
    current_time = time.time()

    if user not in sessions or current_time - sessions[user].get("timestamp", 0) > 900 or incoming_msg in ["hello", "hi", "salaam"]:
        sessions[user] = {"last_query": "", "matches": [], "page": 0, "timestamp": current_time}
        resp.message("Hi! I'm Nima from The North Gear Kashmir. What are you looking for today?")
        return str(resp)

    sessions[user]["timestamp"] = current_time
    session = sessions[user]

    # Show categories on broad question
    if any(x in incoming_msg for x in ["what do you have", "kya milta", "available items", "show items", "list"]):
        resp.message("Here's what we offer: " + all_categories)
        return str(resp)

    if incoming_msg == "more" and session["matches"]:
        session["page"] += 1
    elif incoming_msg.isdigit() and session["matches"]:
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
    else:
        session["page"] = 0
        session["matches"] = match_products(incoming_msg)
        session["last_query"] = incoming_msg

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
