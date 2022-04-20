FROM python:3.10-alpine3.15 AS base

ENV PATH /app/.local/bin:$PATH
RUN adduser -DSh /app -u 1000 app
WORKDIR /app

COPY --chown=1000:1000 setup.cfg pyproject.toml requirements.txt LICENSE ./
COPY --chown=1000:1000 fc2_live_dl fc2_live_dl

RUN set -eux; \
    apk add --no-cache ffmpeg; \
    apk add --no-cache --virtual .build-deps \
        gcc g++ make libffi-dev; \
    su app -s /bin/sh -c 'pip install --no-cache --user .'; \
    apk del --purge .build-deps; \
    rm -rf /var/cache/apk/*;

USER app
CMD ["/app/.local/bin/fc2-live-dl"]
