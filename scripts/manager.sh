#!/usr/bin/env bash

# Variables
SLEEP=30


# Come Online
  # Done. Great work team.

# Report to the DB about being online
  # No place to put this yet

# Check to see if the TSA has been initialized
echo "Loading TSA Signing Manager"
until [ -e /var/structs/tsa/ready ]
do
  echo "Waiting for readiness check. Have you run role-init.sh?"
  sleep 10
done


while :
do

  PENDING_TRANSACTION=$(psql -c 'select signer.CLAIM_INTERNAL_TRANSACTION();' --no-align -t)
  PENDING_TX_ID=$(echo $PENDING_TRANSACTION | jq -r '.id')

  if [[ ! -z "${PENDING_TX_ID}" ]]; then
    echo $PENDING_TRANSACTION > /var/structs/tsa/tmp/tx_${PENDING_TX_ID}.json

    echo "Launching Agent Minion for Transaction ${PENDING_TX_ID}"
    ./agent.sh "${PENDING_TX_ID}" &
  else
      sleep $SLEEP
  fi

  #{
  #  "id": 1,
  #  "role_id": 1,
  #  "account_id": 1,
  #  "command": "moo",
  #  "args": [],
  #  "flags": [],
  #  "status": "pending",
  #  "output: "",
  #  "created_at": "2024-11-29T16:58:50.410149+00:00",
  #  "updated_at": "2024-11-29T16:58:50.410149+00:00"
  #}



  #psql -c 'select signer.TRANSACTION_ERROR(transaction_id INTEGER, transaction_error TEXT);' --no-align -t

  #psql -c 'select signer.TRANSACTION_BROADCAST_RESULTS(transaction_id INTEGER, transaction_output TEXT);' --no-align -t

done

