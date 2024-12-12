
# Variables

NETWORK=""
ROLE=""
ACCOUNT_ID=""
SLEEP=10


sleep 600000

# Come online

# Import Key or Generate New Key

# Report to the DB about being online


PENDING_TRANSACTION=$(psql -c 'select signer.CLAIM_TRANSACTION($ROLE_ID, $ACCOUNT_ID);' --no-align -t)

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
