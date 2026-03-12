#!/usr/bin/env python3
"""
Telegram-бот для юристов сервиса "Визирь"
Регистрация юристов, управление заявками, уведомления, админ-панель
"""

import logging
import os
import re
from typing import Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

import database as db
from admin import (
    admin_command,
    admin_callback,
    admin_message_handler,
    ADMIN_WAITING_MESSAGE,
    ADMIN_WAITING_BLOCK_REASON,
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def clean_env_var(raw: str) -> str:
    """Очистка переменной окружения от невидимых символов"""
    if not raw:
        return ''
    raw = raw.replace('\ufeff', '')
    raw = re.sub(r'[\x00-\x1f\x7f]', '', raw)
    cleaned = ''.join(ch for ch in raw if ch.isprintable() and ord(ch) != 0xFFFD)
    return cleaned.strip()


# Переменные окружения
TELEGRAM_TOKEN = clean_env_var(os.getenv('TELEGRAM_TOKEN', ''))
ADMIN_ID = int(os.getenv('ADMIN_ID', '7728619214'))

# Состояния для ConversationHandler регистрации
REG_NAME, REG_SPEC, REG_CONTACT = range(3)

# Хранилище временных состояний пользователей
user_temp_data = {}


# ==================== ПРИВЕТСТВИЕ И РЕГИСТРАЦИЯ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id

    try:
        # Проверяем, зарегистрирован ли юрист
        lawyer = db.get_lawyer_by_id(user_id)

        if lawyer:
            if lawyer.get("blocked", False):
                await update.message.reply_text(
                    "⛔ Ваш аккаунт заблокирован.\n\n"
                    f"Причина: {lawyer.get('block_reason', 'Не указана')}\n\n"
                    "Для разблокировки обратитесь к администратору сервиса.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END

            # Юрист уже зарегистрирован — показываем главное меню
            await show_main_menu(update, context, lawyer)
            return ConversationHandler.END
        else:
            # Новый юрист — начинаем регистрацию
            welcome_text = (
                "⚖️ *Добро пожаловать в Визирь — платформу для профессиональных юристов!*\n\n"
                "Визирь — это современный юридический сервис, который соединяет клиентов "
                "с квалифицированными специалистами. Присоединяясь к нашей команде, вы получаете:\n\n"
                "📌 *Стабильный поток клиентов* — заявки поступают ежедневно\n"
                "📌 *Гибкий график* — берите заявки когда вам удобно\n"
                "📌 *Профессиональный рост* — разнообразные юридические задачи\n"
                "📌 *Прозрачную систему* — рейтинг и статистика вашей работы\n"
                "📌 *Поддержку команды* — мы всегда на связи\n\n"
                "Для начала работы необходимо пройти короткую регистрацию.\n\n"
                "📝 *Введите ваше ФИО* (полностью):"
            )

            await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
            return REG_NAME

    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже или напишите /start"
        )
        return ConversationHandler.END


async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение ФИО юриста"""
    user_id = update.effective_user.id
    full_name = update.message.text.strip()

    if len(full_name) < 5 or len(full_name.split()) < 2:
        await update.message.reply_text(
            "⚠️ Пожалуйста, введите полное ФИО (минимум имя и фамилия).\n\n"
            "📝 *Введите ваше ФИО:*",
            parse_mode=ParseMode.MARKDOWN
        )
        return REG_NAME

    user_temp_data[user_id] = {"full_name": full_name}

    await update.message.reply_text(
        f"✅ Отлично, *{full_name}*!\n\n"
        "Теперь укажите вашу специализацию. Выберите из списка или напишите свою:",
        parse_mode=ParseMode.MARKDOWN
    )

    keyboard = [
        [InlineKeyboardButton("🏛️ Гражданское право", callback_data="spec_civil")],
        [InlineKeyboardButton("👨‍👩‍👧 Семейное право", callback_data="spec_family")],
        [InlineKeyboardButton("🏢 Корпоративное право", callback_data="spec_corporate")],
        [InlineKeyboardButton("⚖️ Уголовное право", callback_data="spec_criminal")],
        [InlineKeyboardButton("🏠 Жилищное право", callback_data="spec_housing")],
        [InlineKeyboardButton("💼 Трудовое право", callback_data="spec_labor")],
        [InlineKeyboardButton("📋 Административное право", callback_data="spec_admin")],
        [InlineKeyboardButton("🔄 Универсальный специалист", callback_data="spec_universal")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👇 Выберите специализацию или напишите свою:",
        reply_markup=reply_markup
    )
    return REG_SPEC


async def reg_spec_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора специализации через кнопку"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    spec_map = {
        "spec_civil": "Гражданское право",
        "spec_family": "Семейное право",
        "spec_corporate": "Корпоративное право",
        "spec_criminal": "Уголовное право",
        "spec_housing": "Жилищное право",
        "spec_labor": "Трудовое право",
        "spec_admin": "Административное право",
        "spec_universal": "Универсальный специалист",
    }

    spec = spec_map.get(query.data, "Не указана")

    if user_id in user_temp_data:
        user_temp_data[user_id]["specialization"] = spec
    else:
        user_temp_data[user_id] = {"specialization": spec}

    await query.edit_message_text(
        f"✅ Специализация: *{spec}*\n\n"
        "📱 Теперь укажите ваш контакт для связи с клиентами\n"
        "(телефон, email или Telegram username):",
        parse_mode=ParseMode.MARKDOWN
    )
    return REG_CONTACT


async def reg_spec_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текстового ввода специализации"""
    user_id = update.effective_user.id
    spec = update.message.text.strip()

    if user_id in user_temp_data:
        user_temp_data[user_id]["specialization"] = spec
    else:
        user_temp_data[user_id] = {"specialization": spec}

    await update.message.reply_text(
        f"✅ Специализация: *{spec}*\n\n"
        "📱 Теперь укажите ваш контакт для связи с клиентами\n"
        "(телефон, email или Telegram username):",
        parse_mode=ParseMode.MARKDOWN
    )
    return REG_CONTACT


async def reg_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение контакта и завершение регистрации"""
    user = update.effective_user
    user_id = user.id
    contact = update.message.text.strip()

    if len(contact) < 3:
        await update.message.reply_text(
            "⚠️ Пожалуйста, укажите корректный контакт.\n\n"
            "📱 *Введите ваш контакт:*",
            parse_mode=ParseMode.MARKDOWN
        )
        return REG_CONTACT

    try:
        data = user_temp_data.get(user_id, {})
        lawyer_data = {
            "telegram_id": user_id,
            "username": user.username or "не указан",
            "full_name": data.get("full_name", "Не указано"),
            "specialization": data.get("specialization", "Не указана"),
            "contact": contact,
        }

        success = db.register_lawyer(lawyer_data)

        if success:
            await update.message.reply_text(
                "🎉 *Регистрация завершена!*\n\n"
                f"👤 *ФИО:* {lawyer_data['full_name']}\n"
                f"⚖️ *Специализация:* {lawyer_data['specialization']}\n"
                f"📱 *Контакт:* {contact}\n\n"
                "Теперь вы будете получать уведомления о новых заявках от клиентов. "
                "Нажмите «Взять заявку», чтобы начать работу.\n\n"
                "Добро пожаловать в команду *Визирь*! 🤝",
                parse_mode=ParseMode.MARKDOWN
            )

            # Показываем главное меню
            lawyer = db.get_lawyer_by_id(user_id)
            await show_main_menu(update, context, lawyer)
        else:
            await update.message.reply_text(
                "⚠️ Вы уже зарегистрированы в системе.\n"
                "Используйте /start для доступа к главному меню."
            )

        # Очистка временных данных
        user_temp_data.pop(user_id, None)

    except Exception as e:
        logger.error(f"Ошибка при регистрации: {e}")
        await update.message.reply_text(
            "❌ Ошибка при регистрации. Пожалуйста, попробуйте позже."
        )

    return ConversationHandler.END


async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена регистрации"""
    user_id = update.effective_user.id
    user_temp_data.pop(user_id, None)

    await update.message.reply_text(
        "❌ Регистрация отменена.\n"
        "Для повторной регистрации нажмите /start"
    )
    return ConversationHandler.END


# ==================== ГЛАВНОЕ МЕНЮ ====================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lawyer: dict = None):
    """Показать главное меню юриста"""
    user_id = update.effective_user.id

    if not lawyer:
        lawyer = db.get_lawyer_by_id(user_id)

    if not lawyer:
        if update.message:
            await update.message.reply_text(
                "⚠️ Вы не зарегистрированы. Нажмите /start для регистрации."
            )
        return

    # Получаем статистику
    stats = db.get_lawyer_stats(user_id)
    new_requests = db.get_new_requests()

    menu_text = (
        f"👋 *{lawyer.get('full_name', 'Юрист')}*, добро пожаловать!\n\n"
        f"📊 *Ваша статистика:*\n"
        f"├ В работе: {stats.get('in_progress', 0)}\n"
        f"├ Выполнено: {stats.get('completed', 0)}\n"
        f"├ Средняя оценка: {'⭐ ' + str(stats.get('avg_rating', 0)) if stats.get('avg_rating', 0) > 0 else '—'}\n"
        f"└ Всего взято: {stats.get('total_taken', 0)}\n\n"
        f"🔔 *Новых заявок:* {len(new_requests)}\n\n"
        "Выберите действие:"
    )

    keyboard = [
        [InlineKeyboardButton(f"🆕 Новые заявки ({len(new_requests)})", callback_data="view_new_requests")],
        [InlineKeyboardButton("📋 Мои заявки в работе", callback_data="view_my_requests")],
        [InlineKeyboardButton("✅ Выполненные заявки", callback_data="view_completed")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="view_stats")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            menu_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                menu_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.callback_query.message.reply_text(
                menu_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )


# ==================== ОБРАБОТКА ЗАЯВОК ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        await query.answer()
    except Exception:
        pass

    try:
        # Проверяем регистрацию и блокировку
        lawyer = db.get_lawyer_by_id(user_id)

        # Пропускаем проверку для кнопок регистрации
        if query.data.startswith("spec_"):
            return  # Обрабатывается в ConversationHandler

        if not lawyer and user_id != ADMIN_ID:
            await query.edit_message_text(
                "⚠️ Вы не зарегистрированы. Нажмите /start для регистрации."
            )
            return

        if lawyer and lawyer.get("blocked", False) and user_id != ADMIN_ID:
            await query.edit_message_text(
                "⛔ Ваш аккаунт заблокирован. Обратитесь к администратору."
            )
            return

        # ---- Просмотр новых заявок ----
        if query.data == "view_new_requests":
            await view_new_requests(query)

        # ---- Мои заявки в работе ----
        elif query.data == "view_my_requests":
            await view_my_requests(query, user_id)

        # ---- Выполненные заявки ----
        elif query.data == "view_completed":
            await view_completed_requests(query, user_id)

        # ---- Статистика ----
        elif query.data == "view_stats":
            await view_stats(query, user_id)

        # ---- Взять заявку ----
        elif query.data.startswith("take_"):
            request_id = query.data.replace("take_", "")
            await take_request(query, user_id, request_id, context)

        # ---- Выполнить заявку ----
        elif query.data.startswith("complete_"):
            request_id = query.data.replace("complete_", "")
            await complete_request_handler(query, user_id, request_id, context)

        # ---- Детали заявки ----
        elif query.data.startswith("detail_"):
            request_id = query.data.replace("detail_", "")
            await view_request_detail(query, user_id, request_id)

        # ---- Обновить меню ----
        elif query.data == "refresh_menu":
            await show_main_menu(update, context, lawyer)

        # ---- Назад в меню ----
        elif query.data == "back_to_menu":
            await show_main_menu(update, context, lawyer)

        # ---- Админ-кнопки ----
        elif query.data.startswith("admin_"):
            await admin_callback(update, context)

    except Exception as e:
        logger.error(f"Ошибка в button_callback: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                "❌ Произошла ошибка. Попробуйте ещё раз или нажмите /start"
            )
        except Exception:
            pass


async def view_new_requests(query) -> None:
    """Показать новые заявки"""
    new_requests = db.get_new_requests()

    if not new_requests:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "📭 *Новых заявок пока нет*\n\n"
            "Мы уведомим вас, когда появится новая заявка.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = f"🆕 *Новые заявки ({len(new_requests)}):*\n\n"
    keyboard = []

    for req in new_requests[-10:]:  # Последние 10
        req_id = req.get("id", "?")
        client_name = req.get("client_name", "Клиент")
        req_type = req.get("type", "—")
        date = req.get("date", "—")
        description = req.get("description", "")[:80]

        text += (
            f"📌 *{req_id}* | {date}\n"
            f"👤 {client_name} | 📋 {req_type}\n"
            f"💬 {description}...\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(f"📋 {req_id}", callback_data=f"detail_{req_id}"),
            InlineKeyboardButton(f"✅ Взять {req_id}", callback_data=f"take_{req_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def view_my_requests(query, user_id: int) -> None:
    """Показать заявки юриста в работе"""
    my_requests = db.get_requests_by_lawyer(user_id)
    in_progress = [r for r in my_requests if r.get("status") == "в работе"]

    if not in_progress:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "📋 *У вас нет заявок в работе*\n\n"
            "Перейдите в раздел «Новые заявки», чтобы взять заявку.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = f"📋 *Ваши заявки в работе ({len(in_progress)}):*\n\n"
    keyboard = []

    for req in in_progress:
        req_id = req.get("id", "?")
        client_name = req.get("client_name", "Клиент")
        req_type = req.get("type", "—")
        assigned = req.get("assigned_date", "—")

        text += (
            f"📌 *{req_id}* | Взята: {assigned}\n"
            f"👤 {client_name} | 📋 {req_type}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(f"📋 {req_id}", callback_data=f"detail_{req_id}"),
            InlineKeyboardButton(f"✅ Выполнено {req_id}", callback_data=f"complete_{req_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def view_completed_requests(query, user_id: int) -> None:
    """Показать выполненные заявки юриста"""
    my_requests = db.get_requests_by_lawyer(user_id)
    completed = [r for r in my_requests if r.get("status") == "выполнена"]

    if not completed:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "✅ *У вас пока нет выполненных заявок*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = f"✅ *Выполненные заявки ({len(completed)}):*\n\n"

    for req in completed[-10:]:  # Последние 10
        req_id = req.get("id", "?")
        client_name = req.get("client_name", "Клиент")
        completed_date = req.get("completed_date", "—")
        rating = req.get("rating")
        rating_str = f"⭐ {rating}/5" if rating else "Без оценки"

        text += f"📌 *{req_id}* | {client_name} | {completed_date} | {rating_str}\n"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def view_stats(query, user_id: int) -> None:
    """Показать статистику юриста"""
    stats = db.get_lawyer_stats(user_id)

    if not stats:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "⚠️ Статистика недоступна.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Формируем звёзды рейтинга
    avg_rating = stats.get("avg_rating", 0)
    if avg_rating > 0:
        stars = "⭐" * int(avg_rating) + ("½" if avg_rating % 1 >= 0.5 else "")
        rating_text = f"{stars} {avg_rating}/5 ({stats.get('ratings_count', 0)} оценок)"
    else:
        rating_text = "Пока нет оценок"

    # Среднее время
    avg_hours = stats.get("avg_completion_hours", 0)
    if avg_hours > 0:
        if avg_hours < 1:
            time_text = f"{int(avg_hours * 60)} мин"
        elif avg_hours < 24:
            time_text = f"{avg_hours} ч"
        else:
            time_text = f"{round(avg_hours / 24, 1)} дн"
    else:
        time_text = "—"

    text = (
        f"📊 *Статистика: {stats.get('full_name', '—')}*\n\n"
        f"⚖️ Специализация: {stats.get('specialization', '—')}\n"
        f"📅 Дата регистрации: {stats.get('registration_date', '—')}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📈 *Показатели:*\n"
        f"├ Всего взято заявок: *{stats.get('total_taken', 0)}*\n"
        f"├ В работе: *{stats.get('in_progress', 0)}*\n"
        f"├ Выполнено: *{stats.get('completed', 0)}*\n"
        f"├ Средняя оценка: {rating_text}\n"
        f"└ Среднее время выполнения: *{time_text}*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        "Продолжайте работу — каждая выполненная заявка повышает ваш рейтинг!"
    )

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def view_request_detail(query, user_id: int, request_id: str) -> None:
    """Показать детали заявки"""
    req = db.get_request_by_id(request_id)

    if not req:
        await query.edit_message_text("⚠️ Заявка не найдена.")
        return

    status_emoji = {"новая": "🆕", "в работе": "🔄", "выполнена": "✅"}.get(req.get("status"), "❓")

    text = (
        f"📋 *Заявка {request_id}*\n\n"
        f"📅 Дата: {req.get('date', '—')}\n"
        f"👤 Клиент: {req.get('client_name', '—')}\n"
        f"📱 Контакт клиента: @{req.get('client_username', '—')}\n"
        f"📋 Тип: {req.get('type', '—')}\n"
        f"{status_emoji} Статус: {req.get('status', '—')}\n"
    )

    if req.get("lawyer_name"):
        text += f"👨‍⚖️ Юрист: {req.get('lawyer_name')}\n"
    if req.get("assigned_date"):
        text += f"📅 Взята: {req.get('assigned_date')}\n"
    if req.get("completed_date"):
        text += f"✅ Выполнена: {req.get('completed_date')}\n"
    if req.get("rating"):
        text += f"⭐ Оценка: {req.get('rating')}/5\n"

    text += f"\n💬 *Описание:*\n{req.get('description', 'Нет описания')}"

    keyboard = []
    if req.get("status") == "новая":
        keyboard.append([InlineKeyboardButton("✅ Взять заявку", callback_data=f"take_{request_id}")])
    elif req.get("status") == "в работе" and req.get("lawyer_id") == user_id:
        keyboard.append([InlineKeyboardButton("✅ Выполнено", callback_data=f"complete_{request_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def take_request(query, user_id: int, request_id: str, context) -> None:
    """Взять заявку"""
    lawyer = db.get_lawyer_by_id(user_id)
    if not lawyer:
        await query.edit_message_text("⚠️ Вы не зарегистрированы.")
        return

    lawyer_name = lawyer.get("full_name", "Юрист")
    success = db.assign_request(request_id, user_id, lawyer_name)

    if success:
        db.update_lawyer_stats(user_id, "requests_count")

        req = db.get_request_by_id(request_id)
        client_username = req.get("client_username", "не указан") if req else "не указан"
        client_name = req.get("client_name", "Клиент") if req else "Клиент"

        text = (
            f"✅ *Заявка {request_id} закреплена за вами!*\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📱 Контакт: @{client_username}\n"
            f"📋 Тип: {req.get('type', '—') if req else '—'}\n\n"
            f"💬 *Описание:*\n{req.get('description', 'Нет описания') if req else '—'}\n\n"
            "Свяжитесь с клиентом и после завершения нажмите «Выполнено»."
        )

        keyboard = [
            [InlineKeyboardButton("✅ Выполнено", callback_data=f"complete_{request_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # Уведомляем клиента через основной бот (если настроен)
        try:
            client_bot_url = clean_env_var(os.getenv("CLIENT_BOT_URL", ""))
            if client_bot_url and req:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "request_id": request_id,
                        "lawyer_name": lawyer_name,
                        "client_id": req.get("client_id"),
                        "event": "request_taken"
                    }
                    async with session.post(
                        f"{client_bot_url}/api/notify_client",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"Клиент уведомлён о взятии заявки {request_id}")
                        else:
                            logger.warning(f"Не удалось уведомить клиента: {resp.status}")
        except Exception as e:
            logger.error(f"Ошибка при уведомлении клиента: {e}")

    else:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            f"⚠️ Не удалось взять заявку {request_id}.\n"
            "Возможно, она уже взята другим юристом.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def complete_request_handler(query, user_id: int, request_id: str, context) -> None:
    """Отметить заявку как выполненную"""
    success = db.complete_request(request_id, user_id)

    if success:
        db.update_lawyer_stats(user_id, "completed_count")

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            f"✅ *Заявка {request_id} отмечена как выполненная!*\n\n"
            "Спасибо за вашу работу! Клиент получит просьбу оценить консультацию.\n\n"
            "Ваш рейтинг обновится после получения оценки.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # Уведомляем клиента для оценки через основной бот
        try:
            client_bot_url = clean_env_var(os.getenv("CLIENT_BOT_URL", ""))
            req = db.get_request_by_id(request_id)
            if client_bot_url and req:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "request_id": request_id,
                        "lawyer_name": req.get("lawyer_name", "Юрист"),
                        "client_id": req.get("client_id"),
                        "event": "request_completed"
                    }
                    async with session.post(
                        f"{client_bot_url}/api/notify_client",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"Клиент уведомлён о выполнении заявки {request_id}")
        except Exception as e:
            logger.error(f"Ошибка при уведомлении клиента о выполнении: {e}")

    else:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        await query.edit_message_text(
            f"⚠️ Не удалось отметить заявку {request_id} как выполненную.\n"
            "Убедитесь, что заявка закреплена за вами и находится в статусе «в работе».",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ==================== УВЕДОМЛЕНИЯ ====================

async def notify_lawyers_about_new_request(app: Application, request_data: dict):
    """Отправить уведомление всем активным юристам о новой заявке"""
    try:
        lawyers = db.get_active_lawyers()
        request_id = request_data.get("id", "?")
        client_name = request_data.get("client_name", "Клиент")
        req_type = request_data.get("type", "—")
        description = request_data.get("description", "")[:150]

        text = (
            "🔔 *Новая заявка!*\n\n"
            f"📌 *{request_id}*\n"
            f"👤 Клиент: {client_name}\n"
            f"📋 Тип: {req_type}\n"
            f"💬 {description}...\n\n"
            "Нажмите кнопку, чтобы взять заявку:"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Взять заявку", callback_data=f"take_{request_id}")],
            [InlineKeyboardButton("📋 Подробнее", callback_data=f"detail_{request_id}")],
        ])

        sent_count = 0
        for lawyer in lawyers:
            try:
                await app.bot.send_message(
                    chat_id=lawyer["telegram_id"],
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление юристу {lawyer.get('telegram_id')}: {e}")

        # Уведомляем админа
        try:
            admin_text = (
                f"📥 *Новая заявка {request_id}*\n"
                f"👤 {client_name} | 📋 {req_type}\n"
                f"📨 Уведомлено юристов: {sent_count}/{len(lawyers)}"
            )
            await app.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа: {e}")

        logger.info(f"Уведомление о заявке {request_id} отправлено {sent_count} юристам")
        return sent_count

    except Exception as e:
        logger.error(f"Ошибка при рассылке уведомлений: {e}")
        return 0


# ==================== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений (вне ConversationHandler)"""
    user_id = update.effective_user.id

    try:
        lawyer = db.get_lawyer_by_id(user_id)

        if not lawyer:
            await update.message.reply_text(
                "⚠️ Вы не зарегистрированы в системе.\n"
                "Нажмите /start для регистрации."
            )
            return

        if lawyer.get("blocked", False):
            await update.message.reply_text(
                "⛔ Ваш аккаунт заблокирован. Обратитесь к администратору."
            )
            return

        # По умолчанию показываем меню
        await update.message.reply_text(
            "Используйте кнопки меню для навигации.\n"
            "Нажмите /start для открытия главного меню."
        )

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Нажмите /start"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = (
        "⚖️ *Справка — Бот для юристов Визирь*\n\n"
        "*Команды:*\n"
        "/start — Главное меню / Регистрация\n"
        "/help — Эта справка\n"
        "/menu — Открыть главное меню\n"
        "/stats — Моя статистика\n\n"
        "*Как это работает:*\n"
        "1️⃣ Зарегистрируйтесь в боте\n"
        "2️⃣ Получайте уведомления о новых заявках\n"
        "3️⃣ Нажмите «Взять заявку» — она закрепится за вами\n"
        "4️⃣ Свяжитесь с клиентом и решите его вопрос\n"
        "5️⃣ Нажмите «Выполнено» после завершения\n"
        "6️⃣ Клиент оценит вашу работу\n\n"
        "По вопросам обращайтесь к администратору: @abu\\_Ali\\_abduSamat"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /menu"""
    user_id = update.effective_user.id
    lawyer = db.get_lawyer_by_id(user_id)
    if lawyer:
        await show_main_menu(update, context, lawyer)
    else:
        await update.message.reply_text(
            "⚠️ Вы не зарегистрированы. Нажмите /start для регистрации."
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stats"""
    user_id = update.effective_user.id
    stats = db.get_lawyer_stats(user_id)

    if not stats:
        await update.message.reply_text(
            "⚠️ Статистика недоступна. Зарегистрируйтесь через /start"
        )
        return

    avg_rating = stats.get("avg_rating", 0)
    rating_text = f"⭐ {avg_rating}/5" if avg_rating > 0 else "Пока нет оценок"

    text = (
        f"📊 *Ваша статистика*\n\n"
        f"👤 {stats.get('full_name', '—')}\n"
        f"⚖️ {stats.get('specialization', '—')}\n\n"
        f"📈 Всего заявок: *{stats.get('total_taken', 0)}*\n"
        f"🔄 В работе: *{stats.get('in_progress', 0)}*\n"
        f"✅ Выполнено: *{stats.get('completed', 0)}*\n"
        f"⭐ Средняя оценка: {rating_text}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


# ==================== СОЗДАНИЕ ПРИЛОЖЕНИЯ ====================

def create_app() -> Application:
    """Создание и конфигурация приложения"""
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN не задан или пустой")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # ConversationHandler для регистрации
    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name),
            ],
            REG_SPEC: [
                CallbackQueryHandler(reg_spec_callback, pattern="^spec_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_spec_text),
            ],
            REG_CONTACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_contact),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_registration),
            CommandHandler("start", start),
        ],
        per_user=True,
        per_chat=True,
    )

    application.add_handler(reg_handler)

    # Команды
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("admin", admin_command))

    # Обработчик кнопок (вне ConversationHandler)
    application.add_handler(CallbackQueryHandler(button_callback))

    # Обработчик текстовых сообщений для админ-панели
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        admin_message_handler
    ))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    return application


if __name__ == "__main__":
    app = create_app()
    logger.info("Бот юристов инициализирован и готов к запуску")
