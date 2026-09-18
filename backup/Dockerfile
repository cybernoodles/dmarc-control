FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 dmarcbackup \
    && useradd --uid 10001 --gid dmarcbackup --create-home --home-dir /home/dmarcbackup dmarcbackup \
    && pip install --no-cache-dir cryptography==49.0.0

COPY --chmod=0555 backup.py /usr/local/bin/dmarc-backup

USER dmarcbackup

ENTRYPOINT ["/usr/local/bin/dmarc-backup"]
CMD ["daemon"]
