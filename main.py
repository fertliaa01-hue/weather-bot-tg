import asyncio
import sqlite3
import aiohttp
import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройки (убедись, что переменные окружения установлены!)
API_TOKEN = getenv('BOT_TOKEN')
WEATHER_API_KEY = getenv('WEATHER_API_KEY')

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
    # Исправленный URL и параметры
    url = f"http://api.openweathermap.org"
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
                    return None
                
                # ВНИМАНИЕ: weather — это список [0]
                w_info = res['weather'][0]
                w_id = w_info['id']
                temp = round(res['main']['temp'])
                desc = w_info['description']
                name = res['name']
                
                emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
                return f"{emoji} {name}: {temp}°C, {desc.capitalize()}"
        except Exception as e:
            print(f"Ошибка API: {e}")
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
    await msg.answer("Привет! Я погодный бот. Выбери время для утренней рассылки:", reply_markup=get_time_kb())

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    time_val = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=time_val)
    await call.message.edit_text(f"✅ Время установлено на {time_val}:00.\nТеперь напиши название своего города:")

@dp.message()
async def handle_msg(msg: types.Message):
    report = await get_weather(msg.text)
    if report:
        update_user(msg.chat.id, city=msg.text)
        await msg.answer(f"Город сохранен! Текущая погода там:\n\n{report}\n\nБуду присылать обновления в выбранное время.")
    else:
        await msg.answer("❌ Город не найден. Попробуй написать название на русском или английском (например, Москва или Moscow).")

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
        await asyncio.sleep(60)

async def main():
    init_db()
    asyncio.create_task(mailing_service())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
