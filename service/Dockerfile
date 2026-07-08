FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-optional.txt ./

# Core dependencies must install (pure-Python, wheels everywhere).
RUN pip install --no-cache-dir -r requirements.txt

# Optional/hardware dependencies are best-effort: prefer a prebuilt wheel and
# never fail the image build (or an on-device update) when one is unavailable on
# this architecture. Each degrades gracefully at runtime. Installed one at a time
# so one bad package does not stop the rest.
RUN set -eu; \
    while IFS= read -r pkg; do \
      case "$pkg" in ''|\#*) continue ;; esac; \
      pip install --no-cache-dir --prefer-binary --only-binary=:all: "$pkg" \
        || pip install --no-cache-dir --prefer-binary "$pkg" \
        || echo "AutoPi: optional dependency not installed on this platform: $pkg"; \
    done < requirements-optional.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
