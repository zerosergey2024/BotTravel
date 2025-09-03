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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Загрузка переменных окружения
load_dotenv()

# Настройка путей
BASE_DIR = Path(__file__).parent
DATA_DIR = os.path.abspath(os.path.join(os.getcwd(), "data"))
DOWNLOADS_DIR = os.path.abspath(os.path.join(os.getcwd(), "downloads"))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Переменные окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
BASE_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

# Проверка критичных переменных
if not TELEGRAM_BOT_TOKEN:
    logging.error("❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения!")
    exit(1)
else:
    logging.info("✅ TELEGRAM_BOT_TOKEN успешно загружен.")

if not API_KEY:
    logging.error("❌ API_KEY (для OpenAI/Groq) не найден!")
    exit(1)

if not WEATHER_API_KEY:
    logging.warning("⚠️ WEATHER_API_KEY не найден — функции погоды отключены.")

# Создание бота
bot = Bot(token=TELEGRAM_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# Настройка клиента OpenAI (или Groq / Ollama)
client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://api.openai.com/v1",  # Для OpenAI
    # base_url="https://api.groq.com/openai/v1",  # Для Groq
    # base_url="http://localhost:11434/v1",       # Для Ollama
)

# Хранилище данных пользователей
user_data = {}

def restore_user_data():
    """Восстанавливает данные пользователей из файлов"""
    for file_name in os.listdir(DATA_DIR):
        if not file_name.endswith('.txt'):
            continue
        try:
            parts = file_name.replace('.txt', '').split('_')
            if len(parts) != 2:
                continue
            data_type, user_id_str = parts
            user_id = int(user_id_str)
            file_path = os.path.join(DATA_DIR, file_name)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if user_id not in user_data:
                user_data[user_id] = {"knowledge": "", "instruction": ""}
            user_data[user_id][data_type] = content
            logging.info(f"Восстановлены данные для user_id={user_id}, type={data_type}")
        except Exception as e:
            logging.error(f"Ошибка восстановления из файла {file_name}: {e}")

def save_user_data(user_id: int, data_type: str, content: str):
    """Сохраняет данные пользователя в файл"""
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

def load_user_data(user_id: int, data_type: str) -> str:
    """Загружает данные пользователя из файла"""
    file_path = os.path.join(DATA_DIR, f"{data_type}_{user_id}.txt")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            logging.info(f"Данные загружены: {file_path}")
            return content
        except Exception as e:
            logging.error(f"Ошибка чтения файла {file_path}: {e}")
    return ""

# --- Клавиатуры ---
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(
        types.KeyboardButton(text="🌤️ Погода"),
        types.KeyboardButton(text="🌍 Перевод"),
        types.KeyboardButton(text="❓ Спросить")
    )
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
@dp.message(Command("start"))
async def start_command(message: Message):
    photo_path = BASE_DIR / "img" / "ФотоБот1.jpg"
    if photo_path.exists():
        photo = FSInputFile(str(photo_path))
        await message.answer_photo(
            photo=photo,
            caption="Привет! Я ваш AI-помощник в путешествиях. Чем могу помочь?",
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            "Привет! Я ваш AI-помощник в путешествиях. Чем могу помочь?",
            reply_markup=main_keyboard()
        )

@dp.message(F.document)
async def handle_document(message: Message):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("⚠ Принимаются только текстовые файлы (.txt)")
        return

    try:
        file_info = await bot.get_file(message.document.file_id)
        file_name = f"{message.from_user.id}_{file_info.file_path.split('/')[-1]}"
        file_path = Path(DOWNLOADS_DIR) / file_name
        await bot.download_file(file_info.file_path, destination=file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        if not content:
            await message.answer("❌ Файл пустой.")
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
            await message.answer("⚠ Название файла должно содержать 'инструкция' или 'база'.")
            return

        if user_id not in user_data:
            user_data[user_id] = {"knowledge": "", "instruction": ""}
        user_data[user_id][data_type] = content
        save_user_data(user_id, data_type, content)

        await message.answer(reply_text)
    except Exception as e:
        logging.error(f"Ошибка обработки документа: {e}")
        await message.answer("⚠ Ошибка при загрузке файла.")

@dp.message(Command("instruction"))
async def show_instruction(message: Message):
    user_id = message.from_user.id
    instruction = user_data.get(user_id, {}).get("instruction", "Не загружена.")
    await message.answer(f"Ваша инструкция:\n{instruction}")

@dp.message(Command("knowledge"))
async def show_knowledge(message: Message):
    user_id = message.from_user.id
    knowledge = user_data.get(user_id, {}).get("knowledge", "Не загружена.")
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

@dp.message(F.text == "❓ Спросить")
async def ask_handler(message: Message, state: FSMContext):
    await message.answer("Напишите ваш вопрос о путешествиях:", reply_markup=cancel_keyboard())

# --- Обработка погоды ---
@dp.message(Form.weather)
async def get_weather(message: Message, state: FSMContext):
    city = message.text
    if not WEATHER_API_KEY:
        await message.answer("⚠️ Сервис погоды временно недоступен.")
        await state.clear()
        await message.answer("Выберите действие:", reply_markup=main_keyboard())
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_WEATHER_URL}?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            ) as response:
                data = await response.json()
                if response.status != 200:
                    await message.answer(f"❌ Ошибка: {data.get('message', 'Город не найден')}")
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
        logging.error(f"Ошибка погоды: {e}")
        await message.answer("⚠️ Не удалось получить погоду.")
    finally:
        await state.clear()
        await message.answer("Выберите действие:", reply_markup=main_keyboard())

# --- Обработка перевода ---
@dp.message(Form.translate)
async def translate_text(message: Message, state: FSMContext):
    text = message.text
    system_prompt = "Переведи текст на русский язык. Сохрани смысл и стиль. Без пояснений."

    await ai_response(message, system_prompt, text)
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=main_keyboard())

# --- Универсальный AI-ответ ---
async def ai_response(message: Message, system_prompt: str, user_text: str):
    try:
        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",  # или "llama3-8b-8192" для Groq, "llama3" для Ollama
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        response_text = completion.choices[0].message.content
        await message.answer(response_text)
    except Exception as e:
        logging.error(f"Ошибка AI: {e}")
        await message.answer("⚠️ Не удалось обработать запрос. Проверьте API-ключ или попробуйте позже.")

@dp.message(F.text)
async def handle_ai_query(message: Message):
    user_id = message.from_user.id
    text = message.text.strip().lower()

    # Проверка на перевод
    if any(keyword in text for keyword in ["переведи", "перевод", "translate", "на русском", "на английском"]):
        await translate_text(message, None)  # временно, можно улучшить
        return

    # Формируем контекст
    user_context = user_data.get(user_id, {})
    instruction = user_context.get("instruction", "")
    knowledge = user_context.get("knowledge", "")

    system_prompt = "Ты — дружелюбный AI-гид для путешественников. Отвечай кратко и полезно."

    if instruction:
        system_prompt += f" Инструкция: {instruction}"
    if knowledge:
        system_prompt += f" Дополнительно: {knowledge}"

    await ai_response(message, system_prompt, message.text)

# --- Запуск бота ---
async def main():
    dp.include_router(router)
    restore_user_data()
    logging.info("Бот запущен и готов к работе.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())