import asyncio
import sqlite3
import aiohttp
import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

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

# --- ПОЛУЧЕНИЕ ПОГОДЫ (ИСПРАВЛЕННЫЙ URL И ПАРСИНГ) ---
async def get_weather(city_or_coords):
    # ВАЖНО: URL должен быть именно таким
    url = "https://api.openweathermap.org"
    params = {'appid': WEATHER_API_KEY, 'units': 'metric', 'lang': 'ru'}
    
    if isinstance(city_or_coords, dict):
        params.update(city_or_coords)
    else:
        params['q'] = city_or_coords

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                
                res = await resp.json()
                
                # Достаем данные правильно: weather - это СПИСОК
                w_info = res['weather'][0] 
                w_id = w_info['id']
                temp = round(res['main']['temp'])
                desc = w_info['description']
                name = res['name']
                
                emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
                return f"{emoji} {name}: {temp}°C, {desc.capitalize()}"
        except Exception as e:
            print(f"Ошибка парсинга погоды: {e}")
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
    init_db()
    update_user(msg.chat.id, city="Москва")
    await msg.answer("Привет! Выбери время для рассылки (МСК):", reply_markup=get_time_kb())

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    await call.message.edit_text(f"✅ Время: {t}:00. Теперь напиши город или нажми кнопку 👇")
    await call.message.answer("Жду город или локацию...", reply_markup=get_geo_kb())

@dp.message(F.location)
async def handle_location(msg: types.Message):
    coords = {"lat": msg.location.latitude, "lon": msg.location.longitude}
    report = await get_weather(coords)
    if report:
        # Извлекаем название города из начала строки (после эмодзи)
        city_name = report.split(":")[0].split(" ", 1)[1]
        update_user(msg.chat.id, city=city_name)
        await msg.answer(f"📍 Город определен: {city_name}!\n\n{report}", reply_markup=ReplyKeyboardRemove())
    else:
        await msg.answer("Не удалось определить город. Напиши его название текстом.")

@dp.message()
async def handle_city(msg: types.Message):
    report = await get_weather(msg.text)
    if report:
        update_user(msg.chat.id, city=msg.text)
        await msg.answer(f"Запомнил город {msg.text}!\n\n{report}", reply_markup=ReplyKeyboardRemove())
    else:
        await msg.answer("❌ Город не найден. Напиши, например: Москва")

# --- РАССЫЛКА ---
async def mailing():
    while True:
        now = datetime.datetime.now()
        if now.minute == 0:
            try:
                conn = sqlite3.connect('weather_bot.db')
                cur = conn.cursor()
                cur.execute('SELECT id, city FROM users WHERE time = ?', (now.hour,))
                users = cur.fetchall()
                conn.close()
                for u_id, city in users:
                    w = await get_weather(city)
                    if w:
                        try: await bot.send_message(u_id, f"Доброе утро! ☕️\n{w}")
                        except: pass
            except Exception as e:
                print(f"Ошибка в рассылке: {e}")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    init_db()
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
