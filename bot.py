import os
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext, ConversationHandler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import json
import time
from datetime import datetime
import re
import flask

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
SETTING_PRODUCT, SETTING_PRICE, SETTING_SITE = range(3)

# Файлы для хранения данных
PRODUCTS_FILE = "products.json"
SITES_FILE = "sites.json"
CONFIG_FILE = "config.json"

# Глобальные переменные
application = None

# Загрузка данных
def load_data(filename, default=[]):
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filename}: {e}")
    return default

# Сохранение данных
def save_data(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")

# Загрузка конфигурации
def load_config():
    return load_data(CONFIG_FILE, {"chat_id": None})

# Сохранение конфигурации
def save_config(config):
    save_data(CONFIG_FILE, config)

# Загрузка товаров
def load_products():
    return load_data(PRODUCTS_FILE, [])

# Сохранение товаров
def save_products(products):
    save_data(PRODUCTS_FILE, products)

# Загрузка сайтов
def load_sites():
    return load_data(SITES_FILE, [])

# Сохранение сайтов
def save_sites(sites):
    save_data(SITES_FILE, sites)

# Парсер Ozon
def parse_ozon(product_name, max_price):
    try:
        search_query = product_name.replace(' ', '%20')
        url = f"https://www.ozon.ru/search/?text={search_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        products = []
        
        # Поиск карточек товаров
        items = soup.find_all('div', {'class': 'tile-root'}) or soup.find_all('div', {'class': 'widget-search-result-container'})
        
        for item in items[:10]:
            try:
                # Название товара
                name_elem = item.find('a', {'class': 'tile-hover-target'}) or item.find('span', {'class': 'tsBody500Medium'})
                if not name_elem:
                    continue
                
                name = name_elem.get_text(strip=True)
                if product_name.lower() not in name.lower():
                    continue
                
                # Цена товара
                price_elem = item.find('span', {'class': 'tsHeadline500Medium'}) or item.find('span', {'class': 'c3118-a0'})
                if not price_elem:
                    continue
                
                price_text = price_elem.get_text(strip=True).replace(' ', '').replace('₽', '').replace(',', '.')
                price = float(''.join([c for c in price_text if c.isdigit() or c == '.']))
                
                if price > max_price:
                    continue
                
                # Ссылка на товар
                link_elem = item.find('a', href=True)
                if link_elem:
                    link = 'https://www.ozon.ru' + link_elem['href'] if link_elem['href'].startswith('/') else link_elem['href']
                else:
                    continue
                
                # Изображение товара
                img_elem = item.find('img', src=True) or item.find('img', {'data-src': True})
                img_url = None
                if img_elem:
                    img_url = img_elem.get('src') or img_elem.get('data-src')
                    if img_url and img_url.startswith('//'):
                        img_url = 'https:' + img_url
                
                products.append({
                    'name': name,
                    'price': price,
                    'link': link,
                    'image': img_url,
                    'found_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
            except Exception as e:
                continue
                
        return products
        
    except Exception as e:
        logger.error(f"Error parsing Ozon: {e}")
        return []

# Функция проверки товаров
def check_products():
    try:
        config = load_config()
        if not config.get('chat_id'):
            return
        
        products = load_products()
        sites = load_sites()
        
        if not products or not sites:
            return
        
        found_products = []
        
        for product in products:
            for site in sites:
                if site['name'] == 'ozon.ru':
                    results = parse_ozon(product['name'], product['max_price'])
                    
                    for result in results:
                        result['product'] = product['name']
                        result['site'] = site['name']
                        found_products.append(result)
        
        # Отправка найденных товаров
        for product in found_products:
            message = (
                f"🎯 Найден товар!\n\n"
                f"📦 Товар: {product['product']}\n"
                f"🏪 Магазин: {product['site']}\n"
                f"📋 Название: {product['name']}\n"
                f"💰 Цена: {product['price']} руб.\n"
                f"⏰ Найдено: {product['found_at']}\n"
                f"🔗 Ссылка: {product['link']}"
            )
            
            try:
                if application:
                    if product.get('image'):
                        application.bot.send_photo(
                            chat_id=config['chat_id'],
                            photo=product['image'],
                            caption=message
                        )
                    else:
                        application.bot.send_message(
                            chat_id=config['chat_id'],
                            text=message
                        )
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                
    except Exception as e:
        logger.error(f"Error in check_products: {e}")

# Создание основной клавиатуры
def main_keyboard():
    keyboard = [
        ['📦 Мои товары', '🏪 Мои сайты'],
        ['➕ Добавить товар', '➕ Добавить сайт'],
        ['🔍 Проверить сейчас', '⚙️ Настройки']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Команда старта
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    config['chat_id'] = update.effective_chat.id
    save_config(config)
    
    await update.message.reply_text(
        "🤖 Умный парсер бот запущен и работает 24/7! 🎉\n\n"
        "Бот будет работать всегда, даже когда телефон выключен!\n\n"
        "Используйте кнопки меню для управления:",
        reply_markup=main_keyboard()
    )

# Показать список товаров
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = load_products()
    
    if not products:
        await update.message.reply_text("📦 Список товаров пуст.\nИспользуйте '➕ Добавить товар'")
        return
    
    message = "📦 Ваши товары для поиска:\n\n"
    for i, product in enumerate(products, 1):
        message += f"{i}. {product['name']} - до {product['max_price']} руб.\n"
    
    message += "\n❌ Чтобы удалить товар, отправьте: /delete_product номер"
    await update.message.reply_text(message)

# Показать список сайтов
async def show_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sites = load_sites()
    
    if not sites:
        await update.message.reply_text("🏪 Список сайтов пуст.\nИспользуйте '➕ Добавить сайт'")
        return
    
    message = "🏪 Ваши сайты для парсинга:\n\n"
    for i, site in enumerate(sites, 1):
        message += f"{i}. {site['name']}\n"
    
    message += "\n❌ Чтобы удалить сайт, отправьте: /delete_site номер"
    await update.message.reply_text(message)

# Начать добавление товара
async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 Введите название товара для добавления:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SETTING_PRODUCT

# Получить название товара
async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_product'] = {'name': update.message.text}
    await update.message.reply_text("💰 Введите максимальную цену для этого товара (в рублях):")
    return SETTING_PRICE

# Получить цену товара и сохранить
async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text)
        product = context.user_data['new_product']
        product['max_price'] = price
        
        products = load_products()
        products.append(product)
        save_products(products)
        
        await update.message.reply_text(
            f"✅ Товар добавлен!\n"
            f"📦 {product['name']}\n"
            f"💰 До {price} руб.",
            reply_markup=main_keyboard()
        )
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректную цену (число):")
        return SETTING_PRICE

# Начать добавление сайта
async def add_site_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏪 Введите название сайта для добавления (например: ozon.ru):",
        reply_markup=ReplyKeyboardRemove()
    )
    return SETTING_SITE

# Сохранить сайт
async def add_site_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    site_name = update.message.text.lower().strip()
    
    sites = load_sites()
    
    if any(site['name'] == site_name for site in sites):
        await update.message.reply_text(
            f"❌ Сайт {site_name} уже добавлен!",
            reply_markup=main_keyboard()
        )
        return ConversationHandler.END
    
    sites.append({'name': site_name})
    save_sites(sites)
    
    await update.message.reply_text(
        f"✅ Сайт добавлен!\n🏪 {site_name}",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# Удалить товар
async def delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        products = load_products()
        if not products:
            await update.message.reply_text("📦 Список товаров пуст.")
            return
        
        text = update.message.text
        match = re.search(r'/delete_product\s+(\d+)', text)
        if not match:
            await update.message.reply_text("❌ Используйте: /delete_product номер")
            return
        
        index = int(match.group(1)) - 1
        
        if 0 <= index < len(products):
            deleted_product = products.pop(index)
            save_products(products)
            await update.message.reply_text(
                f"✅ Товар удален:\n📦 {deleted_product['name']}"
            )
        else:
            await update.message.reply_text("❌ Неверный номер товара.")
            
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при удалении товара.")

# Удалить сайт
async def delete_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sites = load_sites()
        if not sites:
            await update.message.reply_text("🏪 Список сайтов пуст.")
            return
        
        text = update.message.text
        match = re.search(r'/delete_site\s+(\d+)', text)
        if not match:
            await update.message.reply_text("❌ Используйте: /delete_site номер")
            return
        
        index = int(match.group(1)) - 1
        
        if 0 <= index < len(sites):
            deleted_site = sites.pop(index)
            save_sites(sites)
            await update.message.reply_text(
                f"✅ Сайт удален:\n🏪 {deleted_site['name']}"
            )
        else:
            await update.message.reply_text("❌ Неверный номер сайта.")
            
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при удалении сайта.")

# Проверить сейчас
async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Начинаю проверку...")
    check_products()

# Показать настройки
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = load_products()
    sites = load_sites()
    
    message = (
        f"⚙️ Текущие настройки:\n\n"
        f"📦 Товаров: {len(products)}\n"
        f"🏪 Сайтов: {len(sites)}\n"
        f"⏰ Интервал проверки: 30 минут\n"
        f"🔔 Уведомления: включены\n"
        f"🚀 Режим работы: 24/7 всегда онлайн!"
    )
    
    await update.message.reply_text(message)

# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == '📦 Мои товары':
        await show_products(update, context)
    elif text == '🏪 Мои сайты':
        await show_sites(update, context)
    elif text == '➕ Добавить товар':
        await add_product_start(update, context)
        return SETTING_PRODUCT
    elif text == '➕ Добавить сайт':
        await add_site_start(update, context)
        return SETTING_SITE
    elif text == '🔍 Проверить сейчас':
        await check_now(update, context)
    elif text == '⚙️ Настройки':
        await show_settings(update, context)
    else:
        await update.message.reply_text(
            "Используйте кнопки меню для управления ботом!",
            reply_markup=main_keyboard()
        )

# Отмена диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# Инициализация планировщика
def init_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_products,
        trigger=IntervalTrigger(minutes=30),
        id='check_products_job',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler started - checking every 30 minutes")

# Создание Flask приложения для веб-сервера
app = flask.Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram Parser Bot is running 24/7! 🚀"

@app.route('/health')
def health():
    return "OK", 200

# Основная функция
def main():
    global application
    
    # Инициализация планировщика
    init_scheduler()
    
    # ВСТАВЬТЕ СВОЙ ТОКЕН ЗДЕСЬ!
    TOKEN = "7973881475:AAFLHxTpK5zudwv1LLmuFvNxUmW-3W9BjK8"
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Создаем ConversationHandler для добавления товаров
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^➕ Добавить товар$'), add_product_start)
        ],
        states={
            SETTING_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            SETTING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Создаем ConversationHandler для добавления сайтов
    conv_handler_sites = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^➕ Добавить сайт$'), add_site_start)
        ],
        states={
            SETTING_SITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_site_name)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_now))
    application.add_handler(CommandHandler("settings", show_settings))
    application.add_handler(CommandHandler("delete_product", delete_product))
    application.add_handler(CommandHandler("delete_site", delete_site))
    application.add_handler(conv_handler)
    application.add_handler(conv_handler_sites)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Bot starting...")
    application.run_polling()

if __name__ == '__main__':
    # Запускаем Flask в отдельном потоке
    from threading import Thread
    Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get('PORT', 5000), debug=False)).start()
    
    # Запускаем бота
    main()
