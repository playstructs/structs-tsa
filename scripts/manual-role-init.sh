#!/usr/bin/env bash

echo ""
echo "Trans-Planetary Signing Authority (TSA)"
echo ""


# Read Mnemonic
echo "Are you creating a new primary internal role, or importing an old one? (import/new):"
read -r PROCESS

if [[ "$PROCESS" == "new" ]]
then
  echo "Initializing primary internal role..."

  echo "Adding Mnemonic to the shared keychain"
  TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
  MNEMONIC=$(structsd keys add "$TEMP_NAME" | jq -r ".mnemonic")

  # Get the address of what was just added
  ACCOUNT_ADDRESS=$(structsd keys show "$TEMP_NAME" | jq -r ".address" )

  echo "What is the Guild ID for the new Role? (ex 0-3): "
  read -r GUILD_ID

  # TSA sign a proxy-join message
  SIGNED_PROXY_JSON=$(structs-sign-proxy guild-join ${GUILD_ID} 0 "$MNEMONIC")
  SIGNED_PROXY_PUBKEY=$( echo ${SIGNED_PROXY_JSON} | jq -r ".pubkey" )
  SIGNED_PROXY_SIGNATURE=$( echo ${SIGNED_PROXY_JSON} | jq -r ".signature" )

  echo "Generating Signature for TX..."
  echo "${ACCOUNT_ADDRESS} ${SIGNED_PROXY_PUBKEY} ${SIGNED_PROXY_SIGNATURE}"


  echo "Paste that somewhere good then press [enter] "
  echo "(and by somewhere good, we mean proxy-join.sh on your validator)"
  read -r NOTHING_VARIABLE

else
  echo "Importing a Role..."

  # Read Mnemonic
  echo "Enter the Mnemonic of the existing Role:"
  read MNEMONIC

  # Input Mnemonic directly to structsd
  echo "Adding Mnemonic to the shared keychain"
  TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
  echo "$MNEMONIC" | structsd keys add "$TEMP_NAME" --recover

  # Get the address of what was just added
  ACCOUNT_ADDRESS=$(structsd keys show "$TEMP_NAME" | jq -r ".address" )

fi

# rename the account to the role account id
structsd keys rename $TEMP_NAME account_$ACCOUNT_ADDRESS --yes

# Add the Role to the database
NEW_ACCOUNT=$(psql $DATABASE_URL -c "SELECT signer.CREATE_SYSTEM_ROLE('DRONE' || structs.random_human_string(5),'${GUILD_ID}','${ACCOUNT_ADDRESS}');" --no-align -t)

# Wait for the address to show up in the permissions table
ADDRESS_COUNT=0
until [ $ADDRESS_COUNT -gt 0 ];
do
  sleep 10
  ADDRESS_COUNT=$( psql $DATABASE_URL -c "select count(1) from structs.permission WHERE object_index = '${ACCOUNT_ADDRESS}';" --no-align -t)
done

psql $DATABASE_URL -c "UPDATE signer.account SET status='available' WHERE address = '${ACCOUNT_ADDRESS}';" --no-align -t








