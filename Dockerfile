# Base image
FROM ubuntu:24.04

# Information
LABEL maintainer="Slow Ninja <info@slow.ninja>"

# Variables
ENV DEBIAN_FRONTEND=noninteractive \
      NETWORK_VERSION="100b"

# Install packages
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
        git \
        curl \
        wget \
        golang \
        nodejs \
        npm \
        &&  \
    rm -rf /var/lib/apt/lists/*

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
    mkdir /var/structs/accounts

COPY config/client.toml /var/structs/chain/config/client.toml

ENV PATH="$PATH:/var/structs/bin"


RUN git clone https://github.com/playstructs/structs-sign-proxy.git && \
    cd structs-sign-proxy && \
    npm install -g . && \
    cd ..



# Building latest structsd
RUN git clone https://github.com/playstructs/structsd.git && \
    cd structsd && \
    ignite chain build

# Run Structs
CMD [ "/src/structs/manager.sh" ]
