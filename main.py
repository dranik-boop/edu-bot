import os
import json
import random
import re
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = -1003565334153  # твоя админ-группа

DATA_FILE = Path("tickets.json")
REF_RE = re.compile(r"#ref(\d{4,10})", re.IGNORECASE)

# ====== ТЕКСТЫ ======
TEXT_WELCOME = (
    "Привет, на связи команда Нации Лидеров! Выберите подходящий раздел.\n\n"
    "Если инструкции не помогли или вы хотите поделиться с нами важной информацией — нажмите «Написать админу»."
)

TEXT_INSTRUCTIONS = (
    "⛔️ Ошибка при регистрации на платформе \n\n"
    "Возможно, вы уже регистрировались на нашей платформе раньше. \n\n"
    "Попробуйте пройти через функцию «Забыли пароль?»: \n"
    "• Перейти по ссылке  https://school365edu.org/login/forgot_password.php \n"
    "• В поле <Email> введите адрес электронной почты, на которую пытались зарегистрироваться. "
    "Обратите внимание: если поле <Логин> автоматически заполнилось - удалите из него все данные, "
    "должно быть заполнено только поле <Email> \n"
    "• Нажмите кнопку <Найти> \n"
    "• Если вы регистрировались ранее на платформе, то на указанный вами адрес электронной почты "
    "придет письмо со ссылкой для восстановления пароля \n"
    "• Если e-mail не найден - нажмите «Назад в Меню» --> «✉️ Написать админу»"
)

TEXT_FAQ = (
    "❓ Не получается записаться на курс\n\n"
    "• придумать.\n\n"
    "Если не помогло — нажми «Назад в Меню» --> «✉️ Написать админу»."
)

TEXT_ADMIN_PROMPT = (
    "✉️ Написать админу\n\n"
    "Пожалуйста, опишите проблему. По возможности, приложите скриншоты.\n"
    "Я передам информацию в админ-чат.\n"
    "Обратите внимание: ответ администратора будет дан в рабочее время "
    "(в будние дни с 10:00 до 18:00 по центральному европейскому времени)"
)

TEXT_NOT_IN_MODE = (
    "Я вижу сообщение, но чтобы передать его админу, нажми кнопку «✉️ Написать админу»."
)

# ====== Хранилище тикетов ======
def load_tickets() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_tickets(tickets: dict) -> None:
    DATA_FILE.write_text(json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8")

tickets = load_tickets()
# {"13786": {"user_id": 123, "status": "open"}}

def new_ref() -> str:
    while True:
        r = str(random.randint(10000, 99999))
        if r not in tickets:
            return r

def extract_ref(text: str) -> str | None:
    if not text:
        return None
    m = REF_RE.search(text)
    return m.group(1) if m else None

# ====== КНОПКИ ======
def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⛔️ Ошибка при регистрации на платформе", callback_data="instructions")],
        [InlineKeyboardButton("❓ Не получается записаться на курс", callback_data="faq")],
        [InlineKeyboardButton("✉️ Написать админу", callback_data="to_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)

def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu")]])

def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu")]])

# ====== Команда /start ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    context.user_data["awaiting_ticket"] = False
    await update.message.reply_text(TEXT_WELCOME, reply_markup=main_menu())

# ====== Кнопки ======
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.message.chat.type != "private":
        return

    if q.data == "menu":
        context.user_data["awaiting_ticket"] = False
        await q.edit_message_text(TEXT_WELCOME, reply_markup=main_menu())
        return

    if q.data == "instructions":
        await q.edit_message_text(TEXT_INSTRUCTIONS, reply_markup=back_menu())
        return

    if q.data == "faq":
        await q.edit_message_text(TEXT_FAQ, reply_markup=back_menu())
        return

    if q.data == "to_admin":
        context.user_data["awaiting_ticket"] = True
        await q.edit_message_text(TEXT_ADMIN_PROMPT, reply_markup=admin_menu())
        return

# ====== Личка: сообщение пользователем ======
async def private_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    if not context.user_data.get("awaiting_ticket", False):
        await update.message.reply_text(TEXT_NOT_IN_MODE, reply_markup=main_menu())
        return

    r = new_ref()
    tickets[r] = {"user_id": update.effective_user.id, "status": "open"}
    save_tickets(tickets)

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"Новое обращение #ref{r}:\n\n{text}"
    )

    context.user_data["awaiting_ticket"] = False
    await update.message.reply_text(f"Принято. Номер обращения: #ref{r}")

# ====== Группа админов: reply-ответ ======
async def admin_reply_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return

    msg = update.message
    if not msg or not msg.text:
        return

    if not msg.reply_to_message:
        return

    original = msg.reply_to_message
    if not original.from_user or not original.from_user.is_bot:
        return

    ref = extract_ref(original.text or "")
    if not ref:
        return

    ticket = tickets.get(ref)
    if not ticket:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"Не нашёл обращение для #ref{ref} (нет в tickets.json)."
        )
        return

    user_id = ticket.get("user_id")
    if not user_id:
        return

    await context.bot.send_message(
        chat_id=user_id,
        text=f"Ответ по обращению #ref{ref}:\n\n{msg.text}"
    )

    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Отправлено по #ref{ref}.")

# ====== HTTP для Render Web Service ======
class DummyHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

def build_application():
    if not TOKEN:
        raise RuntimeError("Переменная окружения BOT_TOKEN не задана в Render (Environment).")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))

    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_text_router)
    )
    app.add_handler(
        MessageHandler(filters.Chat(chat_id=ADMIN_CHAT_ID) & filters.TEXT, admin_reply_router)
    )
    return app

def run_bot():
    app = build_application()
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_server()
