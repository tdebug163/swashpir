import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import string
import threading
from flask import Flask

# ================= إعدادات البوت ================= #
TOKEN = "8929101359:AAH0JYPCVRf66No2qIEP4o5_Yr8OEs0-XgI"
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown") # تفعيل الماركداون افتراضياً

ADMINS = [729501226, 936283959, 445421092]
LOG_CHANNEL = -1003840202910

# قفل لمنع التداخل (Race Condition) عند الضغط المتزامن
db_lock = threading.Lock()

# ================= إعدادات Flask ================= #
app = Flask(__name__)

@app.route('/')
def home():
    return "Whisper Bot is Running 100% 🚀"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ================= إعداد قاعدة البيانات ================= #
def init_db():
    with db_lock:
        conn = sqlite3.connect('whispers.db', check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS requests 
                     (req_id TEXT PRIMARY KEY, group_id INTEGER, sender_id INTEGER, receiver_id INTEGER, receiver_name TEXT)''')
        # تم إضافة prompt_msg_id لحفظ أيدي رسالة "اكتب همستك" لحذفها لاحقاً
        c.execute('''CREATE TABLE IF NOT EXISTS pending
                     (user_id INTEGER PRIMARY KEY, group_id INTEGER, target_id INTEGER, target_name TEXT, prompt_msg_id INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS whispers 
                     (wid TEXT PRIMARY KEY, group_id INTEGER, sender_id INTEGER, receiver_id INTEGER, text TEXT, sender_name TEXT, receiver_name TEXT)''')
        conn.commit()
        conn.close()

init_db()

def generate_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# تنظيف الأسماء من الرموز التي تعيق الماركداون
def clean_name(name):
    return str(name).replace('[', '').replace(']', '').replace('*', '').replace('_', '').replace('`', '')

def get_mention(name, user_id):
    return f"[{clean_name(name)}](tg://user?id={user_id})"

# ================= دوال التحكم بالقاعدة ================= #
def add_request(group_id, sender_id, receiver_id, receiver_name):
    req_id = generate_id()
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?)", (req_id, group_id, sender_id, receiver_id, receiver_name))
        conn.commit()
        conn.close()
    return req_id

def get_request(req_id):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("SELECT * FROM requests WHERE req_id=?", (req_id,))
        res = c.fetchone()
        conn.close()
    if res:
        return {"req_id": res[0], "group_id": res[1], "sender_id": res[2], "receiver_id": res[3], "receiver_name": res[4]}
    return None

def delete_request(req_id):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("DELETE FROM requests WHERE req_id=?", (req_id,))
        conn.commit()
        conn.close()

def set_pending(user_id, group_id, target_id, target_name, prompt_msg_id):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("REPLACE INTO pending VALUES (?, ?, ?, ?, ?)", (user_id, group_id, target_id, target_name, prompt_msg_id))
        conn.commit()
        conn.close()

def get_pending(user_id):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("SELECT * FROM pending WHERE user_id=?", (user_id,))
        res = c.fetchone()
        conn.close()
    if res:
        return {"user_id": res[0], "group_id": res[1], "target_id": res[2], "target_name": res[3], "prompt_msg_id": res[4]}
    return None

def delete_pending(user_id):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("DELETE FROM pending WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

def add_whisper(wid, group_id, sender_id, receiver_id, text, sender_name, receiver_name):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("INSERT INTO whispers VALUES (?, ?, ?, ?, ?, ?, ?)", (wid, group_id, sender_id, receiver_id, text, sender_name, receiver_name))
        conn.commit()
        conn.close()

def get_whisper(wid):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("SELECT * FROM whispers WHERE wid=?", (wid,))
        res = c.fetchone()
        conn.close()
    if res:
        return {"wid": res[0], "group_id": res[1], "sender_id": res[2], "receiver_id": res[3], "text": res[4], "sender_name": res[5], "receiver_name": res[6]}
    return None


# ================= 1. استدعاء الهمسة في القروب ================= #
@bot.message_handler(func=lambda m: m.text and m.text.strip() in ['ه', 'اهمس', 'همسه', 'همسة', 'همس'] and m.chat.type in ['group', 'supergroup'])
def group_whisper_trigger(message):
    if not message.reply_to_message:
        return
    
    sender = message.from_user
    receiver = message.reply_to_message.from_user
    
    if receiver.is_bot or sender.id == receiver.id:
        return

    req_id = add_request(message.chat.id, sender.id, receiver.id, receiver.first_name)
    bot_info = bot.get_me()
    deep_link = f"http://t.me/{bot_info.username}?start=req_{req_id}"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("اهمس هنا", url=deep_link, style="danger"))
    
    receiver_mention = get_mention(receiver.first_name, receiver.id)
    text = f"• تم تحديد الهمسه لـ ↤︎ {receiver_mention}\n• اضغط الزر لكتابة الهمسة \n-"
    
    bot.reply_to(message, text, reply_markup=markup, parse_mode="Markdown")


# ================= 2. دخول البوت لكتابة الهمسة (عبر الرابط المخفي) ================= #
@bot.message_handler(commands=['start'], func=lambda m: m.chat.type == 'private')
def start_whisper_deep_link(message):
    args = message.text.split()
    if len(args) > 1:
        payload = args[1]
        
        # [أ] رابط بدء همسة جديدة
        if payload.startswith("req_"):
            req_id = payload.split("req_")[1]
            req = get_request(req_id)
            
            if not req:
                bot.send_message(message.chat.id, "↢ هذه الهمسة قديمة او تم إرسالها مسبقاً.")
                return
            if message.from_user.id != req['sender_id']:
                bot.send_message(message.chat.id, "↢ انت لم تكتب اهمس بالقروب")
                return
            
            delete_request(req_id)
            receiver_mention = get_mention(req['receiver_name'], req['receiver_id'])
            msg = bot.send_message(message.chat.id, f"↢ اكتب همستك لـ {receiver_mention}  .", parse_mode="Markdown")
            # نحفظ الآيدي الخاص بالرسالة عشان نحذفها لما يرسل الهمسة
            set_pending(message.from_user.id, req['group_id'], req['receiver_id'], req['receiver_name'], msg.message_id)
            
        # [ب] رابط الرد على همسة موجودة
        elif payload.startswith("rep_"):
            wid = payload.split("rep_")[1]
            whisper = get_whisper(wid)
            
            if not whisper:
                bot.send_message(message.chat.id, "↢ الهمسة غير موجودة.")
                return
            if message.from_user.id != whisper['receiver_id']:
                bot.send_message(message.chat.id, "↢ هذه الهمسة لا تخصك للرد عليها.")
                return
            
            sender_mention = get_mention(whisper['sender_name'], whisper['sender_id'])
            msg = bot.send_message(message.chat.id, f"↢ اكتب همستك لـ {sender_mention}  .", parse_mode="Markdown")
            set_pending(message.from_user.id, whisper['group_id'], whisper['sender_id'], whisper['sender_name'], msg.message_id)


# ================= 3. استلام نص الهمسة وإرسالها ================= #
@bot.message_handler(content_types=['text'], func=lambda m: m.chat.type == 'private' and not m.text.startswith('/'))
def process_whisper_text(message):
    pending = get_pending(message.from_user.id)
    if not pending:
        return 
        
    # الخطوة الأولى: حذف رسالة الهمسة التي أرسلها المستخدم 
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
        
    # الخطوة الثانية: حذف رسالة "اكتب همستك لـ..."
    if pending['prompt_msg_id']:
        try:
            bot.delete_message(message.chat.id, pending['prompt_msg_id'])
        except:
            pass

    text = message.text
    sender = message.from_user
    wid = generate_id()
    
    add_whisper(wid, pending['group_id'], sender.id, pending['target_id'], text, sender.first_name, pending['target_name'])
    delete_pending(sender.id)
    
    target_mention = get_mention(pending['target_name'], pending['target_id'])
    sender_mention = get_mention(sender.first_name, sender.id)

    # إشعار المرسل
    bot.send_message(message.chat.id, f"تم ارسال همستك لـ {target_mention} بنجاح", parse_mode="Markdown")
    
    # نشر الهمسة في القروب
    bot_info = bot.get_me()
    reply_deep_link = f"http://t.me/{bot_info.username}?start=rep_{wid}"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("رؤيه الهمسة ✉️", callback_data=f"read_{wid}", style="primary"))
    markup.add(InlineKeyboardButton(f"اهمس لـ {clean_name(sender.first_name)}", url=reply_deep_link))
    
    group_text = f"↢ الهمسه لـ ↤︎ {target_mention}\n↢ من ↤︎ {sender_mention}\n-"
    bot.send_message(pending['group_id'], group_text, reply_markup=markup, parse_mode="Markdown")
    
    # سجل القناة
    log_text = (f"همسه جديده 🕵️✉️\n"
                f"المرسل \n: {sender_mention}\n"
                f"المستلم : {target_mention}\n"
                f":محتوى الهمسة\n{text}")
    try:
        bot.send_message(LOG_CHANNEL, log_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Log Error: {e}")


# ================= 4. قراءة الهمسة (نظام الحماية + الإشعارات) ================= #
@bot.callback_query_handler(func=lambda call: call.data.startswith("read_"))
def read_whisper_callback(call):
    wid = call.data.split("read_")[1]
    whisper = get_whisper(wid)
    
    if not whisper:
        bot.answer_callback_query(call.id, "● الهمسة غير موجودة أو تم حذفها.", show_alert=True)
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
        bot.answer_callback_query(call.id, "●الهمسة لا تخصك", show_alert=True)
        try: 
            intruder_mention = get_mention(call.from_user.first_name, call.from_user.id)
            bot.send_message(whisper['sender_id'], f"↢ محاولة قراءة الهمسة .. فاشلة \n↢ من قبل ↤ {intruder_mention}\n-", parse_mode="Markdown")
        except:
            pass
        return

    # الأدمن الشبح
    if is_admin and not is_sender and not is_receiver:
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        return

    # المرسل يقرأ
    if is_sender:
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        return

    # المستلم يقرأ
    if is_receiver:
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        try: 
            receiver_mention = get_mention(whisper['receiver_name'], whisper['receiver_id'])
            bot.send_message(whisper['sender_id'], f"↢ تمت قراءة الهمسة .. بنجاح \n↢ من قبل ↤ {receiver_mention}\n-", parse_mode="Markdown")
        except:
            pass
        return


# ================= تشغيل البوت مع Flask ================= #
if __name__ == "__main__":
    # تشغيل خادم Flask في مسار فرعي
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("Bot is running...")
    # تشغيل البوت الأساسي
    bot.infinity_polling(skip_pending=True)