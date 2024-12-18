#!/usr/bin/env bash

echo ""
echo "Trans-Planetary Signing Authority (TSA)"
echo ""


if [ -e /var/structs/tsa/role ]
then
  ORIGINAL_ROLE_ID=$(cat /var/structs/tsa/role)
  echo "ERROR: Role ${ORIGINAL_ROLE_ID} already found...."
  exit
fi

# Read Mnemonic
echo "Are you creating a new role, or importing an old one? (import/new):"
read -r PROCESS

if [[ "$PROCESS" == "new" ]]
then
  echo "Initializing a Role..."

  echo "Adding Mnemonic to the shared keychain"
  TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
  MNEMONIC=$(structsd keys add "$TEMP_NAME" | jq ".mnemonic")


  until [ -e /var/structs/tsa/guild ]
  do

    echo "What is the Guild ID for the new Role? (ex 0-3): "
    read -r GUILD_ID

    # select id from structs.guild where id = $guild_id
    CHECK_GUILD_ID=$(psql -c "SELECT id FROM structs.guild WHERE id = '$GUILD_ID';" --no-align -t)

    if [[ "$GUILD_ID" == "$CHECK_GUILD_ID" ]]
    then
      echo ${GUILD_ID} > /var/structs/tsa/guild
    else
      echo "ERROR: Guild not found..."
    fi
  done

  # TSA sign a proxy-join message
  SIGNED_PROXY=$(structs-sign-proxy ${GUILD_ID} 0 "$MNEMONIC")
  echo "Generating Signature for TX..."
  echo ""
  echo $SIGNED_PROXY
  echo ""

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

fi


# Get the address of what was just added
ROLE_ADDRESS=$(structsd keys show "$TEMP_NAME" | jq -r ".address" )

# Loop / Check the database for the role
until [ -e /var/structs/tsa/role ]
do
  NEW_ROLE_ID=$(psql -c "SELECT player_id FROM player_address WHERE address = '$ROLE_ADDRESS';" --no-align -t)
  if [[ "$NEW_ROLE_ID" != "" ]]
  then
    echo $NEW_ROLE_ID > /var/structs/tsa/role
  fi
done

# rename the account to the role account id
structsd keys rename $TEMP_NAME $NEW_ROLE_ID

touch /var/structs/tsa/ready

# Create signing accounts
# AGENT_TARGET_NUMBER
# Loop until accounts goal
  # generate key
  # create the signature
  # submit signature
  # loop until there
  # add account to the database








