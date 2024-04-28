import telebot
from dotenv import get_key
from icecream import ic
from ai import UI, users
import db
import config
from telebot.types import Message

bot = telebot.TeleBot(get_key('.env', 'TELEGRAM_BOT_TOKEN'))

old_users = db.get_users()
for user in old_users:
    UI(user['user_id'], user['gpt_tokens'], user['stt_blocks'], user['tts_characters'])
    for prompt in db.get_user_context(user['user_id']):
        users[user['user_id']].add_context(prompt)


@bot.message_handler(commands=['start', 'help'])
def start(message: Message):
    if message.text == '/start':
        text = 'Снова добро пожаловать! Чем могу помочь?'
        if message.from_user.id not in users:
            if len(users) < config.MAX_USERS:
                UI(message.from_user.id)
                db.insert_into_users(message.from_user.id)
                text = ('Здравствуйте! Добро пожаловать в бота - голосового (и текстового) помощника! '
                        'Интерфейс предельно прост: вводите сообщение - получаете ответ. '
                        'Отправляете голосовое - получаете голосовое в ответ. Чтобы узнать сколько у вас осталось'
                        ' блоков расшифровки (это чтобы бот мог превратить вашу речь в текст), '
                        ' символов преобразования (это чтобы бот мог говорить в ответ на ваши голосовые),'
                        'токенов (это чтобы бот мог думать. Они будут расходоваться всегда) используйте команду /limits. '
                        'Развлекайтесь!')
            else:
                bot.send_message(message.from_user.id, 'К сожалению, лимит юзеров исчерпан!')
                bot.register_next_step_handler_by_chat_id(message.chat.id, looser)

    else:
        text = ('Интерфейс предельно прост: вводите сообщение - получаете ответ. '
                'Отправляете голосовое - получаете голосовое в ответ. Чтобы узнать сколько у вас осталось'
                ' блоков расшифровки (это чтобы бот мог превратить вашу речь в текст), '
                ' символов преобразования (это чтобы бот мог говорить в ответ на ваши голосовые),'
                'токенов (это чтобы бот мог думать. Они будут расходоваться всегда) используйте команду /limits. '
                'Развлекайтесь!')

    bot.send_message(message.from_user.id, text)


@bot.message_handler(commands=['limits'])
def limits(message: Message):
    bot.send_message(message.from_user.id, users[message.from_user.id].get_limits())


@bot.message_handler()
def process_text(message: Message):
    ic('Сообщение текстовое!')
    bot.send_message(message.from_user.id, users[message.from_user.id].process_text_message(message.text)[1])


@bot.message_handler(content_types=['audio', 'voice'])
def process_voice(message: Message):
    ic('Сообщение голосовое!')
    duration = message.voice.duration
    voice = bot.download_file(bot.get_file(message.voice.file_id).file_path)
    status, resp = users[message.from_user.id].process_voice_message(voice, duration)
    if not status:
        bot.send_message(message.from_user.id, resp)
    else:
        bot.send_audio(message.from_user.id, resp)


def looser(message: Message):
    bot.send_message(message.from_user.id, 'К сожалению, лимит юзеров исчерпан!')
    bot.register_next_step_handler_by_chat_id(message.chat.id, looser)


bot.polling(none_stop=True)
