# voice_async.py
import os
import aiofiles
from elevenlabs.client import AsyncElevenLabs

API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY не найден")

client = AsyncElevenLabs(api_key=API_KEY)

async def get_all_voices():
    resp = await client.voices.search()
    return [{"name": v.name, "id": v.voice_id} for v in resp.voices]

async def generate_audio(text: str, voice_id: str, out_name: str = "audio.mp3") -> str:
    audio_bytes = await client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    async with aiofiles.open(out_name, "wb") as f:
        await f.write(audio_bytes)
    return out_name
