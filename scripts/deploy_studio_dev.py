"""Deploy the covenant to Studio-dev without storing wallet material.

Set ``GENLAYER_PRIVATE_KEY`` only in the process environment when a persistent
funder account is needed. With no key, an ephemeral account is generated and
only its public address is printed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "typed_grant_covenant.py"
RPC = "https://studio-dev.genlayer.com/api"


class ReceiptUnavailable(Exception):
    """The SDK's receipt endpoint is not needed to track consensus."""


def rpc(client, method: str, params: list, timeout: int = 60):
    response = requests.post(
        RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"Content-Type": "application/json", "User-Agent": "typed-grant-deploy"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("result")


def full_record(client, evm_hash: str, timeout_seconds: int = 240):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            record = rpc(client, "eth_getTransactionByHash", [evm_hash], timeout=60)
            if record:
                return record
        except Exception:
            pass
        time.sleep(4)
    raise TimeoutError(f"no transaction record for {evm_hash}")


def finalized(client, tx_id: str, timeout_seconds: int = 1200):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = rpc(client, "gen_getTransactionLifecycle", [{"txId": tx_id}], timeout=30) or {}
        if result.get("storedStatus") == "Finalized":
            return result
        if result.get("storedStatus") in {"Canceled", "Undetermined"}:
            raise RuntimeError(f"transaction reached {result['storedStatus']}")
        time.sleep(5)
    raise TimeoutError(f"transaction {tx_id} did not finalize")


def main() -> None:
    key = os.environ.get("GENLAYER_PRIVATE_KEY")
    account = create_account(key)
    client = create_client(chain=studio_devnet, account=account)
    client.fund_account(account.address, 10**18)

    estimate = client.estimate_transaction_fees({"rotations": [1]})
    fees = {"distribution": estimate["distribution"], "feeValue": estimate["feeValue"]}

    captured: dict[str, str] = {}

    def capture_receipt(evm_hash):
        captured["evm_hash"] = str(evm_hash)
        raise ReceiptUnavailable

    # Studio can finalize consensus while leaving eth_getTransactionReceipt
    # open. Capture the EVM hash and use the full transaction record instead.
    client.w3.eth.wait_for_transaction_receipt = capture_receipt
    try:
        client.deploy_contract(
            code=CONTRACT.read_text(),
            account=account,
            args=[],
            consensus_max_rotations=1,
            fees=fees,
        )
    except ReceiptUnavailable:
        pass

    evm_hash = captured.get("evm_hash")
    if not evm_hash:
        raise RuntimeError("deployment did not submit an EVM transaction")
    record = full_record(client, evm_hash)
    tx_id = record.get("tx_id") or evm_hash
    lifecycle = finalized(client, tx_id)
    data = record.get("data", {})
    address = data.get("contract_address") if isinstance(data, dict) else None
    if not address:
        raise RuntimeError("finalized deployment did not expose a contract address")
    if record.get("result_name") != "MAJORITY_AGREE" or record.get("txExecutionResultName") != "FINISHED_WITH_RETURN":
        raise RuntimeError(f"deployment execution was not successful: {record.get('result_name')}")

    print(
        json.dumps(
            {
                "account": account.address,
                "contract_address": address,
                "evm_transaction": evm_hash,
                "consensus_transaction": tx_id,
                "lifecycle": lifecycle.get("storedStatus"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
