FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces menjalankan container sebagai user 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
RUN mkdir -p outputs temp data _INBOX_TRANSKRIP

ENV PORT=7860
EXPOSE 7860
# Secret (GROQ_API_KEY, GEMINI_API_KEY, CREATOR_PASSWORD) diisi lewat Settings > Secrets di Space
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
