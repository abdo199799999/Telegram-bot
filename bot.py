import os
import requests
import time
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- إعدادات أساسية ---
URLSCAN_API_KEY = os.getenv("URLSCAN_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
URLSCAN_API_URL = "https://urlscan.io/api/v1"

# --- دالات مساعدة للتفاعل مع urlscan.io API ---

def submit_scan_request(domain: str):
    """يقوم بإرسال طلب فحص جديد إلى urlscan.io"""
    headers = {"API-Key": URLSCAN_API_KEY, "Content-Type": "application/json"}
    data = {"url": domain, "visibility": "public"}
    try:
        response = requests.post(f"{URLSCAN_API_URL}/scan/", headers=headers, json=data)
        response.raise_for_status()  # يطلق استثناءً لأكواد الخطأ (4xx, 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error submitting scan: {e}")
        return None

def get_scan_results(scan_uuid: str):
    """ينتظر ويجلب نتائج الفحص عند اكتماله"""
    result_url = f"{URLSCAN_API_URL}/result/{scan_uuid}/"
    try:
        # الانتظار قليلاً قبل طلب النتائج
        time.sleep(15) # قد تحتاج لزيادة هذا الوقت
        
        response = requests.get(result_url)
        # إذا لم تكن النتيجة جاهزة، سيعود الخطأ 404
        retries = 5
        while response.status_code == 404 and retries > 0:
            print("Result not ready, waiting...")
            time.sleep(10)
            response = requests.get(result_url)
            retries -= 1

        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting results: {e}")
        return None

# --- أوامر البوت ---

def start_command(update: Update, context: CallbackContext):
    """يعرض رسالة الترحيب والأوامر المتاحة"""
    welcome_message = """
👋 أهلاً بك في بوت الفحص المتقدم!

استخدم الأوامر التالية:
🔹 `/scan domain.com` - للبحث عن النطاقات الفرعية.
🔹 `/info domain.com` - لعرض معلومات أساسية عن الموقع.
🔹 `/screenshot domain.com` - للحصول على لقطة شاشة للموقع.
    """
    update.message.reply_text(welcome_message)

def scan_command(update: Update, context: CallbackContext):
    """يبحث عن النطاقات الفرعية"""
    if not context.args:
        update.message.reply_text("⚠️ يرجى إدخال النطاق بعد الأمر. مثال: `/scan example.com`")
        return

    domain = context.args[0]
    sent_message = update.message.reply_text(f"🔍 جاري البحث عن النطاقات الفرعية لـ `{domain}`... يرجى الانتظار.", parse_mode=ParseMode.MARKDOWN)

    scan_submission = submit_scan_request(domain)
    if not scan_submission or "uuid" not in scan_submission:
        sent_message.edit_text("❌ حدث خطأ أثناء إرسال طلب الفحص. قد يكون مفتاح API غير صالح أو أن الخدمة لا تعمل.")
        return

    results = get_scan_results(scan_submission["uuid"])
    if not results or "lists" not in results or "subdomains" not in results["lists"]:
        sent_message.edit_text(f"لم أتمكن من العثور على نتائج لـ `{domain}`.")
        return

    subdomains = results["lists"]["subdomains"]
    if not subdomains:
        sent_message.edit_text(f"✅ لم يتم العثور على نطاقات فرعية لـ `{domain}`.")
        return

    # تنسيق الرسالة
    response_text = f"✅ تم العثور على *{len(subdomains)}* نطاق فرعي لـ `{domain}`:\n\n"
    response_text += "\n".join([f"`{sub}`" for sub in subdomains])
    
    # إرسال النتائج في رسائل متعددة إذا كانت طويلة جداً
    if len(response_text) > 4096:
        sent_message.edit_text(f"✅ تم العثور على *{len(subdomains)}* نطاق فرعي. النتائج كثيرة جداً للعرض المباشر.")
        # يمكنك هنا التفكير في إرسالها كملف
    else:
        sent_message.edit_text(response_text, parse_mode=ParseMode.MARKDOWN)


def info_command(update: Update, context: CallbackContext):
    """يعرض معلومات أساسية عن الموقع"""
    if not context.args:
        update.message.reply_text("⚠️ يرجى إدخال النطاق بعد الأمر. مثال: `/info example.com`")
        return

    domain = context.args[0]
    sent_message = update.message.reply_text(f"ℹ️ جاري جلب المعلومات عن `{domain}`...", parse_mode=ParseMode.MARKDOWN)

    scan_submission = submit_scan_request(domain)
    if not scan_submission or "uuid" not in scan_submission:
        sent_message.edit_text("❌ حدث خطأ أثناء إرسال طلب الفحص.")
        return

    results = get_scan_results(scan_submission["uuid"])
    if not results or "page" not in results:
        sent_message.edit_text(f"لم أتمكن من العثور على معلومات لـ `{domain}`.")
        return

    page_info = results.get("page", {})
    info_text = f"""
*معلومات أساسية عن {domain}:*

*IP Address:* `{page_info.get('ip', 'N/A')}`
*Country:* `{page_info.get('country', 'N/A')}`
*Server:* `{page_info.get('server', 'N/A')}`
*ASN:* `{page_info.get('asn', 'N/A')}`
*ASN Name:* `{page_info.get('asnname', 'N/A')}`
    """
    sent_message.edit_text(info_text, parse_mode=ParseMode.MARKDOWN)


def screenshot_command(update: Update, context: CallbackContext):
    """يرسل لقطة شاشة للموقع"""
    if not context.args:
        update.message.reply_text("⚠️ يرجى إدخال النطاق بعد الأمر. مثال: `/screenshot example.com`")
        return

    domain = context.args[0]
    sent_message = update.message.reply_text(f"📸 جاري أخذ لقطة شاشة لـ `{domain}`...", parse_mode=ParseMode.MARKDOWN)

    scan_submission = submit_scan_request(domain)
    if not scan_submission or "uuid" not in scan_submission:
        sent_message.edit_text("❌ حدث خطأ أثناء إرسال طلب الفحص.")
        return

    results = get_scan_results(scan_submission["uuid"])
    if not results or "screenshot" not in results:
        sent_message.edit_text(f"لم أتمكن من الحصول على لقطة شاشة لـ `{domain}`.")
        return

    screenshot_url = results["screenshot"]
    update.message.reply_photo(photo=screenshot_url, caption=f"لقطة شاشة لـ {domain}")
    sent_message.delete() # حذف رسالة الانتظار


def main():
    """الدالة الرئيسية لتشغيل البوت"""
    if not TELEGRAM_TOKEN or not URLSCAN_API_KEY:
        print("خطأ: يرجى تعيين متغيرات البيئة TELEGRAM_TOKEN و URLSCAN_API_KEY.")
        return

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # إضافة الأوامر
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("scan", scan_command))
    dp.add_handler(CommandHandler("info", info_command))
    dp.add_handler(CommandHandler("screenshot", screenshot_command))

    # بدء تشغيل البوت
    updater.start_polling()
    print("Bot is running...")
    updater.idle()

if __name__ == '__main__':
    main()

