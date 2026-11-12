"""Telegram-бот утренней рутины.

Каждый день в 5:01 присылает «доброе утро» и план тренировки на сегодня.
План — чек-лист: нажимаешь на номер упражнения, и оно отмечается ✅.
"""

import json
import logging
import os
from datetime import datetime, time
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("morning_bot")

# ---------- настройки (через переменные окружения) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"]) if os.environ.get("CHAT_ID") else None
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Moscow"))
SEND_HOUR = int(os.environ.get("SEND_HOUR", "5"))
SEND_MINUTE = int(os.environ.get("SEND_MINUTE", "1"))
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

# ---------- план тренировок ----------
WORKOUTS = {
    "chest": {
        "title": "Грудь и Трицепс",
        "exercises": [
            "Отжимания на брусьях (с грузиками 1.5 кг) — 4 × 12",
            "Отжимания с рюкзаком (8 кг) — 3 × 10-12",
            "Отжимания лучника / печатная машинка — 3 × 6-8 на каждую руку",
            "Классические отжимания — 1 подход до отказа",
        ],
    },
    "back": {
        "title": "Спина, Плечи, Пресс",
        "exercises": [
            "Подтягивания (с грузиками 1.5 кг) — 3 × 6",
            "Отжимания «домиком» (Pike push-ups) — 4 × 10-12",
            "Подъём ног лёжа (с грузиками 3 кг) — 4 × 15-20",
            "Планка — 3 × 60 секунд",
        ],
    },
}

# weekday(): 0 = понедельник ... 6 = воскресенье
SCHEDULE = {0: "chest", 1: "back", 3: "chest", 4: "back"}
REST_DAYS = {
    2: "Среда: отдых / лёгкая растяжка 🧘",
    5: "Суббота: стрит / BMX 🚴",
    6: "Воскресенье: полный отдых 😴",
}
DAY_NAMES = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]

GREETING = "☀️ Доброе утро! Новый день — новые возможности."


# ---------- состояние (какие упражнения отмечены) ----------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Не удалось прочитать state-файл, начинаю с чистого")
    return {}


def save_state(state: dict) -> None:
    # храним только последние 30 сообщений
    if len(state) > 30:
        for key in list(state)[: len(state) - 30]:
            del state[key]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ---------- построение сообщения ----------
def build_text(workout_key: str, weekday: int, done: set[int]) -> str:
    workout = WORKOUTS[workout_key]
    lines = [
        GREETING,
        "",
        f"<b>{DAY_NAMES[weekday]} — {escape(workout['title'])}</b>",
        "",
    ]
    for i, exercise in enumerate(workout["exercises"]):
        mark = "✅" if i in done else "⬜"
        text = escape(exercise)
        if i in done:
            text = f"<s>{text}</s>"
        lines.append(f"{mark} {i + 1}. {text}")
    if len(done) == len(workout["exercises"]):
        lines += ["", "🔥 Тренировка выполнена! Красавчик."]
    else:
        lines += ["", "Нажимай на номер, чтобы отметить упражнение 👇"]
    return "\n".join(lines)


def build_keyboard(workout_key: str, done: set[int]) -> InlineKeyboardMarkup:
    count = len(WORKOUTS[workout_key]["exercises"])
    buttons = [
        InlineKeyboardButton(
            f"{'✅' if i in done else '⬜'} {i + 1}", callback_data=f"toggle:{i}"
        )
        for i in range(count)
    ]
    return InlineKeyboardMarkup([buttons])


# ---------- отправка ----------
async def send_morning(bot, chat_id: int) -> None:
    weekday = datetime.now(TZ).weekday()

    if weekday in REST_DAYS:
        await bot.send_message(chat_id, f"{GREETING}\n\n{REST_DAYS[weekday]}")
        return

    workout_key = SCHEDULE[weekday]
    msg = await bot.send_message(
        chat_id,
        build_text(workout_key, weekday, set()),
        parse_mode=ParseMode.HTML,
        reply_markup=build_keyboard(workout_key, set()),
    )

    state = load_state()
    state[f"{chat_id}:{msg.message_id}"] = {
        "workout": workout_key,
        "weekday": weekday,
        "done": [],
    }
    save_state(state)


async def daily_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_morning(context.bot, CHAT_ID)


# ---------- команды и кнопки ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Привет! Твой CHAT_ID: {chat_id}\n"
        f"Впиши его в переменную CHAT_ID, и я буду писать тебе в "
        f"{SEND_HOUR}:{SEND_MINUTE:02d} каждое утро.\n\n"
        f"/workout — прислать план на сегодня прямо сейчас."
    )


async def cmd_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if CHAT_ID and update.effective_chat.id != CHAT_ID:
        return
    await send_morning(context.bot, update.effective_chat.id)


async def on_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    key = f"{chat_id}:{query.message.message_id}"

    state = load_state()
    entry = state.get(key)
    if entry is None:
        await query.answer("Этот список устарел", show_alert=False)
        return

    index = int(query.data.split(":")[1])
    done = set(entry["done"])
    done.symmetric_difference_update({index})  # переключаем отметку
    entry["done"] = sorted(done)
    save_state(state)

    await query.answer()
    await query.edit_message_text(
        build_text(entry["workout"], entry["weekday"], done),
        parse_mode=ParseMode.HTML,
        reply_markup=build_keyboard(entry["workout"], done),
    )


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("workout", cmd_workout))
    app.add_handler(CallbackQueryHandler(on_toggle, pattern=r"^toggle:\d+$"))

    if CHAT_ID:
        app.job_queue.run_daily(
            daily_job,
            time=time(SEND_HOUR, SEND_MINUTE, tzinfo=TZ),
            name="morning",
        )
        log.info(
            "Рассылка включена: %02d:%02d (%s)", SEND_HOUR, SEND_MINUTE, TZ.key
        )
    else:
        log.warning("CHAT_ID не задан — напиши боту /start, чтобы узнать его")

    app.run_polling()


if __name__ == "__main__":
    main()
