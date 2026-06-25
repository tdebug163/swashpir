import sqlite3
import random
import string
import asyncio
import aiohttp
from pyrogram import Client, filters

# ================= إعدادات البوت ================= #
API_ID = 28797361
API_HASH = "771041b32e83ab232e066b7adeee700b"
BOT_TOKEN = "8929101359:AAHA4pDryGlKK2-uV_vgG7lSnae27P21usA"

ADMINS = [729501226, 936283959, 445421092]
LOG_CHANNEL = -1003840202910

app_bot = Client(
    "whisper_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

db_lock = asyncio.Lock()

# ================= دالة سريعة لإرسال الأزرار الملونة (Raw API) ================= #
async def send_colored_keyboard(chat_id, text, inline_keyboard, reply_to_msg_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": inline_keyboard
        }
    }
    if reply_to_msg_id:
        payload["reply_to_message_id"] = reply_to_msg_id

    # إرسال الطلب بشكل Async لضمان عدم تعليق البوت
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

# ================= إعداد قاعدة البيانات ================= #
def init_db():
    conn = sqlite3.connect('whispers.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS requests 
                 (req_id TEXT PRIMARY KEY, group_id INTEGER, sender_id INTEGER, receiver_id INTEGER, receiver_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending
                 (user_id INTEGER PRIMARY KEY, group_id INTEGER, target_id INTEGER, target_name TEXT, prompt_msg_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS whispers 
                 (wid TEXT PRIMARY KEY, group_id INTEGER, sender_id INTEGER, receiver_id INTEGER, text TEXT, sender_name TEXT, receiver_name TEXT)''')
    conn.commit()
    conn.close()

init_db()

def generate_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def clean_name(name):
    if not name: return "مستخدم"
    return str(name).replace('[', '').replace(']', '').replace('*', '').replace('_', '').replace('`', '')

def get_mention(name, user_id):
    return f"[{clean_name(name)}](tg://user?id={user_id})"

# ================= دوال التحكم بالقاعدة (Async) ================= #
async def add_request(group_id, sender_id, receiver_id, receiver_name):
    req_id = generate_id()
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)", (req_id, group_id, sender_id, receiver_id, receiver_name))
        conn.commit()
        conn.close()
    return req_id

async def get_request(req_id):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("SELECT * FROM requests WHERE req_id=?", (req_id,))
        res = c.fetchone()
        conn.close()
    if res:
        return {"req_id": res[0], "group_id": res[1], "sender_id": res[2], "receiver_id": res[3], "receiver_name": res[4]}
    return None

async def delete_request(req_id):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("DELETE FROM requests WHERE req_id=?", (req_id,))
        conn.commit()
        conn.close()

async def set_pending(user_id, group_id, target_id, target_name, prompt_msg_id):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("REPLACE INTO pending VALUES (?, ?, ?, ?, ?)", (user_id, group_id, target_id, target_name, prompt_msg_id))
        conn.commit()
        conn.close()

async def get_pending(user_id):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("SELECT * FROM pending WHERE user_id=?", (user_id,))
        res = c.fetchone()
        conn.close()
    if res:
        return {"user_id": res[0], "group_id": res[1], "target_id": res[2], "target_name": res[3], "prompt_msg_id": res[4]}
    return None

async def delete_pending(user_id):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("DELETE FROM pending WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

async def add_whisper(wid, group_id, sender_id, receiver_id, text, sender_name, receiver_name):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("INSERT INTO whispers VALUES (?, ?, ?, ?, ?, ?, ?)", (wid, group_id, sender_id, receiver_id, text, sender_name, receiver_name))
        conn.commit()
        conn.close()

async def get_whisper(wid):
    async with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("SELECT * FROM whispers WHERE wid=?", (wid,))
        res = c.fetchone()
        conn.close()
    if res:
        return {"wid": res[0], "group_id": res[1], "sender_id": res[2], "receiver_id": res[3], "text": res[4], "sender_name": res[5], "receiver_name": res[6]}
    return None


# ================= 1. استدعاء الهمسة في القروب ================= #
async def whisper_filter(_, __, message):
    text = message.text.strip() if message.text else ""
    return bool(text in ['ه', 'اهمس', 'همسه', 'همسة', 'همس'])
whisper_cmd = filters.create(whisper_filter)

@app_bot.on_message(filters.group & whisper_cmd & filters.reply)
async def group_whisper_trigger(client, message):
    sender = message.from_user
    receiver = message.reply_to_message.from_user

    if not receiver or receiver.is_bot or sender.id == receiver.id:
        return

    req_id = await add_request(message.chat.id, sender.id, receiver.id, receiver.first_name)
    bot_info = await client.get_me()
    deep_link = f"http://t.me/{bot_info.username}?start=req_{req_id}"

    receiver_mention = get_mention(receiver.first_name, receiver.id)
    text = f"• تم تحديد الهمسه لـ ↤︎ {receiver_mention}\n• اضغط الزر لكتابة الهمسة \n-"

    # بناء الزر الملون للطلب المباشر (Raw API) باللون الأحمر (danger)
    inline_keyboard = [
        [{"text": "اهمس هنا", "url": deep_link, "style": "danger"}]
    ]

    # إرسال الرسالة عبر دالة الألوان المخصصة
    await send_colored_keyboard(message.chat.id, text, inline_keyboard, message.id)


# ================= 2. دخول البوت لكتابة الهمسة (عبر الرابط المخفي) ================= #
@app_bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    if len(message.command) > 1:
        payload = message.command[1]

        # [أ] بدء همسة جديدة
        if payload.startswith("req_"):
            req_id = payload.split("req_")[1]
            req = await get_request(req_id)

            if not req:
                await message.reply_text("↢ هذه الهمسة قديمة او تم إرسالها مسبقاً.")
                return
            if message.from_user.id != req['sender_id']:
                await message.reply_text("↢ انت لم تكتب اهمس بالقروب")
                return

            await delete_request(req_id)
            receiver_mention = get_mention(req['receiver_name'], req['receiver_id'])
            msg = await message.reply_text(f"↢ اكتب همستك لـ {receiver_mention}  .")

            await set_pending(message.from_user.id, req['group_id'], req['receiver_id'], req['receiver_name'], msg.id)

        # [ب] الرد على همسة موجودة
        elif payload.startswith("rep_"):
            wid = payload.split("rep_")[1]
            whisper = await get_whisper(wid)

            if not whisper:
                await message.reply_text("↢ الهمسة غير موجودة.")
                return
            if message.from_user.id != whisper['receiver_id']:
                await message.reply_text("↢ هذه الهمسة لا تخصك للرد عليها.")
                return

            sender_mention = get_mention(whisper['sender_name'], whisper['sender_id'])
            msg = await message.reply_text(f"↢ اكتب همستك لـ {sender_mention}  .")
            await set_pending(message.from_user.id, whisper['group_id'], whisper['sender_id'], whisper['sender_name'], msg.id)


# ================= 3. استلام نص الهمسة وإرسالها ================= #
@app_bot.on_message(filters.private & filters.text & ~filters.command("start"))
async def process_whisper_text(client, message):
    pending = await get_pending(message.from_user.id)
    if not pending:
        return 

    try:
        await message.delete()
    except:
        pass

    if pending['prompt_msg_id']:
        try:
            await client.delete_messages(message.chat.id, pending['prompt_msg_id'])
        except:
            pass

    text = message.text
    sender = message.from_user
    wid = generate_id()

    await add_whisper(wid, pending['group_id'], sender.id, pending['target_id'], text, sender.first_name, pending['target_name'])
    await delete_pending(sender.id)

    target_mention = get_mention(pending['target_name'], pending['target_id'])
    sender_mention = get_mention(sender.first_name, sender.id)

    await message.reply_text(f"تم ارسال همستك لـ {target_mention} بنجاح")

    bot_info = await client.get_me()
    reply_deep_link = f"http://t.me/{bot_info.username}?start=rep_{wid}"

    group_text = f"↢ الهمسه لـ ↤︎ {target_mention}\n↢ من ↤︎ {sender_mention}\n-"

    # بناء الأزرار الملونة (Raw API) للقروب
    inline_keyboard = [
        [{"text": "رؤيه الهمسة ✉️", "callback_data": f"read_{wid}", "style": "primary"}],
        [{"text": f"اهمس لـ {clean_name(sender.first_name)}", "url": reply_deep_link}]
    ]

    # الإرسال للقروب باستخدام الدالة الملونة
    await send_colored_keyboard(pending['group_id'], group_text, inline_keyboard)

    # ================= التعديل هنا للقناة =================
    # جلب معلومات المستلم للحصول على اليوزر الخاص به
    target_username_str = "لا يوجد"
    try:
        t_user = await client.get_users(pending['target_id'])
        if t_user.username:
            target_username_str = f"@{t_user.username}"
    except:
        pass

    sender_username_str = f"@{sender.username}" if sender.username else "لا يوجد"
    
    sender_name_str = sender.first_name if sender.first_name else "بدون اسم"
    target_name_str = pending['target_name'] if pending['target_name'] else "بدون اسم"

    # رسالة القناة بصيغة نص عادي (Plain Text) لضمان عدم فشل الإرسال نهائياً
    log_text = (f"همسه جديده 🕵️✉️\n\n"
                f"يوزر المرسل : {sender_username_str}\n"
                f"اسم المرسل : {sender_name_str}\n\n"
                f"يوزر المستلم : {target_username_str}\n"
                f"اسم المستلم : {target_name_str}\n\n"
                f":محتوى الهمسة\n"
                f"{text}")
    
    try:
        # إرسال الرسالة للقناة بدون أي ParseMode 
        await client.send_message(
            chat_id=LOG_CHANNEL, 
            text=log_text, 
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Error Log: {e}")


# ================= 4. قراءة الهمسة (نظام الحماية) ================= #
# هنا نستخدم Pyrogram بشكل طبيعي لأن الرد المنبثق (Alert) لا يحتاج ألوان
@app_bot.on_callback_query(filters.regex(r"^read_"))
async def read_whisper_callback(client, call):
    wid = call.data.split("read_")[1]
    whisper = await get_whisper(wid)

    if not whisper:
        await call.answer("● الهمسة غير موجودة أو تم حذفها.", show_alert=True)
        return

    user_id = call.from_user.id
    is_sender = (user_id == whisper['sender_id'])
    is_receiver = (user_id == whisper['receiver_id'])
    is_admin = (user_id in ADMINS)

    w_text = whisper['text']
    if len(w_text) > 170:
        w_text = w_text[:167] + "..."
    alert_text = f"{w_text}\n * الصفحة 📄 1 / 1"

    # المتطفل
    if not is_sender and not is_receiver and not is_admin:
        await call.answer("●الهمسة لا تخصك", show_alert=True)
        try: 
            intruder_mention = get_mention(call.from_user.first_name, call.from_user.id)
            await client.send_message(whisper['sender_id'], f"↢ محاولة قراءة الهمسة .. فاشلة \n↢ من قبل ↤ {intruder_mention}\n-", disable_web_page_preview=True)
        except:
            pass
        return

    # الأدمن الشبح
    if is_admin and not is_sender and not is_receiver:
        await call.answer(alert_text, show_alert=True)
        return

    # المرسل يقرأ
    if is_sender:
        await call.answer(alert_text, show_alert=True)
        return

    # المستلم يقرأ
    if is_receiver:
        await call.answer(alert_text, show_alert=True)
        try: 
            receiver_mention = get_mention(whisper['receiver_name'], whisper['receiver_id'])
            await client.send_message(whisper['sender_id'], f"↢ تمت قراءة الهمسة .. بنجاح \n↢ من قبل ↤ {receiver_mention}\n-", disable_web_page_preview=True)
        except:
            pass
        return


# ================= التشغيل ================= #
if __name__ == "__main__":
    print("Starting Pyrogram Whisper Bot with Custom Colors! 🚀...")
    app_bot.run()