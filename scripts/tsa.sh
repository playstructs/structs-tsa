#!/usr/bin/env bash

STAT_SLEEP=20

echo "Loading The TSA"

./role-manager.sh &

./transaction-manager.sh &

./account-manager.sh &

while :
do
  echo "TSA: __ Pending Transactions "

  sleep $STAT_SLEEP
done
