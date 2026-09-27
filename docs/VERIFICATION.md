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
| Real public URL evidence | Corrected transfer probe used the typed `github_commit` flow; the earlier superseded run also returned `PASS` / `marker_present` for the raw README marker | partial; corrected URL-marker run pending |
| Finalized review | Corrected review `0x87da5ae1…` reached `Finalized`; milestone became `WITHDRAWABLE` | passed |
| Withdrawal | Corrected withdraw `0x0209b8f8…` reached `Finalized`; contract balance `100 → 0`, no failed refund, grant `COMPLETED` | passed |
| Browser UI | `npm run build` passed; desktop browser was unavailable for interactive wallet verification | partial |
| Secret scan | Key-material scan found only the documented `GENLAYER_PRIVATE_KEY` variable name and public transaction IDs; no mnemonic or private-key value is committed | passed |

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
`COMPLETED`/`TRANSFER_EMITTED` business state. The raw URL-marker flow remains
marked partial until it is rerun on the corrected deployment.

## Evidence rules

- A submitted transaction is not a successful deployment until its status and execution result are inspected.
- An `ACCEPTED` result is not final settlement.
- A UI badge is not authoritative; the contract state, protocol receipt, explorer, and balance are.
- Synthetic direct-test fixtures are test evidence only. The public demo must use real public inputs.
- Any unavailable check remains listed as unverified rather than being described as passed.
