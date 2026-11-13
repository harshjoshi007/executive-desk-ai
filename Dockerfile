FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 EDA_DB_PATH=/app/data/executive_desk.db
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY web/ ./web/
COPY manage.py ./manage.py
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
