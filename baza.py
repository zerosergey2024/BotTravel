import logging
import os
import aiohttp
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram import Router, F
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

# Инициализация асинхронного клиента OpenAI
client = AsyncOpenAI(
    api_key=PROXY_API_KEY,
    base_url="https://api.proxyapi.ru/openai/v1",  # Корректный эндпоинт
)
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
BASE_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

# Инициализация бота и роутера
bot = Bot(token=TELEGRAM_BOT_TOKEN)
router = Router()
dp = Dispatcher()

# Логика работы с файлами
user_data = {}

def process_text_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    except UnicodeDecodeError:
        logging.error(f"Файл не является текстовым (возможно, неправильная кодировка): {file_path}")
        return None
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
    file_path = f"../aiBot_Travel/downloads/{message.from_user.id}_{file_name}"

    os.makedirs("../aiBot_Travel/downloads", exist_ok=True)

    try:
        downloaded_file = await bot.download_file(file_info.file_path)
        if not hasattr(downloaded_file, 'getvalue'):
            raise ValueError("Скачанный файл не является объектом BytesIO")

        with open(file_path, "wb") as new_file:
            new_file.write(downloaded_file.getvalue())

        content = process_text_file(file_path)
        if content is None:
            await message.answer("❌ Не удалось обработать файл.")
            return

        user_id = message.from_user.id
        if user_id not in user_data:
            user_data[user_id] = {"knowledge": "", "instructions": ""}

        if "инструкция" in file_name.lower():
            user_data[user_id]["instructions"] = content
            await message.answer("✅ Инструкция обновлена!")
        elif "база" in file_name.lower():
            user_data[user_id]["knowledge"] = content
            await message.answer("✅ База знаний обновлена!")

    except Exception as e:
        logging.error(f"Ошибка при обработке файла: {e}")
        await message.answer("⚠ Произошла ошибка при обработке файла.")

@router.message(Command("instructions"))
async def show_instructions(message: Message):
    user_id = message.from_user.id
    instructions = user_data.get(user_id, {}).get("instructions", "Инструкция не загружена.")
    await message.answer(f"Ваши инструкции:\n{instructions}")

@router.message(Command("knowledge"))
async def show_knowledge(message: Message):
    user_id = message.from_user.id
    knowledge = user_data.get(user_id, {}).get("knowledge", "База знаний не загружена.")
    await message.answer(f"Ваша база знаний:\n{knowledge}")


@router.message(Command("start"))
async def start_command(message: Message):
    photo = FSInputFile('img/ФотоБот1.jpg')

    await message.answer_photo(
        photo=photo,
        caption="Привет! Я ваш AI-помощник в путешествии и делах. Задайте любой вопрос или воспользуйтесь кнопками.",
        reply_markup=main_keyboard()
    )

class Form(StatesGroup):
    weather = State()
    translate = State()



# Клавиатура с основными кнопками
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🌤️ Погода"))
    builder.add(types.KeyboardButton(text="🌍 Перевод"))
    return builder.as_markup(resize_keyboard=True)


# Клавиатура для отмены действия
def cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

@dp.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено", reply_markup=main_keyboard())


@dp.message(F.text == "🌤️ Погода")
async def weather_handler(message: Message, state: FSMContext):
    await state.set_state(Form.weather)
    await message.answer(
        "Введите название города:",
        reply_markup=cancel_keyboard()
    )
@dp.message(F.text == "🌍 Перевод")
async def translate_handler(message: Message, state: FSMContext):
    await state.set_state(Form.translate)
    await message.answer(
        "Введите текст для перевода:",
        reply_markup=cancel_keyboard()
    )
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
    try:
        # Формирование запроса к нейросети
        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Отвечай кратко и информативно."},
                {"role": "user", "content": message.text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        # Отправка ответа пользователю
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
    asyncio.run(main())