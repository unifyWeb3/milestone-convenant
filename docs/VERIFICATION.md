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
| Browser UI | `npm run build` passed; interactive wallet verification is still unverified because no desktop browser is connected to this session | unverified |
| Secret scan | Key-material scan of every file added or changed in this commit found only public transaction IDs and the documented `GENLAYER_PRIVATE_KEY` / `GENLAYER_FUNDER_PRIVATE_KEY` / `GENLAYER_GRANTEE_PRIVATE_KEY` variable names; the run's throwaway test keys live only in the gitignored `artifacts/` directory | passed |

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

## Live observation: abandoned preview attempts

The Studio-dev endpoint stalled, reset connections, and dropped requests
repeatedly during this run. Three earlier automated attempts therefore ended
while their accounts existed only in process memory, which stranded their
grants on the temporary preview network. None of this state is released test
GEN, and there is no cancellation path in this slice, so each entry below is
permanent on that network:

| Contract | Grant | Final state | Cause |
| --- | --- | --- | --- |
| `0xB89d3EC54BF8Bc10b328489c54Cb4C58D05b8a87` | `1` | `ACTIVE`, `LOCKED`, 100 test GEN locked | the run validated `result_name` on a record read before finalization and aborted |
| `0x6c9b5591bFCe7d7d70Ce1232F92412B749b1Ab40` | `0` | `ACTIVE`, `WITHDRAWABLE`, 100 test GEN locked | an SDK read without a timeout blocked the process indefinitely |
| `0x98b935711AF3e0Cf8E5B2f22B7c03883052460eB` | `0` | `ACTIVE`, `WITHDRAWABLE`, 100 test GEN locked | a transient error while reading a balance between two writes |

A fourth attempt deployed a contract whose address was never recorded: the run
aborted before it persisted its first transaction, and Studio-dev exposes no
transaction index to recover the address from.

The demo script was changed because of these failures rather than worked
around: every HTTP call now has a timeout, submissions are retried only while
the sender's nonce proves the node never accepted them, observations that sit
between two writes can no longer abort a run, the record is written after every
step, and `--account-file`/`--grant-id` allow a failed run to be finished with
the same accounts instead of being restarted from a new deployment.

## Evidence rules

- A submitted transaction is not a successful deployment until its status and execution result are inspected.
- An `ACCEPTED` result is not final settlement.
- A UI badge is not authoritative; the contract state, protocol receipt, explorer, and balance are.
- Synthetic direct-test fixtures are test evidence only. The public demo must use real public inputs.
- Any unavailable check remains listed as unverified rather than being described as passed.
