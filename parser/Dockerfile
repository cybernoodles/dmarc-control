FROM ghcr.io/domainaware/parsedmarc:11.0.2@sha256:33b704262fbd171b9462c2a66d51e44c761da02ffe65279d4fb9d85bab14f927

USER root
COPY supervisor.py /usr/local/lib/parsedmarc-supervisor.py
COPY base.ini /etc/parsedmarc/base.ini
RUN chmod 0555 /usr/local/lib/parsedmarc-supervisor.py \
    && chmod 0444 /etc/parsedmarc/base.ini

USER parsedmarc

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import os; pid=int(open('/tmp/parsedmarc.pid').read()); os.kill(pid, 0)"]

ENTRYPOINT ["python", "/usr/local/lib/parsedmarc-supervisor.py"]
