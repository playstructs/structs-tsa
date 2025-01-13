#!/usr/bin/env bash

STAT_SLEEP=20

echo "Loading The TSA"

bash /src/structs/role-manager.sh &

bash /src/structs/transaction-manager.sh &

bash /src/structs/account-manager.sh &

while :
do
  # Get latest stats
  PENDING_TRANSACTION_COUNT=$(psql -c "SELECT COUNT(1) FROM signer.tx WHERE status = 'pending';" --no-align -t)
  echo "TSA: ${PENDING_TRANSACTION_COUNT} Pending Transactions "

  sleep $STAT_SLEEP
done
