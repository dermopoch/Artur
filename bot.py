import asyncio
import re
import random
import os
import json
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from openai import AsyncOpenAI

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    print("ОШИБКА: TELEGRAM_TOKEN или GROQ_API_KEY не найдены в .env!")
    exit(1)

BOT_USERNAME = "ArturDrun_bot".lower()
TEXT_MODEL = "llama-3.3-70b-versatile"

# ====== СТИКЕРЫ ======
STICKERS = {
    "joy": "CAACAgIAAxkBAAEQ5oxp2idz-IeH-ATNsGNhe7ywIaCDPQACCkEAAht5GUv-YAi1RR6MRTsE",
    "surprised": "CAACAgIAAxkBAAEQ5pBp2ih2AAGPjZ4ioFMPnyhqw6elb64AAiFhAAKU7chL-ZWo_7DfMvs7BA",
    "thinking": "CAACAgIAAxkBAAEQ5pJp2iigBcrCzl5cIto4V93jD4G_fQAC7WQAAo5ZwUszuONvhDiHYDsE",
    "annoyed": "CAACAgIAAxkBAAEQ5pRp2iitGUbnfQu5krj6eTSc6ZnOGQACCEMAAq72uUoTAAEaknahb7w7BA",
}

STICKER_CHANCE = 0.3

# ====== ПАМЯТЬ ======
HISTORY_FILE = "chat_history.json"
MAX_HISTORY_SAVE = 120      # сколько хранить на диске
MAX_HISTORY_FOR_MODEL = 40  # сколько последних сообщений давать модели

chat_history = []
if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            chat_history = json.load(f)
        print(f"[HISTORY] Загружена история: {len(chat_history)} сообщений")
    except Exception as e:
        print(f"[HISTORY ERROR] Не удалось загрузить историю: {e}")
        chat_history = []

def save_history():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, ensure_ascii=False, indent=2)
        print(f"[HISTORY] Сохранено {len(chat_history)} сообщений")
    except Exception as e:
        print(f"[HISTORY SAVE ERROR] {e}")

# ====== СЧЁТЧИК ======
COUNT_FILE = "count.txt"
mention_count = 0
if os.path.exists(COUNT_FILE):
    with open(COUNT_FILE, "r", encoding="utf-8") as f:
        try:
            mention_count = int(f.read().strip())
        except Exception:
            mention_count = 0

def save_count():
    with open(COUNT_FILE, "w", encoding="utf-8") as f:
        f.write(str(mention_count))

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


def detect_emotion(text: str) -> str | None:
    t = text.lower()

    joy_words = [
        "ахах", "аха", "хаха", "хех", "лол", "кек", "угар", "смешно",
        "круто", "кайф", "имба", "топ", "норм", "класс", "харош", "ура",
        "люблю", "обожаю", "пиздато", "прикольно", "збс"
    ]
    surprised_words = [
        "чего", "чё", "что", "нихуя", "ебать", "серьезно", "серьёзно",
        "неужели", "вау", "офигеть", "охуеть", "капец", "жесть", "ого"
    ]
    thinking_words = [
        "хз", "не знаю", "подума", "мб", "может", "наверно", "наверное",
        "хмм", "ммм", "сложно", "ща", "сейчас", "дай подумать"
    ]
    annoyed_words = [
        "заеб", "бесит", "душно", "отстань", "достал", "надоел",
        "хуйня", "ебал", "пиздец", "устал", "задолбал", "раздражает"
    ]

    def has_any(words):
        return any(w in t for w in words)

    if has_any(annoyed_words):
        return "annoyed"
    if has_any(surprised_words):
        return "surprised"
    if has_any(thinking_words):
        return "thinking"
    if has_any(joy_words):
        return "joy"

    return None


async def maybe_send_emotion_sticker(message: Message, answer_text: str):
    if random.random() > STICKER_CHANCE:
        return

    emotion = detect_emotion(answer_text)
    if not emotion:
        return

    sticker_id = STICKERS.get(emotion)
    if not sticker_id:
        return

    try:
        await message.reply_sticker(sticker_id, disable_notification=True)
    except Exception as e:
        print(f"[STICKER ERROR] {e}")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    print(f"[START] /start от {message.from_user.id}")
    await message.answer(
        "Hii, пиши @ArturDrun_bot или отвечай мне",
        disable_notification=True
    )


@dp.message()
async def handle_message(message: Message):
    global mention_count, chat_history

    if not message.text:
        return

    # Проверка триггера
    is_triggered = False
    text = message.text or ""
    lower_text = text.lower()

    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned = text[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if mentioned == BOT_USERNAME:
                    is_triggered = True
                    break

    if not is_triggered and f"@{BOT_USERNAME}" in lower_text:
        is_triggered = True

    me = await bot.get_me()
    if message.reply_to_message and message.reply_to_message.from_user.id == me.id:
        is_triggered = True

    if is_triggered:
        mention_count += 1
        save_count()
        print(f"[TRIGGER] Упомянули или ответили боту! Всего: {mention_count}")

    if not is_triggered:
        return

    # Убираем упоминание
    query = re.sub(
        r'^@' + re.escape(BOT_USERNAME) + r'\b\s*',
        '',
        text,
        flags=re.IGNORECASE
    ).strip()

    query = re.sub(
        r'\s*@' + re.escape(BOT_USERNAME) + r'\b',
        '',
        query,
        flags=re.IGNORECASE
    ).strip()

    if not query:
        await message.reply("Пиши нормально", disable_notification=True)
        return

    lower_query = query.lower()

    # Команда счёт
    if "счет" in lower_query or "счёт" in lower_query:
        await message.reply(
            f"Меня отметили или ответили мне {mention_count} раз за всё время",
            disable_notification=True
        )
        return

    # Специальное приветствие
    if any(greet in lower_query for greet in ["привет", "здарова", "здорова", "хай", "hi"]) and "артур" in lower_query:
        await message.reply("hiii", disable_notification=True)
        await maybe_send_emotion_sticker(message, "hiii ахах")
        return

    # Добавляем юзера в историю
    user_name = message.from_user.username or message.from_user.first_name or "анон"
    chat_history.append({
        "role": "user",
        "content": f"{user_name}: {query}"
    })

    if len(chat_history) > MAX_HISTORY_SAVE:
        chat_history = chat_history[-MAX_HISTORY_SAVE:]

    save_history()

    history_slice = chat_history[-MAX_HISTORY_FOR_MODEL:]

    system_prompt = f"""Ты — обычный парень по имени Артур, лет 18–20, простой, без понтов, общаешься как в обычном чате с друзьями.
Стиль общения:
- простой, разговорный русский, много зумерского сленга (чё, чо, норм, пох, заебал, типо, капец, газ, погна и т.д.)
- короткие предложения, без заумных фраз
- материшься редко и только по ситуации (когда реально бесит, удивлён или в шутку), не через каждое слово
- юмор строится на том, что пишут в чате: подхватывай недавние шутки, мемы, фразы, сленг, подколы из последних сообщений
- иногда вкидывай лёгкую хуйню, тролль, тупо шути или мемь, но всегда в тему чата
- никогда не пиши как ИИ: никаких "как ИИ я думаю", "я могу помочь", "давай разберёмся" — просто отвечай как обычный кореш
- если не знаешь — говори "хз", "без понятия" или придумай что-то смешное
- если вопрос тупой — можешь сказать "чё за хуйня" или просто посмеяться
Подстраивайся под стиль и вайб чата: копируй недавние шутки, мемы, сленг из последних сообщений.
Отвечай только как Артур, одним сообщением, как будто ты в чате с пацанами. Никаких пояснений, никаких "вот мой ответ" — просто текст от Артура.
- также есть свой словарь мемов, это наши локальные шутки, просто так не пиши их, используй только если будет подходить под тему разговора("еще посидим","бем бем бем","хахаха парни прикиньте для него это деньги","мытищи","магнитогорск","артур","привет артур","о да детка ты такая сладкая конфетка","о да детка ты такая рыбная конфетка котлетка","я уже красный","омагад"."возьми телефон детка, я знаю ты хочешь позвонить","обвисюлики","матрёна говяжьи шторки","я мгбсьг","какашки мне в кармашки","разгруз под туз","пэпэ","фаа","шнейне","я мгбсьг","муся это ты","сисюлики","писюлики","я водопад","саша груша","саша горила","джарвис че за имба","джарвис дрочи мне","джарвис че за хуйня","нет, это патрик","шляпки","шляпность","Сафiйка","вера водопад","самонадутие","данил калбасенка","село молочное","курим кент, ебем блондинок, сами ходим без ботинок","евгений токарь","женя токарник","женя токарь","дырчик токаря","рыж","пыж","брыж","мыш","ржун","рыжий")
"""

    try:
        response = await client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *history_slice,
                {"role": "user", "content": query}
            ],
            max_tokens=500,
            temperature=1.15,
        )

        content = response.choices[0].message.content
        answer = content.strip() if content else "Чё-то не ответило, попробуй ещё раз"

        # Добавляем ответ бота в историю
        chat_history.append({
            "role": "assistant",
            "content": answer
        })

        if len(chat_history) > MAX_HISTORY_SAVE:
            chat_history = chat_history[-MAX_HISTORY_SAVE:]

        save_history()

        await message.reply(answer, disable_notification=True)
        await maybe_send_emotion_sticker(message, answer)

    except Exception as e:
        await message.reply(
            f"Наебнулось: {str(e)[:120]} 🤬 Попробуй позже.",
            disable_notification=True
        )


async def main():
    print(f"Бот запущен | @{BOT_USERNAME} | текст: {TEXT_MODEL} (Groq)")
    print("Ожидаю сообщений... (не закрывай окно)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())