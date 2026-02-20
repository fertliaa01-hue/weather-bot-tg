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
    
    # Проверяем, существует ли пользователь
    cur.execute('SELECT id FROM users WHERE id = ?', (user_id,))
    exists = cur.fetchone()
    
    if not exists:
        # Вставляем нового пользователя
        cur.execute('INSERT INTO users (id, city, time, timezone) VALUES (?, ?, ?, ?)',
                   (user_id, city if city else '', time if time else 8, timezone if timezone else 10800))
    else:
        # Обновляем существующего
        if city:
            cur.execute('UPDATE users SET city = ? WHERE id = ?', (city, user_id))
        if time is not None:
            cur.execute('UPDATE users SET time = ? WHERE id = ?', (int(time), user_id))
        if timezone is not None:
            cur.execute('UPDATE users SET timezone = ? WHERE id = ?', (int(timezone), user_id))
    
    conn.commit()
    conn.close()

# --- ПОЛУЧЕНИЕ ПОГОДЫ ---
async def get_weather(city_or_coords):
    # ИСПРАВЛЕНО: правильный URL для API OpenWeatherMap
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        'appid': WEATHER_API_KEY, 
        'units': 'metric', 
        'lang': 'ru'
    }
    
    if isinstance(city_or_coords, dict):
        params.update(city_or_coords)
    else:
        params['q'] = city_or_coords

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"Ошибка API: статус {resp.status}, ответ: {error_text}")
                    return None
                
                res = await resp.json()
                
                # Проверяем наличие необходимых полей
                if 'weather' not in res or 'main' not in res:
                    print(f"Неожиданный ответ API: {res}")
                    return None
                
                w_info = res['weather'][0] 
                w_id = w_info['id']
                temp = round(res['main']['temp'])
                desc = w_info['description']
                name = res['name']
                tz_offset = res.get('timezone', 10800)
                
                # Выбор эмодзи
                if w_id == 800:
                    emoji = "☀️"
                elif w_id > 800:
                    emoji = "☁️"
                elif w_id >= 500:
                    emoji = "🌧"
                elif w_id >= 600:
                    emoji = "❄️"
                elif w_id >= 300:
                    emoji = "🌦"
                elif w_id >= 200:
                    emoji = "⛈"
                else:
                    emoji = "🌡"
                
                # Совет по одежде
                if temp < 10:
                    advice = "🧤 Оденьтесь теплее!"
                elif temp < 20:
                    advice = "🧥 Можно в легкой куртке."
                else:
                    advice = "👕 Наденьте футболку!"
                
                # Совет по зонту
                if w_id < 600 and w_id >= 200:
                    advice += " И возьмите зонт! ☔️"

                report = f"{emoji} <b>{name}</b>\n🌡 {temp}°C, {desc.capitalize()}\n\n💡 {advice}"
                return report, name, tz_offset
                
        except asyncio.TimeoutError:
            print("Таймаут при запросе к API")
            return None
        except Exception as e:
            print(f"Ошибка при запросе погоды: {e}")
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
    await msg.answer("Привет! Давай настроим рассылку погоды.\nВыбери время:", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    geo_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]], 
        resize_keyboard=True
    )
    await call.message.edit_text(f"✅ Время установлено на {t}:00.\nТеперь отправь локацию или напиши город.")
    await call.message.answer("Жду город...", reply_markup=geo_kb)
    await call.answer()

@dp.message(F.location)
async def handle_location(msg: types.Message):
    coords = {"lat": msg.location.latitude, "lon": msg.location.longitude}
    data = await get_weather(coords)
    if data:
        report, city, tz = data
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"Город определен: {city}!\n\n{report}", 
                        reply_markup=ReplyKeyboardRemove(), 
                        parse_mode="HTML")
    else:
        await msg.answer("❌ Ошибка связи с сервером погоды. Попробуй написать город текстом.")

@dp.message()
async def handle_city(msg: types.Message):
    data = await get_weather(msg.text)
    if data:
        report, city, tz = data
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"✅ Город {city} сохранен!\n\n{report}", 
                        parse_mode="HTML")
    else:
        await msg.answer("❌ Город не найден. Напиши, например: Москва")

# --- РАССЫЛКА ПО МЕСТНОМУ ВРЕМЕНИ ---
async def mailing():
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if now_utc.minute == 0:
                conn = sqlite3.connect('weather_bot.db')
                cur = conn.cursor()
                cur.execute('SELECT id, city, time, timezone FROM users WHERE city IS NOT NULL AND city != ""')
                users = cur.fetchall()
                conn.close()
                
                for u_id, city, target_h, tz_off in users:
                    if not city:
                        continue
                        
                    user_local = now_utc + datetime.timedelta(seconds=tz_off)
                    if user_local.hour == target_h:
                        weather_data = await get_weather(city)
                        if weather_data:
                            report, _, _ = weather_data
                            try: 
                                await bot.send_message(u_id, f"☀️ Доброе утро!\n\n{report}", parse_mode="HTML")
                            except Exception as e:
                                print(f"Не удалось отправить сообщение пользователю {u_id}: {e}")
                await asyncio.sleep(61)
            await asyncio.sleep(30)
        except Exception as e:
            print(f"Ошибка в рассылке: {e}")
            await asyncio.sleep(60)

async def main():
    init_db()
    # Проверяем наличие API ключа
    if not WEATHER_API_KEY:
        print("ОШИБКА: Не установлен WEATHER_API_KEY")
        return
        
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
