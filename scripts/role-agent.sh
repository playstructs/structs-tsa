#!/usr/bin/env bash

# Variables
ROLE_AGENT_SLEEP=30
CLIENT_FLAGS="--gas auto --yes=true"

echo "ROLE AGENT($BASHPID): Started for Stub Role $1"

# Look for the role json blob in the tmp folder
if [[ ! -f "/var/structs/tsa/tmp/role_${1}.json" ]]; then
  echo "ROLE AGENT($BASHPID): I can't work under these conditions! Where the heck is my role ${1} "
  exit
fi

# Extract details from the JSON blob into variables
echo "ROLE AGENT($BASHPID): Reviewing Role Details"

STUB_ROLE_JSON=$(cat /var/structs/tsa/tmp/tx_$1.json)
STUB_ROLE_ID=$( echo ${STUB_ROLE_JSON} | jq -r ".id" )
STUB_ROLE_GUILD_ID=$( echo ${STUB_ROLE_JSON} | jq -r ".guild_id" )

echo "ROLE AGENT($BASHPID): ROLE_ID(${STUB_ROLE_ID}) GUILD_ID(${PENDING_OBJECT_ID})"

echo "ROLE AGENT($BASHPID): Adding Mnemonic to the shared keychain"
# Create the new primary Role address
TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
MNEMONIC=$(structsd keys add "$TEMP_NAME" | jq -r ".mnemonic")

echo "${MNEMONIC}" > /var/structs/accounts/role_${STUB_ROLE_ID}.bu.txt

# Get the address of what was just added
ACCOUNT_ADDRESS=$(structsd keys show "$TEMP_NAME" | jq -r ".address" )
echo "ROLE AGENT($BASHPID): New Account Address ${ACCOUNT_ADDRESS}"

# rename the account to the role account id
echo "ROLE AGENT($BASHPID): Saving Address to account_${ACCOUNT_ADDRESS}"
structsd keys rename $TEMP_NAME account_$ACCOUNT_ADDRESS --yes

# TSA sign a proxy-join message
SIGNED_PROXY_JSON=$(structs-sign-proxy guild-join ${STUB_ROLE_GUILD_ID} 0 "$MNEMONIC")
SIGNED_PROXY_PUBKEY=$( echo ${SIGNED_PROXY_JSON} | jq -r ".pubkey" )
SIGNED_PROXY_SIGNATURE=$( echo ${SIGNED_PROXY_JSON} | jq -r ".signature" )

echo "ROLE AGENT($BASHPID): Signature for Role Proxy Join ${ACCOUNT_ADDRESS} ${SIGNED_PROXY_PUBKEY} ${SIGNED_PROXY_SIGNATURE}"


echo "ROLE AGENT($BASHPID): Updating Player Internal Pending record"
# Set the primary address of the pending internal account
psql $DATABASE_URL -c "SELECT signer.SET_PLAYER_INTERNAL_PENDING_PRIMARY_ADDRESS('${STUB_ROLE_ID}','${ACCOUNT_ADDRESS}');" --no-align -t


echo "ROLE AGENT($BASHPID): Updating Account record"
# Setup the Pending account
psql $DATABASE_URL -c "SELECT signer.CREATE_PENDING_ACCOUNT_FROM_ROLE('${STUB_ROLE_ID}','${ACCOUNT_ADDRESS}');" --no-align -t


# Create a Join Proxy message for the new account
# 16 represents the Association permission needed on the guild object
echo "ROLE AGENT($BASHPID): Adding pending Transaction for Guild Join Proxy of ${ACCOUNT_ADDRESS} to ${STUB_ROLE_GUILD_ID}"
NEW_ROLE_TRANSACTION_JSON=$(psql $DATABASE_URL -c "SELECT signer.CREATE_TRANSACTION('${STUB_ROLE_GUILD_ID}',16,'guild-membership-join-proxy',jsonb_build_array('${ACCOUNT_ADDRESS}','${SIGNED_PROXY_PUBKEY}','${SIGNED_PROXY_SIGNATURE}'),'{}');" --no-align -t)


echo "ROLE AGENT($BASHPID): Waiting for activation...."
ADDRESS_COUNT=0
# Wait for the address to show up in the permissions table
until [ $ADDRESS_COUNT -gt 0 ];
do
  sleep $ROLE_AGENT_SLEEP
  ADDRESS_COUNT=$( psql $DATABASE_URL -c "select count(1) from structs.permission WHERE object_index = '${ACCOUNT_ADDRESS}';" --no-align -t)
done

echo "ROLE AGENT($BASHPID): Address ${ACCOUNT_ADDRESS}  detected on-chain "

echo "ROLE AGENT($BASHPID): Marking Account available ${ACCOUNT_ADDRESS} "
psql $DATABASE_URL -c "UPDATE signer.account SET status='available' WHERE address = '${ACCOUNT_ADDRESS}';" --no-align -t

echo "ROLE AGENT($BASHPID): Agent Done"