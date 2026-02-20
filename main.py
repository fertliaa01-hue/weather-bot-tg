import asyncio
import sqlite3
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

import os
from os import getenv

# Бот будет искать эти названия в настройках хостинга
API_TOKEN = getenv('BOT_TOKEN')
WEATHER_API_KEY = getenv('WEATHER_API_KEY')

# Проверка, что ключи загрузились
if not API_TOKEN or not WEATHER_API_KEY:
    exit("Ошибка: Токены не найдены в переменных окружения!")


bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ (добавили колонку time) ---
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

# --- КРАСИВАЯ ПОГОДА ---
def get_weather(city):
    url = f"http://api.openweathermap.org{city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    res = requests.get(url).json()
    if res.get("cod") != 200: return None
    
    w_id = res['weather'][0]['id']
    emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
    
    return f"{emoji} {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"

# --- КЛАВИАТУРЫ ---
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
    await msg.answer("Выбери время для ежедневного прогноза:", reply_markup=get_time_kb())

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.Callback_Query):
    time_val = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=time_val)
    await call.answer(f"Установлено время: {time_val}:00")
    await call.message.edit_text(f"✅ Время рассылки обновлено на {time_val}:00. Теперь напиши свой город!")

@dp.message()
async def handle_msg(msg: types.Message):
    report = get_weather(msg.text)
    if report:
        update_user(msg.chat.id, city=msg.text)
        await msg.answer(f"Запомнил! Теперь буду присылать погоду по городу {msg.text}.\n\n{report}")
    else:
        await msg.answer("Город не найден 🧐")

# --- ЗАПУСК ---
async def main():
    init_db()
    # Здесь логика scheduler остается прежней (проверка каждый час)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
