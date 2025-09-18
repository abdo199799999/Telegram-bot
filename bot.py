import requests
import logging
import asyncio
import os
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import BadRequest

# --- الإعدادات ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
URLSCAN_API_KEY = os.environ.get("URLSCAN_API_KEY")
GROUP_ID = -1002000171927
GROUP_USERNAME = "fastNetAbdo"

# --- تحميل ملفات الترجمة ---
try:
    with open('ar.json', 'r', encoding='utf-8') as f:
        ar_lang = json.load(f)
    with open('en.json', 'r', encoding='utf-8') as f:
        en_lang = json.load(f)
    translations = {'ar': ar_lang, 'en': en_lang}
except FileNotFoundError:
    logging.error("Language files (ar.json or en.json) not found!")
    translations = {}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- دالة الترجمة ---
def t(key: str, lang_code: str, **kwargs) -> str:
    # الافتراضي إلى الإنجليزية إذا كانت اللغة غير مدعومة أو الملفات غير موجودة
    lang = 'ar' if lang_code == 'ar' else 'en'
    text = translations.get(lang, {}).get(key, f"Translation key '{key}' not found.")
    return text.format(**kwargs)

# --- دالة التحقق من الاشتراك ---
async def is_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

# --- دالة البحث العامة ---
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
                await asyncio.sleep(60)
                continue
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            if not results: break
            for result in results:
                page_domain = result.get("page", {}).get("domain")
                if page_domain: domains.add(page_domain)
            if data.get("has_more"):
                search_after = results[-1]["sort"]
                await asyncio.sleep(1)
            else: break
        return sorted(list(domains))
    except Exception as e:
        logger.error(f"urlscan.io error: {e}", exc_info=True)
        return None

# --- الأوامر ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = update.effective_user.language_code
    if await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('welcome', lang))
    else:
        await update.message.reply_text(t('join_group', lang, group_username=GROUP_USERNAME))

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = update.effective_user.language_code
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('join_group', lang, group_username=GROUP_USERNAME))
        return
    if not context.args:
        await update.message.reply_text(t('specify_domain', lang))
        return
    
    target = context.args[0]
    await update.message.reply_text(t('searching_domain', lang, target=target))
    results = await search_urlscan_async(f"page.domain:{target}")
    target_info = t('target_info_domain', lang, target=target)
    await process_and_send_results(update, context, results, target_info, target, 'no_results_domain')

async def asn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = update.effective_user.language_code
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('join_group', lang, group_username=GROUP_USERNAME))
        return
    if not context.args:
        await update.message.reply_text(t('specify_asn', lang))
        return
    
    target = context.args[0].upper()
    if not target.startswith("AS"): target = "AS" + target
    
    await update.message.reply_text(t('searching_asn', lang, target=target))
    results = await search_urlscan_async(f"asn:{target}")
    target_info = t('target_info_asn', lang, target=target)
    await process_and_send_results(update, context, results, target_info, target, 'no_results_asn')

# --- دالة مساعدة لإرسال النتائج ---
async def process_and_send_results(update: Update, context: ContextTypes.DEFAULT_TYPE, results: list[str] | None, target_info: str, target: str, no_results_key: str):
    lang = update.effective_user.language_code
    if results is None:
        await update.message.reply_text(t('error_searching', lang))
    elif not results:
        await update.message.reply_text(t(no_results_key, lang, target=target))
    else:

        count = len(results)
        results_text = t('found_results', lang, count=count, target_info=target_info)
        message_body = "\n".join(results)
        
        if len(results_text + message_body) > 4096:
            await update.message.reply_text(t('too_many_results', lang, count=count))
            with open("results.txt", "w") as f: f.write(message_body)
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open("results.txt", "rb"), filename=f"results_{target}.txt")
        else:
            await update.message.reply_text(results_text + message_body)

def main() -> None:
    if not all([TELEGRAM_BOT_TOKEN, URLSCAN_API_KEY, translations]):
        logging.critical("CRITICAL: Bot cannot start due to missing config or language files.")
        return
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("asn", asn_command))
    
    logger.info("Bot is starting on the cloud with multi-language support...")
    application.run_polling()

if __name__ == "__main__":
    main()

