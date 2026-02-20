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

# --- ФУНКЦИИ ДЛЯ ПОГОДЫ ---
def get_wind_direction(deg):
    """Получить направление ветра по градусам"""
    directions = ['северный', 'северо-восточный', 'восточный', 'юго-восточный', 
                  'южный', 'юго-западный', 'западный', 'северо-западный']
    ix = round(deg / 45) % 8
    return directions[ix]

def get_wind_emoji(speed):
    """Получить эмодзи для скорости ветра"""
    if speed < 1:
        return "🍃"
    elif speed < 3:
        return "🌬"
    elif speed < 8:
        return "💨"
    else:
        return "🌪"

def get_humidity_emoji(humidity):
    """Получить эмодзи для влажности"""
    if humidity < 30:
        return "🏜"
    elif humidity < 60:
        return "🌿"
    else:
        return "💧"

async def get_weather(city_or_coords):
    """Получить текущую погоду"""
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
            async with session.get(url, params=params, timeout=10) as resp:
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
                
                # Проверяем наличие необходимых полей
                if 'weather' not in res or 'main' not in res:
                    logger.error(f"Неожиданный ответ API: {res}")
                    return None, "❌ Неверный формат ответа от сервера"
                
                # Основная информация
                w_info = res['weather'][0]
                w_id = w_info['id']
                temp = round(res['main']['temp'])
                feels_like = round(res['main']['feels_like'])
                desc = w_info['description']
                name = res['name']
                tz_offset = res.get('timezone', 10800)
                
                # Дополнительная информация
                humidity = res['main']['humidity']
                pressure = round(res['main']['pressure'] * 0.750062)  # переводим в мм рт. ст.
                wind_speed = res['wind']['speed']
                wind_deg = res['wind'].get('deg', 0)
                wind_gust = res['wind'].get('gust', 0)
                clouds = res['clouds']['all']
                
                # Выбор эмодзи для погоды
                if w_id == 800:
                    weather_emoji = "☀️"
                elif w_id > 800:
                    weather_emoji = "☁️"
                elif w_id >= 500:
                    weather_emoji = "🌧"
                elif w_id >= 600:
                    weather_emoji = "❄️"
                elif w_id >= 300:
                    weather_emoji = "🌦"
                elif w_id >= 200:
                    weather_emoji = "⛈"
                else:
                    weather_emoji = "🌡"
                
                # Получаем эмодзи для ветра и влажности
                wind_emoji = get_wind_emoji(wind_speed)
                humidity_emoji = get_humidity_emoji(humidity)
                wind_dir = get_wind_direction(wind_deg)
                
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
                
                # Формируем отчет с дополнительной информацией
                report = (
                    f"{weather_emoji} <b>{name}</b>\n"
                    f"🌡 {temp}°C (ощущается как {feels_like}°C)\n"
                    f"{desc.capitalize()}\n\n"
                    f"{humidity_emoji} Влажность: {humidity}%\n"
                    f"{wind_emoji} Ветер: {wind_speed} м/с, {wind_dir}"
                )
                
                if wind_gust > 0:
                    report += f" (порывы до {wind_gust} м/с)"
                
                report += f"\n📊 Давление: {pressure} мм рт.ст.\n"
                report += f"☁️ Облачность: {clouds}%\n\n"
                report += f"💡 {advice}"
                
                # Добавляем кнопку для почасового прогноза
                return (report, name, tz_offset, None, res['coord'])
                
        except asyncio.TimeoutError:
            logger.error("Таймаут при запросе к API")
            return None, "❌ Превышено время ожидания ответа от сервера", None, None, None
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка клиента: {e}")
            return None, f"❌ Ошибка сети: {e}", None, None, None
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
            return None, f"❌ Неизвестная ошибка: {e}", None, None, None

async def get_hourly_forecast(lat, lon):
    """Получить почасовой прогноз на 24 часа"""
    url = "https://api.openweathermap.org/data/2.5/forecast"
    
    params = {
        'appid': WEATHER_API_KEY,
        'lat': lat,
        'lon': lon,
        'units': 'metric',
        'lang': 'ru',
        'cnt': 8  # Получаем прогноз на 24 часа (каждые 3 часа)
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None, "❌ Не удалось получить прогноз"
                
                res = await resp.json()
                
                forecast_text = "📅 <b>Почасовой прогноз на 24 часа:</b>\n\n"
                
                for item in res['list']:
                    dt = datetime.datetime.fromtimestamp(item['dt'])
                    time_str = dt.strftime("%H:%M")
                    temp = round(item['main']['temp'])
                    weather = item['weather'][0]
                    desc = weather['description']
                    
                    # Эмодзи для времени суток
                    if 6 <= dt.hour < 12:
                        time_emoji = "🌅"
                    elif 12 <= dt.hour < 18:
                        time_emoji = "☀️"
                    elif 18 <= dt.hour < 23:
                        time_emoji = "🌆"
                    else:
                        time_emoji = "🌙"
                    
                    # Эмодзи для погоды
                    weather_id = weather['id']
                    if weather_id == 800:
                        weather_emoji = "☀️"
                    elif weather_id > 800:
                        weather_emoji = "☁️"
                    elif weather_id >= 500:
                        weather_emoji = "🌧"
                    elif weather_id >= 600:
                        weather_emoji = "❄️"
                    elif weather_id >= 300:
                        weather_emoji = "🌦"
                    elif weather_id >= 200:
                        weather_emoji = "⛈"
                    else:
                        weather_emoji = "🌡"
                    
                    forecast_text += f"{time_emoji} <b>{time_str}</b> {weather_emoji} {temp}°C, {desc}\n"
                
                return forecast_text, None
                
        except Exception as e:
            logger.error(f"Ошибка получения прогноза: {e}")
            return None, "❌ Ошибка получения прогноза"

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
    
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _, coord = result
        
        # Сохраняем город
        update_user(msg.chat.id, city=city, timezone=tz)
        
        # Создаем клавиатуру с кнопкой для почасового прогноза
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📅 Почасовой прогноз", callback_data=f"forecast_{coord['lat']}_{coord['lon']}")
        ]])
        
        await msg.answer(f"📍 Город определен: {city}!\n\n{report}", 
                        reply_markup=kb,
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
    
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _, coord = result
        
        # Сохраняем город
        update_user(msg.chat.id, city=city, timezone=tz)
        
        # Создаем клавиатуру с кнопкой для почасового прогноза
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📅 Почасовой прогноз", callback_data=f"forecast_{coord['lat']}_{coord['lon']}")
        ]])
        
        await msg.answer(f"✅ Город {city} сохранен!\n\n{report}", 
                        reply_markup=kb,
                        parse_mode="HTML")
    else:
        error_msg = result[1] if len(result) > 1 else "❌ Город не найден"
        await msg.answer(f"{error_msg}\nНапиши, например: Москва")

@dp.callback_query(F.data.startswith("forecast_"))
async def show_forecast(call: types.CallbackQuery):
    """Показать почасовой прогноз"""
    await call.answer("Загружаю прогноз...")
    
    # Извлекаем координаты из callback_data
    _, lat, lon = call.data.split('_')
    lat, lon = float(lat), float(lon)
    
    forecast, error = await get_hourly_forecast(lat, lon)
    
    if forecast:
        # Добавляем кнопку "Назад" к текущей погоде
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 К текущей погоде", callback_data=f"back_{lat}_{lon}")
        ]])
        
        await call.message.edit_text(forecast, 
                                    reply_markup=kb,
                                    parse_mode="HTML")
    else:
        await call.message.answer(error or "❌ Не удалось получить прогноз")

@dp.callback_query(F.data.startswith("back_"))
async def back_to_current(call: types.CallbackQuery):
    """Вернуться к текущей погоде"""
    await call.answer()
    
    # Извлекаем координаты
    _, lat, lon = call.data.split('_')
    lat, lon = float(lat), float(lon)
    
    # Получаем текущую погоду
    coords = {"lat": lat, "lon": lon}
    result = await get_weather(coords)
    
    if result[0]:
        report, city, tz, _, coord = result
        
        # Создаем клавиатуру с кнопкой для почасового прогноза
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📅 Почасовой прогноз", callback_data=f"forecast_{coord['lat']}_{coord['lon']}")
        ]])
        
        await call.message.edit_text(f"📍 {city}\n\n{report}", 
                                    reply_markup=kb,
                                    parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Не удалось получить погоду")

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
                            report, _, _, _, coord = result
                            
                            # Добавляем кнопку для почасового прогноза
                            kb = InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="📅 Почасовой прогноз", callback_data=f"forecast_{coord['lat']}_{coord['lon']}")
                            ]])
                            
                            try: 
                                await bot.send_message(u_id, 
                                                      f"☀️ <b>Доброе утро!</b>\n\n{report}", 
                                                      reply_markup=kb,
                                                      parse_mode="HTML")
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
