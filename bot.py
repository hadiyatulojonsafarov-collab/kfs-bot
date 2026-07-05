import os
import sqlite3
import threading
from datetime import datetime, timedelta

import telebot
from telebot import types
from flask import Flask

# ================= ТАНЗИМОТ =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # ID-и телеграми admin
DISCOUNT_THRESHOLD = 1000   # сомонӣ — аз ин боло тахфиф дода мешавад
DISCOUNT_PERCENT = 10       # фоизи тахфиф

bot = telebot.TeleBot(BOT_TOKEN)

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price REAL
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    total REAL,
    discount REAL,
    created_at TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    food_id INTEGER,
    food_name TEXT,
    qty INTEGER,
    price REAL
)""")
conn.commit()

# ================= ХОТИРАИ МУВАҚҚАТӢ =================
carts = {}        # user_id -> {food_id: qty}
admin_state = {}  # user_id -> {"step": ...}
user_state = {}   # user_id -> "waiting_name"


# ================= KEYBOARD-ҲО =================
def main_menu(user_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🍗 Хӯрокҳо", "🛒 Саватам")
    kb.row("📦 Фармоишҳои ман")
    if user_id == ADMIN_ID:
        kb.row("⚙️ Панели admin")
    return kb


def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Иловаи хӯрок", "📋 Рӯйхати хӯрокҳо")
    kb.row("📊 Омори моҳона", "⬅️ Бозгашт")
    return kb


# ================= HELPER-ҲО =================
def get_food(food_id):
    cur.execute("SELECT id, name, price FROM foods WHERE id=?", (food_id,))
    return cur.fetchone()


def get_all_foods():
    cur.execute("SELECT id, name, price FROM foods ORDER BY id")
    return cur.fetchall()


def save_user(user_id, name):
    cur.execute("INSERT OR REPLACE INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()


def get_user_name(user_id):
    cur.execute("SELECT name FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None


# ================= /start =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    name = get_user_name(user_id)
    if name:
        bot.send_message(message.chat.id, f"Хуш омадед, {name}! 🍗", reply_markup=main_menu(user_id))
    else:
        user_state[user_id] = "waiting_name"
        bot.send_message(message.chat.id,
                          "Салом! Хуш омадед ба боти фармоиши хӯрок 🍗\n\nЛутфан номи худро нависед:")


@bot.message_handler(func=lambda m: user_state.get(m.from_user.id) == "waiting_name")
def save_name(message):
    user_id = message.from_user.id
    name = message.text.strip()
    save_user(user_id, name)
    user_state.pop(user_id, None)
    bot.send_message(message.chat.id, f"Ташаккур, {name}! Акнун метавонед фармоиш диҳед.",
                      reply_markup=main_menu(user_id))


# ================= ХӮРОКҲО =================
@bot.message_handler(func=lambda m: m.text == "🍗 Хӯрокҳо")
def show_foods(message):
    foods = get_all_foods()
    if not foods:
        bot.send_message(message.chat.id, "Ҳоло хӯроке илова нашудааст.")
        return
    for food_id, name, price in foods:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"➕ Илова ба сават — {price} сомонӣ", callback_data=f"add_{food_id}"))
        bot.send_message(message.chat.id, f"🍽 {name}\n💰 Нарх: {price} сомонӣ", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("add_"))
def add_to_cart(call):
    user_id = call.from_user.id
    food_id = int(call.data.split("_")[1])
    cart = carts.setdefault(user_id, {})
    cart[food_id] = cart.get(food_id, 0) + 1
    bot.answer_callback_query(call.id, "Ба сават илова шуд ✅")


# ================= САВАТ =================
@bot.message_handler(func=lambda m: m.text == "🛒 Саватам")
def show_cart(message):
    user_id = message.from_user.id
    cart = carts.get(user_id, {})
    if not cart:
        bot.send_message(message.chat.id, "Сабади шумо холист.")
        return

    text = "🛒 Сабади шумо:\n\n"
    total = 0
    for food_id, qty in cart.items():
        food = get_food(food_id)
        if not food:
            continue
        _, name, price = food
        subtotal = price * qty
        total += subtotal
        text += f"{name} x{qty} = {subtotal} сомонӣ\n"

    discount = total * DISCOUNT_PERCENT / 100 if total >= DISCOUNT_THRESHOLD else 0
    final = total - discount

    text += f"\nҶамъ: {total} сомонӣ"
    if discount:
        text += f"\n🎁 Тахфиф ({DISCOUNT_PERCENT}%): -{discount} сомонӣ"
    text += f"\n💵 Ба пардохт: {final} сомонӣ (нақд ҳангоми расонидан)"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Тасдиқи фармоиш", callback_data="checkout"))
    kb.add(types.InlineKeyboardButton("🗑 Холӣ кардани сават", callback_data="clear_cart"))
    bot.send_message(message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "clear_cart")
def clear_cart(call):
    carts.pop(call.from_user.id, None)
    bot.answer_callback_query(call.id, "Сабад холӣ карда шуд")
    bot.send_message(call.message.chat.id, "Сабади шумо холӣ карда шуд 🗑")


@bot.callback_query_handler(func=lambda c: c.data == "checkout")
def checkout(call):
    user_id = call.from_user.id
    cart = carts.get(user_id, {})
    if not cart:
        bot.answer_callback_query(call.id, "Сабад холист")
        return

    total = 0
    items = []
    for food_id, qty in cart.items():
        food = get_food(food_id)
        if not food:
            continue
        _, name, price = food
        total += price * qty
        items.append((food_id, name, qty, price))

    discount = total * DISCOUNT_PERCENT / 100 if total >= DISCOUNT_THRESHOLD else 0
    final = total - discount

    cur.execute("INSERT INTO orders (user_id, total, discount, created_at) VALUES (?, ?, ?, ?)",
                (user_id, final, discount, datetime.now().isoformat()))
    order_id = cur.lastrowid
    for food_id, name, qty, price in items:
        cur.execute(
            "INSERT INTO order_items (order_id, food_id, food_name, qty, price) VALUES (?, ?, ?, ?, ?)",
            (order_id, food_id, name, qty, price))
    conn.commit()

    carts.pop(user_id, None)
    name = get_user_name(user_id) or call.from_user.first_name

    bot.answer_callback_query(call.id, "Фармоиши шумо қабул шуд ✅")
    bot.send_message(
        call.message.chat.id,
        f"✅ Фармоиши шумо (№{order_id}) қабул шуд!\n💵 Маблағ: {final} сомонӣ (нақд)\nМунтазири расонидан бошед 🚗"
    )

    if ADMIN_ID:
        text = f"🆕 Фармоиши нав №{order_id}\n👤 Мизоҷ: {name}\n\n"
        for food_id, iname, qty, price in items:
            text += f"{iname} x{qty}\n"
        text += f"\nҶамъ: {total} сомонӣ"
        if discount:
            text += f"\nТахфиф: -{discount} сомонӣ"
        text += f"\nБа пардохт: {final} сомонӣ (нақд)"
        bot.send_message(ADMIN_ID, text)


# ================= ФАРМОИШҲОИ МАН =================
@bot.message_handler(func=lambda m: m.text == "📦 Фармоишҳои ман")
def my_orders(message):
    user_id = message.from_user.id
    cur.execute("SELECT id, total, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "Шумо то ҳол фармоише надодаед.")
        return
    text = "📦 Фармоишҳои охирини шумо:\n\n"
    for oid, total, created in rows:
        text += f"№{oid} — {total} сомонӣ ({created[:16]})\n"
    bot.send_message(message.chat.id, text)


# ================= ADMIN =================
@bot.message_handler(func=lambda m: m.text == "⚙️ Панели admin" and m.from_user.id == ADMIN_ID)
def open_admin(message):
    bot.send_message(message.chat.id, "Панели идоракунӣ:", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: m.text == "⬅️ Бозгашт" and m.from_user.id == ADMIN_ID)
def close_admin(message):
    bot.send_message(message.chat.id, "Бозгашт ба менюи асосӣ", reply_markup=main_menu(message.from_user.id))


@bot.message_handler(func=lambda m: m.text == "➕ Иловаи хӯрок" and m.from_user.id == ADMIN_ID)
def add_food_start(message):
    admin_state[message.from_user.id] = {"step": "name"}
    bot.send_message(message.chat.id, "Номи хӯрокро нависед:")


@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("step") == "name")
def add_food_name(message):
    admin_state[message.from_user.id] = {"step": "price", "name": message.text.strip()}
    bot.send_message(message.chat.id, "Нархи он (сомонӣ)-ро нависед (танҳо рақам):")


@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("step") == "price")
def add_food_price(message):
    user_id = message.from_user.id
    try:
        price = float(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "Лутфан рақами дуруст ворид кунед.")
        return
    name = admin_state[user_id]["name"]
    cur.execute("INSERT INTO foods (name, price) VALUES (?, ?)", (name, price))
    conn.commit()
    admin_state.pop(user_id, None)
    bot.send_message(message.chat.id, f"✅ Хӯрок илова шуд: {name} — {price} сомонӣ", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: m.text == "📋 Рӯйхати хӯрокҳо" and m.from_user.id == ADMIN_ID)
def list_foods_admin(message):
    foods = get_all_foods()
    if not foods:
        bot.send_message(message.chat.id, "Хӯроке нест.")
        return
    text = "📋 Рӯйхати хӯрокҳо:\n\n"
    for fid, name, price in foods:
        text += f"№{fid} — {name} — {price} сомонӣ\n"
    bot.send_message(message.chat.id, text)


@bot.message_handler(func=lambda m: m.text == "📊 Омори моҳона" and m.from_user.id == ADMIN_ID)
def monthly_stats(message):
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()
    cur.execute("""
        SELECT food_name, SUM(qty) as total_qty
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        WHERE o.created_at >= ?
        GROUP BY food_name
        ORDER BY total_qty DESC
    """, (month_ago,))
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "Дар як моҳи охир фармоише сабт нашудааст.")
        return
    text = "📊 Хӯрокҳои бисёр фурӯхташуда (30 рӯзи охир):\n\n"
    for i, (name, qty) in enumerate(rows, 1):
        text += f"{i}. {name} — {qty} дона\n"
    bot.send_message(message.chat.id, text)


# ================= FLASK (барои зинда нигоҳ доштан дар Render) =================
app = Flask(__name__)


@app.route('/')
def index():
    return 'Bot is running'


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


# ================= RUN =================
if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    print("Bot started...")
    bot.infinity_polling()
