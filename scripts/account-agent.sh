#!/usr/bin/env bash

# Variables
ACCOUNT_AGENT_SLEEP=30
CLIENT_FLAGS="--gas auto --yes=true"

# Come online
  # Great work! Keep this up and you'll be promoted to Senior Signer

echo "ACCOUNT AGENT($BASHPID): Started for Stub Account $1"

# Look for the account json blob in the tmp folder
if [[ ! -f "/var/structs/tsa/tmp/account_${1}.json" ]]; then
  echo "ACCOUNT AGENT($BASHPID): I can't work under these conditions! Where the heck is my account ${1} "
  exit
fi

# Extract details from the JSON blob into variables
echo "ACCOUNT AGENT($BASHPID): Reviewing Account Details"

STUB_ACCOUNT_JSON=$(cat /var/structs/tsa/tmp/account_$1.json)
STUB_ACCOUNT_ID=$( echo ${STUB_ACCOUNT_JSON} | jq -r ".id" )
STUB_ACCOUNT_ROLE_ID=$( echo ${STUB_ACCOUNT_JSON} | jq -r ".role_id" )
STUB_ACCOUNT_PLAYER_ID=$( echo ${STUB_ACCOUNT_JSON} | jq -r ".player_id" )

echo "ACCOUNT AGENT($BASHPID): ID(${STUB_ACCOUNT_ID}) RoleID(${STUB_ACCOUNT_ROLE_ID}) PlayerID(${STUB_ACCOUNT_PLAYER_ID})"


echo "ACCOUNT AGENT($BASHPID): Adding Mnemonic to the shared keychain"
TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
MNEMONIC=$(structsd keys add "$TEMP_NAME" | jq -r ".mnemonic")

echo "${MNEMONIC}" > /var/structs/accounts/account_${STUB_ACCOUNT_ID}.bu.txt


# Get the address of what was just added
ACCOUNT_ADDRESS=$(structsd keys show "$TEMP_NAME" | jq -r ".address" )
echo "ACCOUNT AGENT($BASHPID): New Account Address ${ACCOUNT_ADDRESS}"

# rename the account to the role account id
echo "ACCOUNT AGENT($BASHPID): Saving Address to account_${ACCOUNT_ADDRESS}"
structsd keys rename $TEMP_NAME account_$ACCOUNT_ADDRESS --yes

# TSA sign an address-register message
echo "ACCOUNT AGENT($BASHPID): Generating Signature for Address Register"
SIGNED_ADDRESS_REGISTER_JSON=$(structs-sign-proxy address-register ${STUB_ACCOUNT_PLAYER_ID} "$MNEMONIC")
SIGNED_ADDRESS_REGISTER_PUBKEY=$( echo ${SIGNED_ADDRESS_REGISTER_JSON} | jq -r ".pubkey" )
SIGNED_ADDRESS_REGISTER_SIGNATURE=$( echo ${SIGNED_ADDRESS_REGISTER_JSON} | jq -r ".signature" )


echo "ACCOUNT AGENT($BASHPID): '${STUB_ACCOUNT_ID}','${STUB_ACCOUNT_PLAYER_ID}', '${ACCOUNT_ADDRESS}', '${SIGNED_ADDRESS_REGISTER_PUBKEY}', '${SIGNED_ADDRESS_REGISTER_SIGNATURE}'"
# TODO: Fix this permission issue at the end.
psql $DATABASE_URL -c "SELECT signer.UPDATE_PENDING_ACCOUNT('${STUB_ACCOUNT_ID}','${STUB_ACCOUNT_PLAYER_ID}', '${ACCOUNT_ADDRESS}', '${SIGNED_ADDRESS_REGISTER_PUBKEY}', '${SIGNED_ADDRESS_REGISTER_SIGNATURE}', 127);" --no-align -t

# Wait for the address to show up in the permissions table
echo "ACCOUNT AGENT($BASHPID): Waiting for activation...."
ADDRESS_COUNT=0
until [ $ADDRESS_COUNT -gt 0 ];
do
  sleep $ACCOUNT_AGENT_SLEEP
  ADDRESS_COUNT=$( psql $DATABASE_URL -c "select count(1) from structs.permission WHERE object_index = '${ACCOUNT_ADDRESS}';" --no-align -t)
done

echo "ACCOUNT AGENT($BASHPID): Marking Account available ${STUB_ACCOUNT_ID} ${ACCOUNT_ADDRESS} "
psql $DATABASE_URL -c "UPDATE signer.account SET status='available' WHERE address = '${ACCOUNT_ADDRESS}';" --no-align -t

echo "ACCOUNT AGENT($BASHPID): Agent Done"
