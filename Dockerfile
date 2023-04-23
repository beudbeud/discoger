FROM alpine:3.17

LABEL maintainer="beudbeud@beudibox.fr"

RUN apk update && apk add build-base python3 py3-pip

COPY . /src

WORKDIR /src

RUN pip install .

ENTRYPOINT ["discoger"]
