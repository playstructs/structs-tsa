
# Variables

NETWORK=""
ROLE=""
ACCOUNT_ID=""
ACCOUNT_NAME="signer"
SLEEP=10

# Come online


# Import Key or Generate New Key

  # Check the database for what account it is
  # signer.CLAIM_ACCOUNT(requested_role_id CHARACTER VARYING)

  # if all are taken then make a new one
  # if status = new
    # create a new key
    #  signer.PENDING_ACCOUNT(account_id INTEGER, new_address CHARACTER VARYING)
  # else
    # Check the key volume for the key file
    # load it into structsd keychain




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

