FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CLOAKBROWSER_BINARY_PATH=/opt/cloakbrowser/chrome
ENV PORT=3000

WORKDIR /app

COPY cloakbrowser/common/install_cloakbrowser.py /tmp/install_cloakbrowser.py
COPY pricebuddy-scraper-cloakbrowser/app.py /app/app.py

RUN pip install --no-cache-dir beautifulsoup4 cloakbrowser flask gunicorn     && python -m playwright install-deps chromium     && python /tmp/install_cloakbrowser.py     && python -m py_compile /app/app.py

EXPOSE 3000

CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
