# Standard library only, so there is nothing to install.
FROM python:3.12-alpine

WORKDIR /app
COPY config.py alert_format.py email_sender.py main.py ./

USER nobody
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/', timeout=3)"

CMD ["python", "-u", "main.py"]
