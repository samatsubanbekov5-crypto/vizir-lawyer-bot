#!/usr/bin/env python3
"""
FastAPI приложение для бота юристов сервиса "Визирь"
Webhook для получения обновлений от Telegram
API эндпоинты для взаимодействия с ботом клиентов
"""

import os
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import json
from datetime import datetime
import asyncio

# Импорт модулей бота
import database as db
from bot import handle_message, handle_callback
from admin import admin_callback, admin_command, admin_message_handler, is_admin

# Telegram
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Переменные окружения
LAWYER_BOT_TOKEN = os.getenv("LAWYER_BOT_TOKEN", "")
LAWYER_WEBHOOK_URL = os.getenv("LAWYER_WEBHOOK_URL", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7728619214"))

# Инициализация FastAPI
app = FastAPI(title="Визирь - Бот для юристов")

# Инициализация Telegram Bot
bot = Bot(token=LAWYER_BOT_TOKEN)

# Глобальное приложение для обработчиков
application = None


async def init_app():
    """Инициализировать приложение"""
    global application
    
    # Инициализируем БД
    db.init_db()
    logger.info("✅ База данных инициализирована")
    
    # Создаём приложение
    application = Application.builder().token(LAWYER_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    # Команды
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("admin", admin_command))
    
    # Текстовые сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Файлы (для восстановления из бэкапа)
    application.add_handler(MessageHandler(filters.Document.ALL, admin_message_handler))
    
    # Callback кнопки
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("✅ Обработчики зарегистрированы")
    
    # Устанавливаем webhook
    try:
        await application.bot.set_webhook(
            url=LAWYER_WEBHOOK_URL,
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"✅ Webhook установлен: {LAWYER_WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ Ошибка при установке webhook: {e}")


# ==================== WEBHOOK ====================

@app.post("/webhook")
async def webhook(request: Request):
    """Получить обновление от Telegram"""
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        
        if update:
            # Обрабатываем обновление
            await application.process_update(update)
        
        return {"ok": True}
    
    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}")
        return {"ok": False, "error": str(e)}


# ==================== API ЭНДПОИНТЫ ====================

@app.get("/api/health")
async def health_check():
    """Проверка здоровья приложения"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "vizir-lawyer-bot"
    }


@app.get("/api/backup")
async def get_backup():
    """Скачать JSON-бэкап всех данных"""
    try:
        backup_data = db.get_backup_for_download()
        
        if not backup_data:
            raise HTTPException(status_code=404, detail="Backup not found")
        
        return FileResponse(
            content=backup_data,
            media_type="application/json",
            filename=f"vizir_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
    
    except Exception as e:
        logger.error(f"Ошибка при скачивании бэкапа: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backup/create")
async def create_backup():
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


@app.post("/api/backup/restore")
async def restore_backup(request: Request):
    """Восстановить данные из бэкапа"""
    try:
        data = await request.json()
        backup_file = data.get("file")
        
        if not backup_file:
            raise HTTPException(status_code=400, detail="Backup file path required")
        
        success = db.restore_from_backup(backup_file)
        
        if success:
            return {
                "status": "ok",
                "message": "Data restored successfully",
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to restore backup")
    
    except Exception as e:
        logger.error(f"Ошибка при восстановлении бэкапа: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== API ДЛЯ СВЯЗИ С БОТОМ КЛИЕНТОВ ====================

@app.post("/api/notify_new_request")
async def notify_new_request(request: Request):
    """
    Получить уведомление о новой заявке от бота клиентов
    Отправить уведомления активным юристам
    """
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
        
        # Получаем активных юристов
        active_lawyers = db.get_active_lawyers()
        
        if not active_lawyers:
            logger.warning("Нет активных юристов для уведомления")
            return {
                "status": "ok",
                "request_id": request_id,
                "notified": 0,
                "message": "No active lawyers available"
            }
        
        # Отправляем уведомления юристам
        notified_count = 0
        
        for lawyer in active_lawyers:
            try:
                lawyer_id = lawyer.get("telegram_id")
                
                notification_text = (
                    f"🆕 *Новая заявка!*\n\n"
                    f"📋 ID: *{request_id}*\n"
                    f"👤 Клиент: {data.get('client_name', '—')}\n"
                    f"📱 Username: @{data.get('client_username', '—')}\n"
                    f"📌 Тип: {data.get('type', '—')}\n\n"
                    f"📝 *Описание:*\n{data.get('description', '—')}\n\n"
                    f"Нажмите /requests для просмотра"
                )
                
                await bot.send_message(
                    chat_id=lawyer_id,
                    text=notification_text,
                    parse_mode="Markdown"
                )
                
                notified_count += 1
                logger.info(f"✅ Уведомление отправлено юристу {lawyer_id}")
            
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления юристу {lawyer.get('telegram_id')}: {e}")
        
        # Отправляем уведомление админу
        try:
            admin_text = (
                f"📋 *Новая заявка в системе*\n\n"
                f"ID: *{request_id}*\n"
                f"Клиент: {data.get('client_name', '—')}\n"
                f"Тип: {data.get('type', '—')}\n"
                f"Юристов уведомлено: *{notified_count}*"
            )
            
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу: {e}")
        
        return {
            "status": "ok",
            "request_id": request_id,
            "notified": notified_count,
            "message": f"Request saved and {notified_count} lawyers notified"
        }
    
    except Exception as e:
        logger.error(f"Ошибка в notify_new_request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/request_completed")
async def request_completed(request: Request):
    """
    Получить уведомление о завершении заявки от юриста
    Отправить запрос на оценку клиенту
    """
    try:
        data = await request.json()
        request_id = data.get("request_id")
        lawyer_id = data.get("lawyer_id")
        
        if not request_id or not lawyer_id:
            raise HTTPException(status_code=400, detail="request_id and lawyer_id required")
        
        # Отмечаем заявку как выполненную
        success = db.complete_request(request_id, lawyer_id)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to mark request as completed")
        
        # Получаем информацию о заявке
        req = db.get_request_by_id(request_id)
        
        if req and req.get("client_id"):
            # Отправляем запрос на оценку клиенту
            try:
                client_id = req["client_id"]
                client_bot_token = os.getenv("CLIENT_BOT_TOKEN", "")
                client_bot = Bot(token=client_bot_token)
                
                rating_text = (
                    f"✅ *Ваша заявка выполнена!*\n\n"
                    f"📋 ID: *{request_id}*\n"
                    f"👨‍⚖️ Юрист: {req.get('lawyer_name', '—')}\n\n"
                    f"Пожалуйста, оцените качество консультации (1-5 звёзд):\n"
                    f"/rate_1 ⭐\n"
                    f"/rate_2 ⭐⭐\n"
                    f"/rate_3 ⭐⭐⭐\n"
                    f"/rate_4 ⭐⭐⭐⭐\n"
                    f"/rate_5 ⭐⭐⭐⭐⭐"
                )
                
                await client_bot.send_message(
                    chat_id=client_id,
                    text=rating_text,
                    parse_mode="Markdown"
                )
                
                logger.info(f"✅ Запрос на оценку отправлен клиенту {client_id}")
            
            except Exception as e:
                logger.error(f"Ошибка при отправке запроса на оценку: {e}")
        
        return {
            "status": "ok",
            "request_id": request_id,
            "message": "Request marked as completed"
        }
    
    except Exception as e:
        logger.error(f"Ошибка в request_completed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/request_rated")
async def request_rated(request: Request):
    """Получить оценку от клиента и сохранить"""
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
        
        if req and req.get("lawyer_id"):
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
                
                await bot.send_message(
                    chat_id=lawyer_id,
                    text=rating_text,
                    parse_mode="Markdown"
                )
                
                logger.info(f"✅ Уведомление об оценке отправлено юристу {lawyer_id}")
            
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления об оценке: {e}")
        
        # Отправляем уведомление админу
        try:
            admin_text = (
                f"⭐ *Новая оценка*\n\n"
                f"Заявка: {request_id}\n"
                f"Юрист: {req.get('lawyer_name', '—')}\n"
                f"Оценка: {rating}/5"
            )
            
            if comment:
                admin_text += f"\n💬 Комментарий: {comment}"
            
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу об оценке: {e}")
        
        return {
            "status": "ok",
            "request_id": request_id,
            "rating": rating,
            "message": "Rating saved successfully"
        }
    
    except Exception as e:
        logger.error(f"Ошибка в request_rated: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ЗАПУСК ====================

@app.on_event("startup")
async def startup():
    """Инициализация при запуске"""
    logger.info("🚀 Запуск бота юристов...")
    await init_app()
    logger.info("✅ Бот юристов готов к работе")


@app.on_event("shutdown")
async def shutdown():
    """Очистка при завершении"""
    logger.info("🛑 Завершение работы бота юристов...")
    if application:
        await application.stop()


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )
