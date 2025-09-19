import os
import requests
import time
import logging
import asyncio
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

# --- دوال مساعدة للتفاعل مع urlscan.io API ---

async def search_urlscan_list_async(query: str) -> list[str] | None:
    headers = {"API-Key": URLSCAN_API_KEY}
    domains = set()
    search_after = None
    try:
        while True:
            params = {"q": query, "size": 1000}
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
        logger.error(f"An unexpected error occurred with urlscan.io search: {e}", exc_info=True)
        return None

async def get_single_scan_results_async(domain: str) -> dict | None:
    headers = {"API-Key": URLSCAN_API_KEY, "Content-Type": "application/json"}
    data = {"url": domain, "visibility": "public"}
    try:
        submit_response = await asyncio.to_thread(requests.post, "https://urlscan.io/api/v1/scan/", headers=headers, json=data)
        submit_response.raise_for_status()
        scan_data = submit_response.json()
        
        if "uuid" not in scan_data:
            return None

        result_url = scan_data.get("api")
        
        await asyncio.sleep(15)
        retries = 5
        while retries > 0:
            result_response = await asyncio.to_thread(requests.get, result_url)
            if result_response.status_code == 200:
                return result_response.json()
            
            logger.info(f"Result for {domain} not ready, waiting...")
            await asyncio.sleep(10)
            retries -= 1
            
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred in get_single_scan_results_async: {e}", exc_info=True)
        return None

# --- دالة التحقق من الاشتراك ---
async def is_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except BadRequest:
        logger.error(f"Error checking membership. Is the bot an admin in chat {GROUP_ID}?")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred in is_user_in_group: {e}")
        return False

# --- الأوامر ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(
            "أهلاً بك! أنا بوت البحث المتقدم.\n\n"
            "استخدم الأوامر التالية:\n"
            "🔹 `/scan domain.com` للبحث عن النطاقات الفرعية.\n"
            "🔹 `/asn AS15169` للبحث عن النطاقات المرتبطة برقم ASN.\n"
            "🔹 `/info domain.com` لعرض معلومات أساسية عن الموقع.\n"
            "🔹 `/screenshot domain.com` للحصول على لقطة شاشة للموقع."
        )
    else:
        await update.message.reply_text(
            f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً لاستخدام البوت.\n"
            f"رابط المجموعة: https://t.me/{GROUP_USERNAME}"
        )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً.\nرابط المجموعة: https://t.me/{GROUP_USERNAME}")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم النطاق. مثال: /scan google.com")
        return
    
    domain_to_scan = context.args[0]
    await update.message.reply_text(f"🔍 جاري البحث الدقيق عن نطاقات {domain_to_scan}...")
    
    results = await search_urlscan_list_async(f"page.domain:{domain_to_scan}")
    await process_and_send_results(update, context, results, f"للنطاق {domain_to_scan}")

async def asn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً.\nرابط المجموعة: https://t.me/{GROUP_USERNAME}")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد رقم ASN. مثال: /asn AS15169")
        return
    
    asn_to_scan = context.args[0].upper()
    if not asn_to_scan.startswith("AS"):
        asn_to_scan = "AS" + asn_to_scan

    await update.message.reply_text(f"🔍 جاري البحث عن النطاقات المرتبطة بـ {asn_to_scan}...")
    results = await search_urlscan_list_async(f"asn:{asn_to_scan}")
    await process_and_send_results(update, context, results, f"للرقم {asn_to_scan}")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً.\nرابط المجموعة: https://t.me/{GROUP_USERNAME}")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم النطاق. مثال: /info google.com")
        return
    
    domain = context.args[0]
    sent_message = await update.message.reply_text(f"ℹ️ جاري جلب المعلومات عن {domain}...")
    
    results = await get_single_scan_results_async(domain)
    
    if not results or "page" not in results:
        await sent_message.edit_text(f"لم أتمكن من العثور على معلومات لـ {domain}.")
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
    await sent_message.edit_text(info_text, parse_mode='Markdown')

async def screenshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(f"عذراً، يجب عليك الانضمام إلى المجموعة أولاً.\nرابط المجموعة: https://t.me/{GROUP_USERNAME}")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم النطاق. مثال: /screenshot google.com")
        return
    
    domain = context.args[0]
    sent_message = await update.message.reply_text(f"📸 جاري أخذ لقطة شاشة لـ {domain}...")
    
    results = await get_single_scan_results_async(domain)
    
    if not results or "screenshot" not in results:
        await sent_message.edit_text(f"لم أتمكن من الحصول على لقطة شاشة لـ {domain}.")
        return

    screenshot_url = results["screenshot"]
    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=screenshot_url, caption=f"لقطة شاشة لـ {domain}")
    await sent_message.delete()

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
            file_path = "results.txt"
            with open(file_path, "w") as f:
                f.write(message_body)
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open(file_path, "rb"), filename=f"results_{target_info.replace(' ', '_')}.txt")
            os.remove(file_path)
        else:
            await update.message.reply_text(results_text + message_body)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("asn", asn_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("screenshot", screenshot_command))
    
    logger.info("Bot is starting on the cloud...")
    application.run_polling()

if __name__ == "__main__":
    main()

