import os
import json
import time
import html
from telebot import TeleBot, types

# ===== CONFIG =====
BOT_TOKEN = "8592629897:AAESh8E6b5z_Q-u8yEwW4bsIYsYGRvamc9I"
ADMIN_IDS = [5801456438]
DATA_FILE = "data.json"

GROUP_LINK = "https://t.me/OtpRush"   # used for 💬 OTP GROUP button
CHANNEL_LINK = "https://t.me/mailtwist"    # Official channel

# ===== Initialize Bot =====
bot = TeleBot(BOT_TOKEN)

# ===== Global Data =====
country_numbers = {}
user_numbers = {}
used_numbers_global = {}

# ===== Persistence =====
def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'country_numbers': country_numbers,
                'user_numbers': {
                    str(uid): {c: list(nums) for c, nums in cn.items()}
                    for uid, cn in user_numbers.items()
                },
                'used_numbers_global': {
                    c: list(nums) for c, nums in used_numbers_global.items()
                }
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'⚠️ Save error: {e}')

def load_data():
    global country_numbers, user_numbers, used_numbers_global
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                country_numbers = data.get('country_numbers', {})
                used_numbers_global = {
                    c: set(nums)
                    for c, nums in data.get('used_numbers_global', {}).items()
                }
                user_numbers = {
                    int(uid): {c: set(nums) for c, nums in cn.items()}
                    for uid, cn in data.get('user_numbers', {}).items()
                }
        except Exception as e:
            print(f'⚠️ Corrupt data file: {e}, resetting...')
            country_numbers, user_numbers, used_numbers_global = {}, {}, {}
            save_data()

# ===== Utils =====
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_new_number(user_id, country):
    available = [
        n for n in country_numbers.get(country, [])
        if n not in used_numbers_global.get(country, set())
    ]
    if not available:
        return None
    num = available[0]
    used_numbers_global.setdefault(country, set()).add(num)
    user_numbers.setdefault(user_id, {}).setdefault(country, set()).add(num)
    country_numbers[country].remove(num)
    save_data()
    return num

# ===== Keyboards =====
def main_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if is_admin(user_id):
        markup.add('📤 𝗨𝗽𝗹𝗼𝗮𝗱 𝗡𝘂𝗺𝗯𝗲𝗿𝘀', '📊 𝗣𝗮𝗻𝗲𝗹 𝗦𝘁𝗮𝘁𝘂𝘀')
        markup.add('♻️ 𝗥𝗲𝘀𝗲𝘁 𝗔𝗹𝗹 𝗗𝗮𝘁𝗮', '🗑 𝗗𝗲𝗹𝗲𝘁𝗲 𝗖𝗼𝘂𝗻𝘁𝗿𝘆 𝗗𝗮𝘁𝗮')
    markup.add('📞 𝗚𝗲𝘁 𝗡𝘂𝗺𝗯𝗲𝗿')
    return markup

def get_country_inline():
    markup = types.InlineKeyboardMarkup(row_width=2)
    for country in country_numbers.keys():
        markup.add(
            types.InlineKeyboardButton(country, callback_data=f'select_country|{country}')
        )
    return markup

def get_country_delete_inline():
    markup = types.InlineKeyboardMarkup(row_width=2)
    for country in country_numbers.keys():
        markup.add(
            types.InlineKeyboardButton(country, callback_data=f'delete_country|{country}')
        )
    return markup

# ===== Start =====
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id

    # Main panel
    bot.send_message(
        message.chat.id,
        "【 𝗜𝗟𝗬 𝗢𝗧𝗣 𝗕𝗢𝗧 】\n\n"
        "→ 𝗦𝗲𝗹𝗲𝗰𝘁 𝗮𝗻 𝗼𝗽𝘁𝗶𝗼𝗻 𝗳𝗿𝗼𝗺 𝘁𝗵𝗲 𝗺𝗲𝗻𝘂 𝗯𝗲𝗹𝗼𝘄 👇",
        reply_markup=main_keyboard(user_id)
    )

    # Only official channel button (Support Group removed)
    info_markup = types.InlineKeyboardMarkup()
    info_markup.add(
        types.InlineKeyboardButton('📢 𝗢𝗳𝗳𝗶𝗰𝗶𝗮𝗹 𝗖𝗵𝗮𝗻𝗻𝗲𝗹', url=CHANNEL_LINK),
    )
    bot.send_message(
        message.chat.id,
        "ℹ️ 𝗙𝗼𝗿 𝘂𝗽𝗱𝗮𝘁𝗲𝘀, 𝘂𝘀𝗲 𝘁𝗵𝗲 𝗯𝘂𝘁𝘁𝗼𝗻 𝗯𝗲𝗹𝗼𝘄:",
        reply_markup=info_markup
    )

# ===== Number Distribution =====
def send_number_edit(user_id, chat_id, message_id, country):
    num = get_new_number(user_id, country)
    if num is None:
        text = (
            f"❌ 𝗡𝗼 𝗺𝗼𝗿𝗲 𝗮𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗳𝗼𝗿 {country}.\n"
            "⏳ 𝗣𝗹𝗲𝗮𝘀𝗲 𝘄𝗮𝗶𝘁 𝗳𝗼𝗿 𝗮𝗱𝗺𝗶𝗻 𝘁𝗼 𝘂𝗽𝗹𝗼𝗮𝗱 𝗻𝗲𝘄 𝗻𝘂𝗺𝗯𝗲𝗿𝘀."
        )
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except:
            bot.send_message(chat_id, text)
        return

    num_safe = html.escape(num)

    # Inline buttons (your original order)
    markup = types.InlineKeyboardMarkup()
    # 1) OTP GROUP (top)
    markup.row(
        types.InlineKeyboardButton("💬 OTP GROUP", url=GROUP_LINK)
    )
    # 2) Change Number
    markup.row(
        types.InlineKeyboardButton("🔁 Change Number", callback_data=f"change_num|{country}")
    )
    # 3) Change Country
    markup.row(
        types.InlineKeyboardButton("♻️ Change Country", callback_data="change_country")
    )

    # Number Block with code format for easy copying
    text = (
        f"🌍 𝗖𝗼𝘂𝗻𝘁𝗿𝘆: <b>{country}</b>\n\n"
        "──────────  Number  ──────────\n"
        f"           <code>{num_safe}</code>\n"
        "──────────────────────────────\n\n"
        "⌛ 𝗪𝗮𝗶𝘁𝗶𝗻𝗴 𝗳𝗼𝗿 𝗢𝗧𝗣... 🔐\n\n"
        "💡 𝗧𝗮𝗽 𝗼𝗻 𝘁𝗵𝗲 𝗻𝘂𝗺𝗯𝗲𝗿 𝘁𝗼 𝗰𝗼𝗽𝘆"
    )

    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode='HTML',
            reply_markup=markup
        )
    except:
        bot.send_message(
            chat_id,
            text,
            parse_mode='HTML',
            reply_markup=markup
        )

# ===== Button Handlers =====
@bot.message_handler(func=lambda msg: True)
def handle_buttons(message):
    user_id = message.from_user.id
    text = message.text

    # ===== Admin Panel =====
    if text == '📤 𝗨𝗽𝗹𝗼𝗮𝗱 𝗡𝘂𝗺𝗯𝗲𝗿𝘀' and is_admin(user_id):
        msg = bot.send_message(
            message.chat.id,
            "🌍 𝗘𝗻𝘁𝗲𝗿 𝗖𝗢𝗨𝗡𝗧𝗥𝗬 𝗡𝗔𝗠𝗘 (𝗲.𝗴. 𝗨𝗦𝗔, 𝗜𝗡𝗗𝗜𝗔, 𝗨𝗞):"
        )
        bot.register_next_step_handler(msg, ask_country_name)

    elif text == '📊 𝗣𝗮𝗻𝗲𝗹 𝗦𝘁𝗮𝘁𝘂𝘀' and is_admin(user_id):
        total_users = len(user_numbers)
        active_countries = {
            c for c in list(country_numbers.keys()) + list(used_numbers_global.keys())
            if (c in country_numbers and country_numbers[c])
            or (c in used_numbers_global and used_numbers_global[c])
        }
        if not active_countries:
            bot.send_message(message.chat.id, "📭 𝗡𝗼 𝗰𝗼𝘂𝗻𝘁𝗿𝘆 𝗱𝗮𝘁𝗮 𝗳𝗼𝘂𝗻𝗱.")
            return

        status = (
            "📊 【 𝗜𝗟𝗬 𝗢𝗧𝗣 𝗣𝗔𝗡𝗘𝗟 𝗦𝗧𝗔𝗧𝗨𝗦 】\n\n"
            f"👤 𝗧𝗼𝘁𝗮𝗹 𝗨𝘀𝗲𝗿𝘀: {total_users}\n"
            f"🌎 𝗔𝗰𝘁𝗶𝘃𝗲 𝗖𝗼𝘂𝗻𝘁𝗿𝗶𝗲𝘀: {len(active_countries)}\n\n"
        )

        for country in active_countries:
            added = len(country_numbers.get(country, [])) + len(used_numbers_global.get(country, []))
            used = len(used_numbers_global.get(country, []))
            remaining = len(country_numbers.get(country, []))
            status += (
                f"🌍 {country}\n"
                f"📥 𝗧𝗼𝘁𝗮𝗹 𝗔𝗱𝗱𝗲𝗱: {added}\n"
                f"✅ 𝗨𝘀𝗲𝗱: {used}\n"
                f"🕓 𝗥𝗲𝗺𝗮𝗶𝗻𝗶𝗻𝗴: {remaining}\n\n"
            )

        bot.send_message(message.chat.id, status)

    elif text == '♻️ 𝗥𝗲𝘀𝗲𝘁 𝗔𝗹𝗹 𝗗𝗮𝘁𝗮' and is_admin(user_id):
        country_numbers.clear()
        used_numbers_global.clear()
        user_numbers.clear()
        save_data()
        bot.send_message(message.chat.id, "♻️ 𝗔𝗹𝗹 𝗱𝗮𝘁𝗮 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝗰𝗹𝗲𝗮𝗿𝗲𝗱 𝘀𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆.")

    elif text == '🗑 𝗗𝗲𝗹𝗲𝘁𝗲 𝗖𝗼𝘂𝗻𝘁𝗿𝘆 𝗗𝗮𝘁𝗮' and is_admin(user_id):
        if not country_numbers:
            bot.send_message(
                message.chat.id,
                "📭 𝗡𝗼 𝗰𝗼𝘂𝗻𝘁𝗿𝘆 𝗹𝗶𝘀𝘁 𝗳𝗼𝘂𝗻𝗱. 𝗣𝗹𝗲𝗮𝘀𝗲 𝘂𝗽𝗹𝗼𝗮𝗱 𝘀𝗼𝗺𝗲 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗳𝗶𝗿??𝘁."
            )
            return
        bot.send_message(
            message.chat.id,
            "🗑 𝗦𝗲𝗹𝗲𝗰𝘁 𝘁𝗵𝗲 𝗰𝗼𝘂𝗻𝘁𝗿𝘆 𝘆𝗼𝘂 𝘄𝗮𝗻𝘁 𝘁𝗼 𝗱𝗲𝗹𝗲𝘁𝗲 𝗮𝗹𝗹 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗳𝗼𝗿:",
            reply_markup=get_country_delete_inline()
        )

    # ===== User Side =====
    elif text == '📞 𝗚𝗲𝘁 𝗡𝘂𝗺𝗯𝗲𝗿':
        if not country_numbers:
            bot.send_message(
                message.chat.id,
                "📭 𝗡𝗼 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗮𝗿𝗲 𝗮𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲 𝗿𝗶𝗴𝗵𝘁 𝗻𝗼𝘄.\n"
                "⏳ 𝗣𝗹𝗲𝗮𝘀𝗲 𝘁𝗿𝘆 𝗮𝗴𝗮𝗶𝗻 𝗹𝗮𝘁𝗲𝗿."
            )
            return
        bot.send_message(
            message.chat.id,
            "🌍 𝗦𝗲𝗹𝗲𝗰𝘁 𝗮 𝗰𝗼𝘂𝗻𝘁𝗿𝘆 𝘁𝗼 𝗴𝗲𝘁 𝗮 𝗻𝘂𝗺𝗯𝗲𝗿:",
            reply_markup=get_country_inline()
        )

# ===== Upload Flow =====
def ask_country_name(message):
    country = message.text.strip()
    msg = bot.send_message(
        message.chat.id,
        f"✅ 𝗖𝗼𝘂𝗻𝘁𝗿𝘆 𝘀𝗲𝘁 𝘁𝗼: <b>{country}</b>\n\n"
        "📤 𝗡𝗼𝘄 𝘀𝗲𝗻𝗱 𝗻𝘂𝗺𝗯𝗲𝗿𝘀:\n"
        "• 𝗣𝗮𝘀𝘁𝗲 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝘀𝗲𝗽𝗮𝗿𝗮𝘁𝗲𝗱 𝗯𝘆 𝗰𝗼𝗺𝗺𝗮𝘀 (,)\n"
        "• 𝗢𝗿 𝘂𝗽𝗹𝗼𝗮𝗱 𝗮 .𝘁𝘅𝘁 𝗳𝗶𝗹𝗲 (𝗼𝗻𝗲 𝗻𝘂𝗺𝗯𝗲𝗿 𝗽𝗲𝗿 𝗹𝗶𝗻𝗲)",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, lambda m: process_numbers(m, country))

def process_numbers(message, country):
    try:
        numbers = []
        if message.text:
            text_data = message.text.replace('\n', ',')
            numbers = [n.strip() for n in text_data.split(',') if n.strip()]
        elif message.document:
            file_info = bot.get_file(message.document.file_id)
            file_content = bot.download_file(file_info.file_path).decode(
                'utf-8', errors='ignore'
            )
            file_content = file_content.replace('\n', ',')
            numbers = [n.strip() for n in file_content.split(',') if n.strip()]

        if not numbers:
            bot.send_message(
                message.chat.id,
                "❌ 𝗡𝗼 𝘃𝗮𝗹𝗶𝗱 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗱𝗲𝘁𝗲𝗰𝘁𝗲𝗱. 𝗣𝗹𝗲𝗮𝘀𝗲 𝘁𝗿𝘆 𝗮𝗴𝗮𝗶𝗻."
            )
            return

        country_numbers.setdefault(country, []).extend(numbers)
        save_data()
        bot.send_message(
            message.chat.id,
            f"✅ 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗮𝗱𝗱𝗲𝗱 <b>{len(numbers)}</b> 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗳𝗼𝗿 <b>{country}</b> ✅",
            parse_mode='HTML'
        )
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"⚠️ 𝗘𝗿𝗿𝗼𝗿 𝘄𝗵𝗶𝗹𝗲 𝗽𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝗻𝘂𝗺𝗯𝗲𝗿𝘀: {e}"
        )

# ===== Inline Callbacks =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data.startswith('select_country|'):
            _, country = call.data.split('|', 1)
            send_number_edit(
                call.from_user.id,
                call.message.chat.id,
                call.message.message_id,
                country
            )

        elif call.data.startswith('change_num|'):
            _, country = call.data.split('|', 1)
            send_number_edit(
                call.from_user.id,
                call.message.chat.id,
                call.message.message_id,
                country
            )

        elif call.data == 'change_country':
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="🌍 𝗦𝗲𝗹𝗲𝗰𝘁 𝗮 𝗰𝗼𝘂𝗻𝘁𝗿𝘆:",
                reply_markup=get_country_inline()
            )

        elif call.data.startswith('delete_country|') and is_admin(call.from_user.id):
            _, country = call.data.split('|', 1)
            country_numbers.pop(country, None)
            used_numbers_global.pop(country, None)
            save_data()
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🗑 𝗔𝗹𝗹 𝗻𝘂𝗺𝗯𝗲𝗿𝘀 𝗳𝗼𝗿 {country} 𝗵𝗮𝘃𝗲 𝗯𝗲𝗲𝗻 𝗱𝗲𝗹𝗲𝘁𝗲𝗱."
            )
    except Exception as e:
        print(f"⚠️ Callback error: {e}")

# ===== Main Loop =====
load_data()
print("🚀 Bot started")

while True:
    try:
        bot.polling(non_stop=True, interval=1, timeout=60)
    except Exception as e:
        print(f"⚠️ Bot crashed: {e}")
        time.sleep(5)
