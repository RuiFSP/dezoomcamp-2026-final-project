FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Install Bruin CLI so pipeline trigger can be enabled when desired.
RUN curl -LsSf https://getbruin.com/install/cli | sh \
    && cp /root/.local/bin/bruin /usr/local/bin/bruin

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project --extra streamlit

COPY streamlit_app /app/streamlit_app
COPY bruin /app/bruin
COPY src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    BRUIN_DIR=/app/bruin \
    GCP_PROJECT_ID=gh-dezoomcamp \
    BQ_DATASET=gh_analytics \
    ENABLE_PIPELINE_TRIGGER=false

EXPOSE 8080

CMD ["streamlit", "run", "streamlit_app/app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
