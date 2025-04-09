import logging
import os
import aiohttp
import asyncio
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, FSInputFile
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from openai import AsyncOpenAI
from dotenv import load_dotenv
from aiogram.fsm.storage.memory import MemoryStorage

# Загрузка переменных окружения
load_dotenv()

# Настройка путей
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = os.path.abspath(os.path.join(os.getcwd(), "data"))
DOWNLOADS_DIR = os.path.abspath(os.path.join(os.getcwd(), "downloads"))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Переменные окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PROXY_API_KEY = os.getenv("PROXY_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
BASE_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

# Проверка токена
if not TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN не найден в переменных окружения!")
else:
    logging.info("TELEGRAM_BOT_TOKEN успешно загружен.")

# Инициализация бота и клиентов
bot = Bot(token=TELEGRAM_BOT_TOKEN)
router = Router()
dp = Dispatcher(storage=MemoryStorage())

client = AsyncOpenAI(
    api_key=PROXY_API_KEY,
    base_url="https://api.proxyapi.ru/openai/v1",
)

def restore_user_data():
    for file_name in os.listdir(DATA_DIR):
        if not file_name.endswith('.txt'):
            continue
        try:
            parts = file_name.replace('.txt', '').split('_')
            if len(parts) != 2:
                continue
            data_type, user_id = parts
            user_id = int(user_id)
            with open(os.path.join(DATA_DIR, file_name), 'r', encoding='utf-8') as f:
                content = f.read()

            if user_id not in user_data:
                user_data[user_id] = {"knowledge": "", "instruction": ""}
            user_data[user_id][data_type] = content
            logging.info(f"Восстановлены данные для user_id={user_id}, type={data_type}")
        except Exception as e:
            logging.error(f"Ошибка восстановления из файла {file_name}: {e}")


user_data = {}

def process_text_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        return content if content else None
    except Exception as e:
        logging.error(f"Ошибка чтения файла {file_path}: {e}")
        return None

# --- Работа с файлами ---
def save_user_data(user_id: int, data_type: str, content: str):
    if not content.strip():
        logging.warning("Попытка сохранить пустые данные.")
        return

    file_path = os.path.join(DATA_DIR, f"{data_type}_{user_id}.txt")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"Данные сохранены: {file_path}")
    except Exception as e:
        logging.error(f"Ошибка сохранения данных в файл {file_path}: {e}")


def load_user_data(user_id, data_type):
    file_path = os.path.join(DATA_DIR, f"{data_type}_{user_id}.txt")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
            logging.info(f"Данные загружены из файла: {file_path}")
            return content
        except Exception as e:
            logging.error(f"Ошибка при чтении файла {file_path}: {e}")
    else:
        logging.warning(f"Файл не найден: {file_path}")
    return None

# --- Клавиатуры ---
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🌤️ Погода"))
    builder.add(types.KeyboardButton(text="🌍 Перевод"))
    return builder.as_markup(resize_keyboard=True)

def cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

# --- FSM States ---
class Form(StatesGroup):
    weather = State()
    translate = State()

# --- Хендлеры ---
@router.message(Command("start"))
async def start_command(message: Message):
    try:
        photo = FSInputFile('img/ФотоБот1.jpg')
        await message.answer_photo(
            photo=photo,
            caption="Привет! Я ваш AI-помощник в путешествиях. Задайте вопрос или используйте кнопки:",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка загрузки изображения: {e}")
        await message.answer("Добро пожаловать! Чем могу помочь?")

@router.message(F.document)
async def handle_document(message: Message):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("⚠ Принимаются только текстовые файлы (.txt)")
        return

    try:
        file_info = await bot.get_file(message.document.file_id)
        file_path = Path(DOWNLOADS_DIR) / f"{message.from_user.id}_{file_info.file_path.split('/')[-1]}"
        await bot.download_file(file_info.file_path, destination=file_path)

        content = process_text_file(file_path)
        if not content:
            await message.answer("❌ Ошибка обработки файла")
            return

        user_id = message.from_user.id
        filename = message.document.file_name.lower()

        if "инструкция" in filename:
            data_type = "instruction"
            reply_text = "✅ Инструкция обновлена!"
        elif "база" in filename:
            data_type = "knowledge"
            reply_text = "✅ База знаний обновлена!"
        else:
            await message.answer("⚠ Неизвестный тип данных. Используйте 'инструкция' или 'база' в названии файла")
            return

        if user_id not in user_data:
            user_data[user_id] = {"knowledge": "", "instruction": ""}
        user_data[user_id][data_type] = content
        save_user_data(user_id, data_type, content)

        await message.answer(reply_text)
    except Exception as e:
        logging.error(f"Ошибка обработки документа: {e}")
        await message.answer("⚠ Произошла ошибка при обработке файла")

@router.message(Command("instruction"))
async def show_instruction(message: Message):
    user_id = message.from_user.id
    instruction = user_data.get(user_id, {}).get("instruction", "Инструкция не загружена.")
    await message.answer(f"Ваша инструкция:\n{instruction}")

@router.message(Command("knowledge"))
async def show_knowledge(message: Message):
    user_id = message.from_user.id
    knowledge = user_data.get(user_id, {}).get("knowledge", "База знаний не загружена.")
    await message.answer(f"Ваша база знаний:\n{knowledge}")

@dp.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено", reply_markup=main_keyboard())

@dp.message(F.text == "🌤️ Погода")
async def weather_handler(message: Message, state: FSMContext):
    await state.set_state(Form.weather)
    await message.answer("Введите название города:", reply_markup=cancel_keyboard())

@dp.message(F.text == "🌍 Перевод")
async def translate_handler(message: Message, state: FSMContext):
    await state.set_state(Form.translate)
    await message.answer("Введите текст для перевода:", reply_markup=cancel_keyboard())

@dp.message(Form.weather)
async def get_weather(message: Message, state: FSMContext):
    city = message.text
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_WEATHER_URL}?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            ) as response:
                data = await response.json()
                if response.status != 200:
                    await message.answer(f"Ошибка: {data.get('message', 'Неизвестная ошибка')}")
                    return

                weather = data["weather"][0]["description"].capitalize()
                temp = data["main"]["temp"]
                humidity = data["main"]["humidity"]
                wind = data["wind"]["speed"]

                response_text = (
                    f"🌤 Погода в {city}:\n"
                    f"{weather}\n"
                    f"🌡 Температура: {temp}°C\n"
                    f"💧 Влажность: {humidity}%\n"
                    f"🍃 Ветер: {wind} м/с"
                )
                await message.answer(response_text)
    except Exception as e:
        logging.error(f"Weather error: {e}")
        await message.answer("Ошибка при получении погоды")
    finally:
        await state.clear()
        await message.answer("Выберите действие:", reply_markup=main_keyboard())

@dp.message(Form.translate)
async def translate_text(message: Message, state: FSMContext):
    text = message.text
    try:
        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=[
                {"role": "system", "content": "Переведи текст на русский язык. Сохрани исходный смысл."},
                {"role": "user", "content": text}
            ]
        )
        translation = completion.choices[0].message.content
        await message.answer(f"🌍 Перевод:\n{translation}")
    except Exception as e:
        logging.error(f"Translation error: {e}")
        await message.answer("Ошибка при переводе")
    finally:
        await state.clear()
        await message.answer("Выберите действие:", reply_markup=main_keyboard())

@router.message()
async def handle_message(message: Message):
    user_id = message.from_user.id
    user_context = user_data.get(user_id, {})
    instructions = user_context.get("instruction", "")
    knowledge = user_context.get("knowledge", "")

    try:
        system_message = ("Ты туристический AI-гид. Ты ОБЯЗАН строго следовать структуре инструкций.")

        if instructions:
            system_message += f"\nИнструкция: {instructions}"
        if knowledge:
            system_message += f"\nБаза знаний: {knowledge}"

        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": message.text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        await message.answer(completion.choices[0].message.content)
    except Exception as e:
        logging.error(f"Ошибка: {str(e)}")
        await message.answer("⚠️ Произошла ошибка при обработке запроса.")

# --- Запуск бота ---
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    restore_user_data()
    asyncio.run(main())