FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# LibreOffice + wkhtmltopdf are used by the CO-PO Word/PDF export
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-core wkhtmltopdf \
        fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt openpyxl

COPY . .
RUN mkdir -p /app/output

EXPOSE 5000

# create_all() only creates missing tables (safe if the dump already made them)
CMD ["sh", "-c", "python -c \"from app import app, db; ctx = app.app_context(); ctx.push(); db.create_all()\" && flask --app app run --host 0.0.0.0 --port 5000"]