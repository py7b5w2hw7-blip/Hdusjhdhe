# bot.py
# ПОЛНАЯ РАБОЧАЯ ВЕРСИЯ
# Функции: магазин, казино, рефералка, промокоды, зеркала (авто + ручные), отзывы, профиль
# Управление зеркалами: список, удалить, сделать текущим
# Оплата: CryptoBot (прямые ссылки), DonationAlerts (скриншоты), Кнопка «Оплатил» + ручная выдача доступа админом
# В комментарии к переводу пользователь указывает свой USERNAME

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
import sqlite3
import time
import threading
import requests
import random
import string
from datetime import datetime
import os

# ========== ТОКЕНЫ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')
WORKER_BOT_TOKEN = os.getenv('WORKER_BOT_TOKEN')
LOGGER_BOT_TOKEN = os.getenv('LOGGER_BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
CRYPTOBOT_TOKEN = os.getenv('CRYPTOBOT_TOKEN')
DONATIONALERTS_NICK = os.getenv('DONATIONALERTS_NICK')

# Каналы
MAIN_CHANNEL = "https://t.me/+S75wQGSxdBw2Mzhh"
REVIEWS_CHANNEL = "https://t.me/+Bb17ibvo_yMzZTAx"
PAYMENT_CHANNEL = "https://t.me/+tzeYwAOSIRZiNDRh"

# Фото (замени на свои file_id)
PHOTO_5_10 = "AgACAgIAAxkBAAIB"
PHOTO_10_18 = "AgACAgIAAxkBAAIC"

PRICE_5_10 = 600
PRICE_10_18 = 450
USDT_RATE = 100

# Платёжные ссылки CryptoBot (твои)
CRYPTO_PAYMENT_600 = "https://t.me/send?start=IVMzuIHtBnQf"
CRYPTO_PAYMENT_450 = "https://t.me/send?start=IVP4orolsPew"

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect('bot.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS users 
             (user_id TEXT PRIMARY KEY, username TEXT, first_seen INTEGER, last_seen INTEGER, balance INTEGER, channel_msg_id INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS mirrors 
             (token TEXT PRIMARY KEY, username TEXT, added_by TEXT, added_at INTEGER, is_active INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS current_bot 
             (id INTEGER PRIMARY KEY, token TEXT, username TEXT, updated_at INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS payments 
             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, username TEXT, amount INTEGER, method TEXT, status TEXT, invoice_id TEXT, timestamp INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS crypto_invoices 
             (invoice_id TEXT PRIMARY KEY, user_id TEXT, amount_usdt INTEGER, status TEXT, created_at INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS pending_payments 
             (user_id TEXT, username TEXT, amount INTEGER, product TEXT, timestamp INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_sessions 
             (user_id TEXT PRIMARY KEY, step TEXT, data TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS admin_sessions 
             (user_id TEXT PRIMARY KEY, step TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_stats 
             (user_id TEXT PRIMARY KEY, ref_code TEXT, earned INTEGER, ref_clicks INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS referals 
             (code TEXT PRIMARY KEY, owner_id TEXT, earnings INTEGER, clicks INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS promo_codes 
             (code TEXT PRIMARY KEY, discount INTEGER, uses_left INTEGER, created_at INTEGER, is_active INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS user_promo 
             (user_id TEXT PRIMARY KEY, discount INTEGER, expires_at INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS casino_games 
             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, game_type TEXT, bet INTEGER, win INTEGER, timestamp INTEGER)''')
conn.commit()

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========
def log_to_admin(text, photo=None):
    try:
        if photo:
            requests.post(f"https://api.telegram.org/bot{LOGGER_BOT_TOKEN}/sendPhoto", 
                         json={"chat_id": ADMIN_ID, "photo": photo, "caption": text[:1000]}, timeout=5)
        else:
            requests.post(f"https://api.telegram.org/bot{LOGGER_BOT_TOKEN}/sendMessage", 
                         json={"chat_id": ADMIN_ID, "text": text[:4000]}, timeout=5)
    except:
        pass

def register_user(user_id, username, ref_code=None):
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, username, first_seen, last_seen, balance) VALUES (?, ?, ?, ?, 0)",
                  (user_id, username, int(time.time()), int(time.time())))
        if ref_code and ref_code != user_id:
            c.execute("UPDATE referals SET clicks = clicks + 1 WHERE code=?", (ref_code,))
            c.execute("INSERT OR IGNORE INTO user_stats (user_id, ref_code, earned, ref_clicks) VALUES (?, ?, 0, 0)", (user_id, ref_code))
            log_to_admin(f"🔗 новый реферал: {username} по коду {ref_code}")
    else:
        c.execute("UPDATE users SET username=?, last_seen=? WHERE user_id=?", (username, int(time.time()), user_id))
    conn.commit()

def get_balance(user_id):
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else 0

def update_balance(user_id, amount):
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    log_to_admin(f"💰 баланс: +{amount} для {user_id}")

# ========== РЕФЕРАЛКА ==========
def generate_ref_code(user_id):
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    c.execute("INSERT OR REPLACE INTO user_stats (user_id, ref_code, earned, ref_clicks) VALUES (?, ?, 0, 0)", (user_id, code))
    c.execute("INSERT OR IGNORE INTO referals (code, owner_id, earnings, clicks) VALUES (?, ?, 0, 0)", (code, user_id))
    conn.commit()
    return code

def get_ref_link(user_id):
    c.execute("SELECT ref_code FROM user_stats WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row or not row[0]:
        code = generate_ref_code(user_id)
    else:
        code = row[0]
    bot_username = WORKER_BOT_TOKEN.split(':')[0]
    return f"https://t.me/{bot_username}?start=ref_{user_id}"

def add_ref_earnings(ref_code, amount):
    c.execute("SELECT owner_id FROM referals WHERE code=?", (ref_code,))
    row = c.fetchone()
    if row:
        owner = row[0]
        commission = int(amount * 0.4)
        c.execute("UPDATE referals SET earnings = earnings + ? WHERE code=?", (commission, ref_code))
        c.execute("UPDATE user_stats SET earned = earned + ? WHERE user_id=?", (commission, owner))
        conn.commit()
        log_to_admin(f"💸 комиссия {commission}₽ для {owner}")

# ========== ПРОМОКОДЫ ==========
def create_promo_code(code, discount, uses):
    c.execute("INSERT OR REPLACE INTO promo_codes VALUES (?, ?, ?, ?, 1)", (code.upper(), discount, uses, int(time.time()), 1))
    conn.commit()

def get_all_promos():
    c.execute("SELECT code, discount, uses_left FROM promo_codes WHERE is_active=1 AND uses_left>0")
    return c.fetchall()

def apply_promo(user_id, code):
    c.execute("SELECT discount, uses_left FROM promo_codes WHERE code=? AND is_active=1 AND uses_left>0", (code.upper(),))
    row = c.fetchone()
    if not row:
        return False, 0
    discount, uses = row
    c.execute("INSERT OR REPLACE INTO user_promo (user_id, discount, expires_at) VALUES (?, ?, ?)", (user_id, discount, int(time.time()) + 3600))
    c.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code=?", (code.upper(),))
    conn.commit()
    return True, discount

def get_user_discount(user_id):
    c.execute("SELECT discount FROM user_promo WHERE user_id=? AND expires_at > ?", (user_id, int(time.time())))
    row = c.fetchone()
    return row[0] if row else 0

def clear_user_promo(user_id):
    c.execute("DELETE FROM user_promo WHERE user_id=?", (user_id,))
    conn.commit()

# ========== КАЗИНО ==========
def play_mines(bet):
    if bet <= 0:
        return 0, "ставка должна быть больше 0"
    if random.random() < 0.85:
        win = int(bet * random.choice([1.5, 2.0, 2.5]))
        return win, f"🎉 выигрыш: {win}₽!"
    return 0, "💥 мина взорвалась"

def play_rocket(bet):
    if bet <= 0:
        return 0, "ставка должна быть больше 0"
    if random.random() < 0.85:
        multiplier = random.choice([1.5, 2.0, 2.5, 3.0])
        win = int(bet * multiplier)
        return win, f"🚀 выигрыш: {win}₽ (x{multiplier})"
    return 0, "💥 ракета взорвалась"

def open_case(bet):
    items = [
        {"name": "обычный скин", "win": bet * 0.5, "chance": 40},
        {"name": "редкий скин", "win": bet * 1.5, "chance": 30},
        {"name": "эпический скин", "win": bet * 3, "chance": 20},
        {"name": "легендарный скин", "win": bet * 5, "chance": 10}
    ]
    rand = random.randint(1, 100)
    cumulative = 0
    for item in items:
        cumulative += item["chance"]
        if rand <= cumulative:
            return int(item["win"]), f"📦 {item['name']} +{item['win']}₽"
    return 0, "ничего не выпало"

# ========== ЗЕРКАЛА ==========
def get_current_bot():
    c.execute("SELECT token, username FROM current_bot WHERE id=1")
    row = c.fetchone()
    if row:
        return row[0], row[1]
    set_current_bot(WORKER_BOT_TOKEN, "worker_bot")
    return WORKER_BOT_TOKEN, "worker_bot"

def set_current_bot(token, username):
    c.execute("DELETE FROM current_bot WHERE id=1")
    c.execute("INSERT INTO current_bot (id, token, username, updated_at) VALUES (1, ?, ?, ?)", (token, username, int(time.time())))
    conn.commit()
    log_to_admin(f"🔄 текущий бот: @{username}")

def check_bot_alive(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        if r.json().get('ok'):
            return True, r.json()['result']['username']
        return False, None
    except:
        return False, None

def add_mirror(token, username, added_by):
    c.execute("INSERT OR REPLACE INTO mirrors VALUES (?, ?, ?, ?, 1)", (token, username, added_by, int(time.time())))
    conn.commit()
    log_to_admin(f"➕ новое зеркало: @{username} (добавил {added_by})")

def delete_mirror(token):
    c.execute("UPDATE mirrors SET is_active=0 WHERE token=?", (token,))
    conn.commit()
    log_to_admin(f"❌ зеркало удалено: {token[:30]}...")

def get_all_mirrors():
    c.execute("SELECT token, username FROM mirrors WHERE is_active=1 ORDER BY added_at DESC")
    return c.fetchall()

def rotate_bot():
    current_token, current_name = get_current_bot()
    alive, _ = check_bot_alive(current_token)
    if not alive:
        log_to_admin(f"💀 бот @{current_name} умер!")
        for token, username in get_all_mirrors():
            if token == current_token:
                continue
            alive, _ = check_bot_alive(token)
            if alive:
                set_current_bot(token, username)
                log_to_admin(f"🔄 ротация: новый бот @{username}")
                return True
        set_current_bot(WORKER_BOT_TOKEN, "worker_bot_default")
        log_to_admin("❌ нет живых зеркал")
    return True

def monitor_bots():
    while True:
        try:
            rotate_bot()
        except:
            pass
        time.sleep(600)

# ========== ЗАКРЕПЛЁННОЕ СООБЩЕНИЕ ==========
def send_pinned_message(chat_id, user_id):
    c.execute("SELECT channel_msg_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        return
    text = "📢 <b>подпишись на наш канал</b>\n\nв канале мы публикуем:\n▪️ промокоды на скидку\n▪️ анонсы новых товаров\n▪️ розыгрыши"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📢 подписаться", url=MAIN_CHANNEL))
    try:
        sent = worker_bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
        worker_bot.pin_chat_message(chat_id, sent.message_id)
        c.execute("UPDATE users SET channel_msg_id=? WHERE user_id=?", (sent.message_id, user_id))
        conn.commit()
    except:
        pass

# ========== ГЛАВНОЕ МЕНЮ ==========
def main_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🛒 магазин", callback_data="shop"),
        InlineKeyboardButton("🎰 казино", callback_data="casino"),
        InlineKeyboardButton("⭐ отзывы", callback_data="reviews"),
        InlineKeyboardButton("📈 рефералка", callback_data="referral"),
        InlineKeyboardButton("🎟 промокод", callback_data="promo"),
        InlineKeyboardButton("👤 профиль", callback_data="profile"),
        InlineKeyboardButton("🤖 создать зеркало", callback_data="create_mirror")
    )
    return kb

# ========== ОСНОВНОЙ БОТ (ПЕРЕХОДНИК) ==========
main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)

@main_bot.message_handler(commands=['start'])
def main_start(m):
    user_id = str(m.from_user.id)
    username = m.from_user.username if m.from_user.username else "no_username"
    register_user(user_id, username)
    current_token, current_name = get_current_bot()
    alive, real_name = check_bot_alive(current_token)
    if not alive:
        rotate_bot()
        current_token, current_name = get_current_bot()
        alive, real_name = check_bot_alive(current_token)
    if alive and real_name:
        current_name = real_name
    text = f"🤖 актуальный бот\n\n@{current_name}\n\n👇 нажми на username выше"
    main_bot.reply_to(m, text)

# ========== БОТ-ПРОДАЖ ==========
worker_bot = telebot.TeleBot(WORKER_BOT_TOKEN)

@worker_bot.message_handler(commands=['start'])
def worker_start(m):
    user_id = str(m.from_user.id)
    username = m.from_user.username if m.from_user.username else "no_username"
    ref_code = None
    if ' ' in m.text and len(m.text.split()) > 1 and m.text.split()[1].startswith('ref_'):
        ref_code = m.text.split()[1].replace('ref_', '')
    register_user(user_id, username, ref_code)
    send_pinned_message(m.chat.id, user_id)
    text = "🍼 <b>детское питание shop</b>\n\nвыбери действие:"
    worker_bot.send_message(m.chat.id, text, parse_mode='HTML', reply_markup=main_menu())

@worker_bot.callback_query_handler(func=lambda call: True)
def worker_cb(call):
    user_id = str(call.from_user.id)
    username = call.from_user.username if call.from_user.username else "no_username"
    
    if call.data == "shop":
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("👶 5-10 лет — 600₽", callback_data="buy_5_10"),
            InlineKeyboardButton("🧒 10-18 лет — 450₽", callback_data="buy_10_18"),
            InlineKeyboardButton("🔙 назад", callback_data="back")
        )
        worker_bot.edit_message_text("📦 <b>выбери категорию:</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "buy_5_10":
        discount = get_user_discount(user_id)
        price = PRICE_5_10
        if discount > 0:
            price = int(price * (100 - discount) / 100)
        caption = f"👶 5-10 лет\n\n💰 цена: {price}₽\n\n💳 после оплаты нажми «оплатил»\n📺 инструкция: https://youtu.be/l5qt_5l0DfI\n\n⚠️ в комментарии к переводу укажи свой username: @{username}"
        if discount > 0:
            caption = f"👶 5-10 лет\n\n✨ скидка {discount}%!\n💰 цена: {price}₽\n\n💳 после оплаты нажми «оплатил»\n📺 инструкция: https://youtu.be/l5qt_5l0DfI\n\n⚠️ в комментарии к переводу укажи свой username: @{username}"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💳 ОПЛАТИТЬ 600₽", url=CRYPTO_PAYMENT_600))
        kb.add(InlineKeyboardButton("✅ ОПЛАТИЛ", callback_data=f"paid_{price}_5_10"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="shop"))
        try:
            worker_bot.edit_message_media(InputMediaPhoto(PHOTO_5_10, caption=caption, parse_mode='HTML'), 
                                          call.message.chat.id, call.message.message_id, reply_markup=kb)
        except:
            worker_bot.edit_message_text(caption, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "buy_10_18":
        discount = get_user_discount(user_id)
        price = PRICE_10_18
        if discount > 0:
            price = int(price * (100 - discount) / 100)
        caption = f"🧒 10-18 лет\n\n💰 цена: {price}₽\n\n💳 после оплаты нажми «оплатил»\n📺 инструкция: https://youtu.be/l5qt_5l0DfI\n\n⚠️ в комментарии к переводу укажи свой username: @{username}"
        if discount > 0:
            caption = f"🧒 10-18 лет\n\n✨ скидка {discount}%!\n💰 цена: {price}₽\n\n💳 после оплаты нажми «оплатил»\n📺 инструкция: https://youtu.be/l5qt_5l0DfI\n\n⚠️ в комментарии к переводу укажи свой username: @{username}"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💳 ОПЛАТИТЬ 450₽", url=CRYPTO_PAYMENT_450))
        kb.add(InlineKeyboardButton("✅ ОПЛАТИЛ", callback_data=f"paid_{price}_10_18"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="shop"))
        try:
            worker_bot.edit_message_media(InputMediaPhoto(PHOTO_10_18, caption=caption, parse_mode='HTML'), 
                                          call.message.chat.id, call.message.message_id, reply_markup=kb)
        except:
            worker_bot.edit_message_text(caption, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("paid_"):
        parts = call.data.split("_")
        amount = parts[1]
        product = parts[2]
        
        c.execute("INSERT INTO pending_payments (user_id, username, amount, product, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (user_id, username, amount, product, int(time.time())))
        conn.commit()
        
        text = f"💳 НОВАЯ ОПЛАТА\n\n👤 ID: {user_id}\n👤 Username: @{username}\n💰 Сумма: {amount}₽\n📦 Товар: {product}\n\n✅ Нажми на кнопку, чтобы выдать доступ"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🎁 ВЫДАТЬ ДОСТУП", callback_data=f"give_access_{user_id}_{product}"))
        logger_bot.send_message(ADMIN_ID, text, parse_mode='HTML', reply_markup=kb)
        
        worker_bot.answer_callback_query(call.id, "✅ Уведомление отправлено админу! Ожидай подтверждения.")
        worker_bot.send_message(call.message.chat.id, "✅ Уведомление отправлено! Админ скоро проверит оплату и выдаст доступ.")
    
    elif call.data == "reviews":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("⭐ канал с отзывами", url=REVIEWS_CHANNEL))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="back"))
        worker_bot.edit_message_text("⭐ отзывы наших клиентов", call.message.chat.id, call.message.message_id, reply_markup=kb)
    
    elif call.data == "referral":
        ref_link = get_ref_link(user_id)
        c.execute("SELECT earned, ref_clicks FROM user_stats WHERE user_id=?", (user_id,))
        row = c.fetchone()
        earned = row[0] if row else 0
        clicks = row[1] if row else 0
        text = f"📈 <b>рефералка</b>\n\nтвоя ссылка:\n<code>{ref_link}</code>\n\n💰 заработано: {earned}₽\n👥 переходов: {clicks}\n🎁 40% с пополнений рефералов"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="back"))
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "promo":
        worker_bot.send_message(call.message.chat.id, "🎟 введи промокод:")
        c.execute("INSERT OR REPLACE INTO user_sessions VALUES (?, ?, ?)", (user_id, "awaiting_promo", ""))
        conn.commit()
        worker_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "profile":
        balance = get_balance(user_id)
        c.execute("SELECT earned FROM user_stats WHERE user_id=?", (user_id,))
        row = c.fetchone()
        earned = row[0] if row else 0
        text = f"👤 <b>профиль</b>\n\n🆔 id: {user_id}\n👤 username: @{username}\n💰 баланс казино: {balance}₽\n💸 заработано рефералами: {earned}₽"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💰 пополнить баланс", callback_data="deposit"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="back"))
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "deposit":
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("10 usdt (~1000₽)", callback_data="deposit_10"),
            InlineKeyboardButton("20 usdt (~2000₽)", callback_data="deposit_20"),
            InlineKeyboardButton("50 usdt (~5000₽)", callback_data="deposit_50"),
            InlineKeyboardButton("🔙 назад", callback_data="profile")
        )
        worker_bot.edit_message_text("💰 <b>пополнить баланс казино</b>\n\nвыбери сумму usdt:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("deposit_"):
        amount_usdt = int(call.data.split("_")[1])
        rub = amount_usdt * USDT_RATE
        text = f"💰 ПОПОЛНЕНИЕ БАЛАНСА\n\nСумма: {rub}₽ ({amount_usdt} USDT)\n\n⚠️ В комментарии к переводу укажи свой username: @{username}\n\n📺 Инструкция: https://youtu.be/l5qt_5l0DfI"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💳 ОПЛАТИТЬ", url=CRYPTO_PAYMENT_600))
        kb.add(InlineKeyboardButton("✅ ОПЛАТИЛ", callback_data=f"paid_deposit_{rub}"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="deposit"))
        worker_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("paid_deposit_"):
        rub = int(call.data.split("_")[2])
        c.execute("INSERT INTO pending_payments (user_id, username, amount, product, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (user_id, username, rub, "deposit", int(time.time())))
        conn.commit()
        text = f"💳 НОВОЕ ПОПОЛНЕНИЕ БАЛАНСА\n\n👤 ID: {user_id}\n👤 Username: @{username}\n💰 Сумма: {rub}₽"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("💰 ВЫДАТЬ БАЛАНС", callback_data=f"give_balance_{user_id}_{rub}"))
        logger_bot.send_message(ADMIN_ID, text, parse_mode='HTML', reply_markup=kb)
        worker_bot.answer_callback_query(call.id, "✅ Уведомление отправлено админу!")
    
    elif call.data == "create_mirror":
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🤖 создать бота", url="https://t.me/botfather"))
        kb.add(InlineKeyboardButton("📤 отправить токен", callback_data="send_mirror_token"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="back"))
        worker_bot.edit_message_text("🤖 <b>создать зеркало</b>\n\n1️⃣ создай бота в @botfather\n2️⃣ отправь его токен сюда\n3️⃣ бот попадёт в базу зеркал\n\n✅ поможет сервису жить дольше", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data == "send_mirror_token":
        worker_bot.send_message(call.message.chat.id, "📝 отправь токен бота:\n`1234567890:abcde...`", parse_mode='Markdown')
        c.execute("INSERT OR REPLACE INTO user_sessions VALUES (?, ?, ?)", (user_id, "awaiting_mirror", ""))
        conn.commit()
        worker_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "casino":
        balance = get_balance(user_id)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("💣 mine", callback_data="game_mines"),
            InlineKeyboardButton("🚀 rocket", callback_data="game_rocket"),
            InlineKeyboardButton("📦 кейсы", callback_data="game_case"),
            InlineKeyboardButton("🔙 назад", callback_data="back")
        )
        worker_bot.edit_message_text(f"🎰 <b>казино</b>\n\n💰 твой баланс: {balance}₽\n\nвыбери игру:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("game_"):
        game = call.data.split("_")[1]
        balance = get_balance(user_id)
        if balance < 10:
            worker_bot.answer_callback_query(call.id, "❌ недостаточно средств! пополни баланс в профиле", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("10₽", callback_data=f"play_{game}_10"),
            InlineKeyboardButton("50₽", callback_data=f"play_{game}_50"),
            InlineKeyboardButton("100₽", callback_data=f"play_{game}_100"),
            InlineKeyboardButton("🔙 назад", callback_data="casino")
        )
        worker_bot.edit_message_text(f"🎲 {game.upper()}\n💰 твой баланс: {balance}₽\n\nвыбери ставку:", call.message.chat.id, call.message.message_id, reply_markup=kb)
    
    elif call.data.startswith("play_"):
        parts = call.data.split("_")
        game = parts[1]
        bet = int(parts[2])
        balance = get_balance(user_id)
        if balance < bet:
            worker_bot.answer_callback_query(call.id, "❌ недостаточно средств!", show_alert=True)
            return
        update_balance(user_id, -bet)
        if game == "mines":
            win, msg = play_mines(bet)
        elif game == "rocket":
            win, msg = play_rocket(bet)
        else:
            win, msg = open_case(bet)
        if win > 0:
            update_balance(user_id, win)
        new_balance = get_balance(user_id)
        worker_bot.edit_message_text(f"🎮 {game.upper()} | ставка: {bet}₽\n\n{msg}\n\n💰 новый баланс: {new_balance}₽\n\n🎮 сыграть ещё?", call.message.chat.id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 сыграть ещё", callback_data=f"game_{game}"), InlineKeyboardButton("🔙 в казино", callback_data="casino")))
    
    elif call.data == "back":
        worker_bot.edit_message_text("🍼 <b>детское питание shop</b>\n\nвыбери действие:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=main_menu())

@worker_bot.message_handler(func=lambda m: True, content_types=['text', 'photo'])
def worker_text(m):
    user_id = str(m.from_user.id)
    username = m.from_user.username if m.from_user.username else "no_username"
    c.execute("SELECT step FROM user_sessions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    step = row[0] if row else None
    
    if step == "awaiting_promo":
        code = m.text.strip().upper()
        success, discount = apply_promo(user_id, code)
        if success:
            worker_bot.reply_to(m, f"✅ промокод {code} активирован! скидка {discount}%")
        else:
            worker_bot.reply_to(m, "❌ неверный промокод")
        c.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        conn.commit()
    
    elif step == "awaiting_mirror":
        token = m.text.strip()
        if ':' not in token:
            worker_bot.reply_to(m, "❌ неверный формат токена")
            return
        alive, bot_username = check_bot_alive(token)
        if not alive:
            worker_bot.reply_to(m, "❌ бот не существует или заблокирован")
            return
        add_mirror(token, bot_username, username)
        worker_bot.reply_to(m, f"✅ бот @{bot_username} добавлен в зеркала! спасибо 🤝")
        c.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        conn.commit()
    
    elif m.content_type == 'photo':
        photo = m.photo[-1].file_id
        caption = f"📸 СКРИНШОТ ОПЛАТЫ\n\n👤 Username: @{username}\n👤 ID: {user_id}\n\n⚠️ проверь платёж и выдай доступ вручную"
        log_to_admin(caption, photo)
        worker_bot.reply_to(m, "✅ скриншот отправлен админу! ожидай проверки.")
    
    else:
        # Если не в сессии и не фото — игнорируем
        pass

# ========== БОТ-ЛОГГЕР ==========
logger_bot = telebot.TeleBot(LOGGER_BOT_TOKEN)

def admin_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 статистика", callback_data="admin_stats"),
        InlineKeyboardButton("🪞 зеркала", callback_data="admin_mirrors"),
        InlineKeyboardButton("⏳ ожидают оплаты", callback_data="admin_pending"),
        InlineKeyboardButton("📢 рассылка", callback_data="admin_spam"),
        InlineKeyboardButton("🎟 промокоды", callback_data="admin_promos")
    )
    return kb

@logger_bot.message_handler(commands=['start', 'admin'])
def logger_start(m):
    if str(m.from_user.id) != ADMIN_ID:
        logger_bot.reply_to(m, "❌ доступ запрещён")
        return
    logger_bot.send_message(m.chat.id, "🔐 <b>админ панель</b>", parse_mode='HTML', reply_markup=admin_kb())

@logger_bot.callback_query_handler(func=lambda call: True)
def admin_cb(call):
    if str(call.from_user.id) != ADMIN_ID:
        logger_bot.answer_callback_query(call.id, "доступ запрещён")
        return
    
    if call.data == "admin_stats":
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM mirrors WHERE is_active=1")
        mirrors = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM payments WHERE status='completed'")
        total = c.fetchone()[0] or 0
        current_token, current_name = get_current_bot()
        text = f"📊 <b>статистика</b>\n\n👥 пользователей: {users}\n🪞 зеркал: {mirrors}\n💰 оборот: {total}₽\n🤖 текущий бот: @{current_name}"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
    
    elif call.data == "admin_mirrors":
        mirrors = get_all_mirrors()
        if not mirrors:
            text = "🪞 <b>зеркала</b>\n\nнет зеркал"
            logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
            return
        
        kb = InlineKeyboardMarkup(row_width=1)
        for token, username in mirrors:
            alive, _ = check_bot_alive(token)
            status = "✅ жив" if alive else "❌ мёртв"
            kb.add(InlineKeyboardButton(f"{status} @{username}", callback_data=f"mirror_{token}_{username}"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="admin_stats"))
        logger_bot.edit_message_text("🪞 <b>выбери зеркало</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("mirror_"):
        parts = call.data.split("_")
        token = parts[1]
        username = parts[2]
        
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔄 СДЕЛАТЬ ТЕКУЩИМ", callback_data=f"set_current_{token}_{username}"))
        kb.add(InlineKeyboardButton("❌ УДАЛИТЬ", callback_data=f"del_mirror_{token}"))
        kb.add(InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_mirrors"))
        logger_bot.edit_message_text(f"🪞 <b>зеркало @{username}</b>\n\nвыбери действие:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("set_current_"):
        parts = call.data.split("_")
        token = parts[2]
        username = parts[3]
        alive, _ = check_bot_alive(token)
        if alive:
            set_current_bot(token, username)
            logger_bot.answer_callback_query(call.id, f"✅ бот @{username} теперь текущий")
            logger_bot.edit_message_text(f"✅ текущий бот: @{username}", call.message.chat.id, call.message.message_id, reply_markup=admin_kb())
        else:
            logger_bot.answer_callback_query(call.id, "❌ бот мёртв, нельзя сделать текущим", show_alert=True)
    
    elif call.data.startswith("del_mirror_"):
        token = call.data.replace("del_mirror_", "")
        delete_mirror(token)
        logger_bot.answer_callback_query(call.id, "✅ зеркало удалено")
        logger_bot.edit_message_text("✅ зеркало удалено", call.message.chat.id, call.message.message_id, reply_markup=admin_kb())
    
    elif call.data == "admin_pending":
        c.execute("SELECT user_id, username, amount, product, timestamp FROM pending_payments ORDER BY timestamp DESC")
        pendings = c.fetchall()
        if not pendings:
            text = "⏳ нет ожидающих оплат"
            logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())
            return
        
        kb = InlineKeyboardMarkup(row_width=1)
        for uid, uname, amt, prod, ts in pendings:
            dt = datetime.fromtimestamp(ts).strftime("%H:%M %d.%m")
            kb.add(InlineKeyboardButton(f"[{dt}] @{uname} — {amt}₽ ({prod})", callback_data=f"pending_{uid}_{amt}_{prod}"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="admin_stats"))
        logger_bot.edit_message_text("⏳ <b>ожидают оплаты</b>\n\nнажми на пользователя, чтобы выдать доступ:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    
    elif call.data.startswith("pending_"):
        parts = call.data.split("_")
        uid = parts[1]
        amt = parts[2]
        prod = parts[3]
        
        kb = InlineKeyboardMarkup()
        if prod == "deposit":
            kb.add(InlineKeyboardButton("💰 ВЫДАТЬ БАЛАНС", callback_data=f"give_balance_{uid}_{amt}"))
        else:
            kb.add(InlineKeyboardButton("🎁 ВЫДАТЬ ДОСТУП", callback_data=f"give_access_{uid}_{prod}"))
        kb.add(InlineKeyboardButton("🔙 назад", callback_data="admin_pending"))
        logger_bot.edit_message_text(f"⏳ оплата от {uid}\n💰 {amt}₽\n📦 {prod}\n\nвыдай доступ?", call.message.chat.id, call.message.message_id, reply_markup=kb)
    
    elif call.data.startswith("give_access_"):
        parts = call.data.split("_")
        uid = parts[2]
        product = parts[3]
        
        c.execute("DELETE FROM pending_payments WHERE user_id=?", (uid,))
        conn.commit()
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🍼 ПОЛУЧИТЬ ДОСТУП", url=PAYMENT_CHANNEL))
        try:
            worker_bot.send_message(uid, f"✅ Ваша оплата подтверждена! Нажми на кнопку, чтобы получить доступ к каналу:", reply_markup=kb)
            logger_bot.answer_callback_query(call.id, "✅ Доступ выдан")
            logger_bot.edit_message_text(f"✅ Доступ выдан пользователю {uid}", call.message.chat.id, call.message.message_id, reply_markup=admin_kb())
        except:
            logger_bot.answer_callback_query(call.id, "❌ Не удалось отправить сообщение")
    
    elif call.data.startswith("give_balance_"):
        parts = call.data.split("_")
        uid = parts[2]
        amt = int(parts[3])
        
        c.execute("DELETE FROM pending_payments WHERE user_id=?", (uid,))
        conn.commit()
        update_balance(uid, amt)
        
        try:
            worker_bot.send_message(uid, f"✅ Ваш баланс пополнен на {amt}₽! Можешь играть в казино.")
            logger_bot.answer_callback_query(call.id, f"✅ Баланс {amt}₽ выдан")
            logger_bot.edit_message_text(f"✅ Баланс {amt}₽ выдан пользователю {uid}", call.message.chat.id, call.message.message_id, reply_markup=admin_kb())
        except:
            logger_bot.answer_callback_query(call.id, "❌ Не удалось отправить сообщение")
    
    elif call.data == "admin_spam":
        logger_bot.send_message(call.message.chat.id, "📢 отправь текст или фото для рассылки (получат все пользователи бота-продаж):")
        c.execute("INSERT OR REPLACE INTO admin_sessions VALUES (?, ?)", (ADMIN_ID, "spam"))
        conn.commit()
        logger_bot.delete_message(call.message.chat.id, call.message.message_id)
    
    elif call.data == "admin_promos":
        promos = get_all_promos()
        if not promos:
            text = "🎟 <b>промокоды</b>\n\nнет промокодов\n\nсоздать: /create_promo КОД СКИДКА ЛИМИТ"
        else:
            text = "🎟 <b>промокоды</b>\n\n"
            for code, disc, left in promos:
                text += f"▫️ {code} — {disc}% (осталось: {left})\n"
            text += "\nсоздать: /create_promo КОД СКИДКА ЛИМИТ"
        logger_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=admin_kb())

@logger_bot.message_handler(commands=['create_promo'])
def create_promo_cmd(m):
    if str(m.from_user.id) != ADMIN_ID:
        return
    parts = m.text.split()
    if len(parts) != 4:
        logger_bot.reply_to(m, "❌ формат: /create_promo КОД СКИДКА ЛИМИТ\nпример: /create_promo SUMMER10 10 100")
        return
    _, code, discount, limit = parts
    try:
        create_promo_code(code, int(discount), int(limit))
        logger_bot.reply_to(m, f"✅ промокод {code.upper()} создан! скидка {discount}%, {limit} использований")
    except:
        logger_bot.reply_to(m, "❌ ошибка")

@logger_bot.message_handler(func=lambda m: True, content_types=['text', 'photo'])
def admin_text(m):
    if str(m.from_user.id) != ADMIN_ID:
        return
    c.execute("SELECT step FROM admin_sessions WHERE user_id=?", (ADMIN_ID,))
    row = c.fetchone()
    if not row or row[0] != "spam":
        return
    
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    sent = 0
    failed = 0
    for (uid,) in users:
        try:
            if m.content_type == 'text':
                worker_bot.send_message(uid, m.text, parse_mode='HTML')
            elif m.content_type == 'photo':
                photo = m.photo[-1].file_id
                caption = m.caption if m.caption else ""
                worker_bot.send_photo(uid, photo, caption=caption, parse_mode='HTML')
            sent += 1
            time.sleep(0.05)
        except:
            failed += 1
    logger_bot.reply_to(m, f"✅ рассылка: {sent} отправлено, {failed} ошибок")
    c.execute("DELETE FROM admin_sessions WHERE user_id=?", (ADMIN_ID,))
    conn.commit()

# ========== ЗАПУСК ==========
def run_bot(bot_instance, name):
    while True:
        try:
            print(f"✅ {name} запущен")
            bot_instance.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            print(f"❌ {name}: {e}")
            time.sleep(5)

if __name__ == "__main__":
    set_current_bot(WORKER_BOT_TOKEN, "worker_bot")
    
    threading.Thread(target=monitor_bots, daemon=True).start()
    
    threading.Thread(target=run_bot, args=(main_bot, "основной"), daemon=True).start()
    threading.Thread(target=run_bot, args=(worker_bot, "рабочий"), daemon=True).start()
    threading.Thread(target=run_bot, args=(logger_bot, "логгер"), daemon=True).start()
    
    log_to_admin("🚀 все боты запущены")
    print("✅ все боты запущены")
    
    while True:
        time.sleep(1)