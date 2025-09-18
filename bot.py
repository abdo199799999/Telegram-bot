import requests
import logging
import asyncio
import os  # <-- تم إضافة هذا السطر
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- الإعدادات (تقرأ الآن من متغيرات البيئة) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
URLSCAN_API_KEY = os.environ.get("URLSCAN_API_KEY")

# --- التحقق من وجود المفاتيح ---
if not TELEGRAM_BOT_TOKEN or not URLSCAN_API_KEY:
    logging.error("ERROR: Missing environment variables (TELEGRAM_BOT_TOKEN or URLSCAN_API_KEY)")
    # في بيئة الإنتاج، قد ترغب في الخروج من البرنامج إذا كانت المفاتيح غير موجودة
    # exit()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def find_subdomains_paginated_async(domain: str) -> list[str] | None:
    headers = {"API-Key": URLSCAN_API_KEY}
    subdomains = set()
    search_after = None
    try:
        while True:
            params = {"q": f"domain:{domain}", "size": 10000}
            if search_after:
                params["search_after"] = f"{search_after[0]},{search_after[1]}"
            response = await asyncio.to_thread(requests.get, "https://urlscan.io/api/v1/search/", params=params, headers=headers)
            if response.status_code == 429:
                logger.warning("Rate limit hit. Waiting for 60 seconds.")
                await asyncio.sleep(60)
                continue
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            if not results:
                break
            for result in results:
                page_domain = result.get("page", {}).get("domain")
                if page_domain and page_domain.endswith(domain):
                    subdomains.add(page_domain)
            if data.get("has_more"):
                search_after = results[-1]["sort"]
                await asyncio.sleep(1)
            else:
                break
        return sorted(list(subdomains))
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "أهلاً بك! أنا بوت البحث الشامل (مستضاف على السحابة).\n"
        "استخدم الأمر /scan متبوعاً باسم النطاق للبدء."
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم النطاق. مثال: /scan google.com")
        return
    domain_to_scan = context.args[0]
    await update.message.reply_text(f"🔍 جاري البحث عن نطاقات {domain_to_scan}... قد يستغرق هذا بعض الوقت.")
    subdomains = await find_subdomains_paginated_async(domain_to_scan)
    if subdomains is None:
        await update.message.reply_text("حدث خطأ أثناء الاتصال بخدمة urlscan.io. تأكد من صحة مفتاح الـ API.")
    elif not subdomains:
        await update.message.reply_text(f"لم يتم العثور على أي نطاقات فرعية لـ {domain_to_scan}.")
    else:
        results_text = f"✅ تم العثور على {len(subdomains)} نطاق فرعي لـ {domain_to_scan}:\\n\\n"
        message_body = "\\n".join(subdomains)
        if len(results_text + message_body) > 4096:
            await update.message.reply_text(f"النتائج كثيرة جداً ({len(subdomains)} نطاق)، سيتم إرسالها في ملف.")
            with open("subdomains.txt", "w") as f:
                f.write(message_body)
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open("subdomains.txt", "rb"), filename=f"{domain_to_scan}_subdomains.txt")
        else:
            await update.message.reply_text(results_text + message_body)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    logger.info("Bot is starting on the cloud...")
    application.run_polling()

if __name__ == "__main__":
    main()

