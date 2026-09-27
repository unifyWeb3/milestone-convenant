# Typed Grant Covenant architecture

## Boundary

```text
browser wallet
    │ signs create / submit / review / withdraw
    ▼
GenLayer Intelligent Contract (GenVM)
    │ stores locked claim specifications and authorization
    │ enters a non-deterministic block only for evidence retrieval
    ▼
independent validator executions
    │ canonical source → normalized observation → PASS / FAIL / UNKNOWN
    ▼
consensus result stored in contract state
    │ approved result emits an idempotent finalization callback
    ▼
grantee withdrawal transaction
    │ external EVM message emits GEN transfer on finalization
    ▼
Studio-dev explorer + wallet balance
```

## Claim model

A claim is a fixed `(type, target, parameter)` tuple. The canonical claim string is stored at creation and its Keccak fingerprint is also stored. There is no arbitrary Python expression, shell command, LLM-generated predicate, or mutable post-creation criterion.

### `github_commit`

Input:

```text
owner/repo@<40 lowercase hex characters>
```

The contract canonicalizes GitHub web/API forms to the same reference. The evidence must point to the matching `/commit/<sha>` URL. During review, validators fetch:

```text
https://api.github.com/repos/{owner}/{repo}/commits/{sha}
```

They compare the returned `sha` to the locked SHA. A 404 is a business rejection; a rate-limit/server response is `UNKNOWN`.

### `url_marker`

Input:

```text
https://allow-listed-host/path
marker text
```

Validators fetch the canonical URL and compare the exact marker in a bounded response. A missing page is a rejection; an unavailable or malformed source is `UNKNOWN`.

## State model

Business state and GenLayer protocol state are intentionally separate.

| Layer | Values |
| --- | --- |
| Milestone business state | `LOCKED`, `SUBMITTED`, `APPROVED`, `REJECTED`, `UNDETERMINED`, `WITHDRAWABLE`, `WITHDRAWAL_SCHEDULED` |
| Payout state | `NOT_SCHEDULED`, `PENDING_FINALITY`, `WITHDRAWABLE`, `TRANSFER_EMITTED` |
| GenLayer protocol state | `PENDING`, `PROPOSING`, `COMMITTING`, `REVEALING`, `ACCEPTED`, `UNDETERMINED`, `FINALIZED`, timeouts, and appeal states |

A failed or undetermined source does not release funds. A passing review is not treated as final until the relevant GenLayer transaction lifecycle is followed. `TRANSFER_EMITTED` records that a transfer message was scheduled; release evidence additionally requires the finalized message to be delivered and the covenant balance to decrease.

## Deliberate exclusions

- No DAO governance or committee voting.
- No arbitrary event indexing or cross-chain support.
- No LLM authority over objective predicates.
- No production audit claim.
- No real-value or stablecoin settlement.
- No cancellation or funder refund path in this first slice; rejected and undetermined milestones remain locked and must be handled by a future, explicitly authorized state transition.
