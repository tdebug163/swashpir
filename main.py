import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import string
import threading

# ================= إعدادات البوت ================= #
TOKEN = "8929101359:AAH0JYPCVRf66No2qIEP4o5_Yr8OEs0-XgI"
bot = telebot.TeleBot(TOKEN, parse_mode=None)

ADMINS = [729501226, 936283959, 445421092]
LOG_CHANNEL = -1003840202910

# قفل لمنع التداخل (Race Condition) عند الضغط المتزامن
db_lock = threading.Lock()

# ================= إعداد قاعدة البيانات ================= #
def init_db():
    with db_lock:
        conn = sqlite3.connect('whispers.db', check_same_thread=False)
        c = conn.cursor()
        # جدول للهمسات التي لم تُكتب بعد (بين القروب وخاص البوت)
        c.execute('''CREATE TABLE IF NOT EXISTS requests 
                     (req_id TEXT PRIMARY KEY, group_id INTEGER, sender_id INTEGER, receiver_id INTEGER, receiver_name TEXT)''')
        # جدول لحالة المستخدم في خاص البوت (بانتظار كتابة الهمسة)
        c.execute('''CREATE TABLE IF NOT EXISTS pending
                     (user_id INTEGER PRIMARY KEY, group_id INTEGER, target_id INTEGER, target_name TEXT)''')
        # جدول لحفظ الهمسات المكتملة
        c.execute('''CREATE TABLE IF NOT EXISTS whispers 
                     (wid TEXT PRIMARY KEY, group_id INTEGER, sender_id INTEGER, receiver_id INTEGER, text TEXT, sender_name TEXT, receiver_name TEXT)''')
        conn.commit()
        conn.close()

init_db()

def generate_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ================= دوال التحكم بالقاعدة (محمية بالكامل) ================= #
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

def set_pending(user_id, group_id, target_id, target_name):
    with db_lock:
        conn = sqlite3.connect('whispers.db')
        c = conn.cursor()
        c.execute("REPLACE INTO pending VALUES (?, ?, ?, ?)", (user_id, group_id, target_id, target_name))
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
        return {"user_id": res[0], "group_id": res[1], "target_id": res[2], "target_name": res[3]}
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
    
    # منع الهمس للبوت أو لنفس الشخص
    if receiver.is_bot or sender.id == receiver.id:
        return

    req_id = add_request(message.chat.id, sender.id, receiver.id, receiver.first_name)
    bot_info = bot.get_me()
    deep_link = f"http://t.me/{bot_info.username}?start=req_{req_id}"
    
    markup = InlineKeyboardMarkup()
    # زر أحمر (ميزة Bot API 9.4 من عام 2026)
    markup.add(InlineKeyboardButton("اهمس هنا ↗️", url=deep_link, style="danger"))
    
    text = f"• تم تحديد الهمسه لـ ↤︎ {receiver.first_name}\n• اضغط الزر لكتابة الهمسة \n-"
    bot.reply_to(message, text, reply_markup=markup)


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
                # إذا حاول المتطفل ضغط الزر من القروب
                bot.send_message(message.chat.id, "↢ انت لم تكتب اهمس بالقروب")
                return
            
            set_pending(message.from_user.id, req['group_id'], req['receiver_id'], req['receiver_name'])
            delete_request(req_id) # يتم حذف الطلب لضمان عدم استخدامه مرة أخرى
            bot.send_message(message.chat.id, f"↢ اكتب همستك لـ {req['receiver_name']}  .")
            
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
            
            # في حالة الرد، نعكس الأدوار: المستلم يصبح مرسل
            set_pending(message.from_user.id, whisper['group_id'], whisper['sender_id'], whisper['sender_name'])
            bot.send_message(message.chat.id, f"↢ اكتب همستك لـ {whisper['sender_name']}  .")


# ================= 3. استلام نص الهمسة وإرسالها للقروب ================= #
@bot.message_handler(content_types=['text'], func=lambda m: m.chat.type == 'private' and not m.text.startswith('/'))
def process_whisper_text(message):
    pending = get_pending(message.from_user.id)
    if not pending:
        return # يتجاهل أي رسالة في الخاص إذا لم يكن هناك همسة معلقة
        
    try:
        bot.delete_message(message.chat.id, message.message_id) # حذف الهمسة من الشات للمرسل
    except:
        pass

    text = message.text
    sender = message.from_user
    wid = generate_id()
    
    # حفظ الهمسة بآمان
    add_whisper(wid, pending['group_id'], sender.id, pending['target_id'], text, sender.first_name, pending['target_name'])
    delete_pending(sender.id)
    
    # إشعار المرسل بنجاح العملية
    bot.send_message(message.chat.id, f"تم ارسال همستك لـ {pending['target_name']} بنجاح")
    
    # نشر الهمسة في القروب
    bot_info = bot.get_me()
    reply_deep_link = f"http://t.me/{bot_info.username}?start=rep_{wid}"
    
    markup = InlineKeyboardMarkup()
    # زر أزرق للرؤية (primary) وزر طبيعي للرد (بدون style)
    markup.add(InlineKeyboardButton("رؤيه الهمسة ✉️", callback_data=f"read_{wid}", style="primary"))
    markup.add(InlineKeyboardButton(f"اهمس لـ {sender.first_name}", url=reply_deep_link))
    
    group_text = f"↢ الهمسه لـ ↤︎ {pending['target_name']}\n↢ من ↤︎ {sender.first_name}\n-"
    bot.send_message(pending['group_id'], group_text, reply_markup=markup)
    
    # إرسال سجل للقناة بشكل آمن عن طريق الـ HTML لمنع تداخل أخطاء الماركداون
    sender_mention = f'<a href="tg://user?id={sender.id}">{escape_html(sender.first_name)}</a>'
    receiver_mention = f'<a href="tg://user?id={pending["target_id"]}">{escape_html(pending["target_name"])}</a>'
    
    log_text = (f"همسه جديده 🕵️✉️\n"
                f"المرسل \n: {sender_mention}\n"
                f"المستلم : {receiver_mention}\n"
                f":محتوى الهمسة\n{escape_html(text)}")
    try:
        bot.send_message(LOG_CHANNEL, log_text, parse_mode="HTML")
    except Exception as e:
        print(f"Log Error: {e}")


# ================= 4. قراءة الهمسة (نظام الحماية + الشبح) ================= #
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
    
    # قص النص لو كان طويل لتفادي خطأ حد التنبيه لتيليجرام (200 حرف)
    w_text = whisper['text']
    if len(w_text) > 170:
        w_text = w_text[:167] + "..."
    alert_text = f"{w_text}\n * الصفحة 📄 1 / 1"

    # --- حالة 1: شخص غريب (متطفل) يحاول القراءة --- #
    if not is_sender and not is_receiver and not is_admin:
        bot.answer_callback_query(call.id, "●الهمسة لا تخصك", show_alert=True)
        try: # إرسال تنبيه للمرسل مع كل ضغطة للمتطفل!
            bot.send_message(whisper['sender_id'], f"↢ محاولة قراءة الهمسة .. فاشلة \n↢ من قبل ↤ {call.from_user.first_name}\n-")
        except:
            pass
        return

    # --- حالة 2: أدمن (شبح) يقرأ الهمسة --- #
    # إذا كان أدمن ولكنه ليس مرسل أو مستقبل الهمسة (لن يصدر أي تنبيه لأي شخص)
    if is_admin and not is_sender and not is_receiver:
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        return

    # --- حالة 3: المرسل يقرأ همسته --- #
    if is_sender:
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        return

    # --- حالة 4: المستلم يقرأ الهمسة --- #
    if is_receiver:
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        try: # إرسال التنبيه للمرسل مع كل ضغطة يقرأها المستلم!
            bot.send_message(whisper['sender_id'], f"↢ تمت قراءة الهمسة .. بنجاح \n↢ من قبل ↤ {whisper['receiver_name']}\n-")
        except:
            pass
        return


# ================= تشغيل البوت ================= #
if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)
