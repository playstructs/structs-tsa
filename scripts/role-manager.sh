#!/usr/bin/env bash

# Variables
ROLE_MANAGER_SLEEP=10

echo "Loading TSA Role Manager"

while :
do
  STUB_ROLE=$(psql -c 'select signer.CLAIM_ROLE_STUB();' --no-align -t)
  STUB_ROLE_ID=$(echo $STUB_ROLE | jq -r '.id')

  if [[ ! -z "${STUB_ROLE_ID}" ]]; then
    echo $STUB_ROLE > /var/structs/tsa/tmp/role_${STUB_ROLE_ID}.json

    echo "Launching Agent Minion for Role Generation ${STUB_ROLE_ID}"
    ./role-agent.sh "${STUB_ROLE_ID}" &
  else
      sleep $ROLE_MANAGER_SLEEP
  fi

done

