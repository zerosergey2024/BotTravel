# ... ваши импорты ...
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

# >>> ADD: импортируем pydub для конвертации и наш модуль voice
from pydub import AudioSegment
import voice_async
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
    # ... как у вас было ...
    pass  # (оставьте вашу реализацию, я опускаю здесь ради краткости)

def process_text_file(file_path):
    # ... как у вас было ...
    pass

def save_user_data(user_id: int, data_type: str, content: str):
    # ... как у вас было ...
    pass

def load_user_data(user_id, data_type):
    # ... как у вас было ...
    pass

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

@router.message(F.document)
async def handle_document(message: Message):
    # ... ваш код без изменений ...
    pass

@router.message(Command("instruction"))
async def show_instruction(message: Message):
    # ... ваш код ...
    pass

@router.message(Command("knowledge"))
async def show_knowledge(message: Message):
    # ... ваш код ...
    pass

@dp.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено", reply_markup=main_keyboard())

@dp.message(F.text == "🌤️ Погода")
async def weather_handler(message: Message, state: FSMContext):
    # ... ваш код ...
    pass

@dp.message(F.text == "🌍 Перевод")
async def translate_handler(message: Message, state: FSMContext):
    # ... ваш код ...
    pass

@dp.message(Form.weather)
async def get_weather(message: Message, state: FSMContext):
    # ... ваш код ...
    pass

@dp.message(Form.translate)
async def translate_text(message: Message, state: FSMContext):
    # ... ваш код ...
    pass

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
    text = message.text.strip()
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
        # Имена файлов — с user_id и временем, чтобы не пересекались
        base = f"{message.from_user.id}_{int(asyncio.get_event_loop().time()*1000)}"
        mp3_path = os.path.join(AUDIO_DIR, f"{base}.mp3")
        ogg_path = os.path.join(AUDIO_DIR, f"{base}.ogg")

        # Генерация через ElevenLabs (MP3)
        await voice_async.generate_audio("Привет!", voice_id, "audio.mp3")

        # Конвертация в OGG (Opus) для voice
        mp3_to_ogg_opus(mp3_path, ogg_path)

        # Отправляем как аудио (mp3)
        await message.answer_audio(
            audio=FSInputFile(mp3_path),
            caption=f"🎧 Озвучка голосом {voice_name}"
        )

        # И отправляем как голосовое (ogg/opus)
        await message.answer_voice(
            voice=FSInputFile(ogg_path),
            caption=f"🎙️ Голосовое (Opus) — {voice_name}"
        )

    except Exception as e:
        logging.error(f"TTS error: {e}")
        await message.answer("Не удалось сгенерировать аудио. Проверьте ключ ElevenLabs и попробуйте снова.")
    finally:
        # Возвращаемся в главное меню
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
