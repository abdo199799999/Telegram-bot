import requests
import logging
import asyncio
import os
import json
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

# --- الإعدادات ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
URLSCAN_API_KEY = os.environ.get("URLSCAN_API_KEY")
GROUP_ID = -1002000171927
GROUP_USERNAME = "fastNetAbdo"
DEVELOPER_CHAT_ID = 5653624044

# --- تحميل ملفات الترجمة ---
try:
    with open('ar.json', 'r', encoding='utf-8') as f: ar_lang = json.load(f)
    with open('en.json', 'r', encoding='utf-8') as f: en_lang = json.load(f)
    translations = {'ar': ar_lang, 'en': en_lang}
except FileNotFoundError:
    logging.error("Language files not found!")
    translations = {}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- معالج الأخطاء العالمي ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    error_message = (f"An exception was raised:\n<pre>{tb_string}</pre>")
    await context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=error_message, parse_mode='HTML')

# --- دالة الترجمة ---
def t(key: str, context: ContextTypes.DEFAULT_TYPE, update_obj: Update, **kwargs) -> str:
    lang_code = context.user_data.get('language')
    user = update_obj.effective_user or (update_obj.callback_query and update_obj.callback_query.from_user)
    if not lang_code and user: lang_code = user.language_code
    lang = 'ar' if lang_code == 'ar' else 'en'
    text_or_list = translations.get(lang, {}).get(key, f"Key '{key}' not found.")
    if isinstance(text_or_list, list): text = "\n".join(text_or_list)
    else: text = text_or_list
    return text.format(**kwargs)

# --- دالة التحقق من الاشتراك ---
async def is_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception: return False

# --- المهمة التي تعمل في الخلفية (جديد) ---
async def background_search_task(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, target: str, search_type: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    logger.info(f"Starting background search for {target} (user: {user_id})")
    results = await search_urlscan_async(query)
    
    if results is None:
        await context.bot.send_message(chat_id=chat_id, text=t('error_searching', context, update))
    elif not results:
        no_results_key = 'no_results_domain' if search_type == 'domain' else 'no_results_asn'
        await context.bot.send_message(chat_id=chat_id, text=t(no_results_key, context, update, target=target))
    else:
        count = len(results)
        target_info_key = 'target_info_domain' if search_type == 'domain' else 'target_info_asn'
        target_info = t(target_info_key, context, update, target=target)
        results_text = t('found_results', context, update, count=count, target_info=target_info)
        message_body = "\n".join(results)
        
        if len(results_text + message_body) > 4096:
            await context.bot.send_message(chat_id=chat_id, text=t('too_many_results', context, update, count=count))
            with open(f"results_{user_id}.txt", "w") as f: f.write(message_body)
            await context.bot.send_document(chat_id=chat_id, document=open(f"results_{user_id}.txt", "rb"), filename=f"results_{target}.txt")
            os.remove(f"results_{user_id}.txt")
        else:
            await context.bot.send_message(chat_id=chat_id, text=results_text + message_body)
    logger.info(f"Finished background search for {target} (user: {user_id})")

# --- الأوامر (تم تعديلها لتشغيل المهام في الخلفية) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool = False) -> None:
    user = update.effective_user or (update.callback_query and update.callback_query.from_user)
    message_to_reply = update.effective_message or (update.callback_query and update.callback_query.message)
    if await is_user_in_group(user.id, context):
        await message_to_reply.reply_text(t('welcome', context, update))
    else:
        await message_to_reply.reply_text(t('join_group', context, update, group_username=GROUP_USERNAME))

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('join_group', context, update, group_username=GROUP_USERNAME)); return
    if not context.args:
        await update.message.reply_text(t('specify_domain', context, update)); return
    
    target = context.args[0]
    await update.message.reply_text(t('searching_domain', context, update, target=target))
    # تشغيل المهمة في الخلفية
    asyncio.create_task(background_search_task(update, context, f"page.domain:{target}", target, 'domain'))

async def asn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('join_group', context, update, group_username=GROUP_USERNAME)); return
    if not context.args:
        await update.message.reply_text(t('specify_asn', context, update)); return
    
    target = context.args[0].upper()
    if not target.startswith("AS"): target = "AS" + target
    
    await update.message.reply_text(t('searching_asn', context, update, target=target))
    # تشغيل المهمة في الخلفية
    asyncio.create_task(background_search_task(update, context, f"asn:{target}", target, 'asn'))

# (باقي الدوال تبقى كما هي)
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("العربية 🇸🇦", callback_data='set_lang_ar')], [InlineKeyboardButton("English 🇬🇧", callback_data='set_lang_en')]]
    await update.message.reply_text("Please choose your language / الرجاء اختيار لغتك:", reply_markup=InlineKeyboardMarkup(keyboard))

async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split('_')[-1]
    context.user_data['language'] = lang_code
    lang_name = "العربية" if lang_code == 'ar' else "English"
    await query.edit_message_text(text=f"Language has been set to {lang_name}.\nتم ضبط اللغة إلى {lang_name}.")
    await start_command(update, context, from_callback=True)

async def search_urlscan_async(query: str) -> list[str] | None:
    headers = {"API-Key": URLSCAN_API_KEY}
    domains = set()
    search_after = None
    try:
        while True:
            params = {"q": query, "size": 10000}
            if search_after: params["search_after"] = f"{search_after[0]},{search_after[1]}"
            response = await asyncio.to_thread(requests.get, "https://urlscan.io/api/v1/search/", params=params, headers=headers)
            if response.status_code == 429: await asyncio.sleep(60); continue
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

def main() -> None:
    if not all([TELEGRAM_BOT_TOKEN, URLSCAN_API_KEY, translations, DEVELOPER_CHAT_ID]):
        logging.critical("CRITICAL: Bot cannot start due to missing config.")
        return
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("lang", lang_command))
    application.add_handler(CallbackQueryHandler(language_callback, pattern='^set_lang_'))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("asn", asn_command))
    
    logger.info("Bot is starting with non-blocking tasks...")
    application.run_polling()

if __name__ == "__main__":
    main()
