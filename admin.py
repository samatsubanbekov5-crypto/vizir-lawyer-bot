#!/usr/bin/env python3
"""
Админ-панель (мини-CRM) для бота юристов сервиса "Визирь"
Доступна только администратору (ADMIN_ID)
"""

import logging
import os
from datetime import datetime
from typing import Optional
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import database as db

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv('ADMIN_ID', '7728619214'))

# Состояния для обработки текстовых сообщений от админа
ADMIN_WAITING_MESSAGE = "admin_waiting_message"
ADMIN_WAITING_BLOCK_REASON = "admin_waiting_block_reason"

# Временное хранилище состояний админа
admin_state = {}


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    return user_id == ADMIN_ID


# ==================== ГЛАВНАЯ ПАНЕЛЬ ====================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /admin"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ У вас нет доступа к панели администратора."
        )
        return

    await show_admin_panel(update, context)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главную панель администратора"""
    analytics = db.get_analytics(days=30)

    total = analytics.get("total_requests", 0)
    status = analytics.get("status_counts", {})
    new_count = status.get("новая", 0)
    in_progress = status.get("в работе", 0)
    completed = status.get("выполнена", 0)

    text = (
        "🏛️ *ПАНЕЛЬ АДМИНИСТРАТОРА — ВИЗИРЬ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Общая статистика:*\n"
        f"├ Всего заявок: *{total}*\n"
        f"├ 🆕 Новых: *{new_count}*\n"
        f"├ 🔄 В работе: *{in_progress}*\n"
        f"├ ✅ Выполнено: *{completed}*\n"
        f"├ ⭐ Средняя оценка: *{analytics.get('overall_avg_rating', 0)}*\n"
        f"└ 📅 За последние 30 дней: *{analytics.get('period_requests', 0)}*\n\n"
        f"👥 *Юристы:*\n"
        f"├ Всего: *{analytics.get('total_lawyers', 0)}*\n"
        f"├ Активных: *{analytics.get('active_lawyers', 0)}*\n"
        f"└ Заблокировано: *{analytics.get('blocked_lawyers', 0)}*\n\n"
        f"🏆 Самый активный: *{analytics.get('most_active_lawyer', '—')}*\n"
        f"📋 Популярный тип заявок: *{analytics.get('most_popular_type', '—')}*\n"
    )

    keyboard = [
        [InlineKeyboardButton("📋 Все заявки", callback_data="admin_all_requests"),
         InlineKeyboardButton("🆕 Новые", callback_data="admin_filter_new")],
        [InlineKeyboardButton("🔄 В работе", callback_data="admin_filter_progress"),
         InlineKeyboardButton("✅ Выполненные", callback_data="admin_filter_done")],
        [InlineKeyboardButton("👥 Рейтинг юристов", callback_data="admin_lawyer_ranking")],
        [InlineKeyboardButton("📊 Аналитика за день", callback_data="admin_analytics_1"),
         InlineKeyboardButton("📊 За неделю", callback_data="admin_analytics_7")],
        [InlineKeyboardButton("📊 За месяц", callback_data="admin_analytics_30")],
        [InlineKeyboardButton("👨‍⚖️ Управление юристами", callback_data="admin_manage_lawyers")],
        [InlineKeyboardButton("⭐ Оценки клиентов", callback_data="admin_ratings")],
        [InlineKeyboardButton("💾 Резервная копия", callback_data="admin_backup"),
         InlineKeyboardButton("📥 Восстановить", callback_data="admin_restore")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_refresh")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )


# ==================== ОБРАБОТЧИК КНОПОК АДМИНА ====================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик кнопок админ-панели"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_admin(user_id):
        try:
            await query.answer("⛔ Нет доступа", show_alert=True)
        except Exception:
            pass
        return

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data

    try:
        # ---- Все заявки ----
        if data == "admin_all_requests":
            await admin_show_requests(query, status_filter=None)

        # ---- Фильтр по статусу ----
        elif data == "admin_filter_new":
            await admin_show_requests(query, status_filter="новая")
        elif data == "admin_filter_progress":
            await admin_show_requests(query, status_filter="в работе")
        elif data == "admin_filter_done":
            await admin_show_requests(query, status_filter="выполнена")

        # ---- Рейтинг юристов ----
        elif data == "admin_lawyer_ranking":
            await admin_lawyer_ranking(query)

        # ---- Аналитика ----
        elif data.startswith("admin_analytics_"):
            days = int(data.replace("admin_analytics_", ""))
            await admin_analytics(query, days)

        # ---- Управление юристами ----
        elif data == "admin_manage_lawyers":
            await admin_manage_lawyers(query)

        # ---- Детали юриста ----
        elif data.startswith("admin_lawyer_"):
            parts = data.split("_")
            if len(parts) >= 3:
                action = parts[2]
                if action == "detail" and len(parts) >= 4:
                    lawyer_id = int(parts[3])
                    await admin_lawyer_detail(query, lawyer_id)
                elif action == "block" and len(parts) >= 4:
                    lawyer_id = int(parts[3])
                    await admin_block_lawyer_start(query, lawyer_id)
                elif action == "unblock" and len(parts) >= 4:
                    lawyer_id = int(parts[3])
                    await admin_unblock_lawyer(query, lawyer_id)
                elif action == "msg" and len(parts) >= 4:
                    lawyer_id = int(parts[3])
                    await admin_send_message_start(query, lawyer_id, context)

        # ---- Оценки ----
        elif data == "admin_ratings":
            await admin_show_ratings(query)

        # ---- Резервная копия ----
        elif data == "admin_backup":
            await admin_create_backup(query, context)

        # ---- Восстановление ----
        elif data == "admin_restore":
            await admin_restore_backup(query)

        # ---- Обновить ----
        elif data == "admin_refresh":
            await show_admin_panel(update, context)

        # ---- Назад в админ-панель ----
        elif data == "admin_back":
            await show_admin_panel(update, context)

        # ---- Детали заявки (из админки) ----
        elif data.startswith("admin_req_"):
            request_id = data.replace("admin_req_", "")
            await admin_request_detail(query, request_id)

    except Exception as e:
        logger.error(f"Ошибка в admin_callback: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                "❌ Ошибка в админ-панели. Попробуйте /admin"
            )
        except Exception:
            pass


# ==================== ПРОСМОТР ЗАЯВОК ====================

async def admin_show_requests(query, status_filter: Optional[str] = None) -> None:
    """Показать заявки с фильтром"""
    all_requests = db.get_all_requests()

    if status_filter:
        filtered = [r for r in all_requests if r.get("status") == status_filter]
        title = {
            "новая": "🆕 Новые заявки",
            "в работе": "🔄 Заявки в работе",
            "выполнена": "✅ Выполненные заявки",
        }.get(status_filter, "📋 Заявки")
    else:
        filtered = all_requests
        title = "📋 Все заявки"

    if not filtered:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        await query.edit_message_text(
            f"{title}\n\n📭 Заявок не найдено.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Показываем последние 15
    recent = filtered[-15:]
    recent.reverse()

    text = f"*{title}* ({len(filtered)} всего)\n\n"
    keyboard = []

    for req in recent:
        req_id = req.get("id", "?")
        status_emoji = {"новая": "🆕", "в работе": "🔄", "выполнена": "✅"}.get(req.get("status"), "❓")
        client = req.get("client_name", "—")[:15]
        req_type = req.get("type", "—")[:12]
        date = req.get("date", "—")
        lawyer = req.get("lawyer_name", "—")[:15] if req.get("lawyer_name") else "—"
        rating = f"⭐{req.get('rating')}" if req.get("rating") else ""

        text += f"{status_emoji} *{req_id}* | {date}\n"
        text += f"   👤 {client} | 📋 {req_type} | 👨‍⚖️ {lawyer} {rating}\n\n"

        keyboard.append([
            InlineKeyboardButton(f"📋 {req_id}", callback_data=f"admin_req_{req_id}")
        ])

    # Фильтры
    filter_row = []
    if status_filter != "новая":
        filter_row.append(InlineKeyboardButton("🆕 Новые", callback_data="admin_filter_new"))
    if status_filter != "в работе":
        filter_row.append(InlineKeyboardButton("🔄 В работе", callback_data="admin_filter_progress"))
    if status_filter != "выполнена":
        filter_row.append(InlineKeyboardButton("✅ Готовые", callback_data="admin_filter_done"))
    if filter_row:
        keyboard.append(filter_row)

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_request_detail(query, request_id: str) -> None:
    """Детали заявки для админа"""
    req = db.get_request_by_id(request_id)

    if not req:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        await query.edit_message_text(
            "⚠️ Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    status_emoji = {"новая": "🆕", "в работе": "🔄", "выполнена": "✅"}.get(req.get("status"), "❓")

    text = (
        f"📋 *Заявка {request_id}* {status_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Дата создания: {req.get('date', '—')}\n"
        f"👤 Клиент: {req.get('client_name', '—')}\n"
        f"📱 Username: @{req.get('client_username', '—')}\n"
        f"🆔 Client ID: `{req.get('client_id', '—')}`\n"
        f"📋 Тип: {req.get('type', '—')}\n"
        f"📌 Статус: {req.get('status', '—')}\n\n"
    )

    if req.get("lawyer_name"):
        text += f"👨‍⚖️ Юрист: {req.get('lawyer_name')}\n"
        text += f"🆔 Lawyer ID: `{req.get('lawyer_id', '—')}`\n"
    if req.get("assigned_date"):
        text += f"📅 Взята: {req.get('assigned_date')}\n"
    if req.get("completed_date"):
        text += f"✅ Выполнена: {req.get('completed_date')}\n"

        # Время выполнения
        try:
            assigned = datetime.strptime(req.get("assigned_date", ""), "%Y-%m-%d %H:%M")
            done = datetime.strptime(req.get("completed_date", ""), "%Y-%m-%d %H:%M")
            hours = (done - assigned).total_seconds() / 3600
            if hours < 1:
                time_str = f"{int(hours * 60)} мин"
            elif hours < 24:
                time_str = f"{round(hours, 1)} ч"
            else:
                time_str = f"{round(hours / 24, 1)} дн"
            text += f"⏱️ Время выполнения: {time_str}\n"
        except (ValueError, TypeError):
            pass

    if req.get("rating"):
        stars = "⭐" * req["rating"]
        text += f"\n{stars} Оценка: {req['rating']}/5\n"
        if req.get("rating_comment"):
            text += f"💬 Комментарий: {req['rating_comment']}\n"

    text += f"\n💬 *Описание:*\n{req.get('description', 'Нет описания')}"

    keyboard = []
    if req.get("lawyer_id"):
        keyboard.append([
            InlineKeyboardButton(
                "👨‍⚖️ Профиль юриста",
                callback_data=f"admin_lawyer_detail_{req['lawyer_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_all_requests")])
    keyboard.append([InlineKeyboardButton("🏠 Панель", callback_data="admin_back")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== РЕЙТИНГ ЮРИСТОВ ====================

async def admin_lawyer_ranking(query) -> None:
    """Показать рейтинг юристов"""
    analytics = db.get_analytics(days=365)
    rankings = analytics.get("lawyer_rankings", [])

    if not rankings:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        await query.edit_message_text(
            "👥 *Рейтинг юристов*\n\n📭 Юристы не зарегистрированы.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = "🏆 *РЕЙТИНГ ЮРИСТОВ*\n━━━━━━━━━━━━━━━━━━\n\n"

    medals = ["🥇", "🥈", "🥉"]

    for i, stats in enumerate(rankings):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = stats.get("full_name", "—")
        completed = stats.get("completed", 0)
        avg_rating = stats.get("avg_rating", 0)
        avg_time = stats.get("avg_completion_hours", 0)
        blocked = " ⛔" if stats.get("blocked", False) else ""

        rating_str = f"⭐{avg_rating}" if avg_rating > 0 else "—"

        if avg_time > 0:
            if avg_time < 1:
                time_str = f"{int(avg_time * 60)}м"
            elif avg_time < 24:
                time_str = f"{round(avg_time, 1)}ч"
            else:
                time_str = f"{round(avg_time / 24, 1)}д"
        else:
            time_str = "—"

        text += (
            f"{medal} *{name}*{blocked}\n"
            f"   ✅ {completed} выполн. | {rating_str} | ⏱️ {time_str}\n"
            f"   📋 Всего: {stats.get('total_taken', 0)} | 🔄 В работе: {stats.get('in_progress', 0)}\n\n"
        )

    keyboard = [
        [InlineKeyboardButton("👨‍⚖️ Управление юристами", callback_data="admin_manage_lawyers")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== АНАЛИТИКА ====================

async def admin_analytics(query, days: int) -> None:
    """Показать аналитику за период"""
    analytics = db.get_analytics(days=days)

    period_names = {1: "день", 7: "неделю", 30: "месяц"}
    period_name = period_names.get(days, f"{days} дней")

    text = (
        f"📊 *АНАЛИТИКА ЗА {period_name.upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 *Заявки:*\n"
        f"├ За период: *{analytics.get('period_requests', 0)}*\n"
        f"├ Всего в системе: *{analytics.get('total_requests', 0)}*\n"
    )

    # Статусы
    status = analytics.get("status_counts", {})
    text += f"├ 🆕 Новых: *{status.get('новая', 0)}*\n"
    text += f"├ 🔄 В работе: *{status.get('в работе', 0)}*\n"
    text += f"└ ✅ Выполнено: *{status.get('выполнена', 0)}*\n\n"

    # Типы заявок
    type_counts = analytics.get("type_counts", {})
    if type_counts:
        text += "📋 *Типы заявок (за период):*\n"
        sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        for t_name, t_count in sorted_types:
            bar = "█" * min(t_count, 20)
            text += f"├ {t_name}: *{t_count}* {bar}\n"
        text += f"└ Самый популярный: *{analytics.get('most_popular_type', '—')}*\n\n"

    # Юристы
    text += (
        f"👥 *Юристы:*\n"
        f"├ Всего: *{analytics.get('total_lawyers', 0)}*\n"
        f"├ Активных: *{analytics.get('active_lawyers', 0)}*\n"
        f"├ Заблокировано: *{analytics.get('blocked_lawyers', 0)}*\n"
        f"└ Самый активный: *{analytics.get('most_active_lawyer', '—')}*\n\n"
    )

    # Оценки
    text += (
        f"⭐ *Оценки:*\n"
        f"├ Средняя оценка: *{analytics.get('overall_avg_rating', 0)}/5*\n"
        f"└ Всего оценок: *{analytics.get('total_ratings', 0)}*\n\n"
    )

    # Заявки по дням
    daily = analytics.get("daily_counts", {})
    if daily:
        text += "📅 *По дням:*\n"
        sorted_days = sorted(daily.items())[-7:]  # Последние 7 дней
        for day, count in sorted_days:
            bar = "█" * min(count, 15)
            text += f"├ {day}: *{count}* {bar}\n"
        text += "\n"

    keyboard = [
        [
            InlineKeyboardButton("📊 День", callback_data="admin_analytics_1"),
            InlineKeyboardButton("📊 Неделя", callback_data="admin_analytics_7"),
            InlineKeyboardButton("📊 Месяц", callback_data="admin_analytics_30"),
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== УПРАВЛЕНИЕ ЮРИСТАМИ ====================

async def admin_manage_lawyers(query) -> None:
    """Список юристов для управления"""
    lawyers = db.get_all_lawyers()

    if not lawyers:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        await query.edit_message_text(
            "👥 *Управление юристами*\n\n📭 Юристы не зарегистрированы.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = "👥 *УПРАВЛЕНИЕ ЮРИСТАМИ*\n━━━━━━━━━━━━━━━━━━\n\n"
    keyboard = []

    for lawyer in lawyers:
        tid = lawyer.get("telegram_id")
        name = lawyer.get("full_name", "—")
        spec = lawyer.get("specialization", "—")[:20]
        blocked = lawyer.get("blocked", False)
        status_icon = "⛔" if blocked else "✅"

        stats = db.get_lawyer_stats(tid)
        completed = stats.get("completed", 0) if stats else 0
        avg_rating = stats.get("avg_rating", 0) if stats else 0
        rating_str = f"⭐{avg_rating}" if avg_rating > 0 else ""

        text += f"{status_icon} *{name}*\n"
        text += f"   ⚖️ {spec} | ✅ {completed} | {rating_str}\n\n"

        keyboard.append([
            InlineKeyboardButton(f"👤 {name[:20]}", callback_data=f"admin_lawyer_detail_{tid}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_back")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_lawyer_detail(query, lawyer_id: int) -> None:
    """Детальная информация о юристе для админа"""
    stats = db.get_lawyer_stats(lawyer_id)
    lawyer = db.get_lawyer_by_id(lawyer_id)

    if not lawyer or not stats:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_lawyers")]]
        await query.edit_message_text(
            "⚠️ Юрист не найден.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    blocked = lawyer.get("blocked", False)
    status_text = "⛔ ЗАБЛОКИРОВАН" if blocked else "✅ Активен"

    avg_rating = stats.get("avg_rating", 0)
    if avg_rating > 0:
        stars = "⭐" * int(avg_rating)
        rating_text = f"{stars} {avg_rating}/5 ({stats.get('ratings_count', 0)} оценок)"
    else:
        rating_text = "Пока нет оценок"

    avg_hours = stats.get("avg_completion_hours", 0)
    if avg_hours > 0:
        if avg_hours < 1:
            time_text = f"{int(avg_hours * 60)} мин"
        elif avg_hours < 24:
            time_text = f"{round(avg_hours, 1)} ч"
        else:
            time_text = f"{round(avg_hours / 24, 1)} дн"
    else:
        time_text = "—"

    text = (
        f"👤 *ПРОФИЛЬ ЮРИСТА*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 ФИО: *{stats.get('full_name', '—')}*\n"
        f"⚖️ Специализация: {stats.get('specialization', '—')}\n"
        f"📱 Контакт: {stats.get('contact', '—')}\n"
        f"🆔 Telegram ID: `{lawyer_id}`\n"
        f"📱 Username: @{lawyer.get('username', '—')}\n"
        f"📅 Регистрация: {stats.get('registration_date', '—')}\n"
        f"📌 Статус: {status_text}\n"
    )

    if blocked and lawyer.get("block_reason"):
        text += f"📝 Причина блокировки: {lawyer.get('block_reason')}\n"

    text += (
        f"\n📊 *Статистика:*\n"
        f"├ Всего взято: *{stats.get('total_taken', 0)}*\n"
        f"├ В работе: *{stats.get('in_progress', 0)}*\n"
        f"├ Выполнено: *{stats.get('completed', 0)}*\n"
        f"├ Средняя оценка: {rating_text}\n"
        f"└ Среднее время: *{time_text}*\n"
    )

    keyboard = []

    # Кнопка отправки сообщения
    keyboard.append([
        InlineKeyboardButton("💬 Отправить сообщение", callback_data=f"admin_lawyer_msg_{lawyer_id}")
    ])

    # Кнопка блокировки/разблокировки
    if blocked:
        keyboard.append([
            InlineKeyboardButton("✅ Разблокировать", callback_data=f"admin_lawyer_unblock_{lawyer_id}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("⛔ Заблокировать", callback_data=f"admin_lawyer_block_{lawyer_id}")
        ])

    keyboard.append([InlineKeyboardButton("🔙 К списку юристов", callback_data="admin_manage_lawyers")])
    keyboard.append([InlineKeyboardButton("🏠 Панель", callback_data="admin_back")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_block_lawyer_start(query, lawyer_id: int) -> None:
    """Начать процесс блокировки юриста"""
    lawyer = db.get_lawyer_by_id(lawyer_id)
    if not lawyer:
        return

    admin_state[ADMIN_ID] = {
        "action": "block_lawyer",
        "lawyer_id": lawyer_id,
        "lawyer_name": lawyer.get("full_name", "—")
    }

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=f"admin_lawyer_detail_{lawyer_id}")]]

    await query.edit_message_text(
        f"⛔ *Блокировка юриста: {lawyer.get('full_name', '—')}*\n\n"
        "Напишите причину блокировки:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_unblock_lawyer(query, lawyer_id: int) -> None:
    """Разблокировать юриста"""
    success = db.unblock_lawyer(lawyer_id)

    if success:
        # Уведомляем юриста
        try:
            bot = query.get_bot()
            await bot.send_message(
                chat_id=lawyer_id,
                text="✅ *Ваш аккаунт разблокирован!*\n\n"
                     "Вы снова можете принимать заявки. Нажмите /start для начала работы.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить юриста {lawyer_id} о разблокировке: {e}")

        await admin_lawyer_detail(query, lawyer_id)
    else:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_manage_lawyers")]]
        await query.edit_message_text(
            "⚠️ Не удалось разблокировать юриста.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def admin_send_message_start(query, lawyer_id: int, context) -> None:
    """Начать отправку сообщения юристу"""
    lawyer = db.get_lawyer_by_id(lawyer_id)
    if not lawyer:
        return

    admin_state[ADMIN_ID] = {
        "action": "send_message",
        "lawyer_id": lawyer_id,
        "lawyer_name": lawyer.get("full_name", "—")
    }

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=f"admin_lawyer_detail_{lawyer_id}")]]

    await query.edit_message_text(
        f"💬 *Сообщение юристу: {lawyer.get('full_name', '—')}*\n\n"
        "Напишите текст сообщения (похвала, замечание, информация):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== ОЦЕНКИ ====================

async def admin_show_ratings(query) -> None:
    """Показать последние оценки клиентов"""
    all_requests = db.get_all_requests()
    rated = [r for r in all_requests if r.get("rating") is not None]
    rated.sort(key=lambda x: x.get("rating_date", ""), reverse=True)

    if not rated:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        await query.edit_message_text(
            "⭐ *Оценки клиентов*\n\n📭 Оценок пока нет.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = "⭐ *ОЦЕНКИ КЛИЕНТОВ*\n━━━━━━━━━━━━━━━━━━\n\n"

    # Распределение оценок
    rating_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in rated:
        rating = r.get("rating", 0)
        if rating in rating_dist:
            rating_dist[rating] += 1

    text += "📊 *Распределение:*\n"
    total_rated = len(rated)
    for stars in range(5, 0, -1):
        count = rating_dist[stars]
        pct = round(count / total_rated * 100) if total_rated > 0 else 0
        bar = "█" * (pct // 5) if pct > 0 else ""
        text += f"{'⭐' * stars}: *{count}* ({pct}%) {bar}\n"

    avg = sum(r.get("rating", 0) for r in rated) / len(rated) if rated else 0
    text += f"\n📈 Средняя оценка: *{round(avg, 1)}/5*\n\n"

    # Последние 10 оценок
    text += "📝 *Последние оценки:*\n\n"
    for r in rated[:10]:
        req_id = r.get("id", "?")
        stars = "⭐" * r.get("rating", 0)
        lawyer = r.get("lawyer_name", "—")[:15]
        client = r.get("client_name", "—")[:15]
        comment = r.get("rating_comment", "")
        comment_text = f"\n   💬 {comment[:50]}..." if comment else ""

        text += f"{stars} *{req_id}*\n"
        text += f"   👤 {client} → 👨‍⚖️ {lawyer}{comment_text}\n\n"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ АДМИНА ====================

async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений и файлов от админа"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return  # Не админ — пропускаем

    # Обработка загрузки файла для восстановления
    if update.message and update.message.document:
        state = admin_state.get(ADMIN_ID)
        if state and state.get("action") == "restore_backup":
            try:
                file = await context.bot.get_file(update.message.document.file_id)
                file_data = await file.download_as_bytearray()
                backup_data = json.loads(file_data.decode('utf-8'))

                # Сохраняем временный файл
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
                    json.dump(backup_data, tmp)
                    tmp_path = tmp.name

                # Восстанавливаем
                success = db.restore_from_backup(tmp_path)

                # Удаляем временный файл
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

                if success:
                    await update.message.reply_text(
                        "✅ *Данные успешно восстановлены!*\n\n"
                        "Все заявки, юристы и оценки загружены из резервной копии.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text(
                        "❌ *Ошибка при восстановлении данных*\n\n"
                        "Проверьте формат файла и попробуйте ещё раз.",
                        parse_mode=ParseMode.MARKDOWN
                    )

                admin_state.pop(ADMIN_ID, None)
                return

            except Exception as e:
                logger.error(f"Ошибка при восстановлении из файла: {e}")
                await update.message.reply_text(
                    f"❌ *Ошибка при обработке файла*\n\nДеталь: {str(e)[:100]}",
                    parse_mode=ParseMode.MARKDOWN
                )
                admin_state.pop(ADMIN_ID, None)
                return

    # Обработка текстовых сообщений
    if not update.message or not update.message.text:
        return

    state = admin_state.get(ADMIN_ID)
    if not state:
        return  # Нет активного действия — пропускаем

    action = state.get("action")
    message_text = update.message.text.strip()

    try:
        if action == "send_message":
            # Отправка сообщения юристу
            lawyer_id = state.get("lawyer_id")
            lawyer_name = state.get("lawyer_name", "—")

            try:
                await context.bot.send_message(
                    chat_id=lawyer_id,
                    text=f"📩 *Сообщение от администратора Визирь:*\n\n{message_text}",
                    parse_mode=ParseMode.MARKDOWN
                )

                await update.message.reply_text(
                    f"✅ Сообщение отправлено юристу *{lawyer_name}*",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения юристу {lawyer_id}: {e}")
                await update.message.reply_text(
                    f"❌ Не удалось отправить сообщение юристу {lawyer_name}.\n"
                    f"Возможно, юрист заблокировал бота."
                )

            # Очищаем состояние
            admin_state.pop(ADMIN_ID, None)

        elif action == "block_lawyer":
            # Блокировка юриста
            lawyer_id = state.get("lawyer_id")
            lawyer_name = state.get("lawyer_name", "—")

            success = db.block_lawyer(lawyer_id, reason=message_text)

            if success:
                # Уведомляем юриста
                try:
                    await context.bot.send_message(
                        chat_id=lawyer_id,
                        text=f"⛔ *Ваш аккаунт заблокирован*  "
                             f"Причина: {message_text}  "
                             "Для разблокировки обратитесь к администратору: @abu_Ali_abduSamat",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить юриста {lawyer_id} о блокировке: {e}")

                await update.message.reply_text(
                    f"⚠️ Юрист *{lawyer_name}* заблокирован.\n"
                    f"Причина: {message_text}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"❌ Не удалось заблокировать юриста {lawyer_name}."
                )

            # Очищаем состояние
            admin_state.pop(ADMIN_ID, None)

    except Exception as e:
        logger.error(f"Ошибка в admin_message_handler: {e}")
        admin_state.pop(ADMIN_ID, None)
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте /admin"
        )

# ==================== РЕЗЕРВНОЕ КОПИРОВАНИЕ ====================

async def admin_create_backup(query, context) -> None:
    """Создать и отправить резервную копию админу в Телеграм"""
    try:
        await query.answer("💾 Создание резервной копии...", show_alert=False)
    except Exception:
        pass

    try:
        backup_file = db.create_backup()

        if backup_file:
            # Отправляем файл
            with open(backup_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=query.from_user.id,
                    document=f,
                    filename=f"vizir_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    caption="💾 *Резервная копия данных*\n\n"
                            "Файл содержит все данные системы: заявки, юристы, оценки.",
                    parse_mode=ParseMode.MARKDOWN
                )

            keyboard = [[InlineKeyboardButton("🔙 В панель", callback_data="admin_back")]]
            await query.edit_message_text(
                "✅ *Резервная копия сохранена!*\n\n"
                "Файл отправлен в чат.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [[InlineKeyboardButton("🔙 В панель", callback_data="admin_back")]]
            await query.edit_message_text(
                "❌ *Ошибка при сохранении резервной копии*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Ошибка при сохранении резервной копии: {e}")
        keyboard = [[InlineKeyboardButton("🔙 В панель", callback_data="admin_back")]]
        try:
            await query.edit_message_text(
                "❌ *Ошибка*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass


async def admin_restore_backup(query) -> None:
    """Начать процесс восстановления из бэкапа"""
    admin_state[ADMIN_ID] = {"action": "restore_backup"}

    keyboard = [
        [InlineKeyboardButton("🔙 Отменить", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        "📥 *Восстановление данных*\n\n"
        "⚠️ *Внимание!* Эта операция заменит все текущие данные на данные из резервной копии.\n\n"
        "📄 *Отправьте JSON-файл* для восстановления:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
