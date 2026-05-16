FROM alpine:3.21

COPY deploy/downloads/cleaner.sh /usr/local/bin/download-cleaner.sh

RUN chmod +x /usr/local/bin/download-cleaner.sh

ENTRYPOINT ["/bin/sh", "/usr/local/bin/download-cleaner.sh"]
