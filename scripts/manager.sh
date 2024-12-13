#!/usr/bin/env bash

# Variables
SLEEP=60

# Come online

# Import Key or Generate New Key

# Report to the DB about being online

echo "Loading TSA Signing Manager"
until [ -e /var/structs/tsa/ready ]
do
  echo "Waiting for readiness check. Have you run role-init.sh?"
  sleep 10
done

ROLE_ID=$(cat /var/structs/tsa/role)
echo "Loaded Role ${ROLE_ID}"

while :
do

  # need to track the number of accounts in use

  # Check for an unused account




  PENDING_TRANSACTION=$(psql -c 'select signer.CLAIM_TRANSACTION($ROLE_ID, $ACCOUNT_ID);' --no-align -t)
  echo $PENDING_TRANSACTION
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

  sleep $SLEEP
done

