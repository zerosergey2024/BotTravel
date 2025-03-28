import telebot

# Замените 'YOUR_TOKEN' на токен вашего бота
bot = telebot.TeleBot('6595307629:AAFAsYFZ3AmYUDeu8SxTLDFUTtMVE5XyohY')

# Обработчик всех сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    # Отправляем обратно то же сообщение, которое получили
    bot.reply_to(message, message.text)

# Запуск бота
bot.polling()