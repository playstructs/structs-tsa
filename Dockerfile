# Base image
FROM ubuntu:24.04

# Information
LABEL maintainer="Slow Ninja <info@slow.ninja>"

# Variables
ENV DEBIAN_FRONTEND=noninteractive \
      NETWORK_VERSION="102b" \
      AGENT_TARGET_NUMBER=20

# Install packages
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
        postgresql-common \
        git \
        curl \
        wget \
        golang \
        nodejs \
        npm \
        jq



RUN  sed -i "s/read enter//g" /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
RUN  cat /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh && \
     /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh && \
     apt-get -y install postgresql-client


RUN  rm -rf /var/lib/apt/lists/*

ENV PATH=$PATH:/usr/local/go/bin

# Put this file into place so that the ignite command does not
# get stuck waiting for input
RUN mkdir /root/.ignite
COPY config/anon_identity.json /root/.ignite/anon_identity.json

# Install ignite
RUN curl https://get.ignite.com/cli! | bash

# Add the user and groups appropriately
RUN addgroup --system structs && \
    adduser --system --home /src/structs --shell /bin/bash --group structs


# Setup the scripts
WORKDIR /src
RUN chown -R structs /src/structs
COPY scripts/* /src/structs/
RUN chmod a+x /src/structs/*

RUN mkdir /var/structs && \
    mkdir /var/structs/bin && \
    mkdir /var/structs/chain && \
    mkdir /var/structs/accounts && \
    mkdir /var/structs/tsa && \
    mkdir /var/structs/tsa/tmp && \
    mkdir /root/.structs && \
    mkdir /root/.structs/config && \
    ln -s /var/structs/accounts /root/.structs/keyring-test

COPY config/client.toml /var/structs/chain/config/client.toml
COPY config/client.toml /root/.structs/config/client.toml

ENV PATH="$PATH:/var/structs/bin"

RUN git clone https://github.com/playstructs/structs-sign-proxy.git && \
    cd structs-sign-proxy && \
    npm install -g . && \
    cd ..


# Building latest structsd
RUN git clone https://github.com/playstructs/structsd.git && \
    cd structsd && \
    ignite chain build

RUN mkdir -p /usr/local/go/bin && \
    cp /root/go/bin/structsd /usr/local/go/bin/structsd

# Run Structs
CMD [ "/src/structs/tsa.sh" ]
