#!/usr/bin/env bash

STAT_SLEEP=20
ROLE_WAIT_SLEEP=20

echo "Loading The TSA"

echo "Checking for Initialized Roles"
ROLE_COUNT=0
until [ $ROLE_COUNT -gt 0 ];
do
  sleep $ROLE_WAIT_SLEEP
  ROLE_COUNT=$( psql $DATABASE_URL -c "select count(1) from signer.role;" --no-align -t)
done

bash /src/structs/role-manager.sh &

bash /src/structs/account-manager.sh &

bash /src/structs/transaction-manager.sh &

while :
do
  # Get latest stats
  PENDING_TRANSACTION_COUNT=$(psql $DATABASE_URL -c "SELECT COUNT(1) FROM signer.tx WHERE status = 'pending';" --no-align -t)
  echo "TSA: ${PENDING_TRANSACTION_COUNT} Pending Transactions "

  sleep $STAT_SLEEP
done
