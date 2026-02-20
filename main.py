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
                   (id INTEGER PRIMARY KEY, city TEXT, time INTEGER DEFAULT 8, timezone INTEGER DEFAULT 10800)''')
    conn.commit()
    conn.close()

def update_user(user_id, city=None, time=None, timezone=None):
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    if city:
        cur.execute('INSERT INTO users (id, city) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET city=?', (user_id, city, city))
    if time is not None:
        cur.execute('INSERT INTO users (id, time) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET time=?', (user_id, int(time), int(time)))
    if timezone is not None:
        cur.execute('INSERT INTO users (id, timezone) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET timezone=?', (user_id, int(timezone), int(timezone)))
    conn.commit()
    conn.close()

# --- СОВЕТЫ ПО ОДЕЖДЕ ---
def get_clothes_advice(temp, w_id):
    advice = ""
    if 200 <= w_id <= 531: advice += "☔️ Возьми зонт! "
    elif 600 <= w_id <= 622: advice += "❄️ Оденься теплее, на улице снег. "
    
    if temp < -15: advice += "🥶 Очень холодно! Оденься максимально тепло."
    elif -15 <= temp < 0: advice += "🧥 Морозно, надень зимнюю куртку."
    elif 0 <= temp < 10: advice += "🧥 Прохладно, подойдет осенняя куртка."
    elif 10 <= temp < 20: advice += "👕 Тепло, хватит кофты или ветровки."
    else: advice += "☀️ Жарко, одевайся легко."
    return advice

# --- ПОЛУЧЕНИЕ ПОГОДЫ (ИСПРАВЛЕННЫЙ URL) ---
async def get_weather(city_or_coords):
    # ПРАВИЛЬНЫЙ АДРЕС СЕРВЕРА
    url = "https://api.openweathermap.org"
    params = {'appid': WEATHER_API_KEY, 'units': 'metric', 'lang': 'ru'}
    
    if isinstance(city_or_coords, dict): params.update(city_or_coords)
    else: params['q'] = city_or_coords

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200: return None
                res = await resp.json()
                
                # ИСПРАВЛЕНО: weather - это список, берем первый элемент [0]
                w_main = res['weather'][0]
                temp = round(res['main']['temp'])
                name = res['name']
                desc = w_main['description']
                w_id = w_main['id']
                tz_offset = res.get('timezone', 10800) # По умолчанию МСК (3 часа в сек)
                
                emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
                advice = get_clothes_advice(temp, w_id)
                
                report = f"{emoji} <b>{name}</b>\n🌡 {temp}°C, {desc.capitalize()}\n\n💡 <i>{advice}</i>"
                return report, name, tz_offset
        except Exception as e:
            print(f"Ошибка API: {e}")
            return None

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def start(msg: types.Message):
    init_db()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="07:00", callback_data="set_7"),
        InlineKeyboardButton(text="08:00", callback_data="set_8"),
        InlineKeyboardButton(text="09:00", callback_data="set_9")
    ]])
    await msg.answer("Привет! Давай настроим рассылку.\nВыбери время:", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    geo_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]], resize_keyboard=True)
    await call.message.edit_text(f"✅ Время: {t}:00.\nТеперь отправь локацию или напиши город.")
    await call.message.answer("Жду...", reply_markup=geo_kb)

@dp.message(F.location)
async def handle_location(msg: types.Message):
    data = await get_weather({"lat": msg.location.latitude, "lon": msg.location.longitude})
    if data:
        report, city, tz = data
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"Город {city} сохранен!\n\n{report}", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
    else:
        await msg.answer("Ошибка. Напиши город текстом.")

@dp.message()
async def handle_city(msg: types.Message):
    data = await get_weather(msg.text)
    if data:
        report, city, tz = data
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"Город {city} сохранен!\n\n{report}", parse_mode="HTML")
    else:
        await msg.answer("❌ Город не найден.")

# --- РАССЫЛКА ПО МЕСТНОМУ ВРЕМЕНИ ---
async def mailing():
    while True:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if now_utc.minute == 0:
            conn = sqlite3.connect('weather_bot.db')
            cur = conn.cursor()
            cur.execute('SELECT id, city, time, timezone FROM users')
            users = cur.fetchall()
            conn.close()
            for u_id, city, target_h, tz_off in users:
                # Рассчитываем локальное время пользователя
                user_local = now_utc + datetime.timedelta(seconds=tz_off)
                if user_local.hour == target_h:
                    data = await get_weather(city)
                    if data:
                        try: await bot.send_message(u_id, f"Доброе утро! ☕️\n\n{data}", parse_mode="HTML")
                        except: pass
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    init_db()
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
