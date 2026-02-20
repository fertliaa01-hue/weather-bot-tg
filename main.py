import asyncio
import sqlite3
import aiohttp
import datetime
import logging
import math
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

def get_uv_description(uvi):
    """Получить описание уровня UV-индекса [citation:5][citation:9]"""
    if uvi <= 2:
        return "🟢 Низкий", "Нет опасности"
    elif uvi <= 5:
        return "🟡 Умеренный", "Используйте солнцезащитный крем"
    elif uvi <= 7:
        return "🟠 Высокий", "С 11 до 16 часов оставайтесь в тени"
    elif uvi <= 10:
        return "🔴 Очень высокий", "Обязательно используйте защиту от солнца"
    else:
        return "🟣 Экстремальный", "Лучше не выходить на солнце"

def get_uv_emoji(uvi):
    """Получить эмодзи для UV-индекса"""
    if uvi <= 2:
        return "☀️"
    elif uvi <= 5:
        return "☀️☀️"
    elif uvi <= 7:
        return "☀️☀️☀️"
    elif uvi <= 10:
        return "☀️☀️☀️☀️"
    else:
        return "☀️☀️☀️☀️☀️"

def get_kp_description(kp):
    """Получить описание уровня геомагнитной активности"""
    if kp < 4:
        return "🟢 Спокойная", "Магнитных бурь нет"
    elif kp == 4:
        return "🟡 Небольшое возмущение", "Метеочувствительные люди могут ощутить дискомфорт"
    elif kp == 5:
        return "🟠 Слабая буря", "G1 - возможны перепады давления, головные боли"
    elif kp == 6:
        return "🔴 Умеренная буря", "G2 - скачки давления, ухудшение самочувствия"
    elif kp == 7:
        return "🔴 Сильная буря", "G3 - сильная нагрузка на организм"
    elif kp == 8:
        return "🟣 Очень сильная буря", "G4 - серьезное ухудшение самочувствия"
    else:
        return "🟣 Экстремальная буря", "G5 - возможны сбои в работе техники"

def get_kp_emoji(kp):
    """Получить эмодзи для Kp-индекса"""
    if kp < 4:
        return "🌙"
    elif kp == 4:
        return "🌙✨"
    elif kp == 5:
        return "🌙⭐"
    elif kp == 6:
        return "⭐🌙"
    elif kp == 7:
        return "⭐⭐"
    else:
        return "🌟🌟🌟"

async def get_geomagnetic_data():
    """Получить данные о геомагнитной активности от NOAA"""
    url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка получения геомагнитных данных: {resp.status}")
                    return None
                
                data = await resp.json()
                
                # Данные приходят в формате: [время, kp]
                # Последняя запись - текущее значение
                latest = data[-1]
                kp = float(latest[1])
                
                # Предыдущее значение для тренда
                prev = data[-2]
                prev_kp = float(prev[1])
                
                trend = "↗️" if kp > prev_kp else "↘️" if kp < prev_kp else "➡️"
                
                return kp, trend
                
        except Exception as e:
            logger.error(f"Ошибка при получении геомагнитных данных: {e}")
            return None

async def get_weather_with_uv(city_or_coords):
    """Получить текущую погоду с UV-индексом через One Call API 3.0 [citation:5][citation:8]"""
    
    # Сначала получаем координаты города или используем переданные
    if isinstance(city_or_coords, dict):
        lat = city_or_coords['lat']
        lon = city_or_coords['lon']
        city_name = None
    else:
        # Получаем координаты по названию города
        geo_url = "https://api.openweathermap.org/geo/1.0/direct"
        geo_params = {
            'q': city_or_coords,
            'limit': 1,
            'appid': WEATHER_API_KEY
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(geo_url, params=geo_params, timeout=10) as resp:
                    if resp.status != 200:
                        return None, "❌ Город не найден", None, None, None
                    
                    geo_data = await resp.json()
                    if not geo_data:
                        return None, "❌ Город не найден", None, None, None
                    
                    lat = geo_data[0]['lat']
                    lon = geo_data[0]['lon']
                    city_name = geo_data[0].get('local_names', {}).get('ru', geo_data[0]['name'])
            except Exception as e:
                logger.error(f"Ошибка геокодирования: {e}")
                return None, "❌ Ошибка определения координат", None, None, None
    
    # Теперь получаем погоду через One Call API 3.0
    url = "https://api.openweathermap.org/data/3.0/onecall"
    
    params = {
        'appid': WEATHER_API_KEY,
        'lat': lat,
        'lon': lon,
        'units': 'metric',
        'lang': 'ru',
        'exclude': 'minutely,daily'  # Исключаем ненужные данные для экономии
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            logger.info(f"Запрос погоды с UV по координатам: {lat}, {lon}")
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ошибка One Call API: статус {resp.status}, ответ: {error_text}")
                    
                    if resp.status == 401:
                        return None, "❌ Неверный API ключ OpenWeatherMap", None, None, None
                    else:
                        return None, f"❌ Ошибка сервера погоды (код {resp.status})", None, None, None
                
                res = await resp.json()
                
                # Получаем данные текущей погоды
                current = res['current']
                
                # Основная информация
                w_info = current['weather'][0]
                w_id = w_info['id']
                temp = round(current['temp'])
                feels_like = round(current['feels_like'])
                desc = w_info['description']
                tz_offset = res.get('timezone_offset', 10800)
                
                # Дополнительная информация
                humidity = current['humidity']
                pressure = round(current['pressure'] * 0.750062)  # переводим в мм рт. ст.
                wind_speed = current['wind_speed']
                wind_deg = current.get('wind_deg', 0)
                wind_gust = current.get('wind_gust', 0)
                clouds = current['clouds']
                uvi = current.get('uvi', 0)
                
                # Если не получили название города из геокодинга, используем координаты
                if not city_name:
                    city_name = f"📍 {lat:.2f}, {lon:.2f}"
                
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
                
                # Получаем UV информацию
                uv_desc, uv_advice = get_uv_description(uvi)
                uv_emoji = get_uv_emoji(uvi)
                
                # Получаем геомагнитные данные
                geomagnetic = await get_geomagnetic_data()
                if geomagnetic:
                    kp, kp_trend = geomagnetic
                    kp_desc, kp_advice = get_kp_description(kp)
                    kp_emoji = get_kp_emoji(kp)
                    kp_text = f"\n{kp_emoji} Магнитное поле: Kp={kp:.1f} {kp_trend}\n{kp_desc}"
                else:
                    kp_text = ""
                    kp_advice = ""
                
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
                
                # Формируем отчет с UV и магнитными данными
                report = (
                    f"{weather_emoji} <b>{city_name}</b>\n"
                    f"🌡 {temp}°C (ощущается как {feels_like}°C)\n"
                    f"{desc.capitalize()}\n\n"
                    f"{humidity_emoji} Влажность: {humidity}%\n"
                    f"{wind_emoji} Ветер: {wind_speed} м/с, {wind_dir}"
                )
                
                if wind_gust > 0:
                    report += f" (порывы до {wind_gust} м/с)"
                
                report += f"\n📊 Давление: {pressure} мм рт.ст.\n"
                report += f"☁️ Облачность: {clouds}%\n\n"
                report += f"☀️ <b>Солнечная активность:</b>\n"
                report += f"{uv_emoji} UV-индекс: {uvi:.1f} - {uv_desc}\n💡 {uv_advice}\n"
                
                if kp_text:
                    report += f"\n🧲 <b>Геомагнитная обстановка:</b>\n{kp_text}\n💡 {kp_advice}\n"
                
                report += f"\n💡 {advice}"
                
                return (report, city_name, tz_offset, None, {'lat': lat, 'lon': lon})
                
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
    """Получить почасовой прогноз на 24 часа с UV-индексом"""
    url = "https://api.openweathermap.org/data/3.0/onecall"
    
    params = {
        'appid': WEATHER_API_KEY,
        'lat': lat,
        'lon': lon,
        'units': 'metric',
        'lang': 'ru',
        'exclude': 'current,minutely,daily'
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None, "❌ Не удалось получить прогноз"
                
                res = await resp.json()
                
                forecast_text = "📅 <b>Почасовой прогноз на 24 часа:</b>\n\n"
                
                for i, item in enumerate(res['hourly'][:8]):  # Берем 8 записей (24 часа с шагом 3 часа)
                    dt = datetime.datetime.fromtimestamp(item['dt'])
                    time_str = dt.strftime("%H:%M")
                    temp = round(item['temp'])
                    weather = item['weather'][0]
                    desc = weather['description']
                    uvi = item.get('uvi', 0)
                    
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
                    
                    # Эмодзи для UV
                    if uvi <= 2:
                        uv_emoji = "☀️"
                    elif uvi <= 5:
                        uv_emoji = "☀️☀️"
                    elif uvi <= 7:
                        uv_emoji = "☀️☀️☀️"
                    else:
                        uv_emoji = "☀️☀️☀️☀️"
                    
                    forecast_text += f"{time_emoji} <b>{time_str}</b> {weather_emoji} {temp}°C, {desc} | UV: {uvi:.1f} {uv_emoji}\n"
                
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

@dp.message(Command("uv"))
async def uv_info(msg: types.Message):
    """Команда для получения информации о UV-индексе"""
    await msg.answer("☀️ <b>Что такое UV-индекс?</b>\n\n"
                    "UV-индекс показывает уровень ультрафиолетового излучения.\n\n"
                    "🟢 <b>0-2 (Низкий):</b> Безопасно\n"
                    "🟡 <b>3-5 (Умеренный):</b> Используйте солнцезащитный крем\n"
                    "🟠 <b>6-7 (Высокий):</b> С 11 до 16 часов оставайтесь в тени\n"
                    "🔴 <b>8-10 (Очень высокий):</b> Обязательно используйте защиту\n"
                    "🟣 <b>11+ (Экстремальный):</b> Лучше не выходить на солнце", 
                    parse_mode="HTML")

@dp.message(Command("magnet"))
async def magnet_info(msg: types.Message):
    """Команда для получения информации о магнитных бурях"""
    geomagnetic = await get_geomagnetic_data()
    if geomagnetic:
        kp, trend = geomagnetic
        kp_desc, kp_advice = get_kp_description(kp)
        kp_emoji = get_kp_emoji(kp)
        
        await msg.answer(f"🧲 <b>Геомагнитная обстановка сейчас:</b>\n\n"
                        f"{kp_emoji} Kp-индекс: {kp:.1f} {trend}\n"
                        f"{kp_desc}\n\n"
                        f"💡 {kp_advice}\n\n"
                        f"<b>Шкала магнитных бурь:</b>\n"
                        f"• Kp < 4: Спокойно\n"
                        f"• Kp = 4: Небольшое возмущение\n"
                        f"• Kp = 5: Слабая буря (G1)\n"
                        f"• Kp = 6: Умеренная буря (G2)\n"
                        f"• Kp = 7: Сильная буря (G3)\n"
                        f"• Kp >= 8: Очень сильная буря (G4-G5)",
                        parse_mode="HTML")
    else:
        await msg.answer("❌ Не удалось получить данные о геомагнитной обстановке")

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    geo_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]], 
        resize_keyboard=True
    )
    await call.message.edit_text(f"✅ Время установлено на {t}:00.\nТеперь отправь локацию или напиши город.")
    await call.message.answer("Жду город...\n\nДоступные команды:\n/uv - информация о UV-индексе\n/magnet - магнитные бури", reply_markup=geo_kb)
    await call.answer()

@dp.message(F.location)
async def handle_location(msg: types.Message):
    coords = {"lat": msg.location.latitude, "lon": msg.location.longitude}
    result = await get_weather_with_uv(coords)
    
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
        
    result = await get_weather_with_uv(msg.text)
    
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
    result = await get_weather_with_uv(coords)
    
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
                        result = await get_weather_with_uv(city)
                        
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
    
    # Проверяем подключение к API
    logger.info("Проверка подключения к OpenWeatherMap One Call API...")
    test_result = await get_weather_with_uv("Москва")
    if test_result[0]:
        logger.info("✅ Подключение к OpenWeatherMap работает")
    else:
        logger.error(f"❌ Ошибка подключения к OpenWeatherMap: {test_result[1]}")
    
    # Проверяем подключение к NOAA
    logger.info("Проверка подключения к NOAA для геомагнитных данных...")
    geomagnetic = await get_geomagnetic_data()
    if geomagnetic:
        logger.info(f"✅ Подключение к NOAA работает, текущий Kp: {geomagnetic[0]}")
    else:
        logger.warning("⚠️ Не удалось подключиться к NOAA, магнитные бури будут недоступны")
    
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
