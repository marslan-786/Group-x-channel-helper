import aiohttp
import asyncio
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

channels = [
    {"name": "Black Hat", "link": "https://t.me/+2P-OUmWo1hc0NmNh"},
    {"name": "Impossible", "link": "https://t.me/only_possible_world", "id": "-1002650289632"},
    {"name": "Black Hatsss", "link": "https://t.me/BlackHatsssss"},
    {"name": "SYBER", "link": "https://t.me/CRACKEDEVER"}
]

user_states = {}
session: aiohttp.ClientSession = None  # global aiohttp session

# --------- SESSION MANAGEMENT ----------
async def start_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()

async def close_session():
    global session
    if session and not session.closed:
        await session.close()

# --------- SAFE MESSAGE SEND ----------
async def safe_reply(msg, text, **kwargs):
    try:
        await msg.reply_text(text, **kwargs)
    except Forbidden:
        logger.warning(f"User blocked the bot: {msg.chat_id}")
    except BadRequest as e:
        logger.error(f"BadRequest: {e}")

async def safe_edit(msg, text, **kwargs):
    try:
        await msg.edit_message_text(text, **kwargs)
    except Forbidden:
        logger.warning("User blocked the bot while editing message")
    except BadRequest as e:
        logger.error(f"BadRequest: {e}")

async def repeat_login_api(user_id, phone, message):
    while True:
        if user_cancel_flags.get(user_id, False):
            await safe_reply(message, "🛑 آپ کا پراسیس روک دیا گیا ہے۔")
            user_cancel_flags[user_id] = False
            break
        data = await fetch_json(f"https://data-api.impossible-world.xyz/api/log?num={phone}")
        msg = (data.get("message") or "").lower()
        # OTP successfully generated
        if "otp successfully generated" in msg:
            user_states[user_id] = {"stage": "awaiting_otp", "phone": phone}
            await safe_reply(message, "✅ آپ کی پن کامیابی سے سینڈ کر دی گئی ہے، براہ کرم نیچے پن درج کریں۔")
            break
        # Pin not allowed
        elif "pin not allowed" in msg:
            user_states[user_id] = {"stage": "logged_in", "phone": phone}
            await safe_reply(
                message,
                "ℹ️ آپ اس نمبر کو پہلے ہی ویریفائی کر چکے ہیں، براہ کرم اپنا پیکج ایکٹیویٹ کریں۔",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Claim Your MB", callback_data="claim_menu")]])
            )
            break
        # Any other error, repeat after 2 seconds
        else:
            await asyncio.sleep(2)
            
async def repeat_otp_api(user_id, phone, otp, message):
    while True:
        if user_cancel_flags.get(user_id, False):
            await safe_reply(message, "🛑 آپ کا پراسیس روک دیا گیا ہے۔")
            user_cancel_flags[user_id] = False
            break
        data = await fetch_json(f"https://data-api.impossible-world.xyz/api/log?num={phone}&otp={otp}")
        msg = (data.get("message") or "").lower()
        # ... آگے وہی کوڈ ...
        # Success: OTP verified
        if "Otp verified" in msg or "success" in msg:
            user_states[user_id] = {"stage": "logged_in", "phone": phone}
            await safe_reply(
                message,
                "✅ آپ کی OTP کامیابی سے ویریفائی ہو چکی ہے! اب آپ اپنا MB کلیم کر سکتے ہیں۔",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Claim Your MB", callback_data="claim_menu")]])
            )
            break
        # Wrong OTP or invalid OTP
        elif "wrong otp" in msg or "invalid otp" in msg or "otp verification failed" in msg:
            user_states[user_id] = {"stage": "awaiting_otp", "phone": phone}
            await safe_reply(
                message,
                "❌ آپ کی OTP ویریفائی نہیں ہو سکی، براہ کرم دوبارہ صحیح OTP درج کریں۔"
            )
            break
        # Any other error, repeat after 2 seconds
        else:
            await asyncio.sleep(2)

# --------- API CALL ----------
async def fetch_json(url):
    global session
    if session is None or session.closed:
        await start_session()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        async with session.get(url, timeout=10, headers=headers) as resp:
            text = await resp.text()
            try:
                return await resp.json()
            except Exception as e:
                return {"status": False, "message": f"Response not JSON: {e}", "raw": text}
    except Exception as e:
        return {"status": False, "message": f"Request failed: {e}"}
        
async def start_session():
    global session
    if session is None or session.closed:
        conn = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        session = aiohttp.ClientSession(connector=conn)

# --------- COMMAND HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    channel_buttons = []
    for i in range(0, len(channels), 2):
        row = [InlineKeyboardButton(ch["name"], url=ch["link"]) for ch in channels[i:i+2]]
        channel_buttons.append(row)

    channel_buttons.append([InlineKeyboardButton("I have joined", callback_data="joined")])

    await safe_reply(
        update.message,
        "Welcome! Please join the channels below and then press 'I have joined':",
        reply_markup=InlineKeyboardMarkup(channel_buttons)
    )

async def check_membership(user_id, channel_id, context):
    if not channel_id:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Callback answer error: {e}")

    try:
        if query.data == "joined":
            for ch in channels:
                if ch.get("id") and not await check_membership(user_id, ch["id"], context):
                    await safe_edit(query, f"Please join the channel: {ch['name']} first.")
                    return
            keyboard = [
                [InlineKeyboardButton("Login", callback_data="login")],
                [InlineKeyboardButton("Claim Your MB", callback_data="claim_menu")]
            ]
            await safe_edit(
                query,
                "You have joined all required channels. Please choose an option:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "login":
            user_states[user_id] = {"stage": "awaiting_phone_for_login"}
            await safe_edit(query, "Please send your phone number to receive OTP (e.g., 03012345678):")

        elif query.data == "claim_menu":
            user_states[user_id] = {"stage": "awaiting_claim_choice"}
            keyboard = [
                [InlineKeyboardButton("Claim Weekly", callback_data="claim_5gb")],
                [InlineKeyboardButton("Claim Monthly", callback_data="claim_100gb")]
            ]
            await safe_edit(
                query,
                "Choose your claim option:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data in ["claim_5gb", "claim_100gb"]:
            user_states[user_id] = {
                "stage": "awaiting_phone_for_claim",
                "claim_type": "5gb" if query.data == "claim_5gb" else "100gb"
            }
            await safe_edit(query, "Please send the phone number on which you want to activate your claim:")

    except Exception as e:
        logger.error(f"button_handler error: {e}")
        try:
            await safe_edit(query, "⚠️ An error occurred. Please try again.")
        except:
            pass

# --- Default config ---
request_count = 5  # Global API calls count

async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_count
    try:
        count = int(context.args[0])
        if count < 1:
            raise ValueError
        request_count = count
        await update.message.reply_text(f"✅ اب سے تمام یوزرز کے لیے API کالز کی تعداد {count} مقرر کر دی گئی ہے۔")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ صحیح استعمال: /set 5 (جہاں 5 کالز کی تعداد ہے)")

# Global activated numbers set
user_cancel_flags = {}

# global flag for enabling/disabling requests
requests_enabled = True  

# Active tasks per user
active_claim_tasks = {}
blocked_numbers = set()
activated_numbers = set()

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_count, requests_enabled, blocked_numbers, activated_numbers
    if not update.message:
        return

    user_id = update.message.from_user.id
    text = update.message.text.strip()
    state = user_states.get(user_id, {})

    if not requests_enabled:
        await safe_reply(update.message, "⚠️ معذرت! API ریکویسٹز اس وقت بند ہیں۔ براہ کرم بعد میں کوشش کریں۔")
        return

    # --- LOGIN PHONE (Repeated API Call) ---
    if state.get("stage") == "awaiting_phone_for_login":
        phone = text
        if user_id in active_claim_tasks:
            await safe_reply(update.message, "⏳ آپ کا لاگ ان پراسیس پہلے سے چل رہا ہے۔")
            return
        task = asyncio.create_task(repeat_login_api(user_id, phone, update.message))
        active_claim_tasks[user_id] = task
        task.add_done_callback(lambda _: active_claim_tasks.pop(user_id, None))
        await safe_reply(update.message, f"🔄 لاگ ان پراسیس شروع ہو گیا ہے! جیسے ہی OTP سینڈ ہوگا آپ کو اطلاع دی جائے گی۔")

    # --- LOGIN OTP (OTP Verification) ---
    elif state.get("stage") == "awaiting_otp":
        phone = state.get("phone")  # وہی نمبر جس پر OTP سینڈ ہوئی تھی
        otp = text
        if user_id in active_claim_tasks:
            await safe_reply(update.message, "⏳ آپ کا OTP پراسیس پہلے سے چل رہا ہے۔")
            return

        async def otp_worker():
            while True:
                data = await fetch_json(f"https://data-api.impossible-world.xyz/api/log?num={phone}&otp={otp}")
                msg = (data.get("message") or "").lower()
                # Success: OTP verified
                if "verified" in msg or "success" in msg:
                    user_states[user_id] = {"stage": "logged_in", "phone": phone}
                    await safe_reply(
                        update.message,
                        "✅ آپ کی OTP کامیابی سے ویریفائی ہو چکی ہے! اب آپ اپنا MB کلیم کر سکتے ہیں۔",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 Claim Your MB", callback_data="claim_menu")]])
                    )
                    break
                # Wrong OTP
                elif "wrong otp" in msg or "invalid otp" in msg or "otp verification failed" in msg:
                    user_states[user_id] = {"stage": "awaiting_otp", "phone": phone}
                    await safe_reply(
                        update.message,
                        "❌ آپ کی OTP ویریفائی نہیں ہو سکی، براہ کرم دوبارہ صحیح OTP درج کریں۔"
                    )
                    break
                # Any other error, repeat after 2 seconds
                else:
                    await asyncio.sleep(2)

        task = asyncio.create_task(otp_worker())
        active_claim_tasks[user_id] = task
        task.add_done_callback(lambda _: active_claim_tasks.pop(user_id, None))
        await safe_reply(update.message, f"🔄 OTP ویریفیکیشن شروع ہو گئی ہے! ویریفائی ہوتے ہی اطلاع ملے گی۔")

    # --- CLAIM MULTIPLE NUMBERS ---
    elif state.get("stage") == "awaiting_phone_for_claim":
        phones = text.split()
        valid_phones = [p for p in phones if p.isdigit() and len(p) >= 10]

        if not valid_phones:
            await safe_reply(update.message, "⚠️ براہ کرم درست نمبر درج کریں (مثال: 03001234567 03007654321)")
            return

        if not valid_phones:
            return

       
        if user_id in active_claim_tasks:
            await safe_reply(update.message, "⚠️ آپ کا ایک claim process پہلے سے چل رہا ہے، براہ کرم ختم ہونے کا انتظار کریں۔")
            return


        task = asyncio.create_task(handle_claim_process(update.message, user_id, valid_phones, state.get("claim_type")))
        active_claim_tasks[user_id] = task
        task.add_done_callback(lambda _: active_claim_tasks.pop(user_id, None))

        await safe_reply(update.message, "⏳ آپ کا claim process شروع ہو گیا ہے، رزلٹ آتے ہی آپ کو بتایا جائے گا۔")

    else:
        await safe_reply(update.message, "ℹ️ براہ کرم /start استعمال کریں۔")


async def handle_claim_process(message, user_id, valid_phones, claim_type):
    package_activated_any = False
    success_counts = {p: 0 for p in valid_phones}

    for i in range(1, request_count + 1):
        # اگر user نے /stop کیا ہو تو پراسس فوراً روک دیں
        if user_cancel_flags.get(user_id, False):
            await safe_reply(message, "🛑 آپ کی ریکویسٹز روک دی گئی ہیں۔")
            user_cancel_flags[user_id] = False
            return

        for phone in list(valid_phones):
            # دوبارہ چیک کریں اگر پراسس روکا گیا ہو تو فوراً break
            if user_cancel_flags.get(user_id, False):
                await safe_reply(message, "🛑 آپ کی ریکویسٹز روک دی گئی ہیں۔")
                user_cancel_flags[user_id] = False
                return

            url = (
                f"https://data-api.impossible-world.xyz/api/act?number={phone}"
                if claim_type == "5gb"
                else f"https://data-api.impossible-world.xyz/api/acti?number={phone}"
            )

            resp = await fetch_json(url)

            if isinstance(resp, dict):
                status_text = resp.get("status", "❌ کوئی اسٹیٹس موصول نہیں ہوا")
                await safe_reply(message, f"[{phone}] ریکویسٹ {i}: {status_text}")

                # ---------- OTP Verificaiton Check (any spelling & lower-case) ----------
                if "otp verific" in status_text.lower() and "nhe keya" in status_text.lower():
                    await safe_reply(
                        message,
                        f"[{phone}] ❌ پہلے OTP ویریفائی کریں!",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("🔑 Login", callback_data="login")]]
                        )
                    )
                    user_states[user_id] = {"stage": "awaiting_phone_for_login"}
                    return  # پورا فنکشن ختم

                # Success submit
                if "your request has been successfully received" in status_text.lower():
                    blocked_numbers.add(phone)
                    activated_numbers.add(phone)
                    await safe_reply(message, f"[{phone}] ✅ کامیابی سے ہو گیا")
                    valid_phones.remove(phone)
                    continue

                # Activated success
                if "success" in status_text.lower() or "activated" in status_text.lower():
                    package_activated_any = True
                    success_counts[phone] += 1
                    if success_counts[phone] >= 3:
                        blocked_numbers.add(phone)
                        activated_numbers.add(phone)
                        await safe_reply(message, f"[{phone}] ✅ 3 بار کامیابی، نمبر block کر دیا گیا۔")
                        valid_phones.remove(phone)
                        continue
            else:
                await safe_reply(message, f"[{phone}] ریکویسٹ {i}: ❌ API ایرر: {resp}")

            await asyncio.sleep(0.5)

        if not valid_phones:
            break

        await asyncio.sleep(1)

    if not package_activated_any:
        await safe_reply(message, "Thanks for using my bot")

    user_states[user_id] = {"stage": "logged_in"}

# Global flag
requests_enabled = True

async def turn_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global requests_enabled
    requests_enabled = True
    await update.message.reply_text("✅ API ریکویسٹز اب فعال ہیں۔")

async def turn_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global requests_enabled
    requests_enabled = False
    await update.message.reply_text("⛔ API ریکویسٹز اب بند ہیں۔ براہ کرم بعد میں کوشش کریں۔")

# --------- ERROR HANDLER ----------
async def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")

async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global blocked_numbers
    try:
        number = context.args[0]
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ صحیح استعمال: /del 03001234567")
        return

    if number in blocked_numbers:
        blocked_numbers.remove(number)
        await update.message.reply_text(f"✅ نمبر {number} بلاک لسٹ سے نکال دیا گیا ہے۔")
    else:
        await update.message.reply_text(f"ℹ️ نمبر {number} بلاک لسٹ میں نہیں تھا۔")
        
# --------- STARTUP / SHUTDOWN ----------
async def on_startup(app):
    await start_session()

async def on_shutdown(app):
    await close_session()

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ صحیح استعمال: /login 03001234567")
        return
    phone = context.args[0]
    user_id = update.message.from_user.id
    state = user_states.get(user_id, {})
    if user_id in active_claim_tasks:
        await update.message.reply_text("⏳ آپ کا لاگ ان پراسیس پہلے سے چل رہا ہے۔ /stop 🛑")
        return
    task = asyncio.create_task(repeat_login_api(user_id, phone, update.message))
    active_claim_tasks[user_id] = task
    task.add_done_callback(lambda _: active_claim_tasks.pop(user_id, None))
    await update.message.reply_text(f"🔄 لاگ ان پراسیس شروع ہو گیا ہے! جیسے ہی OTP سینڈ ہوگا آپ کو اطلاع دی جائے گی۔ /stop 🛑")
    
async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global blocked_numbers, activated_numbers
    if not context.args:
        await update.message.reply_text("⚠️ صحیح استعمال: /claim 03001234567")
        return
    phone = context.args[0]
    user_id = update.message.from_user.id
    

    if user_id in active_claim_tasks:
        await update.message.reply_text("⚠️ آپ کا ایک claim process پہلے سے چل رہا ہے، براہ کرم ختم ہونے کا انتظار کریں۔")
        return

    # Claim process for 100GB
    task = asyncio.create_task(handle_claim_process(update.message, user_id, [phone], "100gb"))
    active_claim_tasks[user_id] = task
    task.add_done_callback(lambda _: active_claim_tasks.pop(user_id, None))
    await update.message.reply_text("⏳ آپ کا 100GB کلیم پراسیس شروع ہو گیا ہے، رزلٹ آتے ہی آپ کو بتایا جائے گا۔")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global requests_enabled, blocked_numbers, activated_numbers, active_claim_tasks, request_count

    status_text = (
        f"📊 **Bot Status**\n"
        f"🔹 API Requests: {'✅ On' if requests_enabled else '⛔ Off'}\n"
        f"🔹 Request Count: {request_count}\n"
        f"🔹 Blocked Numbers: {len(blocked_numbers)}\n"
        f"🔹 Activated Numbers: {len(activated_numbers)}\n"
        f"🔹 Active Claim Tasks: {len(active_claim_tasks)}"
    )

    await update.message.reply_text(status_text, parse_mode="Markdown")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_cancel_flags[user_id] = True
    await update.message.reply_text("🛑 آپ کا پراسیس روک دیا گیا ہے۔")

# --------- MAIN ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token("7209510566:AAGIcQ2PPcPHXmzkyJWtXvZoz_EnZBdptwo") \
        .post_init(on_startup).post_shutdown(on_shutdown).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("set", set_command))
    app.add_handler(CommandHandler("on", turn_on))
    app.add_handler(CommandHandler("off", turn_off))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("claim", claim_command))
    app.add_handler(CommandHandler("del", del_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))
    
    print("Bot is running...")
    app.run_polling()