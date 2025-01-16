#!/usr/bin/env bash

# Variables
ROLE_MANAGER_SLEEP=10

echo "ROLE MANAGER($BASHPID): Management Online"

while :
do
  STUB_ROLE=$(psql $DATABASE_URL -c 'select signer.CLAIM_ROLE_STUB();' --no-align -t)
  STUB_ROLE_ID=$(echo $STUB_ROLE | jq -r '.id')

  if [[ ! -z "$STUB_ROLE" ]]; then
    if [ "$STUB_ROLE_ID" != "null" ];then
      echo $STUB_ROLE > /var/structs/tsa/tmp/role_${STUB_ROLE_ID}.json

      echo "ROLE MANAGER($BASHPID): Launching Agent Minion for Role Generation ${STUB_ROLE_ID}"
      bash /src/structs/role-agent.sh "${STUB_ROLE_ID}" &
    else
        sleep $ROLE_MANAGER_SLEEP
    fi
  else
      sleep $ROLE_MANAGER_SLEEP
  fi

done

