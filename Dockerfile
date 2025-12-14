FROM ubuntu:24.04

LABEL maintainer="beudbeud@beudibox.fr"

RUN apt update && apt install python3 lynx ca-certificates python3-pip -y

COPY . /src

WORKDIR /src

RUN pip install -r requirements.txt --break-system-packages

RUN pip install . --break-system-packages

ENTRYPOINT ["discoger"]
