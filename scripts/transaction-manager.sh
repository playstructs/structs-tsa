#!/usr/bin/env bash

# Variables
TRANSACTION_MANAGER_SLEEP=30


while :
do
  PENDING_TRANSACTION=$(psql -c 'select signer.CLAIM_INTERNAL_TRANSACTION();' --no-align -t)
  PENDING_TX_ID=$(echo $PENDING_TRANSACTION | jq -r '.id')

  if [[ ! -z "${PENDING_TX_ID}" ]]; then
    echo $PENDING_TRANSACTION > /var/structs/tsa/tmp/tx_${PENDING_TX_ID}.json

    echo "TX MANAGER: Launching Agent Minion for Transaction ${PENDING_TX_ID}"
    ./transaction-agent.sh "${PENDING_TX_ID}" &
  else
      sleep $TRANSACTION_MANAGER_SLEEP
  fi

done

