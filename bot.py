import requests
import logging
import asyncio
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.error import BadRequest

# --- الإعدادات ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
URLSCAN_API_KEY = os.environ.get("URLSCAN_API_KEY")
# --- معرف المجموعة المطلوب الاشتراك بها ---
GROUP_ID = -1002000171927  # <-- تم إضافة معرف المجموعة هنا
GROUP_USERNAME = "fastNetAbdo" # <-- اسم مستخدم المجموعة للرابط

# --- التحقق من وجود المفاتيح ---
if not TELEGRAM_BOT_TOKEN or not URLSCAN_API_KEY:
    logging.error("ERROR: Missing environment variables")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- دالة التحقق من الاشتراك ---
async def is_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        # التحقق مما إذا كان المستخدم عضواً، وليس مغادراً أو محظوراً
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except BadRequest:
        # يحدث هذا إذا كان البوت ليس مشرفاً في المجموعة أو المعرف خاطئ
        logger.error(f"Error checking membership. Is the bot an admin in chat {GROUP_ID}?")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred in is_user_in_group: {e}")
        return False

# --- الأوامر ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if await is_user_in_group(user_id, context):
        await update.message.reply_text(
            "أهلاً بك! أنا بوت البحث عن النطاقات الفرعية.\n"
            "استخدم الأمر /scan متبوعاً باسم النطاق للبدء."
        )
    else:
        await update.message.reply_text(
            f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً لاستخدام البوت.\n"
            f"رابط المجموعة: https://t.me/{GROUP_USERNAME}"
        )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    # --- التحقق من الاشتراك قبل تنفيذ الأمر ---
    if not await is_user_in_group(user_id, context):
        await update.message.reply_text(
            f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً لاستخدام هذا الأمر.\n"
            f"رابط المجموعة: https://t.me/{GROUP_USERNAME}"
        )
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم النطاق. مثال: /scan google.com")
        return
    
    domain_to_scan = context.args[0]
    await update.message.reply_text(f"🔍 جاري البحث الدقيق عن نطاقات {domain_to_scan}... قد يستغرق هذا بعض الوقت.")
    
    subdomains = await find_subdomains_paginated_async(domain_to_scan)
    
    if subdomains is None:
        await update.message.reply_text("حدث خطأ أثناء البحث.")
    elif not subdomains:
        await update.message.reply_text(f"لم يتم العثور على أي نطاقات فرعية لـ {domain_to_scan}.")
    else:
        results_text = f"✅ تم العثور على {len(subdomains)} نطاق فرعي لـ {domain_to_scan}:\n\n"
        message_body = "\n".join(subdomains)
        
        if len(results_text + message_body) > 4096:
            await update.message.reply_text(f"النتائج كثيرة جداً ({len(subdomains)} نطاق)، سيتم إرسالها في ملف.")
            with open("subdomains.txt", "w") as f:
                f.write(message_body)
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open("subdomains.txt", "rb"), filename=f"{domain_to_scan}_subdomains.txt")
        else:
            await update.message.reply_text(results_text + message_body)

async def find_subdomains_paginated_async(domain: str) -> list[str] | None:
    # (هذه الدالة تبقى كما هي، لم يتم تغييرها)
    headers = {"API-Key": URLSCAN_API_KEY}
    subdomains = set()
    search_after = None
    try:
        while True:
            params = {"q": f"page.domain:{domain}", "size": 10000}
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
        logger.error(f"An unexpected error occurred with urlscan.io: {e}", exc_info=True)
        return None

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    logger.info("Bot is starting on the cloud...")
    application.run_polling()

if __name__ == "__main__":
    main()

