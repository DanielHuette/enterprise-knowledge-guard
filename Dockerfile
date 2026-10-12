# API service and test runner, built from locked dependencies.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD python -c "import sys, urllib.request; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "knowledge_guard.api:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS test

ENV PYTEST_ADDOPTS="-p no:cacheprovider"
USER root
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
COPY scripts ./scripts
USER app

CMD ["pytest", "tests"]
