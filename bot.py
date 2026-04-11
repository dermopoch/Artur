import asyncio
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from openai import AsyncOpenAI

# ---------- загрузка env ----------
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    print("ОШИБКА: TELEGRAM_TOKEN или OPENROUTER_API_KEY не найдены в .env")
    raise SystemExit(1)

# username бота в нижнем регистре, БЕЗ @
BOT_USERNAME = "arturdrun_bot"

# Самый простой бесплатный вариант:
# OpenRouter сам выберет доступную free-модель
TEXT_MODEL = "openrouter/free"

# Если захочешь зафиксировать модель вручную, можно потом заменить на что-то вроде:
# TEXT_MODEL = "deepseek/deepseek-r1:free"
# TEXT_MODEL = "qwen/qwen-2.5-72b-instruct:free"
# Но free-модели меняются, поэтому openrouter/free стабильнее.

HISTORY_FILE = "chat_history.json"
COUNT_FILE = "count.txt"

chat_history: list[dict] = []
mention_count = 0

# ---------- загрузка / сохранение ----------
def load_history():
    global chat_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    chat_history = data
                else:
                    chat_history = []
            print(f"[HISTORY] Загружено {len(chat_history)} сообщений")
        except Exception as e:
            print(f"[HISTORY ERROR] {e}")
            chat_history = []

def save_history():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[HISTORY SAVE ERROR] {e}")

def load_count():
    global mention_count
    if os.path.exists(COUNT_FILE):
        try:
            with open(COUNT_FILE, "r", encoding="utf-8") as f:
                mention_count = int(f.read().strip())
        except Exception:
            mention_count = 0

def save_count():
    try:
        with open(COUNT_FILE, "w", encoding="utf-8") as f:
            f.write(str(mention_count))
    except Exception as e:
        print(f"[COUNT SAVE ERROR] {e}")

def add_to_history(role: str, content: str):
    chat_history.append({"role": role, "content": content})
    if len(chat_history) > 30:
        chat_history.pop(0)
    save_history()

# ---------- клиент ----------
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# ---------- системный промпт ----------
SYSTEM_PROMPT = """
Ты отвечаешь кратко, естественно и по-человечески.
Стиль:
- разговорный русский
- без пафоса
- без фразы "как ИИ"
- без длинных простыней без причины
- можно шутить, но уместно
- не будь грубым без причины
- если не знаешь, честно скажи, что не уверен

Отвечай одним обычным сообщением, как в чате.
""".strip()

def build_messages(user_text: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(chat_history[-10:])
    messages.append({"role": "user", "content": user_text})
    return messages

# ---------- команды ----------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет. Напиши @ArturDrun_bot в сообщении или ответь на моё сообщение."
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "/start — запуск\n"
        "/help — помощь\n"
        "/count — сколько раз меня тегнули или мне ответили\n\n"
        "Я отвечаю, если:\n"
        "1) ты упомянул @ArturDrun_bot\n"
        "2) ты ответил на моё сообщение"
    )

@dp.message(Command("count"))
async def cmd_count(message: Message):
    await message.answer(f"Меня упомянули или мне ответили {mention_count} раз(а).")

# ---------- основной обработчик ----------
@dp.message()
async def handle_message(message: Message):
    global mention_count

    if not message.text:
        return

    text = message.text
    lower_text = text.lower()
    is_triggered = False

    # Проверка mention через entities
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned = text[entity.offset: entity.offset + entity.length].lstrip("@").lower()
                if mentioned == BOT_USERNAME:
                    is_triggered = True
                    break

    # Проверка mention через текст
    if not is_triggered and f"@{BOT_USERNAME}" in lower_text:
        is_triggered = True

    # Проверка reply на бота
    me = await bot.get_me()
    if message.reply_to_message and message.reply_to_message.from_user.id == me.id:
        is_triggered = True

    if not is_triggered:
        return

    mention_count += 1
    save_count()

    # Убираем @bot_username из текста
    query = re.sub(
        r"^@" + re.escape(BOT_USERNAME) + r"\b\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    query = re.sub(
        r"\s*@" + re.escape(BOT_USERNAME) + r"\b",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()

    if not query:
        await message.reply("Напиши текст после упоминания.")
        return

    user_name = message.from_user.username or message.from_user.first_name or "anon"
    add_to_history("user", f"{user_name}: {query}")

    try:
        response = await client.chat.completions.create(
            model=TEXT_MODEL,
            messages=build_messages(query),
            max_tokens=400,
            temperature=0.9,
            extra_headers={
                "HTTP-Referer": "https://localhost",
                "X-Title": "Telegram Bot",
            },
        )

        answer = response.choices[0].message.content.strip()
        if not answer:
            answer = "Пусто ответило, попробуй ещё раз."

        add_to_history("assistant", answer)
        await message.reply(answer)

    except Exception as e:
        err_text = str(e)

        if "429" in err_text:
            await message.reply(
                "Лимит запросов кончился или free-модель сейчас занята. Попробуй позже."
            )
        elif "401" in err_text:
            await message.reply("Неверный OPENROUTER_API_KEY.")
        else:
            await message.reply(f"Ошибка модели: {err_text[:180]}")

# ---------- запуск ----------
async def main():
    load_history()
    load_count()

    print(f"Бот запущен | @{BOT_USERNAME}")
    print(f"MODEL={TEXT_MODEL}")
    print("Ожидаю сообщений...")

    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            print(f"[POLLING ERROR] {e}")
            print("Повторная попытка через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())