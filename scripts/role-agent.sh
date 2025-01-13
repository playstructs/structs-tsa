#!/usr/bin/env bash

# Variables
ACCOUNT_WAIT_SLEEP=10
CLIENT_FLAGS="--gas auto --yes=true"

# Come online
  # Great work! Keep this up and you'll be promoted to Senior Signer

# Look for the transaction json blob in the tmp folder
if [ -e /var/structs/tsa/tmp/tx_$1.json ]; then
  echo "AGENT($BASHPID): I can't work under these conditions! Where the heck is my transaction ${1} "
  exit
fi

# Extract details from the JSON blob into variables
echo "AGENT($BASHPID): Reviewing Transaction Details"

PENDING_TRANSACTION_JSON=$(cat /var/structs/tsa/tmp/tx_$1.json)
PENDING_TRANSACTION_ID=$( echo ${PENDING_TRANSACTION_JSON} | jq ".id" )
PENDING_OBJECT_ID=$( echo ${PENDING_TRANSACTION_JSON} | jq ".object_id" )
PENDING_COMMAND=$( echo ${PENDING_TRANSACTION_JSON} | jq ".command" )

echo "AGENT($BASHPID): TX_ID(${PENDING_TRANSACTION_ID}) OBJECT_ID(${PENDING_OBJECT_ID}) COMMAND(${PENDING_COMMAND})"
until [[ ! -z "${PENDING_ACCOUNT_ADDRESS}" ]]
do

  PENDING_TRANSACTION_ACCOUNT_JSON=$( psql -c 'select signer.CLAIM_INTERNAL_ACCOUNT($1);' --no-align -t)
  PENDING_ACCOUNT_ADDRESS=$( echo ${PENDING_TRANSACTION_ACCOUNT_JSON} | jq '.address' )

  if [ -z "${PENDING_ACCOUNT_ADDRESS}" ]; then
    echo "AGENT($BASHPID): Heading to the breakroom, unable to find an account"
    sleep $ACCOUNT_WAIT_SLEEP
  fi
done

PENDING_ACCOUNT_ID=$( echo ${PENDING_TRANSACTION_ACCOUNT_JSON} | jq '.id' )
echo "AGENT($BASHPID): Account ${PENDING_ACCOUNT_ID} ${PENDING_ACCOUNT_ADDRESS}"

PENDING_ACCOUNT_NAME="account_${PENDING_ACCOUNT_ADDRESS}"

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

PENDING_ARGS=$(echo ${PENDING_TRANSACTION_ACCOUNT_JSON} | jq -r '.args | to_entries[] | "\"\(.value)\""' |  tr '\n' ' ')
PENDING_FLAGS=$(echo ${PENDING_TRANSACTION_ACCOUNT_JSON} | jq -r '.flags | to_entries[] | "--\(.key)=\"\(.value)\""' |  tr '\n' ' ')

echo "AGENT($BASHPID): Signing.... structsd tx structs ${PENDING_COMMAND} ${PENDING_ARGS} ${PENDING_FLAGS} --from ${PENDING_ACCOUNT_NAME} ${CLIENT_FLAGS}"
BROADCAST_RESULT=$(structsd tx structs ${PENDING_COMMAND} ${PENDING_ARGS} ${PENDING_FLAGS} --from ${PENDING_ACCOUNT_NAME} ${CLIENT_FLAGS})

echo "AGENT($BASHPID): ${BROADCAST_RESULT}"

#psql -c 'select signer.TRANSACTION_ERROR(transaction_id INTEGER, transaction_error TEXT);' --no-align -t

psql -c 'select signer.TRANSACTION_BROADCAST_RESULTS(${PENDING_TRANSACTION_ID}, ${BROADCAST_RESULT});' --no-align -t

