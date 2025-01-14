#!/usr/bin/env bash

# Variables
ACCOUNT_MANAGER_SLEEP=30

while :
do
  STUB_ACCOUNT_JSON=$(psql $DATABASE_URL -c 'select signer.GET_NEW_ACCOUNT();' --no-align -t)
  STUB_ACCOUNT_ID=$(echo $STUB_ACCOUNT_JSON | jq -r '.id')

  if [[ ! -z "${STUB_ACCOUNT_ID}" ]]; then
    echo $STUB_ACCOUNT_JSON > /var/structs/tsa/tmp/account_${STUB_ACCOUNT_ID}.json

    echo "Launching Agent Minion for Transaction ${STUB_ACCOUNT_ID}"
    bash /src/structs/account-agent.sh "${STUB_ACCOUNT_ID}" &
  else
      sleep $ACCOUNT_MANAGER_SLEEP
  fi

done

