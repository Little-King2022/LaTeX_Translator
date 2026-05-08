# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        latexmk \
        texlive-xetex \
        texlive-latex-extra \
        texlive-publishers \
        texlive-fonts-recommended \
        texlive-science \
        texlive-lang-chinese \
        texlive-plain-generic \
        zip \
        unzip

COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

COPY app /app/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
