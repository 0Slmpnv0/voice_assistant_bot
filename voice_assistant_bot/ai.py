import math
import config
import requests
from icecream import ic
import time
import db
from dotenv import get_key
from conspiracy import iam

users = {}


def create_new_iam_token() -> dict[str: str]:
    """Возвращает метадату нового IAM"""
    metadata_url = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
    headers = {"Metadata-Flavor": "Google"}
    response = requests.get(metadata_url, headers=headers)
    return response.json()


def check_iam() -> None:
    """Проверяет истек ли срок годности IAM токена. Если истек, то вызывает create_new_iam_token()"""
    global expires_at
    if expires_at < time.time():
        global iam
        iam_data = create_new_iam_token()
        iam = iam_data['access_token']
        expires_at = iam_data['expires_in']


#  token_data = create_new_iam_token()
token_data = iam
iam = token_data['access_token']
expires_at = time.time() + token_data['expires_in']
folder_id = get_key('.env', 'FOLDER_ID')


class GPT:
    def __init__(
            self,
            user_id: int,
            tokens: int = config.MAX_USER_TOKENS,
            temperature: float | int = 1,
            max_model_resp_tokens: int = config.MAX_MODEL_RESP_TOKENS,
    ):
        self.user_id = user_id
        self.tokens = tokens
        self.temperature = temperature
        self.model_tokens = max_model_resp_tokens
        self.context: list[dict[str: str]] = []

    def add_context(self, context: dict[str: str]) -> None:
        self.context.append(context)

    def count_tokens(self, text: str) -> int:
        """Отправляет запрос в ....../v1/tokenize, чтобы узнать сколько токенов получается из нашего текста,
        и возвращает полученное число"""
        headers = {
            'Authorization': f'Bearer {iam}',
            'Content-Type': 'application/json'
        }
        data = {
            "modelUri": f"gpt://{folder_id}/yandexgpt/latest",
            "maxTokens": self.model_tokens,
            "text": text
        }
        tokens = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/tokenize",
            json=data,
            headers=headers
        ).json()['tokens']
        return len(tokens)

    def save_prompt(self, prompt) -> None:
        """Сохраняет промпт в БД"""
        db.insert_into_prompts(self.user_id, prompt['role'], prompt['text'])
        db.update_user_limits(self.user_id, 'gpt_tokens', self.tokens)

    def ask_gpt(self, text: str) -> tuple[str, str]:
        """Основной метод класса.
        Принимает текст, составляет запрос, сверяется с лимитом токенов.
        Если что-то пошло не так, то возвращает exc или err.
        Иначе вычитает затраченные токены и возвращает ответ от GPT"""
        sys_prompt = 'Ты - доброжелательный ассистент-помощник по имена Алена. Будь дружелюбной и вежливой'
        tokens_required = self.count_tokens(
            sys_prompt + ' ' +
            ' '.join([prompt['text'] for prompt in self.context]) + ' ' +
            text)
        if tokens_required > self.tokens:
            return 'exc', (f'Запрос вышел слишком длинным. У вас осталось {self.tokens} токенов. Это примерно '
                           f'{self.tokens * 3} символов. Учтите, что токены нужны и ИИ, чтобы сгенерировать ответ. '
                           f'А еще они тратятся на "хранение" контекста. Мы отправляем GPT весь контекст каждое новое сообщение!')
        self.tokens -= tokens_required
        check_iam()
        headers = {
            'Authorization': f'Bearer {iam}',
            'Content-Type': 'application/json'
        }
        if min(self.model_tokens, max(1, self.tokens)) < 50:
            self.tokens += tokens_required
            return 'exc', ('Токенов, которые остались после преобразования вашего запроса недостаточно чтобы ИИ '
                           'мог дать нормальный ответ. Попробуйте переформулировать свою мысль, сделать покороче')
        json = {
            "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.7,
                "maxTokens": min(self.model_tokens, max(1, self.tokens))
            },
            "messages": [{"role": "system", "text": sys_prompt}] + self.context + [{'role': 'user', 'text': text}]
        }
        response = requests.post(
            'https://llm.api.cloud.yandex.net/foundationModels/v1/completion',
            headers=headers,
            json=json
        )
        if response.status_code != 200:
            return 'err', f'Извините! У нас что-то поломалось. Код ошибки: {response.status_code}'
        else:
            resp = response.json()['result']['alternatives'][0]['message']['text']
            self.context.append({'role': 'user', 'text': text})
            self.context.append({'role': 'assistant', 'text': resp})
            self.save_prompt({'role': 'user', 'text': text})
            self.save_prompt({'role': 'assistant', 'text': resp})
            self.tokens -= self.count_tokens(resp)
            return 'succ', resp


class Speechkit:
    def __init__(
            self,
            user_id: int,
            blocks: int = config.MAX_STT_BLOCKS,
            chars: int = config.MAX_TTS_CHARS
    ):
        self.user_id = user_id
        self.blocks = blocks
        self.chars = chars

    def text_to_speech(self, text: str, speaker: str = 'alena') -> tuple[str, str | bytes]:
        check_iam()
        if len(text) > self.chars:
            return 'exc', 'Слишком длинно!!!'
        else:
            headers = {'Authorization': f'Bearer {iam}'}
            data = {
                'text': text,
                'lang': 'ru-RU',
                'voice': speaker,
                'speed': 1
            }
            req = requests.post('https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize',
                                headers=headers, data=data)
            if req.status_code != 200:
                return 'err', f'Что-то поломалось. Код ошибки: {req.status_code}'
            else:
                self.chars -= len(text)
                db.update_user_limits(self.user_id, 'tts_characters', self.chars)
                return 'succ', req.content

    @staticmethod
    def count_blocks(duration) -> int:  # это для красоты
        return math.ceil(duration / config.BLOCK_SIZE)

    def speech_to_text(self, voice: bin, duration: int | float) -> tuple[bool, str | bytes]:
        check_iam()
        blocks = self.count_blocks(duration)
        if not blocks <= self.blocks:
            return False, f'Сообщение слишком длинное! У вас осталось {self.blocks * 15} секунд распознавания голоса'
        else:
            params = '&'.join([
                'topic=general',
                'lang=ru-RU'
            ])

            headers = {
                'Authorization': f'Bearer {iam}',
            }

            response = requests.post(
                f"https://stt.api.cloud.yandex.net/speech/v1/stt:recognize?{params}",
                headers=headers,
                data=voice
            )

            if response.json().get('error_code') is None:
                self.blocks -= blocks
                db.update_user_limits(self.user_id, 'stt_blocks', self.blocks)
                return True, response.json().get('result')
            else:
                return False, f'При попытке обратиться к speechkit возникла ошибка: {response.json().get("error_code")}'


class UI(Speechkit, GPT):
    """Не хотел запихивать все методы и аттрибуты в один класс, потому что решил, что так будет некрасиво.
    Вместо этого наследоваться буду"""
    def __init__(self, user_id: int, tokens=config.MAX_USER_TOKENS,
                 blocks=config.MAX_STT_BLOCKS, chars=config.MAX_TTS_CHARS):
        Speechkit.__init__(self, user_id=user_id, blocks=blocks, chars=chars)  # Я почти уверен, что
        GPT.__init__(self, user_id=user_id, tokens=tokens)  # делаю это неправильно, но super() не работает
        users[user_id] = self

    def process_text_message(self, text: str) -> tuple[str, str]:  # можно было оставить ask_gpt, но мне больше
        # нравится идея вообще не вспоминать даже что у меня там чем занимается, а только process методы использовать
        check_iam()  # тем более так можно айэм проверить
        return self.ask_gpt(text)

    def process_voice_message(self, voice: bin, duration: int | float) -> tuple[bool, str | bytes]:
        check_iam()
        status, text = self.speech_to_text(voice, duration)
        if not status:
            return False, text
        status, text_answer = self.ask_gpt(text)
        if status != 'succ':
            return False, text_answer
        status, resp = self.text_to_speech(text_answer)
        if status == 'exc':
            return (False, 'Текст ответа вышел слишком длинным, чтобы его преобразовать в голос( ответ помощника: \n' +
                    text_answer)
        return True if status == 'succ' else False, resp

    def get_limits(self) -> str:
        return f'''Ваши лимиты:
1. Токены: {self.tokens} (это очень примерно около {self.tokens * 3} символов. 
Учтите, что токены ваших прошлых запросов тоже вычитаются из общей суммы. Нам же нужно хранить контекст! 
Причем токены тратятся не только на обработку вашего запроса, но и на ответ GPT)
2. Блоки: {self.blocks} (это {self.blocks * 15} секунд распознования речи)
3. Символы: {self.chars}. Столько символов можно преобразовать в голосовое сообщение. 
Если количество символов будет меньше, чем длина сообщения, сочиненного нейросетью, то отправим сообщение текстом'''
