FROM python:3.12-slim

LABEL maintainer="beudbeud@beudibox.fr"

COPY . /src

WORKDIR /src

RUN pip install --no-cache-dir .

ENTRYPOINT ["discoger"]
