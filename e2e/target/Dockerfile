# Tiny stdlib-only controlled target for the e2e stack (no dependencies).
FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
EXPOSE 8080
CMD ["python", "server.py"]
