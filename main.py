import asyncio
import sqlite3
import aiohttp
import datetime
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# --- НАСТРОЙКИ (УБЕДИСЬ, ЧТО ОНИ ЗАДАНЫ!) ---
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

# --- СОВЕТЫ ---
def get_clothes_advice(temp, w_id):
    advice = ""
    if 200 <= w_id <= 531: advice += "☔️ Возьми зонт! "
    elif 600 <= w_id <= 622: advice += "❄️ Оденься теплее, на улице снег. "
    
    if temp < -15: advice += "🥶 Очень холодно! Нужна зимняя одежда."
    elif -15 <= temp < 5: advice += "🧥 Холодно, надень пуховик или пальто."
    elif 5 <= temp < 15: advice += "🧥 Прохладно, подойдет куртка."
    elif 15 <= temp < 25: advice += "👕 Тепло, хватит кофты или ветровки."
    else: advice += "☀️ Жарко, одевайся легко."
    return advice

# --- ПОЛУЧЕНИЕ ПОГОДЫ ---
async def get_weather(city_or_coords):
    url = "https://api.openweathermap.org"
    params = {'appid': WEATHER_API_KEY, 'units': 'metric', 'lang': 'ru'}
    if isinstance(city_or_coords, dict): params.update(city_or_coords)
    else: params['q'] = city_or_coords

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200: 
                    return None
                res = await resp.json()
                
                w_main = res['weather'][0] # ИСПРАВЛЕНО: строгий индекс
                temp = round(res['main']['temp'])
                name = res['name']
                desc = w_main['description']
                w_id = w_main['id']
                tz_offset = res.get('timezone', 10800)
                
                emoji = "☀️" if w_id == 800 else "☁️" if w_id > 800 else "🌧" if w_id >= 500 else "❄️"
                advice = get_clothes_advice(temp, w_id)
                
                report = f"{emoji} <b>{name}</b>\n🌡 {temp}°C, {desc.capitalize()}\n\n💡 <i>{advice}</i>"
                return report, name, tz_offset
        except Exception as e:
            print(f"Ошибка API: {e}")
            return None

# --- КЛАВИАТУРЫ ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🌡 Узнать погоду сейчас")],
        [KeyboardButton(text="⚙️ Настройки времени/города")]
    ], resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
@dp.message(F.text == "⚙️ Настройки времени/города")
async def start_setup(msg: types.Message):
    init_db()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="07:00", callback_data="set_7"),
        InlineKeyboardButton(text="08:00", callback_data="set_8"),
        InlineKeyboardButton(text="09:00", callback_data="set_9")
    ]])
    await msg.answer("Выбери время для утренней рассылки:", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    geo_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]], resize_keyboard=True)
    await call.message.answer(f"✅ Время рассылки: {t}:00.\nПришли локацию или напиши город вручную:", reply_markup=geo_kb)
    await call.answer()

@dp.message(F.location)
async def handle_location(msg: types.Message):
    data = await get_weather({"lat": msg.location.latitude, "lon": msg.location.longitude})
    if data:
        report, city, tz = data
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"Город {city} успешно привязан!", reply_markup=main_kb())
        await msg.answer(report, parse_mode="HTML")
    else:
        await msg.answer("❌ Ошибка API при получении координат. Попробуй написать название города текстом.")

@dp.message(F.text == "🌡 Узнать погоду сейчас")
async def check_now(msg: types.Message):
    conn = sqlite3.connect('weather_bot.db'); cur = conn.cursor()
    cur.execute('SELECT city FROM users WHERE id = ?', (msg.from_user.id,))
    res = cur.fetchone(); conn.close()
    if res and res[0]:
        data = await get_weather(res[0])
        if data: await msg.answer(data[0], parse_mode="HTML")
        else: await msg.answer("Ошибка связи с сервером погоды.")
    else:
        await msg.answer("Сначала настрой город через /start")

@dp.message()
async def handle_city(msg: types.Message):
    if msg.text.startswith("/") or msg.text == "🌡 Узнать погоду сейчас": return
    data = await get_weather(msg.text)
    if data:
        report, city, tz = data
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"Город {city} сохранен!", reply_markup=main_kb())
        await msg.answer(report, parse_mode="HTML")
    else:
        await msg.answer("❌ Город не найден. Напиши, например: Москва")

# --- РАССЫЛКА ПО МЕСТНОМУ ВРЕМЕНИ ---
async def mailing():
    while True:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if now_utc.minute == 0:
            conn = sqlite3.connect('weather_bot.db'); cur = conn.cursor()
            cur.execute('SELECT id, city, time, timezone FROM users'); users = cur.fetchall(); conn.close()
            for u_id, city, target_h, tz_off in users:
                user_local = now_utc + datetime.timedelta(seconds=tz_off)
                if user_local.hour == target_h:
                    data = await get_weather(city)
                    if data:
                        try: await bot.send_message(u_id, f"Доброе утро! ☕️\n\n{data[0]}", parse_mode="HTML")
                        except: pass
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def main():
    init_db()
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
