import asyncio
import sqlite3
import aiohttp
import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройки
API_TOKEN = getenv('BOT_TOKEN')
WEATHER_API_KEY = getenv('WEATHER_API_KEY')

if not API_TOKEN or not WEATHER_API_KEY:
    exit("Ошибка: Токены не найдены!")

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

# --- ПОЛУЧЕНИЕ ПОГОДЫ (Async) ---
async def get_weather(city):
    url = f"http://api.openweathermap.org{city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                res = await resp.json()
                if res.get("cod") != 200: return None
                
                w_id = res['weather'][0]['id']
                temp = round(res['main']['temp'])
                desc = res['weather'][0]['description']
                name = res['name']
                
                emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
                return f"{emoji} {name}: {temp}°C, {desc.capitalize()}"
        except Exception:
            return None

# --- КЛАВИАТУРА ---
def get_time_kb():
    buttons = [
        [InlineKeyboardButton(text="07:00", callback_data="set_7"),
         InlineKeyboardButton(text="08:00", callback_data="set_8"),
         InlineKeyboardButton(text="09:00", callback_data="set_9")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def start(msg: types.Message):
    update_user(msg.chat.id, city="Москва")
    await msg.answer("Привет! Я буду присылать погоду каждое утро.\nВыбери время рассылки (по МСК):", reply_markup=get_time_kb())

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    time_val = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=time_val)
    await call.message.edit_text(f"✅ Время установлено на {time_val}:00.\nТеперь напиши название своего города (например: Москва):")

@dp.message()
async def handle_msg(msg: types.Message):
    report = await get_weather(msg.text)
    if report:
        update_user(msg.chat.id, city=msg.text)
        await msg.answer(f"Запомнил! Город: {msg.text}.\n\nТекущая погода:\n{report}")
    else:
        await msg.answer("Не могу найти такой город. Попробуй еще раз!")

# --- СЕРВИС РАССЫЛКИ ---
async def mailing_service():
    while True:
        now = datetime.datetime.now()
        # Проверяем в начале каждого часа
        if now.minute == 0:
            conn = sqlite3.connect('weather_bot.db')
            cur = conn.cursor()
            cur.execute('SELECT id, city FROM users WHERE time = ?', (now.hour,))
            users = cur.fetchall()
            conn.close()

            for user_id, city in users:
                weather = await get_weather(city)
                if weather:
                    try:
                        await bot.send_message(user_id, f"Доброе утро! Прогноз на сегодня:\n{weather}")
                    except Exception:
                        pass 
        await asyncio.sleep(60) # Спим минуту до следующей проверки

# --- ЗАПУСК ---
async def main():
    init_db()
    # Запуск планировщика "в фоне"
    asyncio.create_task(mailing_service())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
