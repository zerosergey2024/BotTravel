@router.message(Command("start"))
async def start_command(message: Message):
    photo ='img/ФотоБот1.jpg'
    await message.answer(
        "Привет! Я ваш AI-помощник в путешествии и делах. Задайте любой вопрос или воспользуйтесь кнопками.",
        reply_markup=main_keyboard()
    )