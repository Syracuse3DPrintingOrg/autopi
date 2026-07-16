FROM python:3.11-slim

WORKDIR /app

# fswebcam grabs a single JPEG from a USB camera for the on-device vision
# reference. Small and optional: the app degrades gracefully without it, but
# shipping it means a camera plugged into the device works with no extra setup
# beyond granting the container access to it (see docker-compose.yml). Kept in
# its own layer with recommends off so the image stays lean. Best-effort: a
# flaky apt mirror must never fail the whole image build (and so an on-device
# update), exactly like the optional Python dependencies below.
RUN (apt-get update \
      && apt-get install -y --no-install-recommends fswebcam \
      && rm -rf /var/lib/apt/lists/*) \
    || echo "AutoPi: fswebcam not installed (apt unavailable on this build); on-device camera capture stays off until it is present"

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
