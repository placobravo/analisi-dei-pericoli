FROM docker.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY manage.py .
COPY config/ config/
COPY portal/ portal/
RUN PORTALE_SECRET_KEY=collectstatic-build-only python manage.py collectstatic --noinput \
    && useradd --uid 10001 --user-group --no-create-home portale

USER portale
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "config.wsgi:application"]
