FROM alpine:3.17

LABEL maintainer="beudbeud@beudibox.fr"

RUN apk update && apk add build-base python3 libxml2-dev libxslt-dev python3-dev

COPY . /src

WORKDIR /src

RUN pip3 install --upgrade pip

RUN pip3 install .

ENTRYPOINT ["discoger"]
