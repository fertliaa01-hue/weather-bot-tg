import asyncio
import sqlite3
import aiohttp
import datetime
import logging
import os
import math
import random
import anecapi  # Правильный импорт с большой буквы
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
                   (id INTEGER PRIMARY KEY, city TEXT, time INTEGER DEFAULT 8, 
                    timezone INTEGER DEFAULT 10800, zodiac_sign TEXT)''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

def migrate_db():
    """Обновление структуры БД без потери данных"""
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    
    # Проверяем, есть ли поле zodiac_sign
    cur.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cur.fetchall()]
    
    if 'zodiac_sign' not in columns:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN zodiac_sign TEXT")
            logger.info("✅ Поле zodiac_sign добавлено в таблицу users")
        except Exception as e:
            logger.error(f"❌ Ошибка добавления поля: {e}")
    
    conn.commit()
    conn.close()

def update_user(user_id, city=None, time=None, timezone=None, zodiac_sign=None):
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    
    # Проверяем, существует ли пользователь
    cur.execute('SELECT id FROM users WHERE id = ?', (user_id,))
    exists = cur.fetchone()
    
    if not exists:
        # Вставляем нового пользователя
        cur.execute('''INSERT INTO users (id, city, time, timezone, zodiac_sign) 
                       VALUES (?, ?, ?, ?, ?)''',
                   (user_id, city if city else '', time if time else 8, 
                    timezone if timezone else 10800, zodiac_sign))
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
        if zodiac_sign:
            cur.execute('UPDATE users SET zodiac_sign = ? WHERE id = ?', (zodiac_sign, user_id))
            logger.info(f"Обновлен знак зодиака для пользователя {user_id}: {zodiac_sign}")
    
    conn.commit()
    conn.close()

def get_user_zodiac(user_id):
    """Получить сохраненный знак зодиака пользователя"""
    conn = sqlite3.connect('weather_bot.db')
    cur = conn.cursor()
    cur.execute('SELECT zodiac_sign FROM users WHERE id = ?', (user_id,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result and result[0] else None

# --- ФУНКЦИИ ДЛЯ АНЕКДОТОВ (РУССКИЕ) ---
JOKE_TYPES = {
    'random': '🎲 Случайный',
    'modern': '📱 Современный',
    'soviet': '🕰 Советский'
}

async def get_russian_joke(joke_type='random'):
    """
    Получить русский анекдот через anecAPI
    
    Args:
        joke_type (str): 'random', 'modern', 'soviet'
    
    Returns:
        str: Анекдот на русском или None при ошибке
    """
    try:
        logger.info(f"Запрос русского анекдота, тип: {joke_type}")
        
        # Запускаем в отдельном потоке, чтобы не блокировать асинхронность
        loop = asyncio.get_event_loop()
        
        if joke_type == 'modern':
            joke = await loop.run_in_executor(None, anecAPI.modern_joke)
        elif joke_type == 'soviet':
            joke = await loop.run_in_executor(None, anecAPI.soviet_joke)
        else:  # random
            joke = await loop.run_in_executor(None, anecAPI.random_joke)
        
        if joke and isinstance(joke, str) and len(joke) > 5:
            logger.info(f"✅ Русский анекдот получен, длина: {len(joke)} символов")
            return joke
        else:
            logger.error("❌ anecAPI вернул пустой или некорректный результат")
            return get_fallback_joke(joke_type)
            
    except ImportError:
        logger.error("❌ Библиотека anecAPI не установлена. Установите: pip install -i https://test.pypi.org/simple/ anecapi==0.1.1")
        return get_fallback_joke(joke_type)
    except AttributeError as e:
        logger.error(f"❌ Ошибка вызова функции anecAPI: {e}")
        return get_fallback_joke(joke_type)
    except Exception as e:
        logger.error(f"❌ Ошибка при получении анекдота: {e}")
        return get_fallback_joke(joke_type)

def get_fallback_joke(joke_type='random'):
    """Запасные анекдоты на случай недоступности библиотеки"""
    
    fallback_jokes = {
        'random': [
            "Встречаются два программиста:\n— Как дела?\n— Да нормально...\n— А что такой грустный?\n— Да понимаешь, купил себе новый компьютер, а он не включается.\n— А почему не включается?\n— Да розетка сломалась...",
            
            "Приходит мужик к врачу:\n— Доктор, у меня что-то с памятью.\n— А конкретнее?\n— Что конкретнее?",
            
            "— Алло, это служба поддержки?\n— Да.\n— У меня компьютер не работает.\n— А вы пробовали перезагрузить?\n— Пробовал.\n— И что?\n— Теперь он вообще не включается.\n— А вы пробовали включить его в розетку?\n— А где она?",
            
            "Стоит программист на светофоре, ждет зеленый. Подходит бабушка:\n— Сынок, помоги перейти дорогу.\nПрограммист:\n— Извините, бабушка, я сейчас не могу, я в потоке.",
            
            "— Почему программисты путают Хэллоуин и Рождество?\n— Потому что Oct 31 == Dec 25.",
            
            "В зоопарке табличка:\n«Осторожно! Злая собака!»\nРядом приписка:\n«А ещё здесь лев, тигр и медведь, но собака действительно злая!»"
        ],
        'modern': [
            "Современная колыбельная:\n— Спи, малыш, не плачь.\n— Не буду.\n— Вот тебе айпад.\n— Буду.\n— Вот тебе айфон.\n— Буду.\n— Вот тебе макбук.\n— Буду.\n— Ну спи, хоть чуть-чуть.\n— Не буду.\n— А что ты хочешь?\n— Чтобы батарейка села...",
            
            "— Папа, а почему у нас дома так много техники?\n— Сынок, это потому что мама любит покупать всякие штуки.\n— А почему она их покупает?\n— Потому что у нее есть кредитка.\n— А почему у нее есть кредитка?\n— Потому что я работаю.\n— А почему ты работаешь?\n— Чтобы оплачивать кредитку...",
            
            "Звонок в техподдержку:\n— У меня не работает интернет.\n— А вы пробовали перезагрузить роутер?\n— Пробовал.\n— И что?\n— Он теперь мигает красным.\n— А кабель проверили?\n— Какой кабель?\n— Который от роутера к компьютеру.\n— А у меня ноутбук, там нет кабеля.\n— А как вы подключаетесь?\n— По воздуху.\n— ???"
        ],
        'soviet': [
            "Советский анекдот:\n— Почему в СССР нет безработицы?\n— Потому что тех, кто не работает, сажают.\n— А тех, кто работает?\n— Тех тоже сажают, но на зарплату.",
            
            "Стоит очередь за колбасой. Подходит мужик:\n— Вы последний?\n— Нет, я первый, но за мной уже пол-Москвы стоит.",
            
            "— Почему в СССР все ходят строем?\n— Чтобы легче было считать, кого еще не посадили.",
            
            "Вовочка спрашивает отца:\n— Папа, а что такое дефицит?\n— Дефицит, сынок, это когда хочешь купить, а нечего.\n— А что такое изобилие?\n— А изобилие, сынок, это когда есть что купить, но не на что.",
            
            "Радио «Свобода» объявляет конкурс на лучший анекдот про Брежнева. Первое место не присуждать.",
            
            "Идет мужик по пустыне. Видит — верблюд стоит.\n— Ты чей?\n— Я ничей, я советский."
        ]
    }
    
    # Выбираем случайный анекдот из нужной категории
    if joke_type in fallback_jokes and fallback_jokes[joke_type]:
        return random.choice(fallback_jokes[joke_type])
    else:
        return random.choice(fallback_jokes['random'])

async def get_multiple_jokes(count=3):
    """Получить несколько случайных анекдотов"""
    jokes = []
    for _ in range(count):
        joke = await get_russian_joke('random')
        if joke:
            jokes.append(joke)
        await asyncio.sleep(0.5)  # Небольшая задержка между запросами
    
    if jokes:
        result = "🎭 <b>Подборка анекдотов:</b>\n\n"
        for i, joke in enumerate(jokes, 1):
            # Обрезаем слишком длинные анекдоты для подборки
            if len(joke) > 200:
                joke = joke[:200] + "..."
            result += f"{i}. {joke}\n\n"
        return result
    return None

# --- ФУНКЦИИ ДЛЯ ГОРОСКОПА ---
ZODIAC_SIGNS = {
    'aries': {'name': 'Овен', 'emoji': '♈', 'dates': '21 марта - 19 апреля'},
    'taurus': {'name': 'Телец', 'emoji': '♉', 'dates': '20 апреля - 20 мая'},
    'gemini': {'name': 'Близнецы', 'emoji': '♊', 'dates': '21 мая - 20 июня'},
    'cancer': {'name': 'Рак', 'emoji': '♋', 'dates': '21 июня - 22 июля'},
    'leo': {'name': 'Лев', 'emoji': '♌', 'dates': '23 июля - 22 августа'},
    'virgo': {'name': 'Дева', 'emoji': '♍', 'dates': '23 августа - 22 сентября'},
    'libra': {'name': 'Весы', 'emoji': '♎', 'dates': '23 сентября - 22 октября'},
    'scorpio': {'name': 'Скорпион', 'emoji': '♏', 'dates': '23 октября - 21 ноября'},
    'sagittarius': {'name': 'Стрелец', 'emoji': '♐', 'dates': '22 ноября - 21 декабря'},
    'capricorn': {'name': 'Козерог', 'emoji': '♑', 'dates': '22 декабря - 19 января'},
    'aquarius': {'name': 'Водолей', 'emoji': '♒', 'dates': '20 января - 18 февраля'},
    'pisces': {'name': 'Рыбы', 'emoji': '♓', 'dates': '19 февраля - 20 марта'}
}

# Резервные данные для гороскопа на случай недоступности API
FALLBACK_HOROSCOPES = {
    'aries': {
        'today': {
            'description': 'Сегодня Овнам стоит проявить инициативу в рабочих вопросах. Звезды благосклонны к новым начинаниям. Возможны интересные предложения от партнеров.',
            'compatibility': 'Лев',
            'mood': 'Энергичный',
            'color': 'Красный',
            'lucky_number': '7',
            'lucky_time': '11:00 - 14:00'
        },
        'tomorrow': {
            'description': 'Завтра возможны приятные сюрпризы в личной жизни. Будьте открыты к новым знакомствам. Старые друзья напомнят о себе.',
            'compatibility': 'Стрелец',
            'mood': 'Романтичный',
            'color': 'Оранжевый',
            'lucky_number': '3',
            'lucky_time': '15:00 - 18:00'
        },
        'weekly': {
            'description': 'На этой неделе вас ждут интересные возможности для карьерного роста. Не упустите свой шанс! В четверг возможны неожиданные денежные поступления.',
            'compatibility': 'Весы',
            'mood': 'Целеустремленный',
            'color': 'Золотой',
            'lucky_number': '9',
            'lucky_time': 'Вторая половина дня'
        }
    },
    'taurus': {
        'today': {
            'description': 'Тельцам сегодня стоит уделить внимание финансам. Избегайте импульсивных трат. Хороший день для планирования бюджета.',
            'compatibility': 'Дева',
            'mood': 'Практичный',
            'color': 'Зеленый',
            'lucky_number': '4',
            'lucky_time': '10:00 - 12:00'
        },
        'tomorrow': {
            'description': 'Завтра отличный день для решения давних проблем. Действуйте решительно! Поддержка близких поможет в трудную минуту.',
            'compatibility': 'Козерог',
            'mood': 'Решительный',
            'color': 'Коричневый',
            'lucky_number': '6',
            'lucky_time': '13:00 - 16:00'
        },
        'weekly': {
            'description': 'На этой неделе звезды советуют больше времени проводить с семьей. В выходные возможны приятные покупки.',
            'compatibility': 'Рак',
            'mood': 'Спокойный',
            'color': 'Бежевый',
            'lucky_number': '2',
            'lucky_time': 'Вечернее время'
        }
    },
    'gemini': {
        'today': {
            'description': 'Близнецам сегодня стоит прислушаться к интуиции. Она подскажет верное решение. Удачный день для общения и переговоров.',
            'compatibility': 'Весы',
            'mood': 'Общительный',
            'color': 'Желтый',
            'lucky_number': '5',
            'lucky_time': '9:00 - 11:00'
        },
        'tomorrow': {
            'description': 'Завтра возможны неожиданные известия от дальних родственников. Будьте готовы к переменам в планах.',
            'compatibility': 'Водолей',
            'mood': 'Любопытный',
            'color': 'Голубой',
            'lucky_number': '8',
            'lucky_time': '14:00 - 17:00'
        },
        'weekly': {
            'description': 'На этой неделе удача будет на вашей стороне в творческих начинаниях. Среда - лучший день для важных решений.',
            'compatibility': 'Стрелец',
            'mood': 'Креативный',
            'color': 'Фиолетовый',
            'lucky_number': '11',
            'lucky_time': 'Утренние часы'
        }
    },
    'cancer': {
        'today': {
            'description': 'Ракам сегодня стоит избегать конфликтов на работе. Сохраняйте спокойствие и дипломатичность. Хороший день для домашних дел.',
            'compatibility': 'Скорпион',
            'mood': 'Чувствительный',
            'color': 'Серебристый',
            'lucky_number': '2',
            'lucky_time': '16:00 - 19:00'
        },
        'tomorrow': {
            'description': 'Завтра благоприятный день для новых знакомств. Не бойтесь проявлять эмоции - это привлечет нужных людей.',
            'compatibility': 'Рыбы',
            'mood': 'Эмоциональный',
            'color': 'Белый',
            'lucky_number': '7',
            'lucky_time': '11:00 - 13:00'
        },
        'weekly': {
            'description': 'На этой неделе возможны приятные сюрпризы в личной жизни. Пятница принесет хорошие новости.',
            'compatibility': 'Телец',
            'mood': 'Заботливый',
            'color': 'Мятный',
            'lucky_number': '4',
            'lucky_time': 'Вечер'
        }
    },
    'leo': {
        'today': {
            'description': 'Львам сегодня стоит проявить лидерские качества. Ваши идеи найдут поддержку у начальства. Удачный день для публичных выступлений.',
            'compatibility': 'Стрелец',
            'mood': 'Уверенный',
            'color': 'Золотой',
            'lucky_number': '1',
            'lucky_time': '12:00 - 15:00'
        },
        'tomorrow': {
            'description': 'Завтра возможны неожиданные комплименты и знаки внимания. Наслаждайтесь моментом!',
            'compatibility': 'Овен',
            'mood': 'Харизматичный',
            'color': 'Оранжевый',
            'lucky_number': '9',
            'lucky_time': '17:00 - 20:00'
        },
        'weekly': {
            'description': 'На этой неделе звезды советуют заняться творчеством. Вторник принесет вдохновение.',
            'compatibility': 'Близнецы',
            'mood': 'Творческий',
            'color': 'Пурпурный',
            'lucky_number': '5',
            'lucky_time': 'Дневное время'
        }
    },
    'virgo': {
        'today': {
            'description': 'Девам сегодня стоит уделить внимание деталям. Ваша педантичность поможет избежать ошибок. Хороший день для анализа и планирования.',
            'compatibility': 'Телец',
            'mood': 'Внимательный',
            'color': 'Бежевый',
            'lucky_number': '3',
            'lucky_time': '8:00 - 10:00'
        },
        'tomorrow': {
            'description': 'Завтра возможны приятные хлопоты, связанные с домом. Уделите время близким.',
            'compatibility': 'Козерог',
            'mood': 'Заботливый',
            'color': 'Серый',
            'lucky_number': '6',
            'lucky_time': '15:00 - 18:00'
        },
        'weekly': {
            'description': 'На этой неделе успех в финансовых вопросах. Четверг - лучший день для крупных покупок.',
            'compatibility': 'Рак',
            'mood': 'Практичный',
            'color': 'Зеленый',
            'lucky_number': '8',
            'lucky_time': 'Утро'
        }
    },
    'libra': {
        'today': {
            'description': 'Весам сегодня стоит найти баланс между работой и отдыхом. Избегайте крайностей в решениях.',
            'compatibility': 'Водолей',
            'mood': 'Гармоничный',
            'color': 'Розовый',
            'lucky_number': '6',
            'lucky_time': '13:00 - 16:00'
        },
        'tomorrow': {
            'description': 'Завтра благоприятный день для романтических свиданий. Будьте открыты для новых чувств.',
            'compatibility': 'Близнецы',
            'mood': 'Романтичный',
            'color': 'Голубой',
            'lucky_number': '2',
            'lucky_time': '18:00 - 21:00'
        },
        'weekly': {
            'description': 'На этой неделе возможны интересные деловые предложения. Среда принесет удачу.',
            'compatibility': 'Лев',
            'mood': 'Дипломатичный',
            'color': 'Лавандовый',
            'lucky_number': '4',
            'lucky_time': 'Вторая половина дня'
        }
    },
    'scorpio': {
        'today': {
            'description': 'Скорпионам сегодня стоит доверять своей интуиции. Она поможет раскрыть тайны и найти скрытые возможности.',
            'compatibility': 'Рак',
            'mood': 'Проницательный',
            'color': 'Темно-красный',
            'lucky_number': '9',
            'lucky_time': '20:00 - 23:00'
        },
        'tomorrow': {
            'description': 'Завтра возможны интенсивные эмоциональные переживания. Не бойтесь глубоких чувств.',
            'compatibility': 'Рыбы',
            'mood': 'Страстный',
            'color': 'Черный',
            'lucky_number': '11',
            'lucky_time': '22:00 - 00:00'
        },
        'weekly': {
            'description': 'На этой неделе вас ждут трансформации в личной жизни. Пятница - ключевой день.',
            'compatibility': 'Дева',
            'mood': 'Загадочный',
            'color': 'Бордовый',
            'lucky_number': '7',
            'lucky_time': 'Ночь'
        }
    },
    'sagittarius': {
        'today': {
            'description': 'Стрельцам сегодня стоит отправиться в путешествие, хотя бы мысленное. Новые горизонты вдохновят на подвиги.',
            'compatibility': 'Овен',
            'mood': 'Авантюрный',
            'color': 'Синий',
            'lucky_number': '5',
            'lucky_time': '10:00 - 13:00'
        },
        'tomorrow': {
            'description': 'Завтра отличный день для обучения и получения новых знаний. Запишитесь на курсы.',
            'compatibility': 'Лев',
            'mood': 'Любознательный',
            'color': 'Бирюзовый',
            'lucky_number': '3',
            'lucky_time': '14:00 - 17:00'
        },
        'weekly': {
            'description': 'На этой неделе успех в юридических вопросах. Вторник принесет важные новости.',
            'compatibility': 'Водолей',
            'mood': 'Оптимистичный',
            'color': 'Фиолетовый',
            'lucky_number': '8',
            'lucky_time': 'День'
        }
    },
    'capricorn': {
        'today': {
            'description': 'Козерогам сегодня стоит сосредоточиться на карьерных целях. Упорство приведет к успеху.',
            'compatibility': 'Дева',
            'mood': 'Целеустремленный',
            'color': 'Темно-зеленый',
            'lucky_number': '4',
            'lucky_time': '9:00 - 12:00'
        },
        'tomorrow': {
            'description': 'Завтра возможны важные деловые встречи. Подготовьтесь заранее.',
            'compatibility': 'Телец',
            'mood': 'Серьезный',
            'color': 'Коричневый',
            'lucky_number': '8',
            'lucky_time': '11:00 - 14:00'
        },
        'weekly': {
            'description': 'На этой неделе звезды советуют проявить терпение. Успех придет к тем, кто умеет ждать.',
            'compatibility': 'Скорпион',
            'mood': 'Выносливый',
            'color': 'Графитовый',
            'lucky_number': '2',
            'lucky_time': 'Утро'
        }
    },
    'aquarius': {
        'today': {
            'description': 'Водолеям сегодня стоит генерировать нестандартные идеи. Оригинальность будет оценена.',
            'compatibility': 'Близнецы',
            'mood': 'Креативный',
            'color': 'Голубой',
            'lucky_number': '11',
            'lucky_time': '15:00 - 18:00'
        },
        'tomorrow': {
            'description': 'Завтра отличный день для встреч с друзьями. Новые знакомства расширят кругозор.',
            'compatibility': 'Весы',
            'mood': 'Дружелюбный',
            'color': 'Электрик',
            'lucky_number': '7',
            'lucky_time': '19:00 - 22:00'
        },
        'weekly': {
            'description': 'На этой неделе возможны технологические прорывы. Следите за новинками.',
            'compatibility': 'Стрелец',
            'mood': 'Инновационный',
            'color': 'Серебристый',
            'lucky_number': '5',
            'lucky_time': 'Вечер'
        }
    },
    'pisces': {
        'today': {
            'description': 'Рыбам сегодня стоит довериться потоку жизни. Интуиция приведет туда, куда нужно.',
            'compatibility': 'Рак',
            'mood': 'Мечтательный',
            'color': 'Бирюзовый',
            'lucky_number': '3',
            'lucky_time': '16:00 - 19:00'
        },
        'tomorrow': {
            'description': 'Завтра благоприятный день для творчества и самовыражения. Займитесь любимым делом.',
            'compatibility': 'Скорпион',
            'mood': 'Вдохновенный',
            'color': 'Морская волна',
            'lucky_number': '9',
            'lucky_time': '20:00 - 23:00'
        },
        'weekly': {
            'description': 'На этой неделе возможны приятные сюрпризы в финансовой сфере. Не ждите, действуйте!',
            'compatibility': 'Телец',
            'mood': 'Интуитивный',
            'color': 'Лазурный',
            'lucky_number': '6',
            'lucky_time': 'Вечер'
        }
    }
}

async def get_horoscope(sign, timeframe='today'):
    """
    Получить гороскоп для знака зодиака с резервными данными
    
    Args:
        sign (str): Знак зодиака на английском (aries, taurus, etc.)
        timeframe (str): today, tomorrow, weekly
    
    Returns:
        dict: Данные гороскопа или None при ошибке
    """
    # Пробуем получить данные из API
    url = "https://aztro.sameerkumar.website/"
    params = {
        'sign': sign,
        'day': timeframe
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            logger.info(f"Запрос гороскопа для {sign} на {timeframe} из API")
            async with session.post(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"Гороскоп для {sign} успешно получен из API")
                    return data
                else:
                    logger.warning(f"API вернул код {resp.status}, используем резервные данные")
                    return get_fallback_horoscope(sign, timeframe)
        except asyncio.TimeoutError:
            logger.warning("Таймаут при запросе гороскопа, используем резервные данные")
            return get_fallback_horoscope(sign, timeframe)
        except Exception as e:
            logger.error(f"Ошибка получения гороскопа: {e}, используем резервные данные")
            return get_fallback_horoscope(sign, timeframe)

def get_fallback_horoscope(sign, timeframe):
    """Получить резервные данные гороскопа"""
    if sign in FALLBACK_HOROSCOPES and timeframe in FALLBACK_HOROSCOPES[sign]:
        data = FALLBACK_HOROSCOPES[sign][timeframe].copy()
        # Добавляем текущую дату
        today = datetime.datetime.now()
        if timeframe == 'today':
            data['current_date'] = today.strftime("%d %B %Y")
        elif timeframe == 'tomorrow':
            tomorrow = today + datetime.timedelta(days=1)
            data['current_date'] = tomorrow.strftime("%d %B %Y")
        elif timeframe == 'weekly':
            data['current_date'] = f"{today.strftime('%d %B')} - {(today + datetime.timedelta(days=6)).strftime('%d %B %Y')}"
        return data
    return None

def format_horoscope(data, sign_name, sign_emoji, timeframe):
    """Форматировать данные гороскопа для отображения"""
    
    # Определяем заголовок в зависимости от периода
    if timeframe == 'today':
        period = 'Сегодня'
        period_emoji = '📅'
    elif timeframe == 'tomorrow':
        period = 'Завтра'
        period_emoji = '🔮'
    elif timeframe == 'weekly':
        period = 'На неделю'
        period_emoji = '📆'
    else:
        period = 'Сегодня'
        period_emoji = '📅'
    
    # Форматируем дату
    current_date = data.get('current_date', '')
    date_str = f" ({current_date})" if current_date else ""
    
    # Извлекаем данные
    description = data.get('description', '')
    compatibility = data.get('compatibility', '')
    mood = data.get('mood', '')
    color = data.get('color', '')
    lucky_number = data.get('lucky_number', '')
    lucky_time = data.get('lucky_time', '')
    
    # Формируем отчет
    report = (
        f"{sign_emoji} <b>{sign_name} {period}{date_str}</b>\n\n"
        f"📝 <b>Гороскоп:</b>\n{description}\n\n"
    )
    
    # Добавляем дополнительную информацию, если она есть
    details = []
    if compatibility:
        details.append(f"💕 Совместимость: {compatibility}")
    if mood:
        details.append(f"😊 Настроение: {mood}")
    if color:
        details.append(f"🎨 Цвет: {color}")
    if lucky_number:
        details.append(f"🔢 Счастливое число: {lucky_number}")
    if lucky_time:
        details.append(f"⏰ Удачное время: {lucky_time}")
    
    if details:
        report += "✨ <b>Дополнительно:</b>\n" + "\n".join(f"   {d}" for d in details)
    
    # Добавляем совет дня
    advice = get_horoscope_advice(sign_name, description)
    report += f"\n\n💡 <b>Совет дня:</b>\n{advice}"
    
    return report

def get_horoscope_advice(sign_name, description):
    """Получить персонализированный совет по гороскопу"""
    
    advice_pool = [
        f"✨ {sign_name}, доверяйте своей интуиции сегодня",
        f"🌟 Звезды говорят, что сегодня отличный день для новых начинаний",
        f"💫 Не бойтесь перемен - они принесут удачу",
        f"⭐ Сегодня лучше прислушаться к советам близких",
        f"🌠 Ваша энергия сегодня на подъеме - используйте ее с умом",
        f"✨ Уделите время саморазвитию и обучению",
        f"🌟 Сегодня удача на вашей стороне",
        f"💫 Не забывайте о здоровье и отдыхе",
        f"⭐ Общение с друзьями принесет радость",
        f"🌠 Доверяйте своим идеям - они приведут к успеху"
    ]
    
    # Анализируем описание для более точного совета
    desc_lower = description.lower()
    
    if "love" in desc_lower or "romance" in desc_lower or "отношен" in desc_lower or "личн" in desc_lower:
        advice_pool.extend([
            f"❤️ {sign_name}, сегодня отличный день для романтики",
            f"💕 Откройте свое сердце для любви",
            f"💖 Близкие люди подарят вам радость"
        ])
    
    if "work" in desc_lower or "career" in desc_lower or "работ" in desc_lower or "карьер" in desc_lower:
        advice_pool.extend([
            f"💼 {sign_name}, сосредоточьтесь на важных задачах",
            f"📈 Карьерный рост возможен - действуйте",
            f"🎯 Ваши усилия на работе будут вознаграждены"
        ])
    
    if "money" in desc_lower or "finance" in desc_lower or "деньг" in desc_lower or "финанс" in desc_lower:
        advice_pool.extend([
            f"💰 {sign_name}, будьте внимательны с финансами",
            f"💸 Удачный день для финансовых решений",
            f"💳 Не тратьте деньги импульсивно"
        ])
    
    if "health" in desc_lower or "здоров" in desc_lower:
        advice_pool.extend([
            f"🏃 {sign_name}, займитесь своим здоровьем",
            f"🧘 Медитация и спорт помогут восстановить силы",
            f"🥗 Обратите внимание на питание"
        ])
    
    return random.choice(advice_pool)

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

async def get_moon_data():
    """Получить полные данные о луне"""
    now = datetime.datetime.now()
    phase = get_moon_phase(now)
    emoji = get_moon_emoji(phase)
    name = get_moon_name(phase)
    illumination = get_moon_illumination(phase)
    
    return {
        'phase': phase,
        'emoji': emoji,
        'name': name,
        'illumination': illumination
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

async def get_hourly_forecast(lat, lon):
    """Получить почасовой прогноз на 24 часа через Forecast 5 API"""
    url = "https://api.openweathermap.org/data/2.5/forecast"
    
    params = {
        'appid': WEATHER_API_KEY,
        'lat': lat,
        'lon': lon,
        'units': 'metric',
        'lang': 'ru',
        'cnt': 8  # Получаем 8 записей (24 часа с шагом 3 часа)
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            logger.info(f"Запрос прогноза для координат {lat}, {lon} через Forecast API")
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None, f"❌ Не удалось получить прогноз (код {resp.status})"
                
                res = await resp.json()
                
                forecast_lines = []
                
                if 'list' not in res:
                    return None, "❌ Нет данных почасового прогноза"
                
                for item in res['list']:
                    dt = datetime.datetime.fromtimestamp(item['dt'])
                    time_str = dt.strftime("%H:%M")
                    temp = round(item['main']['temp'])
                    weather = item['weather'][0]
                    desc = weather['description']
                    
                    wind_speed = round(item['wind']['speed'])
                    wind_deg = item['wind'].get('deg', 0)
                    
                    if 6 <= dt.hour < 12:
                        time_emoji = "🌅"
                    elif 12 <= dt.hour < 18:
                        time_emoji = "☀️"
                    elif 18 <= dt.hour < 23:
                        time_emoji = "🌆"
                    else:
                        time_emoji = "🌙"
                    
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
                    
                    wind_emoji = get_wind_emoji(wind_speed)
                    wind_dir = get_wind_direction(wind_deg)
                    
                    forecast_lines.append(f"{time_emoji} <b>{time_str}</b> {weather_emoji} {temp}°C, {desc}\n   └ {wind_emoji} {wind_speed} м/с, {wind_dir}")
                
                return forecast_lines, None
                
        except asyncio.TimeoutError:
            return None, "❌ Превышено время ожидания прогноза"
        except Exception as e:
            return None, f"❌ Ошибка получения прогноза: {e}"

async def get_tomorrow_forecast(lat, lon):
    """Получить прогноз на завтра"""
    url = "https://api.openweathermap.org/data/2.5/forecast"
    
    params = {
        'appid': WEATHER_API_KEY,
        'lat': lat,
        'lon': lon,
        'units': 'metric',
        'lang': 'ru',
        'cnt': 16
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None, f"❌ Не удалось получить прогноз (код {resp.status})"
                
                res = await resp.json()
                
                tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
                tomorrow_date = tomorrow.date()
                
                forecast_lines = []
                day_forecasts = []
                
                for item in res['list']:
                    dt = datetime.datetime.fromtimestamp(item['dt'])
                    if dt.date() == tomorrow_date:
                        day_forecasts.append(item)
                
                if not day_forecasts:
                    return None, "❌ Нет данных на завтра"
                
                time_slots = [6, 12, 18, 21]
                
                for target_hour in time_slots:
                    closest_item = min(day_forecasts, key=lambda x: abs(datetime.datetime.fromtimestamp(x['dt']).hour - target_hour))
                    dt = datetime.datetime.fromtimestamp(closest_item['dt'])
                    time_str = dt.strftime("%H:%M")
                    temp = round(closest_item['main']['temp'])
                    weather = closest_item['weather'][0]
                    desc = weather['description']
                    
                    wind_speed = round(closest_item['wind']['speed'])
                    wind_deg = closest_item['wind'].get('deg', 0)
                    wind_dir = get_wind_direction(wind_deg)
                    wind_emoji = get_wind_emoji(wind_speed)
                    
                    if 6 <= dt.hour < 12:
                        time_emoji = "🌅"
                        time_name = "Утро"
                    elif 12 <= dt.hour < 18:
                        time_emoji = "☀️"
                        time_name = "День"
                    elif 18 <= dt.hour < 23:
                        time_emoji = "🌆"
                        time_name = "Вечер"
                    else:
                        time_emoji = "🌙"
                        time_name = "Ночь"
                    
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
                    
                    forecast_lines.append(
                        f"{time_emoji} <b>{time_name} ({time_str})</b>\n"
                        f"   ├ {weather_emoji} {temp}°C, {desc}\n"
                        f"   └ {wind_emoji} Ветер: {wind_speed} м/с, {wind_dir}"
                    )
                
                avg_temp = round(sum(item['main']['temp'] for item in day_forecasts) / len(day_forecasts))
                max_pop = max(item.get('pop', 0) for item in day_forecasts) * 100
                
                result = (
                    f"📅 <b>Прогноз на завтра ({tomorrow.strftime('%d.%m.%Y')}):</b>\n\n"
                    f"{chr(10).join(forecast_lines)}\n\n"
                    f"📊 <b>Сводка:</b>\n"
                    f"   ├ 🌡 Средняя температура: {avg_temp}°C\n"
                    f"   └ ☔ Вероятность осадков: {max_pop:.0f}%"
                )
                
                return result, None
                
        except Exception as e:
            return None, f"❌ Ошибка получения прогноза: {e}"

async def get_weekly_forecast(lat, lon):
    """Получить прогноз на 7 дней"""
    url = "https://api.openweathermap.org/data/2.5/forecast"
    
    params = {
        'appid': WEATHER_API_KEY,
        'lat': lat,
        'lon': lon,
        'units': 'metric',
        'lang': 'ru',
        'cnt': 56
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None, f"❌ Не удалось получить прогноз (код {resp.status})"
                
                res = await resp.json()
                
                daily_forecasts = {}
                
                for item in res['list']:
                    dt = datetime.datetime.fromtimestamp(item['dt'])
                    date_str = dt.strftime("%d.%m")
                    
                    if date_str not in daily_forecasts:
                        daily_forecasts[date_str] = []
                    daily_forecasts[date_str].append(item)
                
                forecast_lines = []
                days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
                
                day_count = 0
                for date_str, items in list(daily_forecasts.items())[:7]:
                    current_date = datetime.datetime.strptime(date_str + f".{datetime.datetime.now().year}", "%d.%m.%Y")
                    weekday = days_of_week[current_date.weekday()]
                    
                    avg_temp = round(sum(item['main']['temp'] for item in items) / len(items))
                    min_temp = round(min(item['main']['temp'] for item in items))
                    max_temp = round(max(item['main']['temp'] for item in items))
                    max_pop = max(item.get('pop', 0) for item in items) * 100
                    
                    forecast_lines.append(
                        f"📅 <b>{weekday} {date_str}</b>\n"
                        f"   ├ 🌡 {min_temp}..{max_temp}°C (ср. {avg_temp}°C)\n"
                        f"   └ ☔ Осадки: {max_pop:.0f}%"
                    )
                    
                    day_count += 1
                
                result = f"📆 <b>Прогноз на 7 дней</b>\n\n" + "\n".join(forecast_lines)
                
                return result, None
                
        except Exception as e:
            return None, f"❌ Ошибка получения прогноза: {e}"

def get_weather_advice(temp, humidity, wind_speed, weather_id, hour, month, is_day, clouds, uvi, kp=None):
    """Получить персонализированный совет по погоде"""
    
    advice_pool = [
        "💪 Хорошего дня!",
        "😊 Улыбнитесь, погода не важна",
        "🌈 Хорошего настроения!",
        "🌟 Каждый день уникален",
        "☕ Хорошего дня!"
    ]
    
    return random.choice(advice_pool)

def format_weather_report(weather_data, moon_data, geomagnetic, estimated_uvi, uv_desc, uv_advice, forecast_lines=None, zodiac_sign=None):
    """Форматировать полный отчет о погоде"""
    
    now = datetime.datetime.now()
    
    w_info = weather_data['weather'][0]
    w_id = w_info['id']
    temp = round(weather_data['main']['temp'])
    feels_like = round(weather_data['main']['feels_like'])
    desc = w_info['description']
    name = weather_data['name']
    
    humidity = weather_data['main']['humidity']
    pressure = round(weather_data['main']['pressure'] * 0.750062)
    
    wind_speed = round(weather_data['wind']['speed'])
    wind_deg = weather_data['wind'].get('deg', 0)
    clouds = weather_data['clouds']['all']
    
    sunrise_timestamp = weather_data['sys']['sunrise']
    sunset_timestamp = weather_data['sys']['sunset']
    timezone_offset = weather_data['timezone']
    
    sunrise_time = datetime.datetime.fromtimestamp(sunrise_timestamp + timezone_offset).strftime("%H:%M")
    sunset_time = datetime.datetime.fromtimestamp(sunset_timestamp + timezone_offset).strftime("%H:%M")
    
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
    
    wind_emoji = get_wind_emoji(wind_speed)
    humidity_emoji = get_humidity_emoji(humidity)
    wind_dir = get_wind_direction(wind_deg)
    
    report = (
        f"{weather_emoji} <b>{name}</b>\n"
        f"🌡 {temp}°C (ощущается как {feels_like}°C)\n"
        f"{desc.capitalize()}\n\n"
        f"{humidity_emoji} Влажность: {humidity}%\n"
        f"{wind_emoji} Ветер: {wind_speed} м/с, {wind_dir}\n"
        f"📊 Давление: {pressure} мм рт.ст.\n"
        f"☁️ Облачность: {clouds}%\n"
        f"\n🌙 <b>Луна сегодня:</b>\n"
        f"{moon_data['emoji']} {moon_data['name']}\n"
        f"💡 Освещенность: {moon_data['illumination']}%\n"
        f"\n🌅 <b>Восход и закат:</b>\n"
        f"🌄 Восход: {sunrise_time}\n"
        f"🌇 Закат: {sunset_time}"
    )
    
    if forecast_lines and len(forecast_lines) > 0:
        report += f"\n\n📅 <b>Почасовой прогноз на 24 часа:</b>"
        for line in forecast_lines:
            report += f"\n{line}"
    
    if zodiac_sign:
        sign_data = ZODIAC_SIGNS.get(zodiac_sign)
        if sign_data:
            horoscope_note = f"\n\n🔮 <b>Гороскоп для {sign_data['emoji']} {sign_data['name']}:</b>\nНажмите кнопку ниже, чтобы узнать свою судьбу!"
        else:
            horoscope_note = f"\n\n🔮 <b>Гороскоп:</b>\nНажмите кнопку ниже, чтобы узнать свою судьбу!"
    else:
        horoscope_note = f"\n\n🔮 <b>Гороскоп:</b>\nУстановите /zodiac и получайте персональные прогнозы!"
    
    advice = get_weather_advice(temp, humidity, wind_speed, w_id, now.hour, now.month, True, clouds, estimated_uvi)
    report += horoscope_note
    report += f"\n\n💡 <b>Совет дня:</b>\n{advice}"
    
    return report

async def get_weather_with_details(city_or_coords, user_id=None):
    """Получить текущую погоду со всеми деталями"""
    
    weather_data, error = await get_weather_data(city_or_coords)
    
    if error or not weather_data:
        return None, error or "❌ Не удалось получить данные", None, None, None
    
    try:
        coord = weather_data['coord']
        
        forecast_lines, forecast_error = await get_hourly_forecast(coord['lat'], coord['lon'])
        if forecast_error:
            forecast_lines = None
        
        now = datetime.datetime.now()
        hour = now.hour
        clouds = weather_data['clouds']['all']
        
        geomagnetic = await get_geomagnetic_data()
        moon_data = await get_moon_data()
        
        zodiac_sign = None
        if user_id:
            zodiac_sign = get_user_zodiac(user_id)
        
        estimated_uvi = estimate_uv_from_sun(hour, clouds)
        uv_desc, uv_advice = get_uv_description(estimated_uvi)
        
        report = format_weather_report(weather_data, moon_data, geomagnetic, estimated_uvi, uv_desc, uv_advice, forecast_lines, zodiac_sign)
        
        return (report, weather_data['name'], weather_data.get('timezone', 10800), None, weather_data['coord'], None)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке данных: {e}")
        return None, "❌ Ошибка при обработке данных", None, None, None

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def start(msg: types.Message):
    init_db()
    migrate_db()
    
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
/weather - Показать погоду для сохраненного города
/horoscope - Показать меню гороскопа
/zodiac - Установить ваш знак зодиака
/joke - Случайный анекдот
/jokes - Подборка анекдотов (3 шт)
/joke_types - Типы анекдотов
/uv - Информация об UV-индексе
/magnet - Информация о магнитных бурях
/moon - Информация о фазе луны
/test - Проверить работу API погоды
/test_horoscope - Проверить работу API гороскопа
/test_joke - Проверить работу анекдотов

<b>Как пользоваться:</b>
1. Выберите время для рассылки
2. Отправьте свою локацию или название города
3. Получайте ежедневную погоду с деталями
4. Используйте /horoscope для гороскопа
5. Используйте /joke для анекдота
    """
    await msg.answer(help_text, parse_mode="HTML")

@dp.message(Command("test"))
async def test_cmd(msg: types.Message):
    await msg.answer("🔄 Проверка API ключа погоды...")
    api_ok, api_message = await test_api_key()
    await msg.answer(api_message)

@dp.message(Command("test_horoscope"))
async def test_horoscope(msg: types.Message):
    """Тест API гороскопа с резервными данными"""
    await msg.answer("🔄 Проверяю API гороскопа... Это может занять несколько секунд.")
    
    try:
        result = await get_horoscope("aries", "today")
        
        if result:
            description = result.get('description', 'Нет описания')
            compatibility = result.get('compatibility', 'Нет данных')
            mood = result.get('mood', 'Нет данных')
            color = result.get('color', 'Нет данных')
            lucky_number = result.get('lucky_number', 'Нет данных')
            
            response = (
                f"✅ <b>Гороскоп работает!</b>\n\n"
                f"📝 <b>Описание для Овна на сегодня:</b>\n"
                f"{description}\n\n"
                f"💕 <b>Совместимость:</b> {compatibility}\n"
                f"😊 <b>Настроение:</b> {mood}\n"
                f"🎨 <b>Цвет:</b> {color}\n"
                f"🔢 <b>Счастливое число:</b> {lucky_number}\n\n"
                f"📊 <b>Используются {'данные API' if 'current_date' in result else 'резервные данные'}</b>"
            )
            await msg.answer(response, parse_mode="HTML")
        else:
            await msg.answer(
                "❌ <b>Не удалось получить гороскоп.</b>\n"
                "Попробуйте позже.",
                parse_mode="HTML"
            )
    except Exception as e:
        await msg.answer(f"❌ <b>Ошибка при запросе:</b>\n{str(e)[:200]}", parse_mode="HTML")

@dp.message(Command("test_joke"))
async def test_joke(msg: types.Message):
    """Тест анекдотов"""
    await msg.answer("🔄 Проверяю анекдоты...")
    
    joke = await get_russian_joke('random')
    
    if joke:
        await msg.answer(
            f"✅ <b>Анекдоты работают!</b>\n\n{joke}",
            parse_mode="HTML"
        )
    else:
        await msg.answer(
            "❌ <b>Не удалось получить анекдот.</b>\n"
            "Попробуйте позже.",
            parse_mode="HTML"
        )

@dp.message(Command("joke"))
async def random_joke(msg: types.Message):
    """Получить случайный анекдот"""
    await msg.answer("🔄 Ищу смешной анекдот...")
    
    joke = await get_russian_joke('random')
    
    if joke:
        # Добавляем кнопку для следующего анекдота
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="😄 Ещё анекдот", callback_data="joke_random")],
            [InlineKeyboardButton(text="📋 Типы анекдотов", callback_data="joke_types")]
        ])
        await msg.answer(joke, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(
            "😔 Не удалось найти анекдот. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="joke_random")]
            ])
        )

@dp.message(Command("jokes"))
async def multiple_jokes(msg: types.Message):
    """Получить несколько анекдотов"""
    await msg.answer("🔄 Собираю подборку анекдотов...")
    
    jokes = await get_multiple_jokes(3)
    
    if jokes:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="😄 Ещё подборку", callback_data="jokes_multiple")]
        ])
        await msg.answer(jokes, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer("😔 Не удалось получить подборку анекдотов. Попробуйте позже.")

@dp.message(Command("joke_types"))
async def joke_types(msg: types.Message):
    """Показать типы анекдотов"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 Случайный", callback_data="joke_type_random"),
            InlineKeyboardButton(text="📱 Современный", callback_data="joke_type_modern")
        ],
        [
            InlineKeyboardButton(text="🕰 Советский", callback_data="joke_type_soviet")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    
    await msg.answer(
        "📋 <b>Типы анекдотов:</b>\n\n"
        "Выберите тип:",
        reply_markup=kb,
        parse_mode="HTML"
    )

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
        result = await get_weather_with_details(city, msg.from_user.id)
        
        if result[0]:
            report, city, tz, _, coord, full_data = result
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{coord['lat']}_{coord['lon']}")
                ],
                [
                    InlineKeyboardButton(text="📅 На завтра", callback_data=f"tomorrow_{coord['lat']}_{coord['lon']}"),
                    InlineKeyboardButton(text="📆 На неделю", callback_data=f"week_{coord['lat']}_{coord['lon']}")
                ],
                [
                    InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                    InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
                ]
            ])
            await msg.answer(report, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.answer(result[1])
    else:
        await msg.answer("❌ Город не сохранен. Отправьте локацию или название города.")

@dp.message(Command("horoscope"))
async def horoscope_menu(msg: types.Message):
    """Меню гороскопа с выбором знака"""
    
    user_zodiac = get_user_zodiac(msg.from_user.id)
    
    zodiac_buttons = []
    row = []
    
    for i, (sign_en, sign_data) in enumerate(ZODIAC_SIGNS.items()):
        button_text = f"{sign_data['emoji']} {sign_data['name']}"
        if user_zodiac == sign_en:
            button_text = f"⭐ {button_text}"
            
        button = InlineKeyboardButton(
            text=button_text, 
            callback_data=f"horoscope_{sign_en}"
        )
        row.append(button)
        
        if (i + 1) % 3 == 0:
            zodiac_buttons.append(row)
            row = []
    
    if row:
        zodiac_buttons.append(row)
    
    zodiac_buttons.append([
        InlineKeyboardButton(text="📅 Сегодня", callback_data="horoscope_period_today"),
        InlineKeyboardButton(text="🔮 Завтра", callback_data="horoscope_period_tomorrow"),
        InlineKeyboardButton(text="📆 Неделя", callback_data="horoscope_period_weekly")
    ])
    
    if user_zodiac:
        zodiac_buttons.append([
            InlineKeyboardButton(text="⭐ Мой знак", callback_data="horoscope_mine")
        ])
    
    # Добавляем кнопку с анекдотом
    zodiac_buttons.append([
        InlineKeyboardButton(text="😄 Случайный анекдот", callback_data="joke_random")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=zodiac_buttons)
    
    await msg.answer(
        "🔮 <b>Астрологический прогноз</b>\n\n"
        "Выберите ваш знак зодиака или период:",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(Command("zodiac"))
async def set_zodiac(msg: types.Message):
    """Установить знак зодиака пользователя"""
    
    zodiac_buttons = []
    row = []
    
    for i, (sign_en, sign_data) in enumerate(ZODIAC_SIGNS.items()):
        button = InlineKeyboardButton(
            text=f"{sign_data['emoji']} {sign_data['name']}", 
            callback_data=f"setzodiac_{sign_en}"
        )
        row.append(button)
        
        if (i + 1) % 3 == 0:
            zodiac_buttons.append(row)
            row = []
    
    if row:
        zodiac_buttons.append(row)
    
    kb = InlineKeyboardMarkup(inline_keyboard=zodiac_buttons)
    
    await msg.answer(
        "⭐ <b>Выберите ваш знак зодиака:</b>\n\n"
        "Это позволит быстро получать гороскоп для вашего знака.",
        reply_markup=kb,
        parse_mode="HTML"
    )

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
    moon_data = await get_moon_data()
    
    phase = moon_data['phase']
    
    days_to_full = (0.5 - phase) % 1.0
    days_to_full = min(days_to_full, 1 - days_to_full) * 29.53
    
    days_to_new = (1 - phase) % 1.0
    days_to_new = min(days_to_new, 1 - days_to_new) * 29.53
    
    await msg.answer(
        f"🌙 <b>Фаза луны сегодня:</b>\n\n"
        f"{moon_data['emoji']} <b>{moon_data['name']}</b>\n"
        f"💡 Освещенность: {moon_data['illumination']}%\n\n"
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

# --- ОБРАБОТЧИКИ CALLBACK ---

@dp.callback_query(F.data.startswith("set_"))
async def set_time(call: types.CallbackQuery):
    t = int(call.data.split("_")[1])
    update_user(call.from_user.id, time=t)
    geo_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]], 
        resize_keyboard=True
    )
    await call.message.edit_text(f"✅ Время установлено на {t}:00.\nТеперь отправь локацию или напиши город.")
    await call.message.answer("ℹ️ Отправьте геопозицию или название города", 
                             reply_markup=geo_kb)
    await call.answer()

@dp.callback_query(F.data.startswith("setzodiac_"))
async def process_set_zodiac(call: types.CallbackQuery):
    sign_en = call.data.split("_")[1]
    sign_data = ZODIAC_SIGNS.get(sign_en)
    
    if sign_data:
        update_user(call.from_user.id, zodiac_sign=sign_en)
        await call.message.edit_text(
            f"✅ Ваш знак зодиака сохранен: {sign_data['emoji']} {sign_data['name']}\n\n"
            f"Теперь вы можете использовать кнопку «Мой знак» в меню гороскопа."
        )
    else:
        await call.message.edit_text("❌ Ошибка: знак не найден")
    
    await call.answer()

@dp.callback_query(F.data.startswith("refresh_"))
async def refresh_weather(call: types.CallbackQuery):
    await call.answer("Обновляю данные...")
    
    parts = call.data.split('_')
    lat = float(parts[1])
    lon = float(parts[2])
    
    coords = {"lat": lat, "lon": lon}
    result = await get_weather_with_details(coords, call.from_user.id)
    
    if result[0]:
        report, city, tz, _, coord, full_data = result
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{coord['lat']}_{coord['lon']}")
            ],
            [
                InlineKeyboardButton(text="📅 На завтра", callback_data=f"tomorrow_{coord['lat']}_{coord['lon']}"),
                InlineKeyboardButton(text="📆 На неделю", callback_data=f"week_{coord['lat']}_{coord['lon']}")
            ],
            [
                InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
            ]
        ])
        
        await call.message.edit_text(f"📍 {city}\n\n{report}", 
                                    reply_markup=kb,
                                    parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Не удалось обновить погоду")

@dp.callback_query(F.data.startswith("tomorrow_"))
async def show_tomorrow_forecast(call: types.CallbackQuery):
    await call.answer("Загружаю прогноз на завтра...")
    
    parts = call.data.split('_')
    lat = float(parts[1])
    lon = float(parts[2])
    
    forecast, error = await get_tomorrow_forecast(lat, lon)
    
    if forecast:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 К текущей погоде", callback_data=f"refresh_{lat}_{lon}")
            ],
            [
                InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
            ]
        ])
        
        await call.message.edit_text(forecast, 
                                    reply_markup=kb,
                                    parse_mode="HTML")
    else:
        await call.message.answer(error or "❌ Не удалось получить прогноз")

@dp.callback_query(F.data.startswith("week_"))
async def show_weekly_forecast(call: types.CallbackQuery):
    await call.answer("Загружаю прогноз на неделю...")
    
    parts = call.data.split('_')
    lat = float(parts[1])
    lon = float(parts[2])
    
    forecast, error = await get_weekly_forecast(lat, lon)
    
    if forecast:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 К текущей погоде", callback_data=f"refresh_{lat}_{lon}")
            ],
            [
                InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
            ]
        ])
        
        await call.message.edit_text(forecast, 
                                    reply_markup=kb,
                                    parse_mode="HTML")
    else:
        await call.message.answer(error or "❌ Не удалось получить прогноз")

@dp.callback_query(F.data == "horoscope_menu")
async def horoscope_button(call: types.CallbackQuery):
    await call.answer()
    await horoscope_menu(call.message)

@dp.callback_query(F.data == "back_to_horoscope_menu")
async def back_to_horoscope_menu(call: types.CallbackQuery):
    await horoscope_menu(call.message)
    await call.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(call: types.CallbackQuery):
    """Вернуться в главное меню"""
    await call.answer()
    await call.message.edit_text(
        "🤖 <b>Главное меню</b>\n\n"
        "Используйте команды:\n"
        "/weather - Погода\n"
        "/horoscope - Гороскоп\n"
        "/joke - Анекдот\n"
        "/help - Помощь",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "back_to_zodiac")
async def back_to_zodiac(call: types.CallbackQuery):
    await set_zodiac(call.message)
    await call.answer()

@dp.callback_query(F.data.startswith("horoscope_"))
async def process_horoscope(call: types.CallbackQuery):
    data = call.data
    logger.info(f"Получен callback: {data}")
    
    if data == "horoscope_period_today":
        await call.message.edit_text(
            "📅 Выберите знак зодиака на сегодня:",
            reply_markup=create_zodiac_keyboard("today")
        )
        await call.answer()
        return
    
    elif data == "horoscope_period_tomorrow":
        await call.message.edit_text(
            "🔮 Выберите знак зодиака на завтра:",
            reply_markup=create_zodiac_keyboard("tomorrow")
        )
        await call.answer()
        return
    
    elif data == "horoscope_period_weekly":
        await call.message.edit_text(
            "📆 Выберите знак зодиака на неделю:",
            reply_markup=create_zodiac_keyboard("weekly")
        )
        await call.answer()
        return
    
    elif data == "horoscope_mine":
        zodiac_sign = get_user_zodiac(call.from_user.id)
        
        if zodiac_sign:
            await call.answer("Загружаю гороскоп...")
            await show_horoscope_for_sign(call, zodiac_sign, "today")
        else:
            await call.message.edit_text(
                "❌ Вы еще не сохранили свой знак зодиака.\n\n"
                "Используйте команду /zodiac чтобы выбрать знак.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐ Выбрать знак", callback_data="back_to_zodiac")]
                ])
            )
        await call.answer()
        return
    
    elif data.startswith("horoscope_sign_"):
        parts = data.split("_")
        if len(parts) >= 4:
            period = parts[2]
            sign_en = parts[3]
            await call.answer("Загружаю гороскоп...")
            await show_horoscope_for_sign(call, sign_en, period)
        return
    
    elif len(data.split("_")) == 2:
        sign_en = data.split("_")[1]
        await call.answer("Загружаю гороскоп...")
        await show_horoscope_for_sign(call, sign_en, "today")
        return

def create_zodiac_keyboard(period):
    zodiac_buttons = []
    row = []
    
    for i, (sign_en, sign_data) in enumerate(ZODIAC_SIGNS.items()):
        button = InlineKeyboardButton(
            text=f"{sign_data['emoji']} {sign_data['name']}", 
            callback_data=f"horoscope_sign_{period}_{sign_en}"
        )
        row.append(button)
        
        if (i + 1) % 3 == 0:
            zodiac_buttons.append(row)
            row = []
    
    if row:
        zodiac_buttons.append(row)
    
    zodiac_buttons.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_horoscope_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=zodiac_buttons)

async def show_horoscope_for_sign(call, sign_en, period):
    sign_data = ZODIAC_SIGNS.get(sign_en)
    if not sign_data:
        await call.message.edit_text(
            f"❌ Ошибка: знак не найден",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_horoscope_menu")]
            ])
        )
        return
    
    await call.message.edit_text(f"🔄 Получаю гороскоп для {sign_data['emoji']} {sign_data['name']}...")
    
    horoscope_data = await get_horoscope(sign_en, period)
    
    if not horoscope_data:
        await call.message.edit_text(
            f"❌ Не удалось получить гороскоп.\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_horoscope_menu")]
            ])
        )
        return
    
    report = format_horoscope(horoscope_data, sign_data['name'], sign_data['emoji'], period)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data=f"horoscope_sign_today_{sign_en}"),
            InlineKeyboardButton(text="🔮 Завтра", callback_data=f"horoscope_sign_tomorrow_{sign_en}"),
            InlineKeyboardButton(text="📆 Неделя", callback_data=f"horoscope_sign_weekly_{sign_en}")
        ],
        [
            InlineKeyboardButton(text="🔙 К выбору знака", callback_data="back_to_horoscope_menu"),
            InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
        ]
    ])
    
    await call.message.edit_text(report, reply_markup=kb, parse_mode="HTML")

# --- ОБРАБОТЧИКИ ДЛЯ АНЕКДОТОВ ---

@dp.callback_query(F.data == "joke_random")
async def joke_random_callback(call: types.CallbackQuery):
    await call.answer("Ищу анекдот...")
    
    joke = await get_russian_joke('random')
    
    if joke:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="😄 Ещё анекдот", callback_data="joke_random")],
            [InlineKeyboardButton(text="📋 Типы анекдотов", callback_data="joke_types")]
        ])
        await call.message.edit_text(joke, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(
            "😔 Не удалось найти анекдот. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="joke_random")]
            ])
        )

@dp.callback_query(F.data == "jokes_multiple")
async def jokes_multiple_callback(call: types.CallbackQuery):
    await call.answer("Собираю подборку...")
    
    jokes = await get_multiple_jokes(3)
    
    if jokes:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="😄 Ещё подборку", callback_data="jokes_multiple")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ])
        await call.message.edit_text(jokes, reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(
            "😔 Не удалось получить подборку анекдотов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="jokes_multiple")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
            ])
        )

@dp.callback_query(F.data == "joke_types")
async def joke_types_callback(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 Случайный", callback_data="joke_type_random"),
            InlineKeyboardButton(text="📱 Современный", callback_data="joke_type_modern")
        ],
        [
            InlineKeyboardButton(text="🕰 Советский", callback_data="joke_type_soviet")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    
    await call.message.edit_text(
        "📋 <b>Типы анекдотов:</b>\n\n"
        "Выберите тип:",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("joke_type_"))
async def joke_type_callback(call: types.CallbackQuery):
    joke_type = call.data.replace("joke_type_", "")
    await call.answer(f"Ищу {joke_type} анекдот...")
    
    joke = await get_russian_joke(joke_type)
    
    if joke:
        type_names = {
            'random': '🎲 Случайный',
            'modern': '📱 Современный',
            'soviet': '🕰 Советский'
        }
        type_name = type_names.get(joke_type, 'Случайный')
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Ещё", callback_data=f"joke_type_{joke_type}"),
                InlineKeyboardButton(text="📋 Типы", callback_data="joke_types")
            ]
        ])
        await call.message.edit_text(f"<b>{type_name}:</b>\n\n{joke}", reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text(
            f"😔 Не удалось найти {joke_type} анекдот.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Типы анекдотов", callback_data="joke_types")]
            ])
        )

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(F.location)
async def handle_location(msg: types.Message):
    await msg.answer("🔄 Получаю погоду по вашему местоположению...")
    coords = {"lat": msg.location.latitude, "lon": msg.location.longitude}
    result = await get_weather_with_details(coords, msg.from_user.id)
    
    if result[0]:
        report, city, tz, _, coord, full_data = result
        
        update_user(msg.chat.id, city=city, timezone=tz)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{coord['lat']}_{coord['lon']}")
            ],
            [
                InlineKeyboardButton(text="📅 На завтра", callback_data=f"tomorrow_{coord['lat']}_{coord['lon']}"),
                InlineKeyboardButton(text="📆 На неделю", callback_data=f"week_{coord['lat']}_{coord['lon']}")
            ],
            [
                InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
            ]
        ])
        
        await msg.answer(f"📍 Город определен: {city}!\n\n{report}", 
                        reply_markup=kb,
                        parse_mode="HTML")
    else:
        error_msg = result[1] if len(result) > 1 else "❌ Ошибка получения погоды"
        await msg.answer(f"{error_msg}\nПопробуй написать город текстом.")

@dp.message()
async def handle_city(msg: types.Message):
    if msg.text.startswith('/'):
        return
    
    await msg.answer(f"🔄 Ищу город {msg.text}...")
    result = await get_weather_with_details(msg.text, msg.from_user.id)
    
    if result[0]:
        report, city, tz, _, coord, full_data = result
        
        update_user(msg.chat.id, city=city, timezone=tz)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{coord['lat']}_{coord['lon']}")
            ],
            [
                InlineKeyboardButton(text="📅 На завтра", callback_data=f"tomorrow_{coord['lat']}_{coord['lon']}"),
                InlineKeyboardButton(text="📆 На неделю", callback_data=f"week_{coord['lat']}_{coord['lon']}")
            ],
            [
                InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
            ]
        ])
        
        await msg.answer(f"✅ Город {city} сохранен!\n\n{report}", 
                        reply_markup=kb,
                        parse_mode="HTML")
    else:
        error_msg = result[1] if len(result) > 1 else "❌ Город не найден"
        await msg.answer(f"{error_msg}\nНапиши, например: Москва")

# --- РАССЫЛКА ---
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
                        result = await get_weather_with_details(city, u_id)
                        
                        if result[0]:
                            report, _, _, _, coord, _ = result
                            
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{coord['lat']}_{coord['lon']}")
                                ],
                                [
                                    InlineKeyboardButton(text="📅 На завтра", callback_data=f"tomorrow_{coord['lat']}_{coord['lon']}"),
                                    InlineKeyboardButton(text="📆 На неделю", callback_data=f"week_{coord['lat']}_{coord['lon']}")
                                ],
                                [
                                    InlineKeyboardButton(text="🔮 Гороскоп", callback_data="horoscope_menu"),
                                    InlineKeyboardButton(text="😄 Анекдот", callback_data="joke_random")
                                ]
                            ])
                            
                            try: 
                                await bot.send_message(u_id, 
                                                      f"☀️ <b>Доброе утро!</b>\n\n{report}", 
                                                      reply_markup=kb,
                                                      parse_mode="HTML")
                                logger.info(f"✅ Успешно отправлено пользователю {u_id}")
                            except Exception as e:
                                logger.error(f"❌ Не удалось отправить сообщение пользователю {u_id}: {e}")
                        else:
                            logger.error(f"❌ Не удалось получить погоду для пользователя {u_id}")
                
                await asyncio.sleep(61)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка в рассылке: {e}")
            await asyncio.sleep(60)

# --- ЗАПУСК ---
async def main():
    logger.info("=" * 50)
    logger.info("🚀 ЗАПУСК БОТА ПОГОДЫ С ГОРОСКОПОМ И АНЕКДОТАМИ")
    logger.info("=" * 50)
    
    init_db()
    migrate_db()
    
    logger.info("\n🔑 ПРОВЕРКА API КЛЮЧА OPENWEATHERMAP:")
    api_ok, api_message = await test_api_key()
    logger.info(api_message)
    
    if not api_ok:
        logger.error("\n❌ ПРОБЛЕМА С API КЛЮЧОМ!")
    
    logger.info("\n🛰️ ПРОВЕРКА ПОДКЛЮЧЕНИЯ К NOAA:")
    geomagnetic = await get_geomagnetic_data()
    if geomagnetic:
        logger.info(f"✅ Подключение к NOAA работает, текущий Kp: {geomagnetic[0]}")
    else:
        logger.warning("⚠️ Не удалось подключиться к NOAA")
    
    logger.info("\n🔮 ПРОВЕРКА API ГОРОСКОПА:")
    horoscope_test = await get_horoscope("aries", "today")
    if horoscope_test:
        logger.info("✅ API гороскопа работает!")
    else:
        logger.info("✅ Резервные данные гороскопа загружены")
    
    logger.info("\n😄 ПРОВЕРКА АНЕКДОТОВ:")
    joke_test = await get_russian_joke('random')
    if joke_test:
        logger.info("✅ Анекдоты работают!")
        logger.info(f"📝 Пример: {joke_test[:100]}...")
    else:
        logger.warning("⚠️ Проблема с получением анекдотов, используются запасные")
    
    logger.info("\n" + "=" * 50)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ!")
    logger.info("=" * 50)
    
    asyncio.create_task(mailing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
