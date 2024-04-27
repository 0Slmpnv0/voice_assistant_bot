import math
import config
import requests
from icecream import ic
import time
import db
from dotenv import get_key

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
token_data = create_new_iam_token()
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

    def add_context(self, context: list[dict[str: str]] | dict[str: str]):
        for prompt in context:
            self.context.append(prompt)

    def count_tokens(self, text) -> int:
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

    def save_prompt(self, prompt):
        """Сохраняет промпт в БД и вычитает из доступных токенов токены для prompt"""
        self.tokens -= self.count_tokens(prompt['text'])
        db.insert_into_prompts(self.user_id, prompt['role'], prompt['text'])
        db.update_user_limits(self.user_id, 'gpt_tokens', self.tokens)

    def rm_context(self):
        self.context = []

    def ask_gpt(self, prompt: str):
        sys_prompt = 'Ты - доброжелательный ассистент-помощник'

        if self.count_tokens(prompt) > self.tokens:
            return 'exc', (f'Запрос вышел слишком длинным. У вас осталось {self.tokens} токенов. Это примерно '
                           f'{self.tokens * 3} символов')
        if not self.tokens:
            self.tokens -= self.count_tokens(sys_prompt)
        context_prompt = ''.join([prompt['text'] for prompt in self.context])
        self.tokens -= self.count_tokens(prompt + context_prompt)
        check_iam()

        headers = {
            'Authorization': f'Bearer {iam}',
            'Content-Type': 'application/json'
        }
        json = {
            "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.7,
                "maxTokens": self.model_tokens
            },
            "messages": [{"role": "system", "text": sys_prompt}] + self.context + [{'role': 'user', 'text': prompt}]
        }
        response = requests.post(
            'https://llm.api.cloud.yandex.net/foundationModels/v1/completion',
            headers=headers,
            json=json
        )
        if response.status_code != 200:
            return 'err', f'Извините! У нас что-то поломалось. Код ошибки: {response.status_code}'
        else:
            text = response.json()['result']['alternatives'][0]['message']['text']
            self.context.append({'role': 'user', 'text': prompt})
            self.context.append({'role': 'assistant', 'text': text})
            return 'succ', text


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

    def text_to_speech(self, text: str, speaker: str = 'alena'):
        check_iam()
        if len(text) > self.chars:
            return 'exc', self.chars
        else:
            headers = {'Authorization': f'Bearer {iam}'}
            data = {
                'text': text,
                'lang': 'ru-RU',
                'voice': 'alena',
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
    def count_blocks(duration):
        return math.ceil(duration / config.BLOCK_SIZE)

    def speech_to_text(self, voice: bin, duration: int | float):
        check_iam()
        blocks = self.count_blocks(duration)
        if not blocks <= self.blocks:
            return 'exc', f'Сообщение слишком длинное! У вас осталось {self.blocks * 15} секунд распознавания голоса'
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
    def __init__(self, user_id: int):
        super().__init__(user_id)
        users[user_id] = self

    def process_text_request(self, text: str):
        raise NotImplementedError

    def process_voice_request(self, voice: bin, duration: int | float):
        raise NotImplementedError
