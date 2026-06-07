from flask import Flask, request, jsonify, send_from_directory
import requests
import json
import os
import time
import hmac
import hashlib
from urllib.parse import parse_qsl

app = Flask(__name__)

BOT_TOKEN = "7956734661:AAEM5Yspg4LG6DVm9DgrXz3YEFT0Ad9DQrM"
CRYPTO_PAY_TOKEN = "592971:AADvLsQbRGEPUKV9WoOTDdW2nZGTldZZHXy"

DB_FILE = "database.json"

PRODUCTS = {
    "#13579": {
        "name": "Telegram Bot",
        "price": 10,
        "key": "CD10tb"
    },
    "#24680": {
        "name": "Mini App",
        "price": 6,
        "key": "CD6ma"
    },
    "#35791": {
        "name": "Site",
        "price": 12,
        "key": "CD12s"
    },
    "#46802": {
        "name": "PC Soft",
        "price": 4,
        "key": "CD4ps"
    }
}


def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def verify_telegram_init_data(init_data):
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user = json.loads(parsed.get("user", "{}"))
        return user

    except Exception:
        return None


def get_user_or_error():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data)

    if not user:
        return None, jsonify({"ok": False, "error": "Telegram auth error"}), 403

    user_id = str(user["id"])

    db = load_db()

    if user_id not in db:
        db[user_id] = {
            "id": user_id,
            "username": user.get("username", "unknown"),
            "first_name": user.get("first_name", ""),
            "photo_url": user.get("photo_url", ""),
            "balance": 0.0,
            "history": [],
            "invoices": {}
        }
        save_db(db)

    return user, db, user_id


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/profile", methods=["GET"])
def profile():
    user, db, user_id = get_user_or_error()
    if user is None:
        return db

    profile = db[user_id]

    return jsonify({
        "ok": True,
        "user": {
            "id": user_id,
            "username": profile["username"],
            "first_name": profile["first_name"],
            "photo_url": profile["photo_url"],
            "balance": profile["balance"],
            "history": profile["history"]
        }
    })


@app.route("/api/create_invoice", methods=["POST"])
def create_invoice():
    user, db, user_id = get_user_or_error()
    if user is None:
        return db

    data = request.json
    amount = float(data.get("amount", 0))

    if amount <= 0:
        return jsonify({"ok": False, "error": "Введите сумму больше 0"})

    url = "https://pay.crypt.bot/api/createInvoice"

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN
    }

    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": f"Пополнение баланса для ID {user_id}",
        "hidden_message": "Спасибо за оплату!",
        "paid_btn_name": "openBot",
        "paid_btn_url": "https://t.me/CryptoBot"
    }

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    result = r.json()

    if not result.get("ok"):
        return jsonify({"ok": False, "error": result})

    invoice = result["result"]
    invoice_id = str(invoice["invoice_id"])

    db[user_id]["invoices"][invoice_id] = {
        "amount": amount,
        "status": "active",
        "created_at": int(time.time())
    }

    save_db(db)

    pay_url = invoice.get("mini_app_invoice_url") or invoice.get("bot_invoice_url") or invoice.get("pay_url")

    return jsonify({
        "ok": True,
        "invoice_id": invoice_id,
        "pay_url": pay_url
    })


@app.route("/api/check_invoice", methods=["POST"])
def check_invoice():
    user, db, user_id = get_user_or_error()
    if user is None:
        return db

    invoice_id = str(request.json.get("invoice_id", ""))

    if invoice_id not in db[user_id]["invoices"]:
        return jsonify({"ok": False, "error": "Invoice не найден"})

    url = "https://pay.crypt.bot/api/getInvoices"

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN
    }

    payload = {
        "invoice_ids": invoice_id
    }

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    result = r.json()

    if not result.get("ok"):
        return jsonify({"ok": False, "error": result})

    items = result["result"]["items"]

    if not items:
        return jsonify({"ok": False, "error": "Invoice не найден в CryptoBot"})

    invoice = items[0]
    status = invoice["status"]

    if status == "paid" and db[user_id]["invoices"][invoice_id]["status"] != "paid":
        amount = db[user_id]["invoices"][invoice_id]["amount"]

        db[user_id]["balance"] += amount
        db[user_id]["invoices"][invoice_id]["status"] = "paid"

        db[user_id]["history"].insert(0, {
            "amount": amount,
            "time": time.strftime("%d.%m.%Y %H:%M")
        })

        save_db(db)

        return jsonify({
            "ok": True,
            "paid": True,
            "balance": db[user_id]["balance"]
        })

    return jsonify({
        "ok": True,
        "paid": status == "paid",
        "status": status,
        "balance": db[user_id]["balance"]
    })


@app.route("/api/product", methods=["POST"])
def product():
    user, db, user_id = get_user_or_error()
    if user is None:
        return db

    code = request.json.get("code", "").strip()

    if code not in PRODUCTS:
        return jsonify({"ok": False, "error": "Товар не найден"})

    return jsonify({
        "ok": True,
        "product": PRODUCTS[code],
        "code": code
    })


@app.route("/api/buy", methods=["POST"])
def buy():
    user, db, user_id = get_user_or_error()
    if user is None:
        return db

    code = request.json.get("code", "").strip()

    if code not in PRODUCTS:
        return jsonify({"ok": False, "error": "Товар не найден"})

    product = PRODUCTS[code]
    price = product["price"]

    if db[user_id]["balance"] < price:
        return jsonify({
            "ok": False,
            "error": "Недостаточно средств на балансе"
        })

    db[user_id]["balance"] -= price
    save_db(db)

    access_key = f"{product['key']}{user_id}"

    return jsonify({
        "ok": True,
        "balance": db[user_id]["balance"],
        "product": product["name"],
        "key": access_key
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)