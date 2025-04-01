#!/usr/bin/env bash

# Variables
ACCOUNT_WAIT_SLEEP=10
CLIENT_FLAGS="--gas auto --yes=true"

# Come online
  # Great work! Keep this up and you'll be promoted to Senior Signer

echo "TX AGENT($BASHPID): Started for Transaction $1"

# Look for the transaction json blob in the tmp folder
if [[ ! -f "/var/structs/tsa/tmp/tx_${1}.json" ]]; then
  echo "TX AGENT($BASHPID): I can't work under these conditions! Where the heck is my transaction ${1} "
  exit
fi

# Extract details from the JSON blob into variables
echo "TX AGENT($BASHPID): Reviewing Transaction Details"

PENDING_TRANSACTION_JSON=$(cat /var/structs/tsa/tmp/tx_$1.json)
PENDING_TRANSACTION_ID=$( echo ${PENDING_TRANSACTION_JSON} | jq -r ".id" )
PENDING_OBJECT_ID=$( echo ${PENDING_TRANSACTION_JSON} | jq -r ".object_id" )
PENDING_MODULE=$( echo ${PENDING_TRANSACTION_JSON} | jq -r ".module" )
PENDING_COMMAND=$( echo ${PENDING_TRANSACTION_JSON} | jq -r ".command" )
PENDING_ARGS=$(echo ${PENDING_TRANSACTION_JSON} | jq -r '.args | to_entries[] | "\(.value)"' |  tr '\n' ' ')
PENDING_FLAGS=$(echo ${PENDING_TRANSACTION_JSON} | jq -r '.flags | to_entries[] | "--\(.key) \(.value)"' |  tr '\n' ' ')

echo "TX AGENT($BASHPID): TX_ID(${PENDING_TRANSACTION_ID}) OBJECT_ID(${PENDING_OBJECT_ID}) MODULE(${PENDING_MODULE}) COMMAND(${PENDING_COMMAND}) PENDING_ARGS(${PENDING_ARGS}) PENDING_FLAGS(${PENDING_FLAGS})"

echo "TX AGENT($BASHPID): Transaction ${PENDING_TRANSACTION_ID} searching for signing Account..."
while [[ -z "${PENDING_ACCOUNT_ADDRESS}" ]] || [ "$PENDING_ACCOUNT_ADDRESS" == "null" ]
do

  PENDING_TRANSACTION_ACCOUNT_JSON=$( psql $DATABASE_URL -c "select signer.CLAIM_INTERNAL_ACCOUNT($1);" --no-align -t)
  PENDING_ACCOUNT_ADDRESS=$( echo ${PENDING_TRANSACTION_ACCOUNT_JSON} | jq -r '.address' )

  if [ -z "${PENDING_ACCOUNT_ADDRESS}" ] || [ "$PENDING_ACCOUNT_ADDRESS" == "null" ]; then
    echo "TX AGENT($BASHPID): Heading to the breakroom for $ACCOUNT_WAIT_SLEEP, unable to find an account"
    sleep $ACCOUNT_WAIT_SLEEP
  fi
done

PENDING_ACCOUNT_ID=$( echo ${PENDING_TRANSACTION_ACCOUNT_JSON} | jq -r '.id' )
echo "TX AGENT($BASHPID): Account ${PENDING_ACCOUNT_ID} ${PENDING_ACCOUNT_ADDRESS}"

PENDING_ACCOUNT_NAME="account_${PENDING_ACCOUNT_ADDRESS}"


echo "TX AGENT($BASHPID): Signing.... structsd tx ${PENDING_MODULE} ${PENDING_COMMAND} ${PENDING_ARGS} ${PENDING_FLAGS} --from ${PENDING_ACCOUNT_NAME} ${CLIENT_FLAGS}"
BROADCAST_RESULT=$(structsd tx ${PENDING_MODULE} ${PENDING_COMMAND} ${PENDING_ARGS} ${PENDING_FLAGS} --from ${PENDING_ACCOUNT_NAME} ${CLIENT_FLAGS})

echo "TX AGENT($BASHPID): ${BROADCAST_RESULT}"

#psql -c 'select signer.TRANSACTION_ERROR(transaction_id INTEGER, transaction_error TEXT);' --no-align -t

echo "TX AGENT($BASHPID): Updating transaction results"
psql $DATABASE_URL -c "select signer.TRANSACTION_BROADCAST_RESULTS(${PENDING_TRANSACTION_ID}, '${BROADCAST_RESULT}');" --no-align -t

echo "TX AGENT($BASHPID): Sleeping for a bit..."
sleep 10

echo "TX AGENT($BASHPID): Releasing signer Account ${PENDING_ACCOUNT_ID}"
psql $DATABASE_URL -c "UPDATE signer.account SET status='available' WHERE id = ${PENDING_ACCOUNT_ID};" --no-align -t

echo "TX AGENT($BASHPID): Agent Done"
