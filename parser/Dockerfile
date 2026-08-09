FROM ghcr.io/domainaware/parsedmarc:10.4.0@sha256:314afe30059030c1af20e10bf7051a816b16d00b309b5b799b189b0fc3aad65f

USER root
COPY supervisor.py /usr/local/lib/parsedmarc-supervisor.py
COPY base.ini /etc/parsedmarc/base.ini
RUN chmod 0555 /usr/local/lib/parsedmarc-supervisor.py \
    && chmod 0444 /etc/parsedmarc/base.ini

USER parsedmarc

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import os; pid=int(open('/tmp/parsedmarc.pid').read()); os.kill(pid, 0)"]

ENTRYPOINT ["python", "/usr/local/lib/parsedmarc-supervisor.py"]
