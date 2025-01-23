#!/usr/bin/env bash


# $1 is Guild ID
GUILD_ID=$1
# $2 is Player ID
PLAYER_ID=$2
# Create a player
echo "Initializing test player role..."

echo "Generating Mnemonic"
TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
MNEMONIC=$(structsd keys add "$TEMP_NAME" | jq -r ".mnemonic")
echo "${MNEMONIC}"


# Get the address of what was just added
ACCOUNT_ADDRESS=$(structsd keys show "$TEMP_NAME" | jq -r ".address" )
echo "${ACCOUNT_ADDRESS}"


# Guild Join Message
echo ""
echo "Creating Guild Proxy Join Message/Signature>"
SIGNED_PROXY_JSON=$(structs-sign-proxy guild-join ${GUILD_ID} 0 "$MNEMONIC")
SIGNED_PROXY_PUBKEY=$( echo ${SIGNED_PROXY_JSON} | jq -r ".pubkey" )
SIGNED_PROXY_SIGNATURE=$( echo ${SIGNED_PROXY_JSON} | jq -r ".signature" )
SIGNED_PROXY_MESSAGE=$( echo ${SIGNED_PROXY_JSON} | jq -r ".message" )
echo "${SIGNED_PROXY_MESSAGE}"
echo "[Address] [PubKey] [Signature]"
echo "${ACCOUNT_ADDRESS} ${SIGNED_PROXY_PUBKEY} ${SIGNED_PROXY_SIGNATURE}"
echo "JSON Format"
echo "${SIGNED_PROXY_JSON}"

echo ""
echo "Creating Address Register Message/Signature"

SIGNED_ADDRESS_REGISTER_JSON=$(structs-sign-proxy address-register ${PLAYER_ID} "$MNEMONIC")
SIGNED_ADDRESS_REGISTER_PUBKEY=$( echo ${SIGNED_ADDRESS_REGISTER_JSON} | jq -r ".pubkey" )
SIGNED_ADDRESS_REGISTER_SIGNATURE=$( echo ${SIGNED_ADDRESS_REGISTER_JSON} | jq -r ".signature" )
SIGNED_ADDRESS_REGISTER_MESSAGE=$( echo ${SIGNED_ADDRESS_REGISTER_JSON} | jq -r ".message" )

echo "${SIGNED_ADDRESS_REGISTER_MESSAGE}"
echo "[Address] [PubKey] [Signature]"
echo "${ACCOUNT_ADDRESS} ${SIGNED_ADDRESS_REGISTER_PUBKEY} ${SIGNED_ADDRESS_REGISTER_SIGNATURE}"
echo "JSON Format"
echo "${SIGNED_ADDRESS_REGISTER_JSON}"


echo ""
echo "Creating Guild Login Message/Signature"

NOW_IN_HUMAN=$(date)
NOW_IN_UNIX=$(date +%s)
echo "Creating Login message for ${NOW_IN_HUMAN} which is roughly ${NOW_IN_UNIX}"

SIGNED_GUILD_LOGIN_JSON=$(structs-sign-proxy guild-login ${GUILD_ID} ${NOW_IN_UNIX} "$MNEMONIC")
SIGNED_GUILD_LOGIN_PUBKEY=$( echo ${SIGNED_GUILD_LOGIN_JSON} | jq -r ".pubkey" )
SIGNED_GUILD_LOGIN_SIGNATURE=$( echo ${SIGNED_GUILD_LOGIN_JSON} | jq -r ".signature" )
SIGNED_GUILD_LOGIN_MESSAGE=$( echo ${SIGNED_GUILD_LOGIN_JSON} | jq -r ".message" )

echo "${SIGNED_GUILD_LOGIN_MESSAGE}"
echo "[Address] [PubKey] [Signature]"
echo "${ACCOUNT_ADDRESS} ${SIGNED_GUILD_LOGIN_PUBKEY} ${SIGNED_GUILD_LOGIN_SIGNATURE}"
echo "JSON Format"
echo "${SIGNED_GUILD_LOGIN_JSON}"





