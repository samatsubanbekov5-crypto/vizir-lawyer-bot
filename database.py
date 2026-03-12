#!/usr/bin/env python3
"""
Модуль работы с базой данных SQLite для бота юристов сервиса "Визирь"
С резервным копированием в JSON и восстановлением
"""

import sqlite3
import json
import os
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import shutil

logger = logging.getLogger(__name__)

# Пути к файлам
DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_FILE = os.path.join(DATA_DIR, "vizir.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
LATEST_BACKUP = os.path.join(BACKUP_DIR, "latest_backup.json")

# Блокировка для потокобезопасности
_lock = threading.Lock()

# Подключение к БД (thread-local)
_thread_local = threading.local()


def _ensure_dirs():
    """Создать необходимые директории"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
    except Exception as e:
        logger.error(f"Ошибка при создании директорий: {e}")


def _get_db() -> sqlite3.Connection:
    """Получить подключение к БД (thread-safe)"""
    if not hasattr(_thread_local, 'db') or _thread_local.db is None:
        _ensure_dirs()
        _thread_local.db = sqlite3.connect(DB_FILE, check_same_thread=False)
        _thread_local.db.row_factory = sqlite3.Row
        _thread_local.db.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging для надёжности
    return _thread_local.db


def init_db():
    """Инициализировать базу данных"""
    try:
        db = _get_db()
        cursor = db.cursor()

        # Таблица заявок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                client_id INTEGER,
                client_name TEXT,
                client_username TEXT,
                description TEXT,
                type TEXT,
                status TEXT DEFAULT 'новая',
                date TEXT,
                lawyer_id INTEGER,
                lawyer_name TEXT,
                assigned_date TEXT,
                completed_date TEXT,
                rating INTEGER,
                rating_comment TEXT,
                rating_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица юристов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lawyers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                specialization TEXT,
                contact TEXT,
                registration_date TEXT,
                requests_count INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                block_reason TEXT,
                block_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица оценок (для быстрого доступа)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT UNIQUE,
                lawyer_id INTEGER,
                lawyer_name TEXT,
                client_name TEXT,
                rating INTEGER,
                comment TEXT,
                date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES requests(id),
                FOREIGN KEY (lawyer_id) REFERENCES lawyers(telegram_id)
            )
        """)

        # Индексы для оптимизации
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_lawyer ON requests(lawyer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_date ON requests(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lawyers_blocked ON lawyers(blocked)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ratings_lawyer ON ratings(lawyer_id)")

        db.commit()
        logger.info("База данных инициализирована успешно")

    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")
        raise


def create_backup() -> str:
    """
    Создать JSON-бэкап всех данных
    Возвращает путь к файлу бэкапа
    """
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            # Получаем все данные
            cursor.execute("SELECT * FROM requests")
            requests = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM lawyers")
            lawyers = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM ratings")
            ratings = [dict(row) for row in cursor.fetchall()]

            backup_data = {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0",
                "requests": requests,
                "lawyers": lawyers,
                "ratings": ratings,
            }

            # Сохраняем в файл с временной меткой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(BACKUP_DIR, f"backup_{timestamp}.json")

            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)

            # Также сохраняем как "latest"
            with open(LATEST_BACKUP, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)

            logger.info(f"Бэкап создан: {backup_file}")
            return backup_file

    except Exception as e:
        logger.error(f"Ошибка при создании бэкапа: {e}")
        return None


def restore_from_backup(backup_file: Optional[str] = None) -> bool:
    """
    Восстановить данные из JSON-бэкапа
    Если backup_file не указан, используется latest_backup.json
    """
    try:
        if backup_file is None:
            backup_file = LATEST_BACKUP

        if not os.path.exists(backup_file):
            logger.error(f"Файл бэкапа не найден: {backup_file}")
            return False

        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        with _lock:
            db = _get_db()
            cursor = db.cursor()

            # Очищаем таблицы
            cursor.execute("DELETE FROM ratings")
            cursor.execute("DELETE FROM requests")
            cursor.execute("DELETE FROM lawyers")

            # Восстанавливаем юристов
            for lawyer in backup_data.get("lawyers", []):
                cursor.execute("""
                    INSERT INTO lawyers (
                        telegram_id, username, full_name, specialization, contact,
                        registration_date, requests_count, completed_count, blocked,
                        block_reason, block_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lawyer.get("telegram_id"),
                    lawyer.get("username"),
                    lawyer.get("full_name"),
                    lawyer.get("specialization"),
                    lawyer.get("contact"),
                    lawyer.get("registration_date"),
                    lawyer.get("requests_count", 0),
                    lawyer.get("completed_count", 0),
                    1 if lawyer.get("blocked", False) else 0,
                    lawyer.get("block_reason"),
                    lawyer.get("block_date"),
                ))

            # Восстанавливаем заявки
            for req in backup_data.get("requests", []):
                cursor.execute("""
                    INSERT INTO requests (
                        id, client_id, client_name, client_username, description, type,
                        status, date, lawyer_id, lawyer_name, assigned_date, completed_date,
                        rating, rating_comment, rating_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.get("id"),
                    req.get("client_id"),
                    req.get("client_name"),
                    req.get("client_username"),
                    req.get("description"),
                    req.get("type"),
                    req.get("status", "новая"),
                    req.get("date"),
                    req.get("lawyer_id"),
                    req.get("lawyer_name"),
                    req.get("assigned_date"),
                    req.get("completed_date"),
                    req.get("rating"),
                    req.get("rating_comment"),
                    req.get("rating_date"),
                ))

            # Восстанавливаем оценки
            for rating in backup_data.get("ratings", []):
                cursor.execute("""
                    INSERT INTO ratings (
                        request_id, lawyer_id, lawyer_name, client_name, rating, comment, date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rating.get("request_id"),
                    rating.get("lawyer_id"),
                    rating.get("lawyer_name"),
                    rating.get("client_name"),
                    rating.get("rating"),
                    rating.get("comment"),
                    rating.get("date"),
                ))

            db.commit()
            logger.info(f"Данные восстановлены из {backup_file}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при восстановлении из бэкапа: {e}")
        return False


def get_backup_for_download() -> Optional[bytes]:
    """Получить последний бэкап в виде байтов для скачивания"""
    try:
        if os.path.exists(LATEST_BACKUP):
            with open(LATEST_BACKUP, 'rb') as f:
                return f.read()
        return None
    except Exception as e:
        logger.error(f"Ошибка при чтении бэкапа для скачивания: {e}")
        return None


# ==================== ЗАЯВКИ ====================

def get_all_requests() -> List[Dict[str, Any]]:
    """Получить все заявки"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM requests ORDER BY date DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении заявок: {e}")
        return []


def get_request_by_id(request_id: str) -> Optional[Dict[str, Any]]:
    """Получить заявку по ID"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Ошибка при получении заявки {request_id}: {e}")
        return None


def get_new_requests() -> List[Dict[str, Any]]:
    """Получить все новые (необработанные) заявки"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM requests WHERE status = 'новая' ORDER BY date DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении новых заявок: {e}")
        return []


def get_requests_by_status(status: str) -> List[Dict[str, Any]]:
    """Получить заявки по статусу"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM requests WHERE status = ? ORDER BY date DESC", (status,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении заявок со статусом {status}: {e}")
        return []


def get_requests_by_lawyer(lawyer_id: int) -> List[Dict[str, Any]]:
    """Получить заявки, закреплённые за юристом"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM requests WHERE lawyer_id = ? ORDER BY date DESC", (lawyer_id,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении заявок юриста {lawyer_id}: {e}")
        return []


def get_requests_by_period(days: int = 30) -> List[Dict[str, Any]]:
    """Получить заявки за указанный период (дни)"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
            cursor.execute("SELECT * FROM requests WHERE date >= ? ORDER BY date DESC", (cutoff,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении заявок за период: {e}")
        return []


def get_requests_by_type(req_type: str) -> List[Dict[str, Any]]:
    """Получить заявки по типу"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM requests WHERE type = ? ORDER BY date DESC", (req_type,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении заявок типа {req_type}: {e}")
        return []


def add_request(request_data: Dict[str, Any]) -> str:
    """
    Добавить новую заявку
    Возвращает ID заявки
    """
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            # Генерация ID
            cursor.execute("SELECT MAX(CAST(SUBSTR(id, 4) AS INTEGER)) FROM requests WHERE id LIKE 'VZ-%'")
            result = cursor.fetchone()
            max_num = result[0] if result and result[0] else 0
            request_id = f"VZ-{max_num + 1}"

            # Подготовка данных
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            request_data["id"] = request_id
            request_data.setdefault("status", "новая")
            request_data.setdefault("date", now)
            request_data.setdefault("lawyer_id", None)
            request_data.setdefault("lawyer_name", None)
            request_data.setdefault("assigned_date", None)
            request_data.setdefault("completed_date", None)
            request_data.setdefault("rating", None)
            request_data.setdefault("rating_comment", None)

            cursor.execute("""
                INSERT INTO requests (
                    id, client_id, client_name, client_username, description, type,
                    status, date, lawyer_id, lawyer_name, assigned_date, completed_date,
                    rating, rating_comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id,
                request_data.get("client_id"),
                request_data.get("client_name"),
                request_data.get("client_username"),
                request_data.get("description"),
                request_data.get("type"),
                request_data.get("status"),
                request_data.get("date"),
                request_data.get("lawyer_id"),
                request_data.get("lawyer_name"),
                request_data.get("assigned_date"),
                request_data.get("completed_date"),
                request_data.get("rating"),
                request_data.get("rating_comment"),
            ))

            db.commit()
            logger.info(f"Добавлена заявка {request_id}")

            # Автоматический бэкап
            create_backup()

            return request_id

    except Exception as e:
        logger.error(f"Ошибка при добавлении заявки: {e}")
        return ""


def assign_request(request_id: str, lawyer_id: int, lawyer_name: str) -> bool:
    """Закрепить заявку за юристом"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            cursor.execute("SELECT status FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            if not row or row[0] != "новая":
                return False

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("""
                UPDATE requests
                SET status = 'в работе', lawyer_id = ?, lawyer_name = ?, assigned_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (lawyer_id, lawyer_name, now, request_id))

            db.commit()
            logger.info(f"Заявка {request_id} закреплена за юристом {lawyer_name}")

            # Бэкап
            create_backup()

            return True

    except Exception as e:
        logger.error(f"Ошибка при закреплении заявки: {e}")
        return False


def complete_request(request_id: str, lawyer_id: int) -> bool:
    """Отметить заявку как выполненную"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            cursor.execute("SELECT status, lawyer_id FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            if not row or row[0] != "в работе" or row[1] != lawyer_id:
                return False

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("""
                UPDATE requests
                SET status = 'выполнена', completed_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (now, request_id))

            db.commit()
            logger.info(f"Заявка {request_id} отмечена как выполненная")

            # Бэкап
            create_backup()

            return True

    except Exception as e:
        logger.error(f"Ошибка при завершении заявки: {e}")
        return False


def rate_request(request_id: str, rating: int, comment: str = None) -> bool:
    """Добавить оценку к заявке (от клиента)"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            # Обновляем заявку
            cursor.execute("""
                UPDATE requests
                SET rating = ?, rating_comment = ?, rating_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rating, comment, now, request_id))

            # Получаем информацию о заявке для таблицы оценок
            cursor.execute("SELECT lawyer_id, lawyer_name, client_name FROM requests WHERE id = ?", (request_id,))
            req_row = cursor.fetchone()

            if req_row:
                cursor.execute("""
                    INSERT OR REPLACE INTO ratings (request_id, lawyer_id, lawyer_name, client_name, rating, comment, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (request_id, req_row[0], req_row[1], req_row[2], rating, comment, now))

            db.commit()
            logger.info(f"Заявка {request_id} оценена на {rating}/5")

            # Бэкап
            create_backup()

            return True

    except Exception as e:
        logger.error(f"Ошибка при добавлении оценки: {e}")
        return False


# ==================== ЮРИСТЫ ====================

def get_all_lawyers() -> List[Dict[str, Any]]:
    """Получить всех зарегистрированных юристов"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM lawyers ORDER BY registration_date DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении юристов: {e}")
        return []


def get_active_lawyers() -> List[Dict[str, Any]]:
    """Получить всех активных (не заблокированных) юристов"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM lawyers WHERE blocked = 0 ORDER BY registration_date DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Ошибка при получении активных юристов: {e}")
        return []


def get_lawyer_by_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Получить юриста по Telegram ID"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()
            cursor.execute("SELECT * FROM lawyers WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Ошибка при получении юриста {telegram_id}: {e}")
        return None


def register_lawyer(lawyer_data: Dict[str, Any]) -> bool:
    """Зарегистрировать нового юриста"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            # Проверка что юрист ещё не зарегистрирован
            cursor.execute("SELECT telegram_id FROM lawyers WHERE telegram_id = ?", (lawyer_data.get("telegram_id"),))
            if cursor.fetchone():
                return False

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            lawyer_data.setdefault("registration_date", now)
            lawyer_data.setdefault("requests_count", 0)
            lawyer_data.setdefault("completed_count", 0)
            lawyer_data.setdefault("blocked", 0)

            cursor.execute("""
                INSERT INTO lawyers (
                    telegram_id, username, full_name, specialization, contact,
                    registration_date, requests_count, completed_count, blocked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lawyer_data.get("telegram_id"),
                lawyer_data.get("username"),
                lawyer_data.get("full_name"),
                lawyer_data.get("specialization"),
                lawyer_data.get("contact"),
                lawyer_data.get("registration_date"),
                lawyer_data.get("requests_count", 0),
                lawyer_data.get("completed_count", 0),
                1 if lawyer_data.get("blocked", False) else 0,
            ))

            db.commit()
            logger.info(f"Зарегистрирован юрист: {lawyer_data.get('full_name')}")

            # Бэкап
            create_backup()

            return True

    except Exception as e:
        logger.error(f"Ошибка при регистрации юриста: {e}")
        return False


def update_lawyer_stats(telegram_id: int, field: str = "requests_count"):
    """Увеличить счётчик юриста"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            if field == "requests_count":
                cursor.execute(
                    "UPDATE lawyers SET requests_count = requests_count + 1, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                    (telegram_id,)
                )
            elif field == "completed_count":
                cursor.execute(
                    "UPDATE lawyers SET completed_count = completed_count + 1, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                    (telegram_id,)
                )

            db.commit()

    except Exception as e:
        logger.error(f"Ошибка при обновлении статистики юриста: {e}")


def block_lawyer(telegram_id: int, reason: str = None) -> bool:
    """Заблокировать юриста"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("""
                UPDATE lawyers
                SET blocked = 1, block_reason = ?, block_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (reason, now, telegram_id))

            db.commit()
            logger.info(f"Юрист {telegram_id} заблокирован: {reason}")

            # Бэкап
            create_backup()

            return True

    except Exception as e:
        logger.error(f"Ошибка при блокировке юриста: {e}")
        return False


def unblock_lawyer(telegram_id: int) -> bool:
    """Разблокировать юриста"""
    try:
        with _lock:
            db = _get_db()
            cursor = db.cursor()

            cursor.execute("""
                UPDATE lawyers
                SET blocked = 0, block_reason = NULL, block_date = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (telegram_id,))

            db.commit()
            logger.info(f"Юрист {telegram_id} разблокирован")

            # Бэкап
            create_backup()

            return True

    except Exception as e:
        logger.error(f"Ошибка при разблокировке юриста: {e}")
        return False


def get_lawyer_stats(telegram_id: int) -> Dict[str, Any]:
    """Получить подробную статистику юриста"""
    try:
        lawyer = get_lawyer_by_id(telegram_id)
        if not lawyer:
            return {}

        requests = get_requests_by_lawyer(telegram_id)
        in_progress = [r for r in requests if r.get("status") == "в работе"]
        completed = [r for r in requests if r.get("status") == "выполнена"]

        # Средняя оценка
        ratings = [r.get("rating") for r in completed if r.get("rating") is not None]
        avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0

        # Среднее время выполнения (в часах)
        completion_times = []
        for r in completed:
            try:
                assigned = datetime.strptime(r.get("assigned_date", ""), "%Y-%m-%d %H:%M")
                done = datetime.strptime(r.get("completed_date", ""), "%Y-%m-%d %H:%M")
                hours = (done - assigned).total_seconds() / 3600
                completion_times.append(hours)
            except (ValueError, TypeError):
                pass
        avg_time = round(sum(completion_times) / len(completion_times), 1) if completion_times else 0.0

        return {
            "full_name": lawyer.get("full_name", "—"),
            "specialization": lawyer.get("specialization", "—"),
            "contact": lawyer.get("contact", "—"),
            "registration_date": lawyer.get("registration_date", "—"),
            "blocked": bool(lawyer.get("blocked", 0)),
            "total_taken": len(requests),
            "in_progress": len(in_progress),
            "completed": len(completed),
            "avg_rating": avg_rating,
            "ratings_count": len(ratings),
            "avg_completion_hours": avg_time,
        }

    except Exception as e:
        logger.error(f"Ошибка при получении статистики юриста: {e}")
        return {}


# ==================== АНАЛИТИКА (для админ-панели) ====================

def get_analytics(days: int = 30) -> Dict[str, Any]:
    """Получить аналитику за указанный период"""
    try:
        all_requests = get_all_requests()
        period_requests = get_requests_by_period(days)
        all_lawyers = get_all_lawyers()

        # Заявки по статусам
        status_counts = {}
        for r in all_requests:
            status = r.get("status", "неизвестно")
            status_counts[status] = status_counts.get(status, 0) + 1

        # Заявки по типам
        type_counts = {}
        for r in period_requests:
            req_type = r.get("type", "неизвестно")
            type_counts[req_type] = type_counts.get(req_type, 0) + 1

        # Самый популярный тип
        most_popular_type = max(type_counts, key=type_counts.get) if type_counts else "—"

        # Рейтинг юристов
        lawyer_rankings = []
        for lawyer in all_lawyers:
            stats = get_lawyer_stats(lawyer.get("telegram_id"))
            if stats:
                lawyer_rankings.append(stats)

        # Сортировка по количеству выполненных заявок
        lawyer_rankings.sort(key=lambda x: x.get("completed", 0), reverse=True)

        # Самый активный юрист
        most_active = lawyer_rankings[0]["full_name"] if lawyer_rankings else "—"

        # Заявки по дням (для графика)
        daily_counts = {}
        for r in period_requests:
            try:
                day = r.get("date", "")[:10]
                daily_counts[day] = daily_counts.get(day, 0) + 1
            except (ValueError, TypeError):
                pass

        # Средняя оценка по всем юристам
        all_ratings = []
        for r in all_requests:
            if r.get("rating") is not None:
                all_ratings.append(r["rating"])
        overall_avg_rating = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 0.0

        return {
            "period_days": days,
            "total_requests": len(all_requests),
            "period_requests": len(period_requests),
            "status_counts": status_counts,
            "type_counts": type_counts,
            "most_popular_type": most_popular_type,
            "total_lawyers": len(all_lawyers),
            "active_lawyers": len([l for l in all_lawyers if not l.get("blocked", 0)]),
            "blocked_lawyers": len([l for l in all_lawyers if l.get("blocked", 0)]),
            "lawyer_rankings": lawyer_rankings,
            "most_active_lawyer": most_active,
            "daily_counts": daily_counts,
            "overall_avg_rating": overall_avg_rating,
            "total_ratings": len(all_ratings),
        }

    except Exception as e:
        logger.error(f"Ошибка при получении аналитики: {e}")
        return {}
