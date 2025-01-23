#!/usr/bin/env bash

echo ""
echo "Trans-Planetary Signing Authority (TSA)"
echo ""


# Read Mnemonic
echo "Are you sure you'd like to reload the wallet? (yes/no):"
read -r PROCESS

if [[ "$PROCESS" == "yes" ]]
then

  echo "Extracting wallet details...."
  WALLET_JSON=$(structsd keys list)
  ACCOUNT_COUNT=$(echo ${WALLET_JSON} | jq length )

  for (( p=0; p<ACCOUNT_COUNT; p++ ))
  do

    ACCOUNT_NAME=$(echo ${PLANETS_BLOB} | jq -r ".[${p}].name")
    ACCOUNT_ADDRESS=$(echo ${PLANETS_BLOB} | jq -r ".[${p}].address")

    if [[ $ACCOUNT_NAME == account_* ]]; then
      # Add the Role to the database
      echo "Loading ${ACCOUNT_NAME} ${ACCOUNT_ADDRESS}"
      psql $DATABASE_URL -c "SELECT signer.LOAD_ACCOUNT('${ACCOUNT_ADDRESS}');" --no-align -t
    fi

  done

fi





