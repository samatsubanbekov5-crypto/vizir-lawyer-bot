#!/usr/bin/env python3
"""
Админ-панель (мини-CRM) для бота юристов сервиса "Визирь"
Доступна только администратору (ADMIN_ID)
Полностью на InlineKeyboard — без команд, всё через кнопки
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
ADMIN_WAITING_BROADCAST = "admin_waiting_broadcast"

# Временное хранилище состояний админа
admin_state = {}


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    return user_id == ADMIN_ID


# ==================== ГЛАВНАЯ ПАНЕЛЬ ====================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /admin — работает без регистрации"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ У вас нет доступа к панели администратора."
        )
        return

    # Очищаем любое состояние админа
    admin_state.pop(ADMIN_ID, None)
    await show_admin_panel(update, context)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главную панель администратора — красивая, интуитивная"""
    analytics = db.get_analytics(days=30)

    total = analytics.get("total_requests", 0)
    status = analytics.get("status_counts", {})
    new_count = status.get("новая", 0)
    in_progress = status.get("в работе", 0)
    completed = status.get("выполнена", 0)

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏛️  *ВИЗИРЬ — ПАНЕЛЬ АДМИНИСТРАТОРА*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 *Сводка за 30 дней:*\n\n"
        f"   📋 Всего заявок: *{total}*\n"
        f"   🆕 Новых: *{new_count}*\n"
        f"   🔄 В работе: *{in_progress}*\n"
        f"   ✅ Выполнено: *{completed}*\n\n"
        f"   👥 Юристов: *{analytics.get('total_lawyers', 0)}* "
        f"(активных: *{analytics.get('active_lawyers', 0)}*)\n"
        f"   ⭐ Средняя оценка: *{analytics.get('overall_avg_rating', 0)}/5*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите раздел:"
    )

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats_menu")],
        [InlineKeyboardButton("👨‍⚖️ Юристы", callback_data="admin_lawyers_menu")],
        [InlineKeyboardButton("📋 Заявки", callback_data="admin_requests_menu")],
        [InlineKeyboardButton("⭐ Оценки", callback_data="admin_ratings")],
        [InlineKeyboardButton("📨 Рассылка", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings_menu")],
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
        # ==================== НАВИГАЦИЯ ====================

        # ---- Главная панель ----
        if data in ("admin_back", "admin_refresh"):
            admin_state.pop(ADMIN_ID, None)
            await show_admin_panel(update, context)

        # ==================== СТАТИСТИКА ====================

        elif data == "admin_stats_menu":
            await admin_stats_menu(query)

        elif data.startswith("admin_analytics_"):
            days = int(data.replace("admin_analytics_", ""))
            await admin_analytics(query, days)

        # ==================== ЮРИСТЫ ====================

        elif data == "admin_lawyers_menu":
            await admin_lawyers_menu(query)

        elif data == "admin_lawyer_ranking":
            await admin_lawyer_ranking(query)

        elif data == "admin_manage_lawyers":
            await admin_manage_lawyers(query)

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

        # ==================== ЗАЯВКИ ====================

        elif data == "admin_requests_menu":
            await admin_requests_menu(query)

        elif data == "admin_all_requests":
            await admin_show_requests(query, status_filter=None)

        elif data == "admin_filter_new":
            await admin_show_requests(query, status_filter="новая")

        elif data == "admin_filter_progress":
            await admin_show_requests(query, status_filter="в работе")

        elif data == "admin_filter_done":
            await admin_show_requests(query, status_filter="выполнена")

        elif data.startswith("admin_req_"):
            request_id = data.replace("admin_req_", "")
            await admin_request_detail(query, request_id)

        # ==================== ОЦЕНКИ ====================

        elif data == "admin_ratings":
            await admin_show_ratings(query)

        # ==================== РАССЫЛКА ====================

        elif data == "admin_broadcast_menu":
            await admin_broadcast_menu(query)

        elif data == "admin_broadcast_start":
            await admin_broadcast_start(query)

        elif data == "admin_broadcast_confirm":
            await admin_broadcast_confirm(query, context)

        elif data == "admin_broadcast_cancel":
            admin_state.pop(ADMIN_ID, None)
            await admin_broadcast_menu(query)

        # ==================== НАСТРОЙКИ ====================

        elif data == "admin_settings_menu":
            await admin_settings_menu(query)

        elif data == "admin_backup":
            await admin_create_backup(query, context)

        elif data == "admin_restore":
            await admin_restore_backup(query)

    except Exception as e:
        logger.error(f"Ошибка в admin_callback: {e}", exc_info=True)
        try:
            keyboard = [[InlineKeyboardButton("🏠 На главную", callback_data="admin_back")]]
            await query.edit_message_text(
                "❌ Произошла ошибка. Попробуйте ещё раз.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            pass


# ==================== 📊 СТАТИСТИКА ====================

async def admin_stats_menu(query) -> None:
    """Меню статистики — выбор периода"""
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊  *СТАТИСТИКА*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите период для просмотра\n"
        "детальной статистики:"
    )

    keyboard = [
        [InlineKeyboardButton("📅 За сегодня", callback_data="admin_analytics_1")],
        [InlineKeyboardButton("📅 За неделю", callback_data="admin_analytics_7")],
        [InlineKeyboardButton("📅 За месяц", callback_data="admin_analytics_30")],
        [InlineKeyboardButton("📅 За всё время", callback_data="admin_analytics_365")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_analytics(query, days: int) -> None:
    """Показать аналитику за период"""
    analytics = db.get_analytics(days=days)

    period_names = {1: "сегодня", 7: "неделю", 30: "месяц", 365: "всё время"}
    period_name = period_names.get(days, f"{days} дней")

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊  *СТАТИСТИКА ЗА {period_name.upper()}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 *Заявки:*\n"
        f"   За период: *{analytics.get('period_requests', 0)}*\n"
        f"   Всего в системе: *{analytics.get('total_requests', 0)}*\n\n"
    )

    # Статусы
    status = analytics.get("status_counts", {})
    text += (
        f"📌 *По статусам:*\n"
        f"   🆕 Новых: *{status.get('новая', 0)}*\n"
        f"   🔄 В работе: *{status.get('в работе', 0)}*\n"
        f"   ✅ Выполнено: *{status.get('выполнена', 0)}*\n\n"
    )

    # Типы заявок
    type_counts = analytics.get("type_counts", {})
    if type_counts:
        text += "📋 *Типы заявок:*\n"
        sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        for t_name, t_count in sorted_types[:5]:
            bar = "█" * min(t_count, 15)
            text += f"   {t_name}: *{t_count}* {bar}\n"
        text += "\n"

    # Юристы
    text += (
        f"👥 *Юристы:*\n"
        f"   Всего: *{analytics.get('total_lawyers', 0)}*\n"
        f"   Активных: *{analytics.get('active_lawyers', 0)}*\n"
        f"   Заблокировано: *{analytics.get('blocked_lawyers', 0)}*\n"
        f"   Самый активный: *{analytics.get('most_active_lawyer', '—')}*\n\n"
    )

    # Оценки
    text += (
        f"⭐ *Оценки:*\n"
        f"   Средняя: *{analytics.get('overall_avg_rating', 0)}/5*\n"
        f"   Всего оценок: *{analytics.get('total_ratings', 0)}*\n\n"
    )

    # Заявки по дням
    daily = analytics.get("daily_counts", {})
    if daily:
        text += "📅 *По дням (последние 7):*\n"
        sorted_days = sorted(daily.items())[-7:]
        for day, count in sorted_days:
            bar = "█" * min(count, 10)
            text += f"   {day}: *{count}* {bar}\n"
        text += "\n"

    keyboard = [
        [
            InlineKeyboardButton("📅 День", callback_data="admin_analytics_1"),
            InlineKeyboardButton("📅 Неделя", callback_data="admin_analytics_7"),
        ],
        [
            InlineKeyboardButton("📅 Месяц", callback_data="admin_analytics_30"),
            InlineKeyboardButton("📅 Всё", callback_data="admin_analytics_365"),
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== 👨‍⚖️ ЮРИСТЫ ====================

async def admin_lawyers_menu(query) -> None:
    """Меню управления юристами"""
    analytics = db.get_analytics(days=365)

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍⚖️  *ЮРИСТЫ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"   👥 Всего: *{analytics.get('total_lawyers', 0)}*\n"
        f"   ✅ Активных: *{analytics.get('active_lawyers', 0)}*\n"
        f"   ⛔ Заблокировано: *{analytics.get('blocked_lawyers', 0)}*\n"
        f"   🏆 Лучший: *{analytics.get('most_active_lawyer', '—')}*\n\n"
        "Выберите действие:"
    )

    keyboard = [
        [InlineKeyboardButton("📋 Список юристов", callback_data="admin_manage_lawyers")],
        [InlineKeyboardButton("🏆 Рейтинг юристов", callback_data="admin_lawyer_ranking")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_lawyer_ranking(query) -> None:
    """Показать рейтинг юристов"""
    analytics = db.get_analytics(days=365)
    rankings = analytics.get("lawyer_rankings", [])

    if not rankings:
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_lawyers_menu")],
        ]
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🏆  *РЕЙТИНГ ЮРИСТОВ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 Юристы ещё не зарегистрированы.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏆  *РЕЙТИНГ ЮРИСТОВ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, stats in enumerate(rankings[:10]):
        medal = medals[i] if i < 3 else f"  {i+1}."
        name = stats.get("full_name", "—")
        completed = stats.get("completed", 0)
        avg_rating = stats.get("avg_rating", 0)
        blocked = " ⛔" if stats.get("blocked", False) else ""

        rating_str = f"⭐{avg_rating}" if avg_rating > 0 else "—"

        text += (
            f"{medal} *{name}*{blocked}\n"
            f"      ✅ {completed} выполн. | {rating_str}\n\n"
        )

    keyboard = [
        [InlineKeyboardButton("📋 Управление юристами", callback_data="admin_manage_lawyers")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_lawyers_menu")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_manage_lawyers(query) -> None:
    """Список юристов для управления"""
    lawyers = db.get_all_lawyers()

    if not lawyers:
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_lawyers_menu")],
        ]
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📋  *СПИСОК ЮРИСТОВ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 Юристы ещё не зарегистрированы.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋  *СПИСОК ЮРИСТОВ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

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
        text += f"      ⚖️ {spec} | ✅ {completed} {rating_str}\n\n"

        keyboard.append([
            InlineKeyboardButton(
                f"{'⛔' if blocked else '👤'} {name[:25]}",
                callback_data=f"admin_lawyer_detail_{tid}"
            ),
        ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_lawyers_menu")])

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
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👤  *ПРОФИЛЬ ЮРИСТА*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
        f"   Всего взято: *{stats.get('total_taken', 0)}*\n"
        f"   В работе: *{stats.get('in_progress', 0)}*\n"
        f"   Выполнено: *{stats.get('completed', 0)}*\n"
        f"   Средняя оценка: {rating_text}\n"
        f"   Среднее время: *{time_text}*\n"
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
    keyboard.append([InlineKeyboardButton("🏠 На главную", callback_data="admin_back")])

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
        "✏️ Напишите причину блокировки текстовым сообщением:",
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
        "✏️ Напишите текст сообщения:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== 📋 ЗАЯВКИ ====================

async def admin_requests_menu(query) -> None:
    """Меню заявок"""
    analytics = db.get_analytics(days=30)
    status = analytics.get("status_counts", {})

    new_count = status.get("новая", 0)
    in_progress = status.get("в работе", 0)
    completed = status.get("выполнена", 0)
    total = analytics.get("total_requests", 0)

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋  *ЗАЯВКИ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"   📋 Всего: *{total}*\n"
        f"   🆕 Новых: *{new_count}*\n"
        f"   🔄 В работе: *{in_progress}*\n"
        f"   ✅ Выполнено: *{completed}*\n\n"
        "Выберите фильтр:"
    )

    keyboard = [
        [InlineKeyboardButton(f"🆕 Новые ({new_count})", callback_data="admin_filter_new")],
        [InlineKeyboardButton(f"🔄 В работе ({in_progress})", callback_data="admin_filter_progress")],
        [InlineKeyboardButton(f"✅ Выполненные ({completed})", callback_data="admin_filter_done")],
        [InlineKeyboardButton(f"📋 Все заявки ({total})", callback_data="admin_all_requests")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_show_requests(query, status_filter: Optional[str] = None) -> None:
    """Показать заявки с фильтром"""
    all_requests = db.get_all_requests()

    if status_filter:
        filtered = [r for r in all_requests if r.get("status") == status_filter]
        title = {
            "новая": "🆕 НОВЫЕ ЗАЯВКИ",
            "в работе": "🔄 ЗАЯВКИ В РАБОТЕ",
            "выполнена": "✅ ВЫПОЛНЕННЫЕ ЗАЯВКИ",
        }.get(status_filter, "📋 ЗАЯВКИ")
    else:
        filtered = all_requests
        title = "📋 ВСЕ ЗАЯВКИ"

    if not filtered:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_requests_menu")]]
        await query.edit_message_text(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*{title}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📭 Заявок не найдено.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Показываем последние 10
    recent = filtered[:10]

    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*{title}* ({len(filtered)})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    keyboard = []

    for req in recent:
        req_id = req.get("id", "?")
        status_emoji = {"новая": "🆕", "в работе": "🔄", "выполнена": "✅"}.get(req.get("status"), "❓")
        client = req.get("client_name", "—")[:15]
        req_type = req.get("type", "—")[:12]
        date = req.get("date", "—")
        lawyer = req.get("lawyer_name", "—")[:15] if req.get("lawyer_name") else "—"
        rating = f" ⭐{req.get('rating')}" if req.get("rating") else ""

        text += f"{status_emoji} *{req_id}* | {date}\n"
        text += f"      👤 {client} | 📋 {req_type}\n"
        text += f"      👨‍⚖️ {lawyer}{rating}\n\n"

        keyboard.append([
            InlineKeyboardButton(f"📋 {req_id}", callback_data=f"admin_req_{req_id}")
        ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_requests_menu")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_request_detail(query, request_id: str) -> None:
    """Детали заявки для админа"""
    req = db.get_request_by_id(request_id)

    if not req:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_requests_menu")]]
        await query.edit_message_text(
            "⚠️ Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    status_emoji = {"новая": "🆕", "в работе": "🔄", "выполнена": "✅"}.get(req.get("status"), "❓")

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋  *ЗАЯВКА {request_id}* {status_emoji}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Дата: {req.get('date', '—')}\n"
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
    keyboard.append([InlineKeyboardButton("🔙 К заявкам", callback_data="admin_requests_menu")])
    keyboard.append([InlineKeyboardButton("🏠 На главную", callback_data="admin_back")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== ⭐ ОЦЕНКИ ====================

async def admin_show_ratings(query) -> None:
    """Показать последние оценки клиентов"""
    all_requests = db.get_all_requests()
    rated = [r for r in all_requests if r.get("rating") is not None]
    rated.sort(key=lambda x: x.get("rating_date", ""), reverse=True)

    if not rated:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⭐  *ОЦЕНКИ КЛИЕНТОВ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 Оценок пока нет.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⭐  *ОЦЕНКИ КЛИЕНТОВ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Распределение оценок
    rating_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in rated:
        rating = r.get("rating", 0)
        if rating in rating_dist:
            rating_dist[rating] += 1

    text += "📊 *Распределение:*\n"
    total_rated = len(rated)
    for stars_count in range(5, 0, -1):
        count = rating_dist[stars_count]
        pct = round(count / total_rated * 100) if total_rated > 0 else 0
        bar = "█" * (pct // 5) if pct > 0 else ""
        text += f"   {'⭐' * stars_count}: *{count}* ({pct}%) {bar}\n"

    avg = sum(r.get("rating", 0) for r in rated) / len(rated) if rated else 0
    text += f"\n📈 Средняя оценка: *{round(avg, 1)}/5*\n\n"

    # Последние 8 оценок
    text += "📝 *Последние оценки:*\n\n"
    for r in rated[:8]:
        req_id = r.get("id", "?")
        stars_str = "⭐" * r.get("rating", 0)
        lawyer = r.get("lawyer_name", "—")[:15]
        client = r.get("client_name", "—")[:15]
        comment = r.get("rating_comment", "")
        comment_text = f"\n      💬 {comment[:50]}..." if comment else ""

        text += f"{stars_str} *{req_id}*\n"
        text += f"      👤 {client} → 👨‍⚖️ {lawyer}{comment_text}\n\n"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== 📨 РАССЫЛКА ====================

async def admin_broadcast_menu(query) -> None:
    """Меню рассылки"""
    lawyers = db.get_active_lawyers()

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📨  *РАССЫЛКА*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Активных юристов: *{len(lawyers)}*\n\n"
        "Отправьте сообщение всем активным\n"
        "юристам одним нажатием."
    )

    keyboard = [
        [InlineKeyboardButton("✏️ Написать сообщение", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_broadcast_start(query) -> None:
    """Начать рассылку — ожидаем текст"""
    admin_state[ADMIN_ID] = {
        "action": "broadcast",
        "step": "waiting_text"
    }

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="admin_broadcast_cancel")]]

    await query.edit_message_text(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📨  *РАССЫЛКА — НОВОЕ СООБЩЕНИЕ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✏️ Напишите текст сообщения для\n"
        "рассылки всем юристам.\n\n"
        "Отправьте текст обычным сообщением:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_broadcast_confirm(query, context) -> None:
    """Подтвердить и отправить рассылку"""
    state = admin_state.get(ADMIN_ID)
    if not state or state.get("action") != "broadcast" or not state.get("text"):
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_broadcast_menu")]]
        await query.edit_message_text(
            "⚠️ Текст рассылки не найден. Начните заново.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    broadcast_text = state["text"]
    lawyers = db.get_active_lawyers()

    sent = 0
    failed = 0

    for lawyer in lawyers:
        try:
            await context.bot.send_message(
                chat_id=lawyer["telegram_id"],
                text=f"📩 *Сообщение от администрации Визирь:*\n\n{broadcast_text}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки юристу {lawyer.get('telegram_id')}: {e}")
            failed += 1

    admin_state.pop(ADMIN_ID, None)

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]]

    await query.edit_message_text(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📨  *РАССЫЛКА ЗАВЕРШЕНА*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Доставлено: *{sent}*\n"
        f"❌ Ошибок: *{failed}*\n"
        f"📊 Всего юристов: *{len(lawyers)}*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== ⚙️ НАСТРОЙКИ ====================

async def admin_settings_menu(query) -> None:
    """Меню настроек"""
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️  *НАСТРОЙКИ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Управление данными и\n"
        "резервными копиями:"
    )

    keyboard = [
        [InlineKeyboardButton("💾 Создать бэкап", callback_data="admin_backup")],
        [InlineKeyboardButton("📥 Восстановить из бэкапа", callback_data="admin_restore")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== РЕЗЕРВНОЕ КОПИРОВАНИЕ ====================

async def admin_create_backup(query, context) -> None:
    """Создать и отправить резервную копию"""
    try:
        await query.answer("💾 Создание резервной копии...", show_alert=False)
    except Exception:
        pass

    try:
        backup_file = db.create_backup()

        if backup_file:
            with open(backup_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=query.from_user.id,
                    document=f,
                    filename=f"vizir_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    caption="💾 *Резервная копия данных Визирь*\n\n"
                            "Файл содержит все данные: заявки, юристы, оценки.",
                    parse_mode=ParseMode.MARKDOWN
                )

            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_settings_menu")]]
            await query.edit_message_text(
                "✅ *Резервная копия создана!*\n\n"
                "Файл отправлен в чат.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_settings_menu")]]
            await query.edit_message_text(
                "❌ Ошибка при создании резервной копии.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Ошибка при создании бэкапа: {e}")
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_settings_menu")]]
        try:
            await query.edit_message_text(
                "❌ Ошибка при создании бэкапа.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            pass


async def admin_restore_backup(query) -> None:
    """Начать процесс восстановления из бэкапа"""
    admin_state[ADMIN_ID] = {"action": "restore_backup"}

    keyboard = [
        [InlineKeyboardButton("❌ Отмена", callback_data="admin_settings_menu")],
    ]

    await query.edit_message_text(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📥  *ВОССТАНОВЛЕНИЕ ДАННЫХ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ *Внимание!* Эта операция заменит\n"
        "все текущие данные.\n\n"
        "📄 Отправьте JSON-файл резервной копии:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ АДМИНА ====================

async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений и файлов от админа"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        # Не админ — обрабатываем как обычное сообщение юриста
        try:
            from bot import handle_message
            await handle_message(update, context)
        except Exception:
            pass
        return

    # Обработка загрузки файла для восстановления
    if update.message and update.message.document:
        state = admin_state.get(ADMIN_ID)
        if state and state.get("action") == "restore_backup":
            try:
                file = await context.bot.get_file(update.message.document.file_id)
                file_data = await file.download_as_bytearray()
                backup_data = json.loads(file_data.decode('utf-8'))

                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
                    json.dump(backup_data, tmp)
                    tmp_path = tmp.name

                success = db.restore_from_backup(tmp_path)

                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

                if success:
                    await update.message.reply_text(
                        "✅ *Данные успешно восстановлены!*\n\n"
                        "Все заявки, юристы и оценки загружены.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text(
                        "❌ Ошибка при восстановлении данных.\n"
                        "Проверьте формат файла.",
                        parse_mode=ParseMode.MARKDOWN
                    )

                admin_state.pop(ADMIN_ID, None)
                return

            except Exception as e:
                logger.error(f"Ошибка при восстановлении из файла: {e}")
                await update.message.reply_text(
                    f"❌ Ошибка при обработке файла: {str(e)[:100]}",
                    parse_mode=ParseMode.MARKDOWN
                )
                admin_state.pop(ADMIN_ID, None)
                return

    # Обработка текстовых сообщений
    if not update.message or not update.message.text:
        return

    state = admin_state.get(ADMIN_ID)
    if not state:
        # Нет активного действия — показываем подсказку
        await update.message.reply_text(
            "Используйте /admin для открытия панели администратора."
        )
        return

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

            admin_state.pop(ADMIN_ID, None)

        elif action == "block_lawyer":
            # Блокировка юриста
            lawyer_id = state.get("lawyer_id")
            lawyer_name = state.get("lawyer_name", "—")

            success = db.block_lawyer(lawyer_id, reason=message_text)

            if success:
                try:
                    await context.bot.send_message(
                        chat_id=lawyer_id,
                        text=f"⛔ *Ваш аккаунт заблокирован*\n\n"
                             f"Причина: {message_text}\n\n"
                             "Для разблокировки обратитесь к администратору.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить юриста {lawyer_id} о блокировке: {e}")

                await update.message.reply_text(
                    f"⛔ Юрист *{lawyer_name}* заблокирован.\n"
                    f"Причина: {message_text}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"❌ Не удалось заблокировать юриста {lawyer_name}."
                )

            admin_state.pop(ADMIN_ID, None)

        elif action == "broadcast":
            # Рассылка — сохраняем текст и просим подтвердить
            admin_state[ADMIN_ID] = {
                "action": "broadcast",
                "step": "confirm",
                "text": message_text
            }

            lawyers = db.get_active_lawyers()

            keyboard = [
                [InlineKeyboardButton("✅ Отправить", callback_data="admin_broadcast_confirm")],
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_broadcast_cancel")],
            ]

            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📨  *ПОДТВЕРЖДЕНИЕ РАССЫЛКИ*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝 *Текст:*\n{message_text}\n\n"
                f"👥 Получателей: *{len(lawyers)}* юристов\n\n"
                "Подтвердите отправку:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Ошибка в admin_message_handler: {e}")
        admin_state.pop(ADMIN_ID, None)
        await update.message.reply_text(
            "❌ Произошла ошибка. Нажмите /admin"
        )
