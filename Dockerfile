FROM python:3.12.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY config ./config
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
