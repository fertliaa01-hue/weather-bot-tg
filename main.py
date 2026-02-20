import asyncio
import sqlite3
import aiohttp
import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
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
async def get_weather(city_or_coords):
    url = "http://api.openweathermap.org"
    params = {'appid': WEATHER_API_KEY, 'units': 'metric', 'lang': 'ru'}
    
    if isinstance(city_or_coords, dict): # Если переданы координаты
        params.update(city_or_coords)
    else: # Если передан текст города
        params['q'] = city_or_coords

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                res = await resp.json()
                if res.get("cod") != 200: return None
                
                # ИСПРАВЛЕНО: берем первый элемент из списка weather [0]
                w_data = res['weather'][0]
                w_id = w_data['id']
                temp = round(res['main']['temp'])
                desc = w_data['description']
                name = res['name']
                
                emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
                return f"{emoji} {name}: {temp}°C, {desc.capitalize()}"
        except Exception as e:
            print(f"Ошибка API: {e}")
            return None

# --- КЛАВИАТУРЫ ---
def get_time_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="07:00", callback_data="set_7"),
        InlineKeyboardButton(text="08:00", callback_data="set_8"),
        InlineKeyboardButton(text="09:00", callback_data="set_9")
    ]])

def get_geo_kb():
    return ReplyKeyboardMarkup(keyboard=[[
        KeyboardButton(text="📍 Отправить местоположение", request_location=True)
    ]], resize_keyboard=True, one_time_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def start(msg: types.Message):
    update_user(msg.chat.id, city="Москва")
    await msg.answer("Привет! Выбери время для рассылки (МСК):", reply_markup=get_time_kb())

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    await call.message.edit_text(f"✅ Время: {t}:00. Теперь напиши город или нажми кнопку ниже 👇")
    await call.message.answer("Жду город...", reply_markup=get_geo_kb())

# Обработка геолокации
@dp.message(F.location)
async def handle_location(msg: types.Message):
    coords = {"lat": msg.location.latitude, "lon": msg.location.longitude}
    report = await get_weather(coords)
    if report:
        city_name = report.split(":")[0].strip()[2:] # Вырезаем имя города из отчета
        update_user(msg.chat.id, city=city_name)
        await msg.answer(f"📍 Вижу тебя! Твой город: {city_name}.\n\n{report}", reply_markup=types.ReplyKeyboardRemove())
    else:
        await msg.answer("Не удалось определить город по координатам.")

# Обработка текста
@dp.message()
async def handle_city(msg: types.Message):
    report = await get_weather(msg.text)
    if report:
        update_user(msg.chat.id, city=msg.text)
        await msg.answer(f"Запомнил: {msg.text}!\n\n{report}", reply_markup=types.ReplyKeyboardRemove())
    else:
        await msg.answer("❌ Город не найден. Попробуй еще раз.")

# --- РАССЫЛКА ---
async def mailing():
    while True:
        now = datetime.datetime.now()
        if now.minute == 0:
            conn = sqlite3.connect('weather_bot.db'); cur = conn.cursor()
            cur.execute('SELECT id, city FROM users WHERE time = ?', (now.hour,))
            users = cur.fetchall(); conn.close()
            for u_id, city in users:
                w = await get_weather(city)
                if w:
                    try: await bot.send_message(u_id, f"Доброе утро! ☕️\n{w}")
                    except: pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)

async def main():
    init_db()
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
