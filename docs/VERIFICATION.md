# Verification record

This file is intentionally a live evidence log. It must not claim completion before the corresponding observation exists.

## Verification log

| Check | Evidence | Status |
| --- | --- | --- |
| Direct contract tests | `GENVM_VERSION=v0.6.0-rc5 .venv/bin/pytest -p no:gltest -q` → `10 passed` | passed |
| Contract lint/schema | `genvm-lint check contracts/typed_grant_covenant.py` → lint and SDK validation passed; 9 methods | passed |
| Canonical/malformed/auth/conflict cases | Direct tests cover URL/SHA canonicalization, malformed shapes, identity checks, authorization, validator agreement/conflict, rejection, `UNKNOWN`, and payout guards | passed |
| Studio-dev code/schema probe | `gen_getContractSchemaForCode` against `https://studio-dev.genlayer.com/api` → 9 methods on GenVM `v0.3.0-rc7` | passed |
| Studio-dev deployment | Corrected contract at `0xB89d3EC54BF8Bc10b328489c54Cb4C58D05b8a87`; deploy `0x7d1c6f89…` finalized with `FINISHED_WITH_RETURN` | passed |
| Real GitHub evidence | `genlayerlabs/genlayer-py@dd25ef7f…` returned `PASS` / `commit_present` on the corrected run | passed |
| Real public URL evidence | `url_marker` claim on the raw genlayer-py README with marker `GenLayer` returned `PASS` / `marker_present` / `url_marker_found`; review `0x46936db3…` finalized, then withdraw `0xc36e9da6…` moved the covenant balance `100 → 0` | passed |
| Finalized review | Corrected review `0x87da5ae1…` reached `Finalized`; milestone became `WITHDRAWABLE` | passed |
| Withdrawal | Corrected withdraw `0x0209b8f8…` reached `Finalized`; contract balance `100 → 0`, no failed refund, grant `COMPLETED` | passed |
| Browser UI | Client rebuilt pointed at `0xb2044176…` and served over HTTP with every asset returning `200`; static checks confirm chain `61997`, the Studio-dev RPC endpoint, and the EIP-1193 methods in the built bundle. The interactive wallet flow was re-attempted on 2026-09-28 and is still unverified: no desktop browser is connected, so no EIP-1193 provider exists | unverified |
| Secret scan | No key material is present anywhere in the checkout: the demo runner rejects any account file inside the repository, `artifacts/` holds public run records only, and the one throwaway account file a previous run had written there has been deleted. Every 32-byte hex literal in the tracked docs resolves on chain to a public transaction | passed |

## Live observation: superseded transfer path

The pre-fix Studio-dev run used the current pinned contract header and produced
these public transaction IDs:

- deploy: `0xb203a32cad1fe6c716789b77ed18a77ba2c2c8740a4ee7eb9408466488e0af17`
- create grant: `0xd475f4cfd071e568273ed85ee19bd16eb846f739d610babf6ba7017bd125cc95`
- GitHub review: `0x107237487c84593d93f6cf002ea189db6f7dbd7701c2753afc5ebfd9a3dd93c8`
- URL-marker review: `0x95db9dddb716505ccc96e4ac1b5f81731da9b46cfcf36d9e7ed860ac0302ac05`
- withdrawals: `0x9572f74b244ef8b7c5bfd3b9ad50adc410b2e40c8965041115596d6b6b94ffae`, `0xe8242575d09e24a550135809430dbd6c6d5312875b61bc5af134aa71949d7c0f`

The contract state showed both milestones as `PASS` and
`payout_status=TRANSFER_EMITTED`, but the finalized receipts recorded
`message_value_effects[*].skipped=true` and refunded message value. The
covenant balance stayed at `300`; therefore this run is a useful negative
observation, not successful payout evidence. The contract now uses the
`gl.evm.contract_interface` external-message path for EOA transfers.

## Corrected live observation

The compact public record is in
[`docs/evidence/studio-dev-2026-09-27.json`](evidence/studio-dev-2026-09-27.json).
It records the corrected contract address, real GitHub commit, all finalized
transaction IDs, the `100 → 0` covenant balance change, and the final
`COMPLETED`/`TRANSFER_EMITTED` business state.

## Live observation: corrected `url_marker` run

The raw URL-marker claim was rerun end to end on a fresh deployment of the
current contract source. The record is in
[`docs/evidence/studio-dev-2026-09-27-url-marker.json`](evidence/studio-dev-2026-09-27-url-marker.json).

- deployed contract: `0xb20441769A60a501e8B47E196216f1456d7783c1`; the code in
  the deploy transaction record is byte-identical to
  `contracts/typed_grant_covenant.py` (`sha256 063cb121…`)
- claim: `url_marker` on
  `https://raw.githubusercontent.com/genlayerlabs/genlayer-py/dd25ef7f43e99a14b8fe42a64e01374845ad4d2d/README.md`
  with marker `GenLayer`
- deploy `0x9b68ba0d…`, create `0x757b6a24…`, submit `0xbf33d709…`,
  review `0x46936db3…`, finalization callback `0xc4e18922…`, withdraw `0xc36e9da6…`
  — every one `Finalized` with `MAJORITY_AGREE` / `FINISHED_WITH_RETURN`
- review verdict `PASS`, `observed=marker_present`, `reason=url_marker_found`
- business state per step: `LOCKED` → `SUBMITTED` → `APPROVED` /
  `PENDING_FINALITY` → `WITHDRAWABLE` after the callback that reports
  `triggered_on=finalized` → `WITHDRAWAL_SCHEDULED` / `TRANSFER_EMITTED`
- covenant balance `0 → 100 → 100 → 0`; the withdraw emitted an external
  message of value `100` to the grantee and the balance decrease proves delivery
- grant `COMPLETED` with `locked=0`

The runner is `scripts/run_url_marker_demo.py`. It reads contract state with
`latest-final`, and it re-reads each transaction record after the lifecycle
reports `Finalized`; a record read immediately after submission still carries
in-flight consensus fields and can misreport a transaction that finalized
successfully.

## Known limitation: stranded preview grants

The Studio-dev endpoint stalled, reset connections, and dropped requests
repeatedly during the live run. Four earlier automated attempts therefore ended
while their accounts existed only in process memory. Their grants still hold
test GEN on the temporary preview network, and there is no way to act on them:

| Contract | Grant | Re-checked state | Cause of abandonment |
| --- | --- | --- | --- |
| `0xB89d3EC54BF8Bc10b328489c54Cb4C58D05b8a87` | `1` | `ACTIVE`, `LOCKED`, `NOT_SCHEDULED`, 100 test GEN locked, balance `100` | the run validated `result_name` on a record read before finalization and aborted |
| `0x6c9b5591bFCe7d7d70Ce1232F92412B749b1Ab40` | `0` | `ACTIVE`, `WITHDRAWABLE`, `PASS` / `marker_present`, 100 test GEN locked, balance `100` | an SDK read without a timeout blocked the process indefinitely |
| `0x98b935711AF3e0Cf8E5B2f22B7c03883052460eB` | `0` | `ACTIVE`, `WITHDRAWABLE`, `PASS` / `marker_present`, 100 test GEN locked, balance `100` | a transient error while reading a balance between two writes |
| not recorded | not recorded | not observable; Studio-dev exposes no transaction index to recover the address | the endpoint reset a connection during the deployment send, before the run persisted its first transaction |

Every state in that table was re-read from `latest-final` during the cleanup
pass on 2026-09-27, after the completed `url_marker` run. The completed
deployment `0xb2044176…` was re-checked in the same pass and is still
`COMPLETED` with `locked=0` and the contract balance `0`.

**Decision: the contract is left unchanged and these grants are recorded as a
known limitation.** The slice deliberately has no cancellation or funder refund
path, and this record does not add one. Two facts make an in-place repair
impossible in any case: the grantee of every stranded grant is an account whose
key was discarded, so the `withdraw` authorization cannot be exercised, and the
funder key was discarded as well, so a funder-initiated action would be equally
unreachable. The 100-unit payouts are therefore unrecoverable on this network
until Studio-dev resets.

Releasing a locked milestone would require a new, explicitly authorized contract
feature — for example a funder-initiated cancellation that returns the locked
value to the funder, restricted to milestones that have never reached
`WITHDRAWABLE`, with its own tests and live evidence. That is a separate change
with its own risk review, and it is not started here.

The demo runner was changed because of these failures rather than worked around:
every HTTP call now has a timeout, submissions are retried only while the
sender's nonce proves the node never accepted them, observations that sit
between two writes can no longer abort a run, the record is written after every
step, and `--account-file`/`--grant-id` allow a failed run to be finished with
the same accounts instead of being restarted from a new deployment. Key
persistence is now refused inside the repository, so a resumed run keeps its
throwaway keys outside the checkout.

## Browser wallet verification: unverified

The interactive client flow is **not verified**, and nothing in this section
should be read as a wallet result. The attempt was repeated on 2026-09-28,
after an environment restart, and every call to reach a desktop browser in this
session returned the same blocker:

```text
browser.disconnected — No desktop browser is connected to this session.
Open this session in the desktop app, enable the experimental browser setting,
and wait for it to connect.
```

Connecting the browser is a desktop-side action that this environment cannot
perform, so the attempt stopped at the blocker. Without a connected browser
there is no EIP-1193 provider, and therefore no observation of any of the
following: wallet connection, the chain-61997 switch or `wallet_addEthereumChain`,
contract configuration, or the create → submit → review → withdraw clicks and
their lifecycle and error rendering. No wallet key was placed in the repository,
and no simulated provider was substituted for a real one.

### What was done instead, and what it does not prove

The client was prepared so that a browser test can run without further setup.
These are build and transport observations, not wallet observations:

- `frontend/.env` (gitignored, public value only) pins
  `VITE_CONTRACT_ADDRESS=0xb20441769A60a501e8B47E196216f1456d7783c1`, the
  verified `url_marker` deployment. `npm run build` succeeds and the address is
  present in the emitted bundle, so the client opens already pointed at the
  contract that this repository's evidence covers.
- The built client was served with `vite preview` on `127.0.0.1:4173` and every
  asset resolved: `/` → `200 text/html`, `/assets/index-*.js` → `200
  text/javascript` (621774 bytes), `/assets/ccip-*.js` → `200
  text/javascript`, `/assets/index-*.css` → `200 text/css`. No asset 404s and
  no empty chunk, so a browser test will not fail on asset wiring. The preview
  server was stopped afterwards.
- `genlayer-js` resolves to the pinned `2.0.0-rc.1` in `package-lock.json`.
- The source and the built bundle both contain chain id `61997`, the
  `https://studio-dev.genlayer.com/api` endpoint from `studioDevnet`, and the
  `eth_requestAccounts`, `wallet_switchEthereumChain`, and
  `gen_getTransactionLifecycle` calls the flow depends on.

None of this exercises a wallet, a signature, a lifecycle transition, or the
error paths, so the browser row stays `unverified`. No defect was found in the
client by these checks, and no contract or live evidence flow was changed on
their basis.

To close this row, a reviewer needs to open the session in the desktop app with
the experimental browser setting enabled, connect a funded Studio-dev wallet on
chain 61997, and repeat the flow. The client is already pointed at
`0xb2044176…`, so the flow can start immediately. The contract's state for a
fresh grant was re-read on 2026-09-28: `grant_count=1`, balance `0`, grant `0`
`COMPLETED` with `locked=0` and milestone `WITHDRAWAL_SCHEDULED` /
`TRANSFER_EMITTED`. A new grant therefore takes grant id `1`. Note that the
grantee of the completed grant, `0x32e5Df17…`, is an account whose key was
discarded when its run finished, so a browser test must use its own funded
wallet for both the funder and the grantee role.

## Evidence rules

- A submitted transaction is not a successful deployment until its status and execution result are inspected.
- An `ACCEPTED` result is not final settlement.
- A UI badge is not authoritative; the contract state, protocol receipt, explorer, and balance are.
- Synthetic direct-test fixtures are test evidence only. The public demo must use real public inputs.
- Any unavailable check remains listed as unverified rather than being described as passed.
