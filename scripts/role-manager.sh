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
    ./role-agent.sh "${PENDING_TX_ID}" &
  else
      sleep $SLEEP
  fi

done

