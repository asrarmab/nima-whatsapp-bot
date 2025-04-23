from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import pandas as pd
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = Flask(__name__)

# Load Excel catalog once
CATALOG_PATH = "Data/nima_gear_catalog.xlsx"
catalog_df = pd.read_excel(CATALOG_PATH)

# Simple in-memory session store
sessions = {}  # Format: { phone_number: { 'last_query': '', 'matches': [], 'page': 0 } }

# Match products using Excel data
def match_products(user_input):
    message = user_input.lower()
    show_rent = any(word in message for word in ["rent", "borrow", "kiraye"])

    filtered = catalog_df[catalog_df.apply(
        lambda row: (
            row['Category'].lower() in message or
            str(row['Subcategory']).lower() in message or
            str(row['Type']).lower() in message
        ), axis=1)]

    # Sort by stock: in-stock first
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

# Format a single product for messaging
def format_product(idx, p):
    return f"""{idx+1}. {p['model']} ({p['category']} - {p['type']})
👥 Size: {p['people']}
💸 Price: {p['price']}
{f'💼 Rent: {p["rent_price"]}' if p["rent_price"] else ''}
📦 Stock: {p['stock']}"""

# WhatsApp webhook route
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From")
    user = sender.replace("whatsapp:", "")
    resp = MessagingResponse()

    # Setup session
    if user not in sessions:
        sessions[user] = {"last_query": "", "matches": [], "page": 0}

    session = sessions[user]

    # If user types "more"
    if incoming_msg == "more" and session["matches"]:
        session["page"] += 1

    # If user selects a number from previous list
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

    # If it's a new search query
    else:
        session["page"] = 0
        session["matches"] = match_products(incoming_msg)
        session["last_query"] = incoming_msg

    # Paginate results
    page_size = 5
    start = session["page"] * page_size
    end = start + page_size
    page_items = session["matches"][start:end]

    if not page_items:
        resp.message("No items found or end of list reached. Try a new query.")
        return str(resp)

    for i, item in enumerate(page_items, start=start):
        msg = resp.message(format_product(i, item))
        if item.get("image"):
            msg.media(item["image"])

    if end < len(session["matches"]):
        resp.message("Reply with 'more' to see more options or reply with a number (e.g. 1, 2) to select.")

    return str(resp)

# Start the Flask server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
