#!/usr/bin/env bash

# Variables
MANAGER_READINESS_WAIT_SLEEP=10
CLIENT_FLAGS="--gas auto --yes=true"

# Come online
  # Great work! Keep this up and you'll be promoted to Senior Signer

# Wait until the Role is initiated
until [ -e /var/structs/tsa/role ]
do
  sleep $MANAGER_READINESS_WAIT_SLEEP
done

PRIMARY_ROLE=$( cat /var/structs/tsa/role )


while :
do

  # Check for pending addresses
  NEW_ACCOUNT=$(psql -c "SELECT * FROM signer.account WHERE status = 'new';" --no-align -t)

  # sign the message


  echo "Adding Mnemonic to the shared keychain"
  TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
  MNEMONIC=$(structsd keys add "$TEMP_NAME" | jq ".mnemonic")

  GUILD_ID=$( cat /var/structs/tsa/guild )

  # TSA sign a proxy-join message
  echo "Generating Signature for TX..."
  echo ""
  SIGNED_PROXY=$(structs-sign-proxy ${GUILD_ID} 0 "$MNEMONIC")
  echo $SIGNED_PROXY
  echo ""

  # Add to the db
  #signer.PENDING_ACCOUNT(account_id INTEGER, role_id CHARACTER VARYING, new_address CHARACTER VARYING, pubkey CHARACTER VARYING, signature CHARACTER VARYING, permission INTEGER)

done


