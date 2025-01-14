#!/usr/bin/env bash

# Variables
TRANSACTION_MANAGER_SLEEP=30


while :
do
  PENDING_TRANSACTION=$(psql $DATABASE_URL -c 'select signer.CLAIM_INTERNAL_TRANSACTION();' --no-align -t)
  PENDING_TX_ID=$(echo $PENDING_TRANSACTION | jq -r '.id')

  if [[ ! -z "$PENDING_TRANSACTION" ]]; then
    if [ "$PENDING_TX_ID" != "null" ]; then
      echo $PENDING_TRANSACTION > /var/structs/tsa/tmp/tx_${PENDING_TX_ID}.json

      echo "TX MANAGER: Launching Agent Minion for Transaction ${PENDING_TX_ID}"
      bash /src/structs/transaction-agent.sh "${PENDING_TX_ID}" &
    else
        sleep $TRANSACTION_MANAGER_SLEEP
    fi
  else
    sleep $TRANSACTION_MANAGER_SLEEP
  fi

done

