#!/usr/bin/env bash

echo ""
echo "Trans-Planetary Signing Authority (TSA)"
echo ""

echo "Initializing a Role..."

# Read Mnemonic
echo "Enter the Mnemonic of the existing Role:"
read MNEMONIC

# Input Mnemonic directly to structsd
echo "Adding Mnemonic to the shared keychain"
TEMP_NAME=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c10)
echo "$MNEMONIC" | structsd keys add "$TEMP_NAME" --recover

# Get the address of what was just added

# Loop / Check the database for the role

# rename the account to the role account id

# Create signing accounts
# Loop until accounts goal
  # generate key
  # create the signature
  # submit signature
  # loop until there
  # add account to the database








