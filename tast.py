import logging
import os
import aiohttp
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram import Router, F
from aiogram.client.session.aiohttp import AiohttpSession  # Импорт сессии с прокси
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from openai import AsyncOpenAI
from dotenv import load_dotenv
from aiogram.types import FSInputFile

# Загрузка переменных окружения
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PROXY_API_KEY = os.getenv("PROXY_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")


# Инициализация бота с кастомной сессией
bot = Bot(token=TELEGRAM_BOT_TOKEN)
router = Router()
dp = Dispatcher()

# Абсолютные пути
BASE_DIR = "/ваш_username/BotTravel"  # Укажите ваш путь
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
IMG_DIR = os.path.join(BASE_DIR, "img")

# Создаем директории при старте
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

# Инициализация OpenAI клиента
client = AsyncOpenAI(
    api_key=PROXY_API_KEY,
    base_url="https://api.proxyapi.ru/openai/v1",
)

BASE_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

user_data = {}


def process_text_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as e:
        logging.error(f"Ошибка при чтении файла: {e}")
        return None


@router.message(F.content_type == "document")
async def handle_docs(message: Message):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("⚠ Пожалуйста, отправляйте текстовые файлы (.txt).")
        return

    file_info = await bot.get_file(message.document.file_id)
    file_name = file_info.file_path.split('/')[-1]
    file_path = os.path.join(DOWNLOADS_DIR, f"{message.from_user.id}_{file_name}")

    try:
        downloaded_file = await bot.download_file(file_info.file_path)
        with open(file_path, "wb") as new_file:
            if hasattr(downloaded_file, 'getvalue'):
                new_file.write(downloaded_file.getvalue())
            else:
                new_file.write(downloaded_file.read())

        content = process_text_file(file_path)
        if content is None:
            await message.answer("❌ Не удалось обработать файл.")
            return

        user_id = message.from_user.id
        user_data.setdefault(user_id, {"knowledge": "", "instructions": ""})

        if "инструкция" in file_name.lower():
            user_data[user_id]["instructions"] = content
            await message.answer("✅ Инструкция обновлена!")
        elif "база" in file_name.lower():
            user_data[user_id]["knowledge"] = content
            await message.answer("✅ База знаний обновлена!")

    except Exception as e:
        logging.error(f"Ошибка при обработке файла: {e}")
        await message.answer("⚠ Произошла ошибка при обработке файла.")


@router.message(Command("start"))
async def start_command(message: Message):
    photo_path = os.path.join(IMG_DIR, 'ФотоБот1.jpg')

    try:
        photo = FSInputFile(photo_path)
        await message.answer_photo(
            photo=photo,
            caption="Привет! Я ваш AI-помощник в путешествии и делах.",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка загрузки фото: {e}")
        await message.answer("Добро пожаловать! Задайте вопрос или используйте кнопки.",
                             reply_markup=main_keyboard())

class Form(StatesGroup):
    weather = State()
    translate = State()

def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🌤️ Погода"))
    builder.add(types.KeyboardButton(text="🌍 Перевод"))
    return builder.as_markup(resize_keyboard=True)

def cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено", reply_markup=main_keyboard())

@router.message(F.text == "🌤️ Погода")
async def weather_handler(message: Message, state: FSMContext):
    await state.set_state(Form.weather)
    await message.answer(
        "Введите название города:",
        reply_markup=cancel_keyboard()
    )

@router.message(F.text == "🌍 Перевод")
async def translate_handler(message: Message, state: FSMContext):
    await state.set_state(Form.translate)
    await message.answer(
        "Введите текст для перевода:",
        reply_markup=cancel_keyboard()
    )

@router.message(Form.weather)
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

@router.message(Form.translate)
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
    try:
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Отвечай кратко и информативно."},
                {"role": "user", "content": message.text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        await message.answer(completion.choices[0].message.content)
    except Exception as e:
        logging.error(f"Ошибка: {str(e)}")
        await message.answer("⚠️ Произошла ошибка при обработке запроса.")


async def main():
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Проверка окружения
    if not TELEGRAM_BOT_TOKEN:
        logging.error("Токен бота не найден!")
        exit(1)

    asyncio.run(main())