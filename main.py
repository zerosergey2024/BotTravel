# ... ваши импорты ...
import logging
import os
import aiohttp
import asyncio
import time
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

# >>> ADD: импортируем pydub для конвертации и наш модуль voice
from pydub import AudioSegment
import voice_async
from main2 import ai_response

# ---

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = os.path.abspath(os.path.join(os.getcwd(), "data"))
DOWNLOADS_DIR = os.path.abspath(os.path.join(os.getcwd(), "downloads"))
AUDIO_DIR = os.path.abspath(os.path.join(os.getcwd(), "audio"))  # >>> ADD

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)  # >>> ADD

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
BASE_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

if not TELEGRAM_BOT_TOKEN:
    logging.error("❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения!")
    exit(1)
else:
    logging.info("✅ TELEGRAM_BOT_TOKEN успешно загружен.")

if not WEATHER_API_KEY:
    logging.warning("⚠️ WEATHER_API_KEY не найден — функции погоды отключены.")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://api.openai.com/v1",
)

user_data = {}

# >>> ADD: вспомогательная функция конвертации mp3 -> ogg (opus)
def mp3_to_ogg_opus(mp3_path: str, ogg_path: str) -> str:
    """
    Конвертирует mp3 в ogg (Opus) для voice-сообщения Telegram.
    Требует установленного ffmpeg в системе.
    """
    audio = AudioSegment.from_file(mp3_path, format="mp3")
    # Telegram рекомендует ~48kbps opus для голосовых, но это не строго.
    audio.export(ogg_path, format="ogg", codec="libopus", bitrate="48k")
    return ogg_path
# ---

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

def process_text_file(file_path):
    # ... как у вас было ...
    pass

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
    builder.add(types.KeyboardButton(text="🎙️ Озвучка"))
    builder.add(types.KeyboardButton(text="🌤️ Погода"))
    builder.add(types.KeyboardButton(text="🌍 Перевод"))
    return builder.as_markup(resize_keyboard=True)

def cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

# >>> ADD: клавиатура выбора голоса (reply)
def voices_keyboard(voices: list[dict]):
    """
    voices: [{'name': str, 'id': str}, ...]
    """
    builder = ReplyKeyboardBuilder()
    # Разложим кнопки по 2-3 в ряд:
    for v in voices:
        # На случай коллизий имён добавим хвост из id
        name = v["name"]
        builder.add(types.KeyboardButton(text=name))
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)
# ---

# --- FSM States ---
class Form(StatesGroup):
    weather = State()
    translate = State()

# >>> ADD: состояния для TTS
class TTS(StatesGroup):
    choosing_voice = State()
    waiting_text = State()
# ---

@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    try:
        # Подтягиваем голоса и показываем выбор
        voices = await voice_async.get_all_voices()  # [{'name','id'},...]
        # Сохраним соответствие имя->id в состоянии для конкретного юзера
        await state.update_data(voices_map={v["name"]: v["id"] for v in voices})
        await state.set_state(TTS.choosing_voice)

        photo = None
        try:
            photo = FSInputFile('img/ФотоБот1.jpg')
        except Exception:
            pass

        text = (
            "Привет! Я ваш AI-помощник. Выберите голос для озвучки, а затем пришлите текст.\n\n"
            "Сначала выберите голос:"
        )

        if photo:
            await message.answer_photo(
                photo=photo,
                caption=text,
                reply_markup=voices_keyboard(voices)
            )
        else:
            await message.answer(text, reply_markup=voices_keyboard(voices))
    except Exception as e:
        logging.error(f"Ошибка /start: {e}")
        await message.answer("Добро пожаловать! Чем могу помочь?", reply_markup=main_keyboard())

# >>> ADD: отдельная кнопка из главного меню для озвучки
@dp.message(F.text == "🎙️ Озвучка")
async def tts_entry(message: Message, state: FSMContext):
    try:
        voices = await voice_async.get_all_voices()
        await state.update_data(voices_map={v["name"]: v["id"] for v in voices})
        await state.set_state(TTS.choosing_voice)
        await message.answer("Выберите голос:", reply_markup=voices_keyboard(voices))
    except Exception as e:
        logging.error(f"TTS entry error: {e}")
        await message.answer("Не удалось загрузить список голосов.", reply_markup=main_keyboard())
# ---

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

# >>> ADD: выбор голоса (состояние TTS.choosing_voice)
@dp.message(TTS.choosing_voice)
async def choose_voice(message: Message, state: FSMContext):
    user_choice = message.text.strip()
    data = await state.get_data()
    voices_map = data.get("voices_map", {})

    if user_choice not in voices_map:
        await message.answer("Пожалуйста, выберите голос кнопкой на клавиатуре или нажмите «❌ Отмена».")
        return

    voice_id = voices_map[user_choice]
    await state.update_data(selected_voice_id=voice_id, selected_voice_name=user_choice)
    await state.set_state(TTS.waiting_text)
    await message.answer(
        f"✅ Голос «{user_choice}» выбран.\nТеперь отправьте текст, который нужно озвучить.",
        reply_markup=cancel_keyboard()
    )

# >>> ADD: генерация и отправка аудио (состояние TTS.waiting_text)
@dp.message(TTS.waiting_text)
async def tts_generate_and_send(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришлите, пожалуйста, непустой текст.")
        return

    data = await state.get_data()
    voice_id = data.get("selected_voice_id")
    voice_name = data.get("selected_voice_name", "voice")

    if not voice_id:
        await message.answer("Не найден выбранный голос. Начните заново: /start")
        await state.clear()
        return

    try:
        # Уникальные ИМЕНА ФАЙЛОВ + абсолютные пути
        base = f"{message.from_user.id}_{time.time_ns()}"
        mp3_path = os.path.abspath(os.path.join(AUDIO_DIR, f"{base}.mp3"))
        ogg_path = os.path.abspath(os.path.join(AUDIO_DIR, f"{base}.ogg"))

        # 1) Генерация MP3 (ИМЕННО в mp3_path, а не 'audio.mp3')
        await voice_async.generate_audio(text=text, voice_id=voice_id, out_name=mp3_path)

        # 2) Проверяем, что файл реально создан
        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            logging.error(f"MP3 не создан: {mp3_path}")
            await message.answer("⚠️ Не удалось сохранить аудио-файл. Попробуйте ещё раз.")
            return

        # 3) Конвертация в OGG (Opus) для voice
        try:
            mp3_to_ogg_opus(mp3_path, ogg_path)
        except Exception as conv_err:
            logging.error(f"OGG convert error: {conv_err}")
            await message.answer("Аудио создано, но не удалось сделать голосовое. Отправляю только mp3.")

        # 4) Отправляем MP3
        await message.answer_audio(
            audio=FSInputFile(mp3_path),
            caption=f"🎧 Озвучка голосом {voice_name}",
        )

        # 5) Если получилось — отправляем и voice (OGG)
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            await message.answer_voice(
                voice=FSInputFile(ogg_path),
                caption=f"🎙️ Голосовое (Opus) — {voice_name}",
            )

    except Exception as e:
        logging.error(f"TTS error: {e}", exc_info=True)
        msg = str(e)
        if "detected_unusual_activity" in msg:
            await message.answer(
                "❌ ElevenLabs заблокировал Free-тариф (detected_unusual_activity). "
                "Подключите платную подписку или используйте другой ключ/движок."
            )
        elif "voice_not_found" in msg or "404" in msg:
            await message.answer(
                "⚠️ Этот голос сейчас недоступен. Пожалуйста, выберите другой голос."
            )
            voices = await voice_async.get_all_voices()
            await state.update_data(voices_map={v["name"]: v["id"] for v in voices})
            await state.set_state(TTS.choosing_voice)
            await message.answer("Выберите голос:", reply_markup=voices_keyboard(voices))
            return
        else:
            await message.answer("Не удалось сгенерировать аудио. Проверьте ключ/подписку ElevenLabs.")
    finally:
        # Возвращаемся в главное меню только если не остались в выборе голоса
        curr = await state.get_state()
        if curr != TTS.choosing_voice:
            await state.clear()
            await message.answer("Готово. Выберите следующее действие:", reply_markup=main_keyboard())

@router.message()
async def handle_message(message: Message):
    # ... ваш существующий обработчик чата с OpenAI ...
    pass

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    restore_user_data()
    asyncio.run(main())
