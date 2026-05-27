FROM python:3.11-alpine

RUN adduser -D -u 1000 ctf && \
    pip install --no-cache-dir pillow

WORKDIR /app

# Copy challenge files from source repo (copied by build script before docker build)
COPY listener.py .
COPY agadir_tifo_challenge.png .
COPY entrypoint.sh .

USER root
RUN chmod +x entrypoint.sh
USER 1000

EXPOSE 1337

ENTRYPOINT ["./entrypoint.sh"]
