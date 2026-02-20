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
    """Получить описание уровня UV-индекса на основе времени суток"""
    # Если UV не доступен, оцениваем на основе времени и облачности
    if uvi is None:
        return "🟡 Неизвестно", "Используйте солнцезащитный крем в солнечную погоду"
    
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

def estimate_uv_from_sun(hour, clouds):
    """Примерно оценить UV-индекс на основе времени суток и облачности"""
    # Грубая оценка для демонстрации
    if hour < 8 or hour > 18:
        return 0.5  # Низкий
    elif 11 <= hour <= 15:
        base_uv = 6.0  # Высокий в полдень
    else:
        base_uv = 3.0  # Умеренный
    
    # Облачность уменьшает UV
    cloud_factor = max(0.2, 1 - (clouds / 100) * 0.7)
    return round(base_uv * cloud_factor, 1)

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

async def get_uv_index(lat, lon):
    """Попытка получить UV-индекс через отдельный API"""
    # Используем бесплатный API для UV-индекса
    url = f"https://currentuvindex.com/api/v1/uvi"
    
    async with aiohttp.ClientSession() as session:
        try:
            # Пробуем получить UV через альтернативный источник
            params = {
                'lat': lat,
                'lon': lon
            }
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('uvi', None)
        except:
            pass
    
    # Если не удалось, возвращаем None
    return None

async def get_weather_with_details(city_or_coords):
    """Получить текущую погоду со всеми деталями, используя стандартное API """
    
    # Используем стандартный Current Weather API
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
            logger.info(f"Отправка запроса к {url}")
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ошибка API: статус {resp.status}, ответ: {error_text}")
                    
                    if resp.status == 401:
                        return None, "❌ Неверный API ключ OpenWeatherMap", None, None, None
                    elif resp.status == 404:
                        return None, "❌ Город не найден", None, None, None
                    else:
                        return None, f"❌ Ошибка сервера погоды (код {resp.status})", None, None, None
                
                res = await resp.json()
                logger.info(f"Успешно получены данные для {res.get('name', 'неизвестного города')}")
                
                # Получаем текущее время для расчета UV
                now = datetime.datetime.now()
                
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
                
                # Координаты для прогноза
                coord = res['coord']
                
                # Получаем геомагнитные данные
                geomagnetic = await get_geomagnetic_data()
                
                # Оцениваем UV-индекс (так как стандартное API не дает UV)
                hour = now.hour
                estimated_uvi = estimate_uv_from_sun(hour, clouds)
                uv_desc, uv_advice = get_uv_description(estimated_uvi)
                
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
                
                # Формируем UV строку
                if 6 <= hour <= 20:  # Дневное время
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
                report += f"\n\n💡 {advice}"
                
                return (report, name, tz_offset, None, coord)
                
        except asyncio.TimeoutError:
            logger.error("Таймаут при запросе к API")
            return None, "❌ Превышено время ожидания ответа от сервера", None, None, None
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка клиента: {e}")
            return None, f"❌ Ошибка сети: {e}", None, None, None
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
            return None, f"❌ Неизвестная ошибка: {e}", None, None, None

async def get_hourly_forecast(city):
    """Получить почасовой прогноз на 24 часа (имитация)"""
    # Из-за ограничений API, делаем прогноз на основе текущих данных
    # В реальности нужно использовать forecast API
    
    forecast_text = "📅 <b>Прогноз на сегодня:</b>\n\n"
    now = datetime.datetime.now()
    
    for i in range(8):  # 8 временных точек
        hour = (now.hour + i * 3) % 24
        time_str = f"{hour:02d}:00"
        
        # Эмодзи для времени суток
        if 6 <= hour < 12:
            time_emoji = "🌅"
        elif 12 <= hour < 18:
            time_emoji = "☀️"
        elif 18 <= hour < 23:
            time_emoji = "🌆"
        else:
            time_emoji = "🌙"
        
        # Примерная температура (колеблется в течение дня)
        if 12 <= hour <= 15:
            temp = "~20°"
        elif hour < 6 or hour > 21:
            temp = "~12°"
        else:
            temp = "~16°"
        
        forecast_text += f"{time_emoji} <b>{time_str}</b> {temp}\n"
    
    forecast_text += "\n💡 Для точного прогноза используйте специализированные сервисы"
    
    return forecast_text, None

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
                    "🟣 <b>11+ (Экстремальный):</b> Лучше не выходить на солнце\n\n"
                    "⚠️ <i>Примечание: приблизительная оценка на основе времени суток</i>", 
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
    result = await get_weather_with_details(coords)
    
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _, coord = result
        
        # Сохраняем город
        update_user(msg.chat.id, city=city, timezone=tz)
        
        # Создаем клавиатуру с кнопкой для прогноза
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📅 Прогноз на сегодня", callback_data=f"forecast_{city}")
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
        
    result = await get_weather_with_details(msg.text)
    
    if result[0]:  # если есть отчет о погоде
        report, city, tz, _, coord = result
        
        # Сохраняем город
        update_user(msg.chat.id, city=city, timezone=tz)
        
        # Создаем клавиатуру с кнопкой для прогноза
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📅 Прогноз на сегодня", callback_data=f"forecast_{city}")
        ]])
        
        await msg.answer(f"✅ Город {city} сохранен!\n\n{report}", 
                        reply_markup=kb,
                        parse_mode="HTML")
    else:
        error_msg = result[1] if len(result) > 1 else "❌ Город не найден"
        await msg.answer(f"{error_msg}\nНапиши, например: Москва")

@dp.callback_query(F.data.startswith("forecast_"))
async def show_forecast(call: types.CallbackQuery):
    """Показать прогноз"""
    await call.answer("Загружаю прогноз...")
    
    # Извлекаем город из callback_data
    city = call.data.replace("forecast_", "")
    
    forecast, error = await get_hourly_forecast(city)
    
    if forecast:
        # Добавляем кнопку "Назад" к текущей погоде
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 К текущей погоде", callback_data=f"back_{city}")
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
    
    # Извлекаем город
    city = call.data.replace("back_", "")
    
    # Получаем текущую погоду
    result = await get_weather_with_details(city)
    
    if result[0]:
        report, city, tz, _, coord = result
        
        # Создаем клавиатуру с кнопкой для прогноза
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📅 Прогноз на сегодня", callback_data=f"forecast_{city}")
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
                            report, _, _, _, coord = result
                            
                            # Добавляем кнопку для прогноза
                            kb = InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="📅 Прогноз на сегодня", callback_data=f"forecast_{city}")
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
    
    # Проверяем подключение к API с простым запросом
    logger.info("Проверка подключения к OpenWeatherMap...")
    try:
        test_result = await get_weather_with_details("Москва")
        if test_result[0]:
            logger.info("✅ Подключение к OpenWeatherMap работает")
            logger.info("✅ API ключ корректен")
        else:
            logger.error(f"❌ Ошибка: {test_result[1]}")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке: {e}")
    
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
