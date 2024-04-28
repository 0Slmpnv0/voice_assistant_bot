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
    UI(user['user_id'])

