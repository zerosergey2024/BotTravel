# voice_async.py
import os
import logging
from typing import List, Dict, Optional

import aiofiles
from httpx import HTTPStatusError
from elevenlabs.client import AsyncElevenLabs

# --- Fallback движок: OpenAI TTS (по желанию) ---
from openai import AsyncOpenAI

_LOG = logging.getLogger("voice_async")

# Предустановленные голоса (без обращения к API списков)
FALLBACK_VOICES: List[Dict[str, str]] = [
    {"name": "Rachel",    "id": "21m00Tcm4TlvDq8ikWAM"},
    {"name": "Elli",      "id": "MF3mGyEYCl7XYWbV9V6O"},
    {"name": "Josh",      "id": "TxGEqnHWrfWFTfGW9XjX"},
    {"name": "Matilda",   "id": "XrExE9yKIg1WjnnlVkGX"},
    {"name": "Charlotte", "id": "XB0fDUnXU5powFXDhCwa"},
    {"name": "James",     "id": "ZQe5CZNOzWyzPSCn5a3c"},
    {"name": "Callum",    "id": "N2lVS1w4EtoT3dr4eOWO"},
    {"name": "Arnold",    "id": "VR6AewLTigWG4xSOukaG"},
]

# Настройки ElevenLabs по умолчанию
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

_client_el: Optional[AsyncElevenLabs] = None
_client_oai: Optional[AsyncOpenAI] = None


# ---------- Клиенты ----------
def _get_el_api_key() -> str:
    k = os.getenv("ELEVENLABS_API_KEY")
    if not k:
        raise RuntimeError("ELEVENLABS_API_KEY не найден")
    return k

def _get_el_client() -> AsyncElevenLabs:
    global _client_el
    if _client_el is None:
        _client_el = AsyncElevenLabs(api_key=_get_el_api_key())
    return _client_el

def _get_oai_client() -> Optional[AsyncOpenAI]:
    # Берём OpenAI ключ из OPENAI_API_KEY или API_KEY
    global _client_oai
    key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    if not key:
        return None
    if _client_oai is None:
        _client_oai = AsyncOpenAI(api_key=key)
    return _client_oai


# ---------- Публичные функции ----------
async def get_all_voices() -> List[Dict[str, str]]:
    """Возвращает фиксированный список голосов (без API-запросов)."""
    return FALLBACK_VOICES

async def find_voice_id_by_name(name: str) -> Optional[str]:
    if not name:
        return None
    name_lower = name.strip().lower()
    for v in FALLBACK_VOICES:
        if v["name"].strip().lower() == name_lower:
            return v["id"]
    return None


# ---------- Вспомогательные ----------
async def _write_stream_to_file(stream, out_name: str) -> None:
    """
    Записывает async-генератор байтов в файл «атомарно»:
    сначала *.part, затем os.replace.
    """
    out_dir = os.path.dirname(out_name)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tmp_name = out_name + ".part"
    try:
        async with aiofiles.open(tmp_name, "wb") as f:
            async for chunk in stream:
                if chunk:
                    await f.write(chunk)

        if not os.path.exists(tmp_name) or os.path.getsize(tmp_name) == 0:
            raise RuntimeError("Пустой аудиопоток — файл не создан")
        os.replace(tmp_name, out_name)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass
        raise


# ---------- Генерация через ElevenLabs / OpenAI ----------
async def _generate_with_elevenlabs(*, text: str, voice_id: str, out_name: str,
                                    model_id: str = DEFAULT_MODEL_ID,
                                    output_format: str = DEFAULT_OUTPUT_FORMAT) -> str:
    client = _get_el_client()
    # convert() возвращает async-генератор
    stream = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=output_format,
    )
    await _write_stream_to_file(stream, out_name)
    return out_name

async def _generate_with_openai(*, text: str, out_name: str, voice: str = "alloy") -> str:
    """
    Fallback на OpenAI TTS (mp3). Нужен OPENAI_API_KEY или API_KEY.
    Модель: gpt-4o-mini-tts (встроенный стрим в файл).
    """
    oai = _get_oai_client()
    if not oai:
        raise RuntimeError("Нет ключа OpenAI для fallback (OPENAI_API_KEY/API_KEY)")

    resp = await oai.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice=voice,   # alloy/verse/coral/… — выберите любой
        input=text,
        format="mp3",
    )
    # Убедимся, что каталог существует
    out_dir = os.path.dirname(out_name)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    await resp.stream_to_file(out_name)
    return out_name


async def generate_audio(
    text: str,
    voice_id: str,
    out_name: str = "audio.mp3",
    *,
    model_id: str = DEFAULT_MODEL_ID,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> str:
    """
    Пытается озвучить через ElevenLabs. Если словили 401 (detected_unusual_activity),
    пробует OpenAI TTS как fallback. Возвращает путь к файлу.
    """
    if not text or not text.strip():
        raise ValueError("Пустой text")
    if not voice_id:
        raise ValueError("Пустой voice_id")

    try:
        return await _generate_with_elevenlabs(
            text=text, voice_id=voice_id, out_name=out_name,
            model_id=model_id, output_format=output_format
        )
    except HTTPStatusError as e:
        status = getattr(e.response, "status_code", None)
        try:
            detail = e.response.json()
        except Exception:
            detail = {}
        _LOG.error("ElevenLabs HTTP %s: %s", status, detail)

        # Спец-кейс: бан фритарифа — переключаемся на OpenAI
        if status == 401 and "detected_unusual_activity" in str(detail):
            _LOG.warning("ElevenLabs заблокирован (Free Tier). Пытаюсь OpenAI TTS fallback.")
            try:
                return await _generate_with_openai(text=text, out_name=out_name, voice="alloy")
            except Exception as ee:
                _LOG.error("OpenAI fallback failed: %r", ee)
                raise RuntimeError(
                    "TTS недоступен: ElevenLabs заблокирован, OpenAI fallback не сработал."
                )
        # 404 voice_not_found и другие — пробрасываем наверх (пусть хендлер решает)
        raise
    except Exception as e:
        _LOG.error("TTS общий сбой: %r", e)
        raise


__all__ = [
    "get_all_voices",
    "generate_audio",
    "find_voice_id_by_name",
    "FALLBACK_VOICES",
]





