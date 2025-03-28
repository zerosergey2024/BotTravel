import os
from openai import OpenAI

client = OpenAI(
    api_key="sk-eojihWMYuwlwO4oNjNMX8DbkkkBtLg7I",  # Загружаем API-ключ из переменной среды
    base_url="https://api.proxyapi.ru/openai/v1",
)

def chat_with_ai():
    print("Добро пожаловать в консольный чат с нейросетью! Введите 'exit' для выхода.")

    messages = [
        {"role": "system", "content": "Отвечай в деловом стиле."}  # Исправлено system
    ]

    while True:
        user_input = input("Вы: ")
        if user_input.lower() == "exit":
            print("Чат завершен.")
            break

        try:
            messages.append({"role": "user", "content": user_input})

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )

            reply = response.choices[0].message.content
            print("Нейросеть:", reply)

            messages.append({"role": "assistant", "content": reply})  # Сохраняем ответ бота

        except Exception as e:
            print("Ошибка при обращении к API:", e)


if __name__ == "__main__":
    chat_with_ai()
