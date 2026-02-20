import asyncio
import sqlite3
import aiohttp
import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ ---
# Убедись, что эти переменные заданы в настройках твоего хостинга или системы
API_TOKEN = getenv('BOT_TOKEN')
WEATHER_API_KEY = getenv('WEATHER_API_KEY')

if not API_TOKEN or not WEATHER_API_KEY:
    print("ОШИБКА: Токены BOT_TOKEN или WEATHER_API_KEY не найдены!")
    exit()

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, city TEXT, time INTEGER DEFAULT 8)''')
    conn.commit()
    conn.close()

def update_user(user_id, city=None, time=None):
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    if city:
        cur.execute('INSERT INTO users (id, city) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET city=?', (user_id, city, city))
    if time is not None:
        cur.execute('INSERT INTO users (id, time) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET time=?', (user_id, time, time))
    conn.commit()
    conn.close()

# --- ПОЛУЧЕНИЕ ПОГОДЫ ---
async def get_weather(city):
    url = "http://api.openweathermap.org"
    params = {
        'q': city,
        'appid': WEATHER_API_KEY,
        'units': 'metric',
        'lang': 'ru'
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                
                if res.get("cod") != 200:
                    print(f"Ошибка API для города {city}: {res.get('message')}")
                    return None
                
                # ИСПРАВЛЕНО: weather — это список, берем индекс [0]
                w_info = res['weather'][0]
                w_id = w_info['id']
                desc = w_info['description']
                temp = round(res['main']['temp'])
                name = res['name']
                
                # Эмодзи по ID погоды
                if w_id == 800: emoji = "☀️"
                elif 801 <= w_id <= 804: emoji = "☁️"
                elif 500 <= w_id <= 531: emoji = "🌧"
                elif 600 <= w_id <= 622: emoji = "❄️"
                else: emoji = "🌡"
                
                return f"{emoji} {name}: {temp}°C, {desc.capitalize()}"
        except Exception as e:
            print(f"Критическая ошибка при запросе погоды: {e}")
            return None

# --- КЛАВИАТУРА ---
def get_time_kb():
    buttons = [
        [
            InlineKeyboardButton(text="07:00", callback_data="set_7"),
            InlineKeyboardButton(text="08:00", callback_data="set_8"),
            InlineKeyboardButton(text="09:00", callback_data="set_9")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    update_user(msg.chat.id, city="Москва")
    await msg.answer(
        "Привет! Я буду присылать тебе прогноз погоды каждое утро.\n"
        "Сначала выбери время рассылки (по серверному времени):",
        reply_markup=get_time_kb()
    )

@dp.callback_query(F.data.startswith("set_"))
async def set_time_callback(call: types.CallbackQuery):
    time_val = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=time_val)
    await call.message.edit_text(
        f"✅ Время рассылки: {time_val}:00.\n"
        "Теперь напиши название своего города (например: Москва или London):"
    )
    await call.answer()

@dp.message()
async def handle_city(msg: types.Message):
    report = await get_weather(msg.text)
    if report:
        update_user(msg.chat.id, city=msg.text)
        await msg.answer(f"Город сохранен! Текущая погода:\n\n{report}\n\nБуду присылать прогноз каждое утро.")
    else:
        await msg.answer("❌ Город не найден. Попробуй еще раз (проверь раскладку или напиши на английском).")

# --- СЕРВИС РАССЫЛКИ ---
async def mailing_service():
    while True:
        now = datetime.datetime.now()
        # Проверяем в 00 секунд каждой минуты (чтобы не спамить)
        if now.minute == 0:
            conn = sqlite3.connect('weather_bot.db')
            cur = conn.cursor()
            # Берем всех пользователей, у которых время совпадает с текущим часом
            cur.execute('SELECT id, city FROM users WHERE time = ?', (now.hour,))
            users = cur.fetchall()
            conn.close()

            for user_id, city in users:
                weather = await get_weather(city)
                if weather:
                    try:
                        await bot.send_message(user_id, f"Доброе утро! Погода на сегодня:\n{weather}")
                    except Exception as e:
                        print(f"Не удалось отправить сообщение {user_id}: {e}")
            
            # Ждем минуту, чтобы не сработать повторно в ту же минуту
            await asyncio.sleep(60)
        
        await asyncio.sleep(30) # Проверка каждые 30 секунд

# --- ЗАПУСК ---
async def main():
    init_db()
    # Запускаем рассылку фоновой задачей
    asyncio.create_task(mailing_service())
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
