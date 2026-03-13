#!/usr/bin/env python3
"""
FastAPI приложение для бота юристов сервиса "Визирь"
Webhook для получения обновлений от Telegram
API эндпоинты для взаимодействия с ботом клиентов
"""

import os
import re
import logging
import json
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

import database as db

# Telegram
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)
from telegram.constants import ParseMode

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
LAWYER_BOT_TOKEN = clean_env_var(os.getenv("LAWYER_BOT_TOKEN", ""))
LAWYER_WEBHOOK_URL = clean_env_var(os.getenv("LAWYER_WEBHOOK_URL", ""))
# Автоформирование webhook URL если не задан вручную
if not LAWYER_WEBHOOK_URL:
    _render_url = clean_env_var(os.getenv("RENDER_EXTERNAL_URL", ""))
    if _render_url:
        LAWYER_WEBHOOK_URL = f"{_render_url}/webhook"
    else:
        LAWYER_WEBHOOK_URL = "https://vizir-lawyer-bot.onrender.com/webhook"
CLIENT_BOT_URL = clean_env_var(os.getenv("CLIENT_BOT_URL", ""))
CLIENT_BOT_TOKEN = clean_env_var(os.getenv("CLIENT_BOT_TOKEN", ""))
ADMIN_ID = int(os.getenv("ADMIN_ID", "7728619214"))
PORT = int(os.getenv("PORT", "8000"))

logger.info(f"LAWYER_BOT_TOKEN: {'задан' if LAWYER_BOT_TOKEN else 'НЕ ЗАДАН'}")
logger.info(f"LAWYER_WEBHOOK_URL: '{LAWYER_WEBHOOK_URL}'")
logger.info(f"CLIENT_BOT_URL: '{CLIENT_BOT_URL}'")
logger.info(f"CLIENT_BOT_TOKEN: {'задан' if CLIENT_BOT_TOKEN else 'НЕ ЗАДАН'}")
logger.info(f"ADMIN_ID: {ADMIN_ID}")

# Глобальное приложение Telegram
telegram_app: Application = None


# ==================== LIFESPAN ====================

@asynccontextmanager
async def lifespan(app):
    """Управление жизненным циклом приложения"""
    global telegram_app

    logger.info("🚀 Запуск бота юристов...")

    # Инициализируем БД
    try:
        db.init_db()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

    # Создаём Telegram Application
    try:
        from bot import (
            start, reg_name, reg_spec_callback, reg_spec_text, reg_contact,
            cancel_registration, help_command, menu_command, stats_command,
            button_callback, handle_message,
            REG_NAME, REG_SPEC, REG_CONTACT,
        )
        from admin import admin_command, admin_callback, admin_message_handler

        telegram_app = Application.builder().token(LAWYER_BOT_TOKEN).build()

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

        telegram_app.add_handler(reg_handler)

        # Команды
        telegram_app.add_handler(CommandHandler("help", help_command))
        telegram_app.add_handler(CommandHandler("menu", menu_command))
        telegram_app.add_handler(CommandHandler("stats", stats_command))
        telegram_app.add_handler(CommandHandler("admin", admin_command))

        # Callback кнопки — сначала админские, потом основные
        telegram_app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
        telegram_app.add_handler(CallbackQueryHandler(button_callback))

        # Файлы (для восстановления из бэкапа)
        telegram_app.add_handler(MessageHandler(filters.Document.ALL, admin_message_handler))

        # Текстовые сообщения (для админ-панели и прочего)
        telegram_app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_message_handler
        ))

        # Инициализируем приложение
        await telegram_app.initialize()

        logger.info("✅ Telegram Application создано и обработчики зарегистрированы")

        # Устанавливаем webhook
        if LAWYER_WEBHOOK_URL:
            try:
                await telegram_app.bot.set_webhook(
                    url=LAWYER_WEBHOOK_URL,
                    allowed_updates=["message", "callback_query"],
                    drop_pending_updates=True,
                )
                webhook_info = await telegram_app.bot.get_webhook_info()
                logger.info(f"✅ Webhook установлен: {webhook_info.url}")
            except Exception as e:
                logger.error(f"❌ Ошибка при установке webhook: {e}")
        else:
            logger.warning("⚠️ LAWYER_WEBHOOK_URL не задан — webhook не установлен")

        # Запускаем обработку
        await telegram_app.start()
        logger.info("✅ Бот юристов готов к работе!")

    except Exception as e:
        logger.error(f"❌ Ошибка при создании Telegram Application: {e}", exc_info=True)

    yield

    # Shutdown
    logger.info("🛑 Завершение работы бота юристов...")
    if telegram_app:
        try:
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception as e:
            logger.error(f"Ошибка при остановке: {e}")
    logger.info("✅ Бот юристов остановлен")


# Инициализация FastAPI
app = FastAPI(title="Визирь - Бот для юристов", lifespan=lifespan)


# ==================== WEBHOOK ====================

@app.post("/webhook")
async def webhook(request: Request):
    """Получить обновление от Telegram"""
    global telegram_app

    if not telegram_app:
        logger.error("Telegram app не инициализирован")
        return {"ok": False, "error": "Not initialized"}

    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)

        if update:
            await telegram_app.process_update(update)

        return {"ok": True}

    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


# ==================== HEALTH & STATUS ====================

@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "service": "vizir-lawyer-bot",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health():
    """Проверка здоровья"""
    return {
        "status": "ok",
        "service": "vizir-lawyer-bot",
        "bot_initialized": telegram_app is not None,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/health")
async def api_health():
    """API проверка здоровья"""
    return {
        "status": "ok",
        "service": "vizir-lawyer-bot",
        "bot_initialized": telegram_app is not None,
        "timestamp": datetime.now().isoformat()
    }


# ==================== BACKUP API ====================

@app.get("/api/backup")
async def get_backup():
    """Скачать JSON-бэкап всех данных"""
    try:
        backup_file = db.create_backup()
        if not backup_file:
            raise HTTPException(status_code=500, detail="Failed to create backup")

        backup_data = db.get_backup_for_download()
        if not backup_data:
            raise HTTPException(status_code=404, detail="Backup not found")

        return JSONResponse(
            content=json.loads(backup_data.decode('utf-8')),
            media_type="application/json"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при скачивании бэкапа: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backup/create")
async def create_backup_api():
    """Создать новый бэкап"""
    try:
        backup_file = db.create_backup()
        if backup_file:
            return {
                "status": "ok",
                "file": backup_file,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create backup")
    except Exception as e:
        logger.error(f"Ошибка при создании бэкапа: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== API ДЛЯ СВЯЗИ С БОТОМ КЛИЕНТОВ ====================

@app.post("/api/notify_new_request")
async def notify_new_request(request: Request):
    """
    Получить уведомление о новой заявке от бота клиентов.
    Сохранить заявку в БД и уведомить юристов.
    """
    global telegram_app

    try:
        data = await request.json()

        # Сохраняем заявку в БД
        request_data = {
            "client_id": data.get("client_id"),
            "client_name": data.get("client_name"),
            "client_username": data.get("client_username"),
            "description": data.get("description"),
            "type": data.get("type"),
        }

        request_id = db.add_request(request_data)

        if not request_id:
            raise HTTPException(status_code=500, detail="Failed to save request")

        logger.info(f"✅ Заявка {request_id} сохранена в БД")

        # Получаем активных юристов
        active_lawyers = db.get_active_lawyers()

        if not active_lawyers:
            logger.warning("⚠️ Нет активных юристов для уведомления")
            return {
                "status": "ok",
                "request_id": request_id,
                "notified": 0,
                "message": "No active lawyers available"
            }

        if not telegram_app:
            logger.warning("⚠️ Telegram app не инициализирован — уведомления не отправлены")
            return {
                "status": "ok",
                "request_id": request_id,
                "notified": 0,
                "message": "Bot not initialized"
            }

        # Формируем уведомление
        notification_text = (
            f"🔔 *Новая заявка!*\n\n"
            f"📌 *{request_id}*\n"
            f"👤 Клиент: {data.get('client_name', '—')}\n"
            f"📱 Username: @{data.get('client_username', '—')}\n"
            f"📋 Тип: {data.get('type', '—')}\n\n"
            f"💬 *Описание:*\n{data.get('description', '—')[:200]}\n\n"
            f"Нажмите кнопку, чтобы взять заявку:"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Взять заявку", callback_data=f"take_{request_id}")],
            [InlineKeyboardButton("📋 Подробнее", callback_data=f"detail_{request_id}")],
        ])

        # Отправляем уведомления юристам
        notified_count = 0
        for lawyer in active_lawyers:
            try:
                lawyer_id = lawyer.get("telegram_id")
                await telegram_app.bot.send_message(
                    chat_id=lawyer_id,
                    text=notification_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
                notified_count += 1
                logger.info(f"✅ Уведомление отправлено юристу {lawyer_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления юристу {lawyer.get('telegram_id')}: {e}")

        # Уведомляем админа
        try:
            admin_text = (
                f"📋 *Новая заявка в системе*\n\n"
                f"ID: *{request_id}*\n"
                f"Клиент: {data.get('client_name', '—')}\n"
                f"Тип: {data.get('type', '—')}\n"
                f"Юристов уведомлено: *{notified_count}*"
            )
            await telegram_app.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка при уведомлении админа: {e}")

        return {
            "status": "ok",
            "request_id": request_id,
            "notified": notified_count,
            "message": f"Request saved and {notified_count} lawyers notified"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка в notify_new_request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/request_rated")
async def request_rated(request: Request):
    """Получить оценку от клиента и сохранить"""
    global telegram_app

    try:
        data = await request.json()
        request_id = data.get("request_id")
        rating = data.get("rating")
        comment = data.get("comment", "")

        if not request_id or not rating:
            raise HTTPException(status_code=400, detail="request_id and rating required")

        # Сохраняем оценку
        success = db.rate_request(request_id, rating, comment)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to save rating")

        # Получаем информацию о заявке
        req = db.get_request_by_id(request_id)

        if req and req.get("lawyer_id") and telegram_app:
            # Отправляем уведомление юристу об оценке
            try:
                lawyer_id = req["lawyer_id"]
                stars = "⭐" * rating

                rating_text = (
                    f"{stars} *Вашу работу оценили!*\n\n"
                    f"Оценка: {rating}/5\n"
                    f"Заявка: {request_id}"
                )

                if comment:
                    rating_text += f"\n💬 Комментарий: {comment}"

                await telegram_app.bot.send_message(
                    chat_id=lawyer_id,
                    text=rating_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"✅ Уведомление об оценке отправлено юристу {lawyer_id}")

            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления об оценке юристу: {e}")

        # Уведомляем админа
        if telegram_app:
            try:
                admin_text = (
                    f"⭐ *Новая оценка*\n\n"
                    f"Заявка: {request_id}\n"
                    f"Юрист: {req.get('lawyer_name', '—') if req else '—'}\n"
                    f"Оценка: {rating}/5"
                )
                if comment:
                    admin_text += f"\n💬 Комментарий: {comment}"

                await telegram_app.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_text,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Ошибка при уведомлении админа об оценке: {e}")

        return {
            "status": "ok",
            "request_id": request_id,
            "rating": rating,
            "message": "Rating saved successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка в request_rated: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/notify_client")
async def notify_client_endpoint(request: Request):
    """
    Эндпоинт-заглушка для обратной связи.
    Реальное уведомление клиента идёт через бот клиентов.
    Этот эндпоинт вызывается из bot.py при взятии/выполнении заявки.
    """
    try:
        data = await request.json()
        event = data.get("event")
        client_id = data.get("client_id")
        request_id = data.get("request_id")
        lawyer_name = data.get("lawyer_name", "Специалист")

        logger.info(f"Событие {event} для клиента {client_id}, заявка {request_id}")

        # Если есть токен клиентского бота — отправляем уведомление напрямую
        if CLIENT_BOT_TOKEN and client_id:
            try:
                client_bot = Bot(token=CLIENT_BOT_TOKEN)

                if event == "request_taken":
                    text = (
                        f"📋 *Обновление по вашей заявке*\n\n"
                        f"Юрист *{lawyer_name}* взял вашу заявку в работу.\n"
                        f"Ожидайте — специалист свяжется с вами в ближайшее время."
                    )
                    await client_bot.send_message(
                        chat_id=client_id,
                        text=text,
                        parse_mode=ParseMode.MARKDOWN
                    )

                elif event == "request_completed":
                    # Отправляем запрос на оценку
                    text = (
                        f"✅ *Ваша заявка выполнена!*\n\n"
                        f"👨‍⚖️ Юрист: {lawyer_name}\n\n"
                        f"Пожалуйста, оцените качество консультации:"
                    )
                    keyboard = [
                        [
                            InlineKeyboardButton("1⭐", callback_data=f"rate_{request_id}_1"),
                            InlineKeyboardButton("2⭐", callback_data=f"rate_{request_id}_2"),
                            InlineKeyboardButton("3⭐", callback_data=f"rate_{request_id}_3"),
                        ],
                        [
                            InlineKeyboardButton("4⭐", callback_data=f"rate_{request_id}_4"),
                            InlineKeyboardButton("5⭐", callback_data=f"rate_{request_id}_5"),
                        ],
                    ]
                    await client_bot.send_message(
                        chat_id=client_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.MARKDOWN
                    )

                logger.info(f"✅ Уведомление клиенту {client_id} отправлено ({event})")
                return {"status": "ok", "message": f"Client notified: {event}"}

            except Exception as e:
                logger.error(f"Ошибка при уведомлении клиента через CLIENT_BOT_TOKEN: {e}")
                return {"status": "error", "message": str(e)}

        # Если нет токена — пробуем через API клиентского бота
        elif CLIENT_BOT_URL and event == "request_completed":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{CLIENT_BOT_URL}/api/request_completed",
                        json={
                            "client_id": client_id,
                            "request_id": request_id,
                            "lawyer_name": lawyer_name
                        }
                    )
                    if resp.status_code == 200:
                        logger.info(f"✅ Уведомление отправлено через API клиентского бота")
                        return {"status": "ok"}
                    else:
                        logger.warning(f"⚠️ Ответ клиентского бота: {resp.status_code}")
                        return {"status": "warning", "message": f"Client bot returned {resp.status_code}"}
            except Exception as e:
                logger.error(f"Ошибка при вызове API клиентского бота: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "ok", "message": "No client notification method available"}

    except Exception as e:
        logger.error(f"Ошибка в notify_client: {e}")
        return {"status": "error", "message": str(e)}


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    import uvicorn

    logger.info(f"Запуск приложения на порту {PORT}")
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info"
    )
