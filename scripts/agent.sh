
# Variables

NETWORK=""
ACCOUNT_ID=""
ACCOUNT_NAME=""
SLEEP=5

# Come online
  # Great work! Keep this up and you'll be promoted to Senior Signer


if [ -e /var/structs/tsa/tmp/tx_$1.json ]; then
  echo "AGENT: I can't work under these conditions! Where the heck is my transaction ${1} "
  exit
fi

echo "AGENT: Reviewing Transaction Details"

PENDING_TRANSACTION_ID=$()
PENDING_COMMAND=$()
echo "ECHO"

PENDING_TRANSACTION_ACCOUNT=$(psql -c 'select signer.CLAIM_INTERNAL_ACCOUNT($1);' --no-align -t)



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




psql -c 'select signer.TRANSACTION_ERROR(transaction_id INTEGER, transaction_error TEXT);' --no-align -t

psql -c 'select signer.TRANSACTION_BROADCAST_RESULTS(transaction_id INTEGER, transaction_output TEXT);' --no-align -t

