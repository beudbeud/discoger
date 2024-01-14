FROM alpine:3.17

LABEL maintainer="beudbeud@beudibox.fr"

RUN apk update && apk add build-base python3 py3-pip lynx

COPY . /src

WORKDIR /src

RUN pip install -r requirements.txt

RUN pip install .

ENTRYPOINT ["discoger"]
