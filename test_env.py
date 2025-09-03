import os
from dotenv import load_dotenv

print("Текущая папка:", os.getcwd())
print("Файлы:", os.listdir())

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
if token:
    print("✅ Токен найден:", token[:10] + "...")
else:
    print("❌ Токен НЕ найден")