import asyncio
import sqlite3
import aiohttp
import datetime
import logging
import os
import math
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# Включаем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
# Пробуем получить токены из переменных окружения
API_TOKEN = os.getenv('BOT_TOKEN')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')

# ЕСЛИ НЕ РАБОТАЕТ С ПЕРЕМЕННЫМИ ОКРУЖЕНИЯ, 
# РАСКОММЕНТИРУЙТЕ СЛЕДУЮЩИЕ СТРОКИ И ВСТАВЬТЕ ВАШИ КЛЮЧИ:
# API_TOKEN = "7380636107:AAHwIamzDnWliie9ykZ77Og9iXm58yGz-hE"
# WEATHER_API_KEY = "b50d4e07ca1d8d3e24ffc7c7a6e27a1c"

# Проверяем наличие токенов
if not API_TOKEN:
    logger.error("❌ Не установлен BOT_TOKEN")
    logger.error("Как исправить:")
    logger.error("1. Создайте файл .env в папке с ботом")
    logger.error("2. Добавьте в него строки:")
    logger.error("   BOT_TOKEN=ваш_токен_бота")
    logger.error("   WEATHER_API_KEY=ваш_ключ_openweather")
    logger.error("3. Или вставьте ключи прямо в код (раскомментируйте строки выше)")
    exit(1)

if not WEATHER_API_KEY:
    logger.error("❌ Не установлен WEATHER_API_KEY")
    logger.error("Получите ключ на https://openweathermap.org/api")
    exit(1)

logger.info(f"✅ API токен бота загружен: {API_TOKEN[:5]}...")
logger.info(f"✅ Weather API ключ загружен: {WEATHER_API_KEY[:5]}...")

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
    logger.info("✅ База данных инициализирована")

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

def estimate_uv_from_sun(hour, clouds):
    """Примерно оценить UV-индекс на основе времени суток и облачности"""
    if hour < 8 or hour > 18:
        return 0.5  # Низкий
    elif 11 <= hour <= 15:
        base_uv = 6.0  # Высокий в полдень
    else:
        base_uv = 3.0  # Умеренный
    
    # Облачность уменьшает UV
    cloud_factor = max(0.2, 1 - (clouds / 100) * 0.7)
    return round(base_uv * cloud_factor, 1)

def get_uv_description(uvi):
    """Получить описание уровня UV-индекса"""
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

# --- ФУНКЦИИ ДЛЯ ФАЗ ЛУНЫ ---
def get_moon_phase(date=None):
    """Рассчитать фазу луны на указанную дату"""
    if date is None:
        date = datetime.datetime.now()
    
    # Известное новолуние (пример)
    known_new_moon = datetime.datetime(2000, 1, 6, 18, 14)
    
    # Синодический месяц (период смены фаз) в днях
    synodic_month = 29.530588853
    
    # Разница в днях
    delta = date - known_new_moon
    days = delta.days + delta.seconds / 86400.0
    
    # Текущая фаза (0-1, где 0 - новолуние, 0.5 - полнолуние)
    phase = (days % synodic_month) / synodic_month
    
    return phase

def get_moon_emoji(phase):
    """Получить эмодзи для фазы луны"""
    if phase < 0.03 or phase > 0.97:
        return "🌑"  # Новолуние
    elif phase < 0.13:
        return "🌒"  # Растущий серп
    elif phase < 0.25:
        return "🌓"  # Первая четверть
    elif phase < 0.38:
        return "🌔"  # Растущая луна
    elif phase < 0.47:
        return "🌕"  # Полнолуние (приближается)
    elif phase < 0.53:
        return "🌕"  # Полнолуние
    elif phase < 0.62:
        return "🌖"  # Убывающая луна
    elif phase < 0.75:
        return "🌗"  # Последняя четверть
    elif phase < 0.88:
        return "🌘"  # Убывающий серп
    else:
        return "🌑"  # Новолуние (приближается)

def get_moon_name(phase):
    """Получить название фазы луны"""
    if phase < 0.03 or phase > 0.97:
        return "Новолуние"
    elif phase < 0.13:
        return "Растущий серп"
    elif phase < 0.25:
        return "Первая четверть"
    elif phase < 0.38:
        return "Растущая луна"
    elif phase < 0.47:
        return "Прибывающая луна"
    elif phase < 0.53:
        return "Полнолуние"
    elif phase < 0.62:
        return "Убывающая луна"
    elif phase < 0.75:
        return "Последняя четверть"
    elif phase < 0.88:
        return "Убывающий серп"
    else:
        return "Старая луна"

def get_moon_illumination(phase):
    """Получить процент освещенности луны"""
    # Освещенность от 0 до 100%
    illumination = math.sin(phase * math.pi) ** 2 * 100
    return round(illumination, 1)

def get_zodiac_sign(date=None):
    """Определить знак зодиака по дате (для дополнительной информации)"""
    if date is None:
        date = datetime.datetime.now()
    
    month = date.month
    day = date.day
    
    if (month == 3 and day >= 21) or (month == 4 and day <= 19):
        return "♈ Овен"
    elif (month == 4 and day >= 20) or (month == 5 and day <= 20):
        return "♉ Телец"
    elif (month == 5 and day >= 21) or (month == 6 and day <= 20):
        return "♊ Близнецы"
    elif (month == 6 and day >= 21) or (month == 7 and day <= 22):
        return "♋ Рак"
    elif (month == 7 and day >= 23) or (month == 8 and day <= 22):
        return "♌ Лев"
    elif (month == 8 and day >= 23) or (month == 9 and day <= 22):
        return "♍ Дева"
    elif (month == 9 and day >= 23) or (month == 10 and day <= 22):
        return "♎ Весы"
    elif (month == 10 and day >= 23) or (month == 11 and day <= 21):
        return "♏ Скорпион"
    elif (month == 11 and day >= 22) or (month == 12 and day <= 21):
        return "♐ Стрелец"
    elif (month == 12 and day >= 22) or (month == 1 and day <= 19):
        return "♑ Козерог"
    elif (month == 1 and day >= 20) or (month == 2 and day <= 18):
        return "♒ Водолей"
    else:
        return "♓ Рыбы"

async def get_moon_data():
    """Получить полные данные о луне"""
    now = datetime.datetime.now()
    phase = get_moon_phase(now)
    emoji = get_moon_emoji(phase)
    name = get_moon_name(phase)
    illumination = get_moon_illumination(phase)
    zodiac = get_zodiac_sign(now)
    
    return {
        'phase': phase,
        'emoji': emoji,
        'name': name,
        'illumination': illumination,
        'zodiac': zodiac
    }

async def test_api_key():
    """Тестирование API ключа OpenWeatherMap"""
    test_url = "https://api.openweathermap.org/data/2.5/weather"
    test_params = {
        'q': 'London',
        'appid': WEATHER_API_KEY,
        'units': 'metric'
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(test_url, params=test_params, timeout=10) as resp:
                if resp.status == 200:
                    return True, "✅ API ключ работает!"
                elif resp.status == 401:
                    return False, "❌ API ключ недействителен (код 401)"
                else:
                    return False, f"❌ Ошибка API: код {resp.status}"
        except Exception as e:
            return False, f"❌ Ошибка подключения: {e}"

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

async def get_weather_data(city_or_coords):
    """Получить данные о погоде без форматирования"""
    
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
                    return None, f"❌ Ошибка: код {resp.status}"
                
                res = await resp.json()
                return res, None
                
        except Exception as e:
            return None, f"❌ Ошибка: {e}"

def format_weather_report(weather_data, moon_data, geomagnetic, estimated_uvi, uv_desc, uv_advice):
    """Форматировать полный отчет о погоде с восходом и закатом"""
    
    now = datetime.datetime.now()
    hour = now.hour
    
    # Основная информация
    w_info = weather_data['weather'][0]
    w_id = w_info['id']
    temp = round(weather_data['main']['temp'])
    feels_like = round(weather_data['main']['feels_like'])
    desc = w_info['description']
    name = weather_data['name']
    
    # Дополнительная информация
    humidity = weather_data['main']['humidity']
    pressure = round(weather_data['main']['pressure'] * 0.750062)
    wind_speed = weather_data['wind']['speed']
    wind_deg = weather_data['wind'].get('deg', 0)
    wind_gust = weather_data['wind'].get('gust', 0)
    clouds = weather_data['clouds']['all']
    
    # НОВОЕ: Получаем время восхода и заката
    sunrise_timestamp = weather_data['sys']['sunrise']
    sunset_timestamp = weather_data['sys']['sunset']
    timezone_offset = weather_data['timezone']
    
    # Конвертируем UTC в местное время
    sunrise_time = datetime.datetime.fromtimestamp(sunrise_timestamp + timezone_offset).strftime("%H:%M")
    sunset_time = datetime.datetime.fromtimestamp(sunset_timestamp + timezone_offset).strftime("%H:%M")
    
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
    
    # НОВОЕ: Определяем, день сейчас или ночь
    current_local_time = now.timestamp() + timezone_offset
    is_day = sunrise_timestamp < current_local_time < sunset_timestamp
    
    # Формируем UV строку
    if 6 <= hour <= 20:
        uv_text = f"\n☀️ <b>Солнечная активность:</b>\nUV-индекс: {estimated_uvi:.1f} - {uv_desc}\n💡 {uv_advice}"
    else:
        uv_text = "\n🌙 Сейчас ночь, UV-индекс минимальный"
    
    # Формируем геомагнитную строку
    if geomagnetic:
        kp, kp_trend = geomagnetic
        kp_desc, kp_advice = get_kp_description(kp)
        kp_emoji = get_kp_emoji(kp)
        magnet_text = f"\n\n🧲 <b>Геомагнитная обстановка:</b>\n{kp_emoji} Kp={kp:.1f} {kp_trend} - {kp_desc}\n💡 {kp_advice}"
    else:
        magnet_text = ""
    
    # Формируем строку с луной
    moon_text = (
        f"\n\n🌙 <b>Луна сегодня:</b>\n"
        f"{moon_data['emoji']} {moon_data['name']}\n"
        f"💡 Освещенность: {moon_data['illumination']}%\n"
        f"♈ Знак зодиака: {moon_data['zodiac']}"
    )
    
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
    
    # НОВОЕ: Добавляем информацию о восходе и закате
    sun_text = f"\n\n🌅 <b>Восход и закат:</b>\n🌄 Восход: {sunrise_time}\n🌇 Закат: {sunset_time}"
    
    # Формируем полный отчет
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
    report += f"☁️ Облачность: {clouds}%\n"
    report += uv_text
    report += magnet_text
    report += moon_text
    report += sun_text  # НОВОЕ: Добавляем информацию о восходе/закате
    report += f"\n\n💡 {advice}"
    
    return report

async def get_weather_with_details(city_or_coords):
    """Получить текущую погоду со всеми деталями"""
    
    # Получаем данные о погоде
    weather_data, error = await get_weather_data(city_or_coords)
    
    if error or not weather_data:
        return None, error or "❌ Не удалось получить данные", None, None, None
    
    try:
        # Получаем текущее время для расчета UV
        now = datetime.datetime.now()
        hour = now.hour
        clouds = weather_data['clouds']['all']
        
        # Получаем геомагнитные данные
        geomagnetic = await get_geomagnetic_data()
        
        # Получаем данные о луне
        moon_data = await get_moon_data()
        
        # Оцениваем UV-индекс
        estimated_uvi = estimate_uv_from_sun(hour, clouds)
        uv_desc, uv_advice = get_uv_description(estimated_uvi)
        
        # Форматируем отчет
        report = format_weather_report(weather_data, moon_data, geomagnetic, estimated_uvi, uv_desc, uv_advice)
        
        # Сохраняем все данные для возврата
        full_data = {
            'weather': weather_data,
            'moon': moon_data,
            'geomagnetic': geomagnetic,
            'uvi': estimated_uvi,
            'uv_desc': uv_desc,
            'uv_advice': uv_advice,
            'report': report
        }
        
        return (report, weather_data['name'], weather_data.get('timezone', 10800), None, weather_data['coord'], full_data)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке данных: {e}")
        return None, "❌ Ошибка при обработке данных", None, None, None

async def get_hourly_forecast(lat, lon):
    """Получить почасовой прогноз на 24 часа через One Call API"""
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
    
    # Проверяем API ключ при старте
    api_ok, api_message = await test_api_key()
    if not api_ok:
        await msg.answer(f"⚠️ {api_message}\nБот может работать некорректно.")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="07:00", callback_data="set_7"),
        InlineKeyboardButton(text="08:00", callback_data="set_8"),
        InlineKeyboardButton(text="09:00", callback_data="set_9")
    ]])
    await msg.answer("Привет! Давай настроим рассылку погоды.\nВыбери время:", reply_markup=kb)

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    help_text = """
<b>🤖 Команды бота:</b>

/start - Начать настройку
/help - Показать эту справку
/uv - Информация об UV-индексе
/magnet - Информация о магнитных бурях
/moon - Информация о фазе луны
/weather - Показать погоду для сохраненного города
/test - Проверить работу API

<b>Как пользоваться:</b>
1. Выберите время для рассылки
2. Отправьте свою локацию или название города
3. Получайте ежедневную погоду с деталями

<b>В погоде отображается:</b>
• Температура и ощущение
• Влажность и ветер
• Давление и облачность
• UV-индекс (оценка)
• Магнитные бури
• Фаза луны
• Восход и закат
• Советы по одежде
    """
    await msg.answer(help_text, parse_mode="HTML")

@dp.message(Command("test"))
async def test_cmd(msg: types.Message):
    await msg.answer("🔄 Проверка API ключа...")
    api_ok, api_message = await test_api_key()
    await msg.answer(api_message)

@dp.message(Command("weather"))
async def weather_cmd(msg: types.Message):
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    cur.execute('SELECT city FROM users WHERE id = ?', (msg.from_user.id,))
    result = cur.fetchone()
    conn.close()
    
    if result and result[0]:
        city = result[0]
        await msg.answer(f"🔄 Получаю погоду для {city}...")
        result = await get_weather_with_details(city)
        
        if result[0]:
            report, city, tz, _, coord, full_data = result
            # Сохраняем полные данные в callback_data (координаты достаточно)
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📅 Почасовой прогноз", callback_data=f"forecast_{coord['lat']}_{coord['lon']}")
            ]])
            await msg.answer(report, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.answer(result[1])
    else:
        await msg.answer("❌ Город не сохранен. Отправьте локацию или название города.")

@dp.message(Command("uv"))
async def uv_info(msg: types.Message):
    await msg.answer("☀️ <b>Что такое UV-индекс?</b>\n\n"
                    "UV-индекс показывает уровень ультрафиолетового излучения.\n\n"
                    "🟢 <b>0-2 (Низкий):</b> Безопасно\n"
                    "🟡 <b>3-5 (Умеренный):</b> Используйте солнцезащитный крем\n"
                    "🟠 <b>6-7 (Высокий):</b> С 11 до 16 часов оставайтесь в тени\n"
                    "🔴 <b>8-10 (Очень высокий):</b> Обязательно используйте защиту\n"
                    "🟣 <b>11+ (Экстремальный):</b> Лучше не выходить на солнце\n\n"
                    "⚠️ <i>Примечание: приблизительная оценка на основе времени суток</i>", 
                    parse_mode="HTML")

@dp.message(Command("magnet"))
async def magnet_info(msg: types.Message):
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

@dp.message(Command("moon"))
async def moon_info(msg: types.Message):
    """Команда для получения информации о луне"""
    moon_data = await get_moon_data()
    
    # Расчет дней до следующего полнолуния/новолуния
    phase = moon_data['phase']
    
    days_to_full = (0.5 - phase) % 1.0
    days_to_full = min(days_to_full, 1 - days_to_full) * 29.53
    
    days_to_new = (1 - phase) % 1.0
    days_to_new = min(days_to_new, 1 - days_to_new) * 29.53
    
    await msg.answer(
        f"🌙 <b>Фаза луны сегодня:</b>\n\n"
        f"{moon_data['emoji']} <b>{moon_data['name']}</b>\n"
        f"💡 Освещенность: {moon_data['illumination']}%\n"
        f"♈ Знак зодиака: {moon_data['zodiac']}\n\n"
        f"📅 <b>Ближайшие события:</b>\n"
        f"• До полнолуния: {days_to_full:.1f} дней\n"
        f"• До новолуния: {days_to_new:.1f} дней\n\n"
        f"<b>Все фазы луны:</b>\n"
        f"🌑 Новолуние\n"
        f"🌒 Растущий серп\n"
        f"🌓 Первая четверть\n"
        f"🌔 Растущая луна\n"
        f"🌕 Полнолуние\n"
        f"🌖 Убывающая луна\n"
        f"🌗 Последняя четверть\n"
        f"🌘 Убывающий серп",
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    geo_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]], 
        resize_keyboard=True
    )
    await call.message.edit_text(f"✅ Время установлено на {t}:00.\nТеперь отправь локацию или напиши город.")
    await call.message.answer("ℹ️ Отправьте геопозицию или название города\n\n"
                             "Доступные команды:\n"
                             "/uv - информация об UV-индексе\n"
                             "/magnet - магнитные бури\n"
                             "/moon - фаза луны\n"
                             "/help - помощь", 
                             reply_markup=geo_kb)
    await call.answer()

@dp.message(F.location)
async def handle_location(msg: types.Message):
    await msg.answer("🔄 Получаю погоду по вашему местоположению...")
    coords = {"lat": msg.location.latitude, "lon": msg.location.longitude}
    result = await get_weather_with_details(coords)
    
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _, coord, full_data = result
        
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
    
    await msg.answer(f"🔄 Ищу город {msg.text}...")
    result = await get_weather_with_details(msg.text)
    
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _, coord, full_data = result
        
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
    parts = call.data.split('_')
    lat = float(parts[1])
    lon = float(parts[2])
    
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
    parts = call.data.split('_')
    lat = float(parts[1])
    lon = float(parts[2])
    
    # Получаем текущую погоду заново
    coords = {"lat": lat, "lon": lon}
    result = await get_weather_with_details(coords)
    
    if result[0]:
        report, city, tz, _, coord, full_data = result
        
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
                        result = await get_weather_with_details(city)
                        
                        if result[0]:  # если есть отчет о погоде
                            report, _, _, _, coord, _ = result
                            
                            # Добавляем кнопку для почасового прогноза
                            kb = InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="📅 Почасовой прогноз", callback_data=f"forecast_{coord['lat']}_{coord['lon']}")
                            ]])
                            
                            try: 
                                await bot.send_message(u_id, 
                                                      f"☀️ <b>Доброе утро!</b>\n\n{report}", 
                                                      reply_markup=kb,
                                                      parse_mode="HTML")
                                logger.info(f"✅ Успешно отправлено пользователю {u_id}")
                            except Exception as e:
                                logger.error(f"❌ Не удалось отправить сообщение пользователю {u_id}: {e}")
                        else:
                            logger.error(f"❌ Не удалось получить погоду для пользователя {u_id}: {result[1]}")
                
                await asyncio.sleep(61)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка в рассылке: {e}")
            await asyncio.sleep(60)

async def main():
    logger.info("=" * 50)
    logger.info("🚀 ЗАПУСК БОТА ПОГОДЫ")
    logger.info("=" * 50)
    
    init_db()
    
    # Проверяем API ключ
    logger.info("\n🔑 ПРОВЕРКА API КЛЮЧА OPENWEATHERMAP:")
    api_ok, api_message = await test_api_key()
    logger.info(api_message)
    
    if not api_ok:
        logger.error("\n❌ ПРОБЛЕМА С API КЛЮЧОМ!")
        logger.error("Как получить правильный ключ:")
        logger.error("1. Зарегистрируйтесь на https://openweathermap.org")
        logger.error("2. Перейдите в раздел API Keys")
        logger.error("3. Скопируйте ключ (должен выглядеть как '1a2b3c4d5e6f7g8h9i0j')")
        logger.error("4. Вставьте его в код или в переменную окружения WEATHER_API_KEY")
    
    # Проверяем подключение к NOAA
    logger.info("\n🛰️ ПРОВЕРКА ПОДКЛЮЧЕНИЯ К NOAA:")
    geomagnetic = await get_geomagnetic_data()
    if geomagnetic:
        logger.info(f"✅ Подключение к NOAA работает, текущий Kp: {geomagnetic[0]}")
    else:
        logger.warning("⚠️ Не удалось подключиться к NOAA, магнитные бури будут недоступны")
    
    logger.info("\n" + "=" * 50)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ!")
    logger.info("=" * 50)
    
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
