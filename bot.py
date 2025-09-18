import requests
import logging
import asyncio
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import BadRequest

# --- الإعدادات ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
URLSCAN_API_KEY = os.environ.get("URLSCAN_API_KEY")
GROUP_ID = -1002000171927
GROUP_USERNAME = "fastNetAbdo"

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
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except BadRequest:
        logger.error(f"Error checking membership. Is the bot an admin in chat {GROUP_ID}?")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred in is_user_in_group: {e}")
        return False

# --- دالة البحث العامة (تم تعديلها لتقبل نوع البحث) ---
async def search_urlscan_async(query: str) -> list[str] | None:
    headers = {"API-Key": URLSCAN_API_KEY}
    domains = set()
    search_after = None
    try:
        while True:
            params = {"q": query, "size": 10000}
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
                if page_domain:
                    domains.add(page_domain)
            
            if data.get("has_more"):
                search_after = results[-1]["sort"]
                await asyncio.sleep(1)
            else:
                break
        return sorted(list(domains))
    except Exception as e:
        logger.error(f"An unexpected error occurred with urlscan.io: {e}", exc_info=True)
        return None

# --- الأوامر ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if await is_user_in_group(user_id, context):
        await update.message.reply_text(
            "أهلاً بك! أنا بوت البحث المتقدم.\n\n"
            "استخدم الأوامر التالية:\n"
            "🔹 `/scan domain.com` للبحث عن النطاقات الفرعية.\n"
            "🔹 `/asn AS15169` للبحث عن النطاقات المرتبطة برقم ASN."
        )
    else:
        await update.message.reply_text(
            f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً لاستخدام البوت.\n"
            f"رابط المجموعة: https://t.me/{GROUP_USERNAME}"
        )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not await is_user_in_group(user_id, context):
        await update.message.reply_text(f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً.\nرابط المجموعة: https://t.me/{GROUP_USERNAME}")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم النطاق. مثال: /scan google.com")
        return
    
    domain_to_scan = context.args[0]
    await update.message.reply_text(f"🔍 جاري البحث الدقيق عن نطاقات {domain_to_scan}...")
    
    # استخدام الدالة العامة مع الاستعلام الصحيح
    results = await search_urlscan_async(f"page.domain:{domain_to_scan}")
    
    await process_and_send_results(update, context, results, f"للنطاق {domain_to_scan}")

# --- الأمر الجديد: البحث بـ ASN ---
async def asn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not await is_user_in_group(user_id, context):
        await update.message.reply_text(f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً.\nرابط المجموعة: https://t.me/{GROUP_USERNAME}")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد رقم ASN. مثال: /asn AS15169")
        return
    
    asn_to_scan = context.args[0]
    # التأكد من أن الإدخال يبدأ بـ AS (اختياري ولكن جيد)
    if not asn_to_scan.upper().startswith("AS"):
        asn_to_scan = "AS" + asn_to_scan

    await update.message.reply_text(f"🔍 جاري البحث عن النطاقات المرتبطة بـ {asn_to_scan.upper()}...")
    
    # استخدام الدالة العامة مع استعلام ASN
    results = await search_urlscan_async(f"asn:{asn_to_scan.upper()}")
    
    await process_and_send_results(update, context, results, f"للرقم {asn_to_scan.upper()}")

# --- دالة مساعدة لإرسال النتائج (لمنع تكرار الكود) ---
async def process_and_send_results(update: Update, context: ContextTypes.DEFAULT_TYPE, results: list[str] | None, target_info: str):
    if results is None:
        await update.message.reply_text("حدث خطأ أثناء البحث.")
    elif not results:
        await update.message.reply_text(f"لم يتم العثور على أي نطاقات {target_info}.")
    else:
        results_text = f"✅ تم العثور على {len(results)} نطاق {target_info}:\n\n"
        message_body = "\n".join(results)
        
        if len(results_text + message_body) > 4096:
            await update.message.reply_text(f"النتائج كثيرة جداً ({len(results)} نطاق)، سيتم إرسالها في ملف.")
            with open("results.txt", "w") as f:
                f.write(message_body)
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open("results.txt", "rb"), filename=f"results_{target_info.replace(' ', '_')}.txt")
        else:
            await update.message.reply_text(results_text + message_body)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # إضافة الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("asn", asn_command)) # <-- إضافة الأمر الجديد هنا
    
    logger.info("Bot is starting on the cloud...")
    application.run_polling()

if __name__ == "__main__":
    main()

