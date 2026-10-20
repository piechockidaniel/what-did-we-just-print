FROM node:22-alpine AS frontend
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PRINT_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY vision ./vision
COPY tests ./tests
COPY scripts ./scripts
COPY --from=frontend /web/dist ./dist
RUN useradd --uid 10001 --create-home printapp && mkdir -p /data && chown printapp:printapp /data
USER printapp
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
