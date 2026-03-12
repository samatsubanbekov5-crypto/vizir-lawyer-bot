FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание директории для данных
RUN mkdir -p /data

# Переменные окружения по умолчанию
ENV PORT=8000
ENV DATA_DIR=/data

# Запуск приложения (PORT подставляется из переменной окружения)
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
