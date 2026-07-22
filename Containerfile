FROM docker.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip

COPY pyproject.toml README.md ./
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY sql ./sql
COPY src ./src

RUN python -m pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "rural_basic_income.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
