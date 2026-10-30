# structs-tsa

The Trans-Planetary Signing Authority signs queued Structs transactions with keys held by a guild stack. This release supports **structsd v0.22.0**, testnet `structstestnet-111`, from height **3,353,000**. It requires the coordinated v022 signer/database contract; it does not run against the legacy queue schema.

## Behavior

- Every transaction is authorized for its explicit acting player and current signing-key grant. Account numbers, sequences, amounts and permission masks remain exact integers.
- Signing uses the pinned release CLI, offline direct signatures and independent signature verification. The worker checks current ownership, account state and simulation before transport.
- SQL stores the immutable signed bytes, hash and account state. A journal on the key volume is persisted before obtaining the one-use SQL send permit. The worker makes **one broadcast attempt**. Timeout, lost acknowledgement, missing index results and restarts only trigger observation of that same identity. They never automatically replace or resend it.
- Keys remain reserved until a definitive rejection, an unsent cancellation, or matching transaction bytes and results in a chain block. Unresolved sends survive database loss through the local journal.
- Startup and periodic reconciliation inventory **all local keyring names**, including legacy `account_*` keys. Registered keys are restored to SQL only when current chain ownership/permissions match a ready index. Unregistered, conflicting or uncertain keys remain visible and inactive. Existing claims and managed-registration evidence are preserved.
- Queue pressure can request extra keys for an existing role. Each request records one eligible source key's exact current grant, the queued work and an idempotency UUID. It never combines grants. The total is at most **40 keys per role**, including keys still being generated or registered. Shared throttles do not trigger growth. Available eligible local keys are used first.
- **Additional roles are created manually**, or from existing explicit onboarding requests. Queue pressure never creates a new player/role. A new role's primary key receives the protocol-required `33554431` grant; subsequent scoped authority still needs to be granted explicitly.

The keyring uses the existing `test` backend. Protect and back up the entire persistent volume: it contains signing keys, recovery phrases and the send journal. SQL contains public key identifiers and transaction evidence, never recovery phrases. Do not share one volume between the old shell workers and this worker.

## Build

```sh
docker build --platform linux/amd64 -t structs/structs-tsa:v0.22.0 .
```

The Dockerfile pins the Ubuntu base manifest, official v0.22.0 archive checksum, proof-helper Git commit and Python dependency hashes. Only `linux/amd64` is supported by this artifact. OS packages are installed from the Ubuntu repository at build time. Promote the tested image digest rather than rebuilding or deploying a floating `latest` tag.

The container starts `python -m tsa`; legacy `agent-*.sh` scripts are not installed or launched. Preserve the existing volume mount at `/var/structs/accounts`. `/var/structs/chain` is CLI configuration, not a chain-node data directory.

## Configuration

| Variable | Default / requirement |
| --- | --- |
| `DATABASE_URL` | Required. Use the dedicated `structs_tsa` login and the stack's TLS/authentication policy. |
| `TSA_RPC_URL` | `http://structsd:26657`; current trusted RPC with transaction, block and block-result history. |
| `TSA_LCD_URL` | `http://structsd:1317`; height-pinned API responses required. |
| `TSA_CHAIN_ID` | `structstestnet-111`; other networks are rejected by this release. |
| `TSA_WORKERS` | `30`, valid 1–128. Legacy `AGENT_TARGET_NUMBER` is accepted as a fallback. |
| `TSA_ROLE_MAX_KEYS` | `40`, valid 1–40; counts existing and pending keys. |
| `TSA_GAS_PRICE` | No implicit value. Exact native price such as `0.025ualpha`; required for priced GuildCreate/ReactorRestart operations. Configure for the target node's admission policy. |
| `TSA_KEYRING_DIR` | `/var/structs/accounts`. |
| `TSA_HOME` | `/var/structs/chain`. |

Do not put credentials in logs, command-line arguments or copied diagnostics. Docker Compose can supply `DATABASE_URL` through the existing private environment configuration. RPC/LCD URLs must not contain credentials or redirect to another endpoint.

The healthcheck requires a responsive supervisor, recent successful inventory reconciliation and at least one verified usable local key. An empty installation or a stack waiting for index/role registration stays unhealthy while reconciliation continues. Shutdown stops new claims and waits for bounded in-flight work; configure a **180-second stop grace period**. A forced stop remains recoverable, but does not prove a broadcast failed.

The first guild onboarding request is processed automatically once the SQL index and native node satisfy the v0.22 readiness checks. An empty keyring does not require a seed command: the worker generates and retains that request's primary key. Without an existing authorized guild signer, it publishes the proof for approval through the existing external guild approval flow. The key becomes usable after registration is confirmed and indexed. Do not request a duplicate role to repair an existing pending request. `known:0` only describes the configured local keyring; check readiness, pending account state and the persistent volume mount before replacing or generating anything manually.

## Operator commands

Run these in the candidate container with the same database configuration and persistent key volume. Every new key request requires an explicit permission mask.

```sh
python -m tsa reconcile
python -m tsa request-key --role-id 7 --permissions 16 --maximum 40
python -m tsa request-role --name guild-service-two --guild-id 0-1 --permissions 33554431
python -m tsa import-key --name retained-service-key
```

`import-key` reads the recovery phrase privately from the terminal or standard input. Never pass it as an argument or environment variable. Imported keys still need current on-chain registration before they can sign.

Requests print and persist a public request UUID **before** calling SQL. If the acknowledgement is lost, repeat identical arguments with `--request-id UUID`; do not invent another request. Manual intent files live in `tsa-v022/operator-requests/`. `manual-reload.sh` is now an optional immediate reconciliation command; normal startup and periodic operation perform it automatically. `manual-role-init.sh` delegates to these explicit operator commands.

Reconciliation recovers keys, not lost application requests. It does not reconstruct an old transaction queue or automatically repeat a business action after database destruction. Entries in `tsa-v022/outbox/pending/` need exact inclusion/rejection evidence; do not delete them to free a key. Completed history is retained in `outbox/completed/`.

## Database and rollout

Deploy `structs-pg` through **`function-signer-operator-20261030`**, including the dedicated worker login and guarded functions. `structs_tsa` gets selected reads and guarded function calls, without direct mutation grants on game projections or signer tables. The Docker PG startup helper inherits the existing webapp TLS connection rule for this login; an explicitly configured TSA rule is preserved. On an existing server, apply/reload its matching HBA rule as a separate reviewed deployment step. Do not change PostgreSQL/Timescale versions merely to obtain this access rule.

1. Build and verify the pinned candidate image. Back up SQL **and the full TSA volume**.
2. Complete the paired writer/application readiness checks. Pause enqueueing and drain or explicitly reconcile outstanding legacy sends. Stop the old TSA before enabling the new contract; retain its queue and key history.
3. Stop the old writer for its paired schema transition. Apply the full Sqitch plan with the explicitly selected `denomination-v1` ledger and `v022-1` signer contracts. Restore/catch up source coverage as required by the migration runbook; never overwrite newer indexed state with an exact-height repair.
4. Confirm current source coverage and API readiness, worker login/TLS access, RPC/LCD version and history, and the candidate image digest. Start only the replacement writer/TSA/application services scheduled for this cutover.
5. Check inventory, pending registrations, pool count, guarded claims and one controlled transaction through definitive inclusion before reopening writes. Verify restart recovery and health.

The existing bounded auto-migrator target remains **`table-signer-tx-20261030-authority-contract`** until that coordinated switch. Publishing this source does not authorize bypassing the transition gates. After any uncertain send, rollback preserves SQL and volume evidence and must not restart the legacy broadcaster against the new queue.

## Validation

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
docker run --rm --platform linux/amd64 --network none \
  -e PYTHONPATH=/workspace -v "$PWD:/workspace:ro" --entrypoint python \
  structs/structs-tsa:v0.22.0 /workspace/tests/cli_integration.py
docker run --rm --platform linux/amd64 --network none \
  -e PYTHONPATH=/workspace -v "$PWD:/workspace:ro" --entrypoint python \
  structs/structs-tsa:v0.22.0 /workspace/tests/inventory_cli_integration.py
docker run --rm --platform linux/amd64 --network none \
  -e TSA_DISPOSABLE_TEST=network-none -e PYTHONPATH=/workspace \
  -v "$PWD:/workspace:ro" --entrypoint python \
  structs/structs-tsa:v0.22.0 /workspace/tests/chain_integration.py
```

The last test creates a private validator/genesis inside the network-disabled container, simulates and commits a transaction, registers a newly generated key using the actual nonce proof, and signs with that new key. It never reaches testnet.

`tests/run_database_integration.py` is the workspace harness for full Sqitch deployment on two disposable PostgreSQL instances, real CLI signing, SQL-volume-loss recovery and actual daemon health/shutdown under `structs_tsa`. It requires adjacent `structs-pg`, the labelled disposable `structs-v022-pg` image and the local candidate tag `structs-v022-tsa-candidate:development`. It creates an internal Docker network and removes its containers/network afterward. Run the companion signer SQL suites in a disposable database only. Fixture RPCs test recovery behavior; the network-disabled node test separately checks real chain semantics.
