import asyncio
import sqlite3
import aiohttp
import datetime
import logging
from os import getenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# Включаем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
API_TOKEN = getenv('BOT_TOKEN')
WEATHER_API_KEY = getenv('WEATHER_API_KEY')

# Проверяем наличие токенов
if not API_TOKEN:
    logger.error("Не установлен BOT_TOKEN")
    exit(1)
if not WEATHER_API_KEY:
    logger.error("Не установлен WEATHER_API_KEY")
    exit(1)

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
    logger.info("База данных инициализирована")

def update_user(user_id, city=None, time=None, timezone=None):
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    
    # Проверяем, существует ли пользователь
    cur.execute('SELECT id FROM users WHERE id = ?', (user_id,))
    exists = cur.fetchone()
    
    if not exists:
        # Вставляем нового пользователя
        cur.execute('''INSERT INTO users (id, city, time, timezone) 
                       VALUES (?, ?, ?, ?)''',
                   (user_id, city if city else '', time if time else 8, timezone if timezone else 10800))
        logger.info(f"Новый пользователь {user_id} добавлен")
    else:
        # Обновляем существующего
        if city:
            cur.execute('UPDATE users SET city = ? WHERE id = ?', (city, user_id))
            logger.info(f"Обновлен город для пользователя {user_id}: {city}")
        if time is not None:
            cur.execute('UPDATE users SET time = ? WHERE id = ?', (int(time), user_id))
        if timezone is not None:
            cur.execute('UPDATE users SET timezone = ? WHERE id = ?', (int(timezone), user_id))
    
    conn.commit()
    conn.close()

# --- ПОЛУЧЕНИЕ ПОГОДЫ ---
async def get_weather(city_or_coords):
    # Правильный URL для API OpenWeatherMap
    url = "https://api.openweathermap.org/data/2.5/weather"
    
    params = {
        'appid': WEATHER_API_KEY,
        'units': 'metric',
        'lang': 'ru'
    }
    
    if isinstance(city_or_coords, dict):
        params.update(city_or_coords)
        logger.info(f"Запрос погоды по координатам: {city_or_coords}")
    else:
        params['q'] = city_or_coords
        logger.info(f"Запрос погоды по городу: {city_or_coords}")

    async with aiohttp.ClientSession() as session:
        try:
            logger.info(f"Отправка запроса к {url} с params={params}")
            async with session.get(url, params=params, timeout=10) as resp:
                logger.info(f"Статус ответа: {resp.status}")
                
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ошибка API: статус {resp.status}, ответ: {error_text}")
                    
                    if resp.status == 401:
                        return None, "❌ Неверный API ключ OpenWeatherMap"
                    elif resp.status == 404:
                        return None, "❌ Город не найден"
                    else:
                        return None, f"❌ Ошибка сервера погоды (код {resp.status})"
                
                res = await resp.json()
                logger.info(f"Получен ответ от API: {res}")
                
                # Проверяем наличие необходимых полей
                if 'weather' not in res or 'main' not in res:
                    logger.error(f"Неожиданный ответ API: {res}")
                    return None, "❌ Неверный формат ответа от сервера"
                
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
                
                # ИСПРАВЛЕНО: теперь возвращаем кортеж из 4 элементов
                report = f"{emoji} <b>{name}</b>\n🌡 {temp}°C, {desc.capitalize()}\n\n💡 {advice}"
                return (report, name, tz_offset, None)  # Добавляем None для сообщения об ошибке
                
        except asyncio.TimeoutError:
            logger.error("Таймаут при запросе к API")
            return None, "❌ Превышено время ожидания ответа от сервера"
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка клиента: {e}")
            return None, f"❌ Ошибка сети: {e}"
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
            return None, f"❌ Неизвестная ошибка: {e}"

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
    result = await get_weather(coords)
    
    # ИСПРАВЛЕНО: обрабатываем новый формат возврата
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _ = result
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"📍 Город определен: {city}!\n\n{report}", 
                        reply_markup=ReplyKeyboardRemove(), 
                        parse_mode="HTML")
    else:
        error_msg = result[1] if len(result) > 1 else "❌ Ошибка получения погоды"
        await msg.answer(f"{error_msg}\nПопробуй написать город текстом.")

@dp.message()
async def handle_city(msg: types.Message):
    # Игнорируем команды
    if msg.text.startswith('/'):
        return
        
    result = await get_weather(msg.text)
    
    # ИСПРАВЛЕНО: обрабатываем новый формат возврата
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _ = result
        update_user(msg.chat.id, city=city, timezone=tz)
        await msg.answer(f"✅ Город {city} сохранен!\n\n{report}", 
                        parse_mode="HTML")
    else:
        error_msg = result[1] if len(result) > 1 else "❌ Город не найден"
        await msg.answer(f"{error_msg}\nНапиши, например: Москва")

# --- РАССЫЛКА ПО МЕСТНОМУ ВРЕМЕНИ ---
async def mailing():
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if now_utc.minute == 0:
                logger.info(f"Запуск рассылки в {now_utc}")
                
                conn = sqlite3.connect('weather_bot.db')
                cur = conn.cursor()
                cur.execute('SELECT id, city, time, timezone FROM users WHERE city IS NOT NULL AND city != ""')
                users = cur.fetchall()
                conn.close()
                
                logger.info(f"Найдено {len(users)} пользователей для рассылки")
                
                for u_id, city, target_h, tz_off in users:
                    if not city:
                        continue
                        
                    user_local = now_utc + datetime.timedelta(seconds=tz_off)
                    if user_local.hour == target_h:
                        logger.info(f"Отправка погоды пользователю {u_id} в {user_local.hour}:00")
                        result = await get_weather(city)
                        
                        if result[0]:  # если есть отчет о погоде
                            report, _, _, _ = result
                            try: 
                                await bot.send_message(u_id, f"☀️ Доброе утро!\n\n{report}", parse_mode="HTML")
                                logger.info(f"Успешно отправлено пользователю {u_id}")
                            except Exception as e:
                                logger.error(f"Не удалось отправить сообщение пользователю {u_id}: {e}")
                        else:
                            logger.error(f"Не удалось получить погоду для пользователя {u_id}: {result[1]}")
                
                await asyncio.sleep(61)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка в рассылке: {e}")
            await asyncio.sleep(60)

async def main():
    logger.info("Запуск бота...")
    init_db()
    
    # Тестовый запрос к API
    logger.info("Проверка подключения к OpenWeatherMap...")
    test_result = await get_weather("Москва")
    if test_result[0]:
        logger.info("✅ Подключение к OpenWeatherMap работает")
    else:
        logger.error(f"❌ Ошибка подключения к OpenWeatherMap: {test_result[1]}")
    
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
