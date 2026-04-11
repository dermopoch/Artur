import asyncio
import re
import random
import os
import json
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, PhotoSize
from openai import AsyncOpenAI

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    print("ОШИБКА: TELEGRAM_TOKEN или GROQ_API_KEY не найдены в .env!")
    exit(1)

BOT_USERNAME = "ArturDrun_bot".lower()
TEXT_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"  # vision + текст
IMAGE_MODEL = "black-forest-labs/flux.1-schnell"               # генерация картинок

# Память чата
HISTORY_FILE = "chat_history.json"
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

# Счётчик
COUNT_FILE = "count.txt"
mention_count = 0
if os.path.exists(COUNT_FILE):
    with open(COUNT_FILE, "r") as f:
        try:
            mention_count = int(f.read().strip())
        except:
            mention_count = 0

def save_count():
    with open(COUNT_FILE, "w") as f:
        f.write(str(mention_count))

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    print(f"[START] /start от {message.from_user.id}")
    await message.answer("Hii, сука! Пиши @ArturDrun_bot или отвечай мне", disable_notification=True)

@dp.message()
async def handle_message(message: Message):
    global mention_count

    if not message.text and not message.photo:
        return

    # Добавляем в историю
    user_name = message.from_user.username or message.from_user.first_name or "анон"
    msg_text = message.text or message.caption or "[фото без подписи]"
    chat_history.append(f"{user_name}: {msg_text}")
    if len(chat_history) > 30:
        chat_history.pop(0)
    save_history()

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

    if message.reply_to_message and message.reply_to_message.from_user.id == (await bot.get_me()).id:
        is_triggered = True

    if is_triggered:
        mention_count += 1
        save_count()
        print(f"[TRIGGER] Упомянули или ответили боту! Всего: {mention_count}")

    if not is_triggered:
        return

    # Убираем упоминание
    query = re.sub(r'^@' + re.escape(BOT_USERNAME) + r'\b\s*', '', text, flags=re.IGNORECASE).strip()
    query = re.sub(r'\s*@' + re.escape(BOT_USERNAME) + r'\b', '', query, flags=re.IGNORECASE).strip()

    lower_query = query.lower()

    # Команда help
    if "help" in lower_query or "/help" in lower_query:
        help_text = (
            "Я Артур — пацан с района, общаюсь по-пацански.  \n"
            "Команды:  \n"
            "• кинь кубик [диапазон] — рандомное число  \n"
            "• кинь кубик — 1-6  \n"
            "• нарисуй [промпт] — сгенерирую картинку через Flux.1  \n"
            "• фотка с упоминанием — прочитаю и отвечу  \n"
            "• упомяни меня или ответь на мой ответ — буду болтать  \n"
            "• счет — сколько раз меня отметили или ответили мне"
        )
        await message.reply(help_text, disable_notification=True)
        return

    # Команда счет
    if "счет" in lower_query or "счёт" in lower_query:
        await message.reply(f"Меня отметили или ответили мне {mention_count} раз за всё время", disable_notification=True)
        return

    # Команда кинь кубик
    if any(word in lower_query for word in ["кинь кубик", "кинь куб", "брось кубик", "кинь кость", "dice", "кинь", "брось"]):
        numbers = re.findall(r'\d+', lower_query)

        min_val = 1
        max_val = 6

        if len(numbers) == 1:
            try:
                max_val = int(numbers[0])
                if max_val < 1:
                    max_val = 6
            except:
                pass
        elif len(numbers) >= 2:
            try:
                min_val = int(numbers[0])
                max_val = int(numbers[1])
                if min_val > max_val:
                    min_val, max_val = max_val, min_val
                if max_val < 1 or min_val < 1:
                    min_val, max_val = 1, 6
            except:
                pass

        result = random.randint(min_val, max_val)
        await message.reply(f"{result} 🎲", disable_notification=True)
        return

    # Команда "нарисуй" / "сгенери" (Flux.1 на Groq)
    if any(word in lower_query for word in ["нарисуй", "сгенери", "сделай картинку", "generate image", "draw"]):
        prompt = query.replace("нарисуй", "").replace("сгенери", "").replace("сделай картинку", "").strip()
        if not prompt:
            await message.reply("Чё нарисовать-то? Скажи промпт", disable_notification=True)
            return

        try:
            print(f"[IMAGE GEN] Генерируем через Groq Flux.1: {prompt}")
            response = await client.images.generate(
                model=IMAGE_MODEL,
                prompt=prompt,
                n=1,
                size="1024x1024",
                response_format="url"
            )

            image_url = response.data[0].url
            await message.reply_photo(photo=image_url, caption=f"Вот твоя картинка: {prompt}", disable_notification=True)
            return

        except Exception as e:
            print(f"[IMAGE GEN ERROR] {str(e)}")
            await message.reply(f"С генерацией наебнулось: {str(e)[:120]} 🤬 Попробуй позже.", disable_notification=True)
            return

    # Обработка фото (чтение)
    if message.photo:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"

        caption = message.caption.strip() if message.caption else "Опиши фотку по-пацански, прочитай текст если есть"

        history_str = "\n".join(chat_history[-10:])

        try:
            response = await client.chat.completions.create(
                model=TEXT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": f"""Ты — обычный парень по имени Артур, лет 18–20, простой, без понтов, общаешься как в обычном чате с друзьями.
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
Последние сообщения в чате:
{history_str}""".format(history_str=history_str)
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": caption},
                            {"type": "image_url", "image_url": {"url": file_url}}
                        ]
                    }
                ],
                max_tokens=800,
                temperature=1.15,
            )

            answer = response.choices[0].message.content.strip()
            await message.reply(answer, disable_notification=True)
            return

        except Exception as e:
            await message.reply(f"С фоткой наебнулось: {str(e)[:120]} 🤬", disable_notification=True)
            return

    # Обычный текст
    if not query:
        await message.reply("Чё молчишь, пидор? Пиши нормально", disable_notification=True)
        return

    # Специальное приветствие
    if any(greet in lower_query for greet in ["привет", "здарова", "здорова", "хай", "hi"]) and "артур" in lower_query:
        await message.reply("hiii", disable_notification=True)
        return

    # Основной ответ от модели
    history_str = "\n".join(chat_history[-10:])

    try:
        response = await client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"""Ты — обычный парень по имени Артур, лет 18–20, простой, без понтов, общаешься как в обычном чате с друзьями.
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
Последние сообщения в чате:

Последние сообщения в чате:
{history_str}""".format(history_str=history_str)
                },
                {"role": "user", "content": query}
            ],
            max_tokens=800,
            temperature=1.15,
        )

        answer = response.choices[0].message.content.strip()
        await message.reply(answer, disable_notification=True)

    except Exception as e:
        await message.reply(f"Наебнулось: {str(e)[:120]} 🤬 Попробуй позже.", disable_notification=True)

async def main():
    print(f"Бот запущен | @{BOT_USERNAME} | текст: {TEXT_MODEL}, картинки: {IMAGE_MODEL} (Groq)")
    print("Ожидаю сообщений... (не закрывай окно)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
