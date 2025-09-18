import requests
import logging
import asyncio
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest

# --- الإعدادات ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
URLSCAN_API_KEY = os.environ.get("URLSCAN_API_KEY")
GROUP_ID = -1002000171927
GROUP_USERNAME = "fastNetAbdo"

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

# --- دالة الترجمة (تم تحديثها لتقرأ من ذاكرة المستخدم) ---
def t(key: str, context: ContextTypes.DEFAULT_TYPE, update: Update, **kwargs) -> str:
    # 1. احصل على اللغة من ذاكرة المستخدم
    lang_code = context.user_data.get('language')
    # 2. إذا لم يختر المستخدم لغة، استخدم لغة تليجرام
    if not lang_code:
        lang_code = update.effective_user.language_code
    
    lang = 'ar' if lang_code == 'ar' else 'en'
    text_or_list = translations.get(lang, {}).get(key, f"Key '{key}' not found.")
    
    if isinstance(text_or_list, list):
        text = "\n".join(text_or_list)
    else:
        text = text_or_list
        
    return text.format(**kwargs)

# --- دالة التحقق من الاشتراك ---
async def is_user_in_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

# --- الأوامر ---

# --- الأمر الجديد: /lang ---
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("العربية 🇸🇦", callback_data='set_lang_ar')],
        [InlineKeyboardButton("English 🇬🇧", callback_data='set_lang_en')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please choose your language / الرجاء اختيار لغتك:", reply_markup=reply_markup)

# --- معالج أزرار اختيار اللغة ---
async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split('_')[-1]  # 'ar' or 'en'
    context.user_data['language'] = lang_code
    
    lang_name = "العربية" if lang_code == 'ar' else "English"
    await query.edit_message_text(text=f"Language has been set to {lang_name}.\nتم ضبط اللغة إلى {lang_name}.")
    # إظهار رسالة الترحيب باللغة الجديدة
    await start_command(update, context, from_callback=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool = False) -> None:
    # تحديد مصدر التحديث (رسالة عادية أو زر)
    effective_update = update.callback_query if from_callback else update
    
    if await is_user_in_group(effective_update.from_user.id, context):
        # هنا نستخدم update الأصلية للحصول على لغة المستخدم إذا لم يتم تعيينها
        await effective_update.message.reply_text(t('welcome', context, update.callback_query or update))
    else:
        await effective_update.message.reply_text(t('join_group', context, update.callback_query or update, group_username=GROUP_USERNAME))

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('join_group', context, update, group_username=GROUP_USERNAME))
        return
    if not context.args:
        await update.message.reply_text(t('specify_domain', context, update))
        return
    
    target = context.args[0]
    await update.message.reply_text(t('searching_domain', context, update, target=target))
    results = await search_urlscan_async(f"page.domain:{target}")
    target_info = t('target_info_domain', context, update, target=target)
    await process_and_send_results(update, context, results, target_info, target, 'no_results_domain')

async def asn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_user_in_group(update.effective_user.id, context):
        await update.message.reply_text(t('join_group', context, update, group_username=GROUP_USERNAME))
        return
    if not context.args:
        await update.message.reply_text(t('specify_asn', context, update))
        return
    
    target = context.args[0].upper()
    if not target.startswith("AS"): target = "AS" + target
    
    await update.message.reply_text(t('searching_asn', context, update, target=target))
    results = await search_urlscan_async(f"asn:{target}")
    target_info = t('target_info_asn', context, update, target=target)
    await process_and_send_results(update, context, results, target_info, target, 'no_results_asn')

# --- دوال مساعدة (تبقى كما هي) ---
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

async def process_and_send_results(update: Update, context: ContextTypes.DEFAULT_TYPE, results: list[str] | None, target_info: str, target: str, no_results_key: str):
    if results is None:
        await update.message.reply_text(t('error_searching', context, update))
    elif not results:
        await update.message.reply_text(t(no_results_key, context, update, target=target))
    else:
        count = len(results)
        results_text = t('found_results', context, update, count=count, target_info=target_info)
        message_body = "\n".join(results)
        if len(results_text + message_body) > 4096:
            await update.message.reply_text(t('too_many_results', context, update, count=count))
            with open("results.txt", "w") as f: f.write(message_body)
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open("results.txt", "rb"), filename=f"results_{target}.txt")
        else:
            await update.message.reply_text(results_text + message_body)

def main() -> None:
    if not all([TELEGRAM_BOT_TOKEN, URLSCAN_API_KEY, translations]):
        logging.critical("CRITICAL: Bot cannot start due to missing config or language files.")
        return
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # إضافة الأوامر ومعالج الأزرار
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("lang", lang_command))
    application.add_handler(CallbackQueryHandler(language_callback, pattern='^set_lang_'))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("asn", asn_command))
    
    logger.info("Bot is starting on the cloud with user-selectable language...")
    application.run_polling()

if __name__ == "__main__":
    main()
