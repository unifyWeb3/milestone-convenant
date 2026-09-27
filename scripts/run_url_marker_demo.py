"""Run the real ``url_marker`` flow on Studio-dev and emit an evidence record.

The script performs the complete public flow and verifies every step against
finalized chain state:

1. deploy the covenant from ``contracts/typed_grant_covenant.py`` (or reuse an
   address passed with ``--contract``)
2. a funder creates a grant with one immutable ``url_marker`` claim and locks
   test GEN equal to the payout
3. the grantee submits the canonical evidence URL
4. the grantee triggers the validator-backed review
5. the internal finalization callback marks the milestone withdrawable
6. the grantee withdraws and the external EVM message moves test GEN

Reads use ``latest-final`` so a recorded state is never an unaccepted one, and
every write is confirmed from the transaction record only after the GenLayer
lifecycle reports ``Finalized``.

No key material belongs in this repository. ``GENLAYER_FUNDER_PRIVATE_KEY`` and
``GENLAYER_GRANTEE_PRIVATE_KEY`` are read from the process environment only and
are never written to disk. Without them both actors are ephemeral Studio faucet
accounts whose keys are discarded when the process exits, so a grant created by
an ephemeral grantee cannot be resumed later. Because Studio-dev regularly
stalls or drops a request, ``--account-file`` can persist the run's throwaway
test keys so a failed run is finished with ``--contract`` and ``--grant-id``
instead of being restarted from a new deployment. The file must be supplied
explicitly and must resolve outside this checkout; any path inside it,
``artifacts/`` included, is rejected. Those keys are unencrypted test accounts
on a temporary preview network; never use them for real funds.

The raw run record is written after every step to ``artifacts/`` (gitignored)
and echoed to stdout as JSON so it can be reviewed before it becomes public
evidence. ``artifacts/`` holds public run records only and must never hold keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet
from genlayer_py.types import TransactionHashVariant

# Resolved so a checkout reached through a symlinked path is still recognized
# as the repository when an account-file path is checked against it.
ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SOURCE = ROOT / "contracts" / "typed_grant_covenant.py"
ARTIFACTS = ROOT / "artifacts"
RPC = "https://studio-dev.genlayer.com/api"

# Real, immutable public input: the genlayer-py README at a pinned commit.
DEFAULT_CLAIM_URL = (
    "https://raw.githubusercontent.com/genlayerlabs/genlayer-py/"
    "dd25ef7f43e99a14b8fe42a64e01374845ad4d2d/README.md"
)
DEFAULT_MARKER = "GenLayer"
DEFAULT_TITLE = "Publish the SDK README marker"
DEFAULT_PAYOUT = 100
FUND_AMOUNT = 10**18
CONSENSUS_ROTATIONS = 1
REQUEST_TIMEOUT = 90
FINALIZED_POLL_SECONDS = 1800
FINALIZATION_CALLBACK_POLL_SECONDS = 900
READ_ATTEMPTS = 6


class ReceiptUnavailable(Exception):
    """The SDK's receipt endpoint is not needed to track consensus."""


def install_request_timeouts() -> None:
    """Give every SDK HTTP call a timeout.

    ``genlayer_py.provider`` calls ``requests.post`` without a timeout, and
    Studio-dev regularly stalls a read for minutes under load. Without a
    timeout a single stalled call blocks the run forever while the accounts it
    controls become unrecoverable, so a default timeout is installed globally
    and left to explicit callers.
    """
    original_post = requests.post

    def post_with_default_timeout(url, *args, **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        return original_post(url, *args, **kwargs)

    requests.post = post_with_default_timeout


def progress(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def rpc(method: str, params: list, timeout: int = 60, attempts: int = 6):
    """One JSON-RPC call that tolerates the preview network's flaky reads."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                RPC,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "typed-grant-url-marker",
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            last_error = error
            time.sleep(3 + 2 * attempt)
            continue
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload.get("result")
    raise RuntimeError(f"{method} failed after {attempts} attempts: {last_error}")


def full_record(evm_hash: str, timeout_seconds: int = 300) -> dict:
    deadline = time.time() + timeout_seconds
    while True:
        try:
            record = rpc("eth_getTransactionByHash", [evm_hash], timeout=60, attempts=2)
        except RuntimeError:
            record = None
        if record:
            return record
        if time.time() >= deadline:
            raise TimeoutError(f"no transaction record for {evm_hash}")
        time.sleep(4)


def await_finalized(tx_id: str, timeout_seconds: int = FINALIZED_POLL_SECONDS) -> str:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            lifecycle = rpc("gen_getTransactionLifecycle", [{"txId": tx_id}], timeout=60) or {}
        except RuntimeError as error:
            # A read timeout on the lifecycle endpoint is not a chain failure.
            last_error = error
            time.sleep(5)
            continue
        status = lifecycle.get("storedStatus")
        if status == "Finalized":
            return status
        if status in {"Canceled", "Undetermined"}:
            raise RuntimeError(f"transaction reached {status}")
        time.sleep(5)
    raise RuntimeError(f"transaction {tx_id} did not finalize: {last_error}")


def wait_until_settled(evm_hash: str, tx_id: str) -> dict:
    """Return the transaction record as it stands after finalization.

    The record is read again on purpose: a record fetched right after
    submission still carries the in-flight consensus fields, so validating
    ``result_name`` on that snapshot can report a transaction that finalized
    successfully as undetermined.
    """
    status = await_finalized(tx_id)
    record = full_record(evm_hash)
    if record.get("result_name") != "MAJORITY_AGREE":
        raise RuntimeError(
            f"consensus was {record.get('result_name')} after {status}: "
            f"{json.dumps(record.get('consensus_history'))[:400]}"
        )
    if record.get("txExecutionResultName") != "FINISHED_WITH_RETURN":
        raise RuntimeError(
            f"execution was {record.get('txExecutionResultName')}: "
            f"{json.dumps(record.get('txExecutionResult'))[:400]}"
        )
    record["observed_lifecycle"] = status
    return record


def submit(client, account, address: str, function_name: str, args: list, value: int = 0) -> dict:
    """Submit one write and return its verified, finalized transaction record."""
    fees = estimate_write_fees(client, account, address, function_name, args, value)
    evm_hash = send_write(client, account, address, function_name, args, value, fees)
    progress(f"submitted {function_name} {evm_hash}")
    pending = full_record(evm_hash)
    tx_id = pending.get("tx_id") or evm_hash
    record = wait_until_settled(evm_hash, tx_id)
    progress(f"finalized {function_name} {tx_id}")
    return {
        "function": function_name,
        "evm_transaction": evm_hash,
        "consensus_transaction": tx_id,
        "lifecycle": record["observed_lifecycle"],
        "result_name": record.get("result_name"),
        "execution": record.get("txExecutionResultName"),
        "user_value": (record.get("data") or {}).get("user_value"),
        "messages": record.get("messages"),
        "triggered_transactions": record.get("triggered_transactions"),
        "return": record.get("result"),
    }


def deploy(client, account, code: str) -> tuple[str, dict]:
    estimate = retry(
        "fee estimate deploy",
        lambda: client.estimate_transaction_fees({"rotations": [CONSENSUS_ROTATIONS]}),
    )
    fees = {"distribution": estimate["distribution"], "feeValue": estimate["feeValue"]}
    evm_hash = send_deploy(client, account, code, fees)
    progress(f"submitted deploy {evm_hash}")
    pending = full_record(evm_hash)
    record = wait_until_settled(evm_hash, pending.get("tx_id") or evm_hash)
    progress(f"finalized deploy {record.get('tx_id') or evm_hash}")
    data = record.get("data") or {}
    address = data.get("contract_address")
    if not address:
        raise RuntimeError("finalized deployment did not expose a contract address")
    return address, {
        "function": "deploy",
        "evm_transaction": evm_hash,
        "consensus_transaction": record.get("tx_id") or evm_hash,
        "lifecycle": record["observed_lifecycle"],
        "result_name": record.get("result_name"),
        "execution": record.get("txExecutionResultName"),
        "contract_address": address,
    }


def retry(label: str, call, attempts: int = READ_ATTEMPTS):
    """Call ``call`` until it succeeds, reporting every failed attempt."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as error:  # the preview node stalls and resets routinely
            last_error = error
            progress(f"{label} retry {attempt + 1}: {str(error)[:140]}")
            time.sleep(5 + 3 * attempt)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}")


def read(client, address: str, function_name: str, args: list | None = None):
    """Read finalized state, retrying the preview network's transient errors."""
    return retry(
        f"read {function_name}",
        lambda: client.read_contract(
            address=address,
            function_name=function_name,
            args=args or [],
            transaction_hash_variant=TransactionHashVariant.LATEST_FINAL,
        ),
    )


def estimate_write_fees(
    client, account, address: str, function_name: str, args: list, value: int
) -> dict:
    estimate = retry(
        f"fee estimate {function_name}",
        lambda: client.estimate_transaction_fees_for_write(
            address=address,
            function_name=function_name,
            account=account,
            args=args,
            value=value,
            options={"rotations": [CONSENSUS_ROTATIONS]},
        ),
    )
    fees = {"distribution": estimate["distribution"], "feeValue": estimate["feeValue"]}
    if estimate.get("messageAllocations"):
        fees["messageAllocations"] = estimate["messageAllocations"]
    return fees


def account_balance(address: str) -> int:
    """Read a native balance over the retrying transport.

    ``web3.eth.get_balance`` goes through the SDK provider, which the busy
    preview node can fail transiently; the balance is evidence, not flow
    control, so it is read with the same retry policy as the other calls.
    """
    return int(rpc("eth_getBalance", [address, "latest"], timeout=60, attempts=READ_ATTEMPTS), 16)


def observe(read_call, *args):
    """Best-effort read: record the failure instead of aborting the run.

    Reads that happen between two writes must never be fatal. Losing the
    account keys mid-flow would strand the grant, so an observation that
    cannot be collected is stored as an error and the flow continues.
    """
    try:
        return read_call(*args)
    except Exception as error:
        progress(f"observation unavailable: {str(error)[:160]}")
        return {"error": str(error)[:200]}


def await_payout_withdrawable(client, address: str, grant_id: str, index: int) -> dict:
    deadline = time.time() + FINALIZATION_CALLBACK_POLL_SECONDS
    milestone = read(client, address, "get_milestone", [grant_id, index])
    while milestone["payout_status"] != "WITHDRAWABLE" and time.time() < deadline:
        progress(f"finalization callback pending; payout_status={milestone['payout_status']}")
        time.sleep(10)
        milestone = read(client, address, "get_milestone", [grant_id, index])
    if milestone["payout_status"] != "WITHDRAWABLE":
        raise RuntimeError(
            f"finalization callback did not run; payout_status={milestone['payout_status']}"
        )
    return milestone


def is_inside_repository(path: Path) -> bool:
    """Return whether ``path`` resolves inside this checkout.

    Symlinks are resolved first, so a path outside the checkout that points
    into it is still rejected.
    """
    return path.is_relative_to(ROOT)


def resolve_accounts(options) -> tuple[object, object]:
    """Return the funder and grantee accounts for this run.

    Keys come from the process environment, or from ``--account-file`` when the
    caller explicitly supplies a file outside this repository. An existing
    account file is reused so a run that was interrupted can be finished with
    the same accounts. The default run keeps every key in memory only, which
    means a grant created by an ephemeral grantee cannot be resumed once the
    process exits.
    """
    funder_key = os.environ.get("GENLAYER_FUNDER_PRIVATE_KEY")
    grantee_key = os.environ.get("GENLAYER_GRANTEE_PRIVATE_KEY")
    if funder_key and grantee_key:
        return create_account(funder_key), create_account(grantee_key)
    if not options.account_file:
        return create_account(funder_key), create_account(grantee_key)

    account_file = Path(options.account_file).resolve()
    if is_inside_repository(account_file):
        raise SystemExit(
            f"refusing to keep private keys inside the repository: {account_file}. "
            "Pass a path outside the checkout, or use the "
            "GENLAYER_FUNDER_PRIVATE_KEY and GENLAYER_GRANTEE_PRIVATE_KEY "
            "environment variables. artifacts/ holds public run records only."
        )
    if account_file.exists():
        stored = json.loads(account_file.read_text())
        progress(f"reusing demo accounts from {account_file}")
        return create_account(stored["funder"]), create_account(stored["grantee"])

    funder = create_account(funder_key)
    grantee = create_account(grantee_key)
    account_file.parent.mkdir(parents=True, exist_ok=True)
    account_file.write_text(
        json.dumps({"funder": funder.key.hex(), "grantee": grantee.key.hex()}, indent=2) + "\n"
    )
    account_file.chmod(0o600)
    progress(f"wrote demo account keys to {account_file} (outside the repository, unencrypted test keys)")
    return funder, grantee


def pending_nonce(address: str) -> int:
    return int(
        rpc("eth_getTransactionCount", [address, "pending"], timeout=60, attempts=READ_ATTEMPTS),
        16,
    )


def send_once(client, account, description: str, action) -> str:
    """Run one submission and return its EVM transaction hash.

    The submission is retried only while the sender's nonce is unchanged, which
    proves the node never accepted the transaction. A reset connection raised
    while the node was still assembling the transaction is common on Studio-dev
    and must not cost the run its accounts.
    """
    last_error: Exception | None = None
    for attempt in range(READ_ATTEMPTS):
        nonce_before = pending_nonce(account.address)
        captured: dict[str, str] = {}

        def capture_receipt(evm_hash):
            captured["evm_hash"] = str(evm_hash)
            raise ReceiptUnavailable

        # Studio can finalize consensus while leaving eth_getTransactionReceipt
        # open. Capture the EVM hash and read the consensus record instead.
        client.w3.eth.wait_for_transaction_receipt = capture_receipt
        try:
            action()
        except ReceiptUnavailable:
            pass
        except Exception as error:
            last_error = error
            if pending_nonce(account.address) != nonce_before:
                raise RuntimeError(
                    f"{description} failed after the node accepted it ({str(error)[:200]}); "
                    "reconcile the sender's transactions before trusting the state."
                ) from error
            progress(f"send {description} retry {attempt + 1}: {str(error)[:140]}")
            time.sleep(5 + 3 * attempt)
            continue
        if captured.get("evm_hash"):
            return captured["evm_hash"]
        raise RuntimeError(f"{description} returned without an EVM transaction hash")
    raise RuntimeError(
        f"{description} was not submitted after {READ_ATTEMPTS} attempts: {last_error}"
    )


def send_write(client, account, address: str, function_name: str, args: list, value: int, fees) -> str:
    return send_once(
        client,
        account,
        function_name,
        lambda: client.write_contract(
            address=address,
            function_name=function_name,
            account=account,
            args=args,
            value=value,
            consensus_max_rotations=CONSENSUS_ROTATIONS,
            fees=fees,
        ),
    )


def send_deploy(client, account, code: str, fees) -> str:
    return send_once(
        client,
        account,
        "deploy",
        lambda: client.deploy_contract(
            code=code,
            account=account,
            args=[],
            consensus_max_rotations=CONSENSUS_ROTATIONS,
            fees=fees,
        ),
    )


def fund(client, account) -> None:
    retry(f"fund {account.address}", lambda: client.fund_account(account.address, FUND_AMOUNT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", help="use an existing deployed covenant")
    parser.add_argument("--deploy", action="store_true", help="deploy the covenant first")
    parser.add_argument("--claim-url", default=DEFAULT_CLAIM_URL)
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--payout", type=int, default=DEFAULT_PAYOUT)
    parser.add_argument(
        "--grant-id",
        default="",
        help="continue an existing grant instead of creating one; the locked claim "
        "is read from the contract",
    )
    parser.add_argument("--output", default=str(ARTIFACTS / "url_marker_run.json"))
    parser.add_argument(
        "--account-file",
        default="",
        help="reuse or store the run's throwaway test keys in this file. It must be "
        "supplied explicitly and must resolve outside this checkout; a path inside "
        "the repository, artifacts/ included, is rejected. Prefer the "
        "GENLAYER_FUNDER_PRIVATE_KEY and GENLAYER_GRANTEE_PRIVATE_KEY environment "
        "variables; never use these accounts for real funds",
    )
    options = parser.parse_args()
    if not options.deploy and not options.contract:
        parser.error("pass --deploy or --contract ADDRESS")
    install_request_timeouts()

    funder, grantee = resolve_accounts(options)
    funder_client = create_client(chain=studio_devnet, account=funder)
    grantee_client = create_client(chain=studio_devnet, account=grantee)
    for client, account in ((funder_client, funder), (grantee_client, grantee)):
        fund(client, account)

    record: dict = {
        "network": "GenLayer Studio-dev",
        "rpc": RPC,
        "chain_id": funder_client.chain_id,
        "state_read_variant": TransactionHashVariant.LATEST_FINAL.value,
        "observed_on": time.strftime("%Y-%m-%d"),
        "actors": {"funder": funder.address, "grantee": grantee.address},
        "claim": {
            "type": "url_marker",
            "target": options.claim_url,
            "parameter": options.marker,
            "title": options.title,
            "payout": options.payout,
        },
        "transactions": [],
    }
    output = Path(options.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def save(step: str) -> None:
        """Persist after every step so a later failure keeps the evidence."""
        record["completed_steps"] = [
            entry["function"] for entry in record["transactions"] if not entry.get("skipped")
        ] + ([step] if step else [])
        output.write_text(json.dumps(record, indent=2) + "\n")
        progress(f"recorded {step or 'start'} -> {output}")

    if options.deploy:
        code = CONTRACT_SOURCE.read_text()
        address, deploy_tx = deploy(funder_client, funder, code)
        record["contract_address"] = address
        record["contract_code_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
        record["transactions"].append(deploy_tx)
        save("deploy")
    else:
        address = options.contract
        record["contract_address"] = address
        save("")

    record["grant_count_before"] = read(funder_client, address, "get_grant_count")
    record["contract_balance_before_create"] = observe(
        read, funder_client, address, "get_contract_balance"
    )

    if options.grant_id:
        # Continue a grant that already holds the locked claim.
        grant_id = str(options.grant_id)
        claim_url = options.claim_url
        locked = read(funder_client, address, "get_milestone", [grant_id, 0])
        record["grant_id"] = grant_id
        record["resumed_grant"] = True
        record["claim"] = {
            "type": locked["claim_type"],
            "target": locked["claim_target"],
            "parameter": locked["claim_parameter"],
            "fingerprint": locked["claim_fingerprint"],
            "status_at_resume": locked["status"],
            "payout_status_at_resume": locked["payout_status"],
        }
        claim_url = locked["claim_target"]
        if locked["status"] not in ("LOCKED", "REJECTED", "UNDETERMINED"):
            if locked["status"] == "SUBMITTED":
                progress("grant is already submitted; skipping submit_evidence")
                record["transactions"].append({"function": "submit_evidence", "skipped": True})
            elif locked["payout_status"] == "WITHDRAWABLE":
                progress("milestone is withdrawable; skipping submit_evidence and review")
                record["transactions"].append({"function": "submit_evidence", "skipped": True})
                record["transactions"].append({"function": "review_milestone", "skipped": True})
        else:
            submit_tx = submit(
                grantee_client, grantee, address, "submit_evidence", [grant_id, 0, claim_url]
            )
            record["transactions"].append(submit_tx)
            record["state_after_submit"] = observe(
                read, funder_client, address, "get_milestone", [grant_id, 0]
            )
            save("submit_evidence")
            review_tx = submit(grantee_client, grantee, address, "review_milestone", [grant_id, 0])
            record["transactions"].append(review_tx)
        if locked["payout_status"] != "WITHDRAWABLE":
            record["state_after_finalization"] = await_payout_withdrawable(
                funder_client, address, grant_id, 0
            )
        else:
            record["state_after_finalization"] = locked
        save("review_milestone")
    else:
        grant_id = str(record["grant_count_before"])

        create_tx = submit(
            funder_client,
            funder,
            address,
            "create_grant",
            [
                grantee.address,
                [options.title],
                ["url_marker"],
                [options.claim_url],
                [options.marker],
                [options.payout],
            ],
            value=options.payout,
        )
        record["transactions"].append(create_tx)
        record["grant_id"] = grant_id
        record["contract_balance_after_create"] = observe(
            read, funder_client, address, "get_contract_balance"
        )
        record["state_after_create"] = observe(
            read, funder_client, address, "get_milestone", [grant_id, 0]
        )
        save("create_grant")

        submit_tx = submit(
            grantee_client, grantee, address, "submit_evidence", [grant_id, 0, options.claim_url]
        )
        record["transactions"].append(submit_tx)
        record["state_after_submit"] = observe(
            read, funder_client, address, "get_milestone", [grant_id, 0]
        )
        save("submit_evidence")

        review_tx = submit(grantee_client, grantee, address, "review_milestone", [grant_id, 0])
        record["transactions"].append(review_tx)
        record["state_after_review"] = observe(
            read, funder_client, address, "get_milestone", [grant_id, 0]
        )
        save("review_milestone")
        record["state_after_finalization"] = await_payout_withdrawable(
            funder_client, address, grant_id, 0
        )
        save("finalization_callback")

    record["contract_balance_before_withdraw"] = observe(
        read, funder_client, address, "get_contract_balance"
    )
    record["grantee_balance_before_withdraw"] = observe(account_balance, grantee.address)
    save("withdraw_setup")
    withdraw_tx = submit(grantee_client, grantee, address, "withdraw", [grant_id, 0])
    record["transactions"].append(withdraw_tx)
    save("withdraw")

    record["contract_balance_after_withdraw"] = observe(
        read, funder_client, address, "get_contract_balance"
    )
    record["grantee_balance_after_withdraw"] = observe(account_balance, grantee.address)
    record["funder_balance_after"] = observe(account_balance, funder.address)
    record["final_grant"] = observe(read, funder_client, address, "get_grant", [grant_id])
    record["final_milestone"] = observe(
        read, funder_client, address, "get_milestone", [grant_id, 0]
    )
    save("observations")

    print(json.dumps(record, indent=2), flush=True)
    print(f"raw record: {output}", flush=True)


if __name__ == "__main__":
    main()
