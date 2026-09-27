import json


GITHUB_SHA = "1" * 40
GITHUB_REF = f"genlayerlabs/genlayer-docs@{GITHUB_SHA}"
GITHUB_EVIDENCE_URL = f"https://github.com/genlayerlabs/genlayer-docs/commit/{GITHUB_SHA}"
PUBLIC_URL = "https://raw.githubusercontent.com/genlayerlabs/genlayer-docs/main/README.md"


def _address_hex(value):
    if hasattr(value, "as_hex"):
        return value.as_hex
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return str(value)


def _create_one_milestone(contract, direct_vm, funder, grantee):
    direct_vm.sender = funder
    direct_vm.value = 100
    return contract.create_grant(
        _address_hex(grantee),
        ["First covenant slice"],
        ["github_commit"],
        [GITHUB_REF],
        [""],
        [100],
    )


def _create_two_milestones(contract, direct_vm, funder, grantee):
    direct_vm.sender = funder
    direct_vm.value = 300
    return contract.create_grant(
        _address_hex(grantee),
        ["First covenant slice", "Publish the evidence note"],
        ["github_commit", "url_marker"],
        [GITHUB_REF, PUBLIC_URL],
        ["", "GenLayer"],
        [100, 200],
    )


def _mock_github(direct_vm, sha=GITHUB_SHA, status=200):
    direct_vm.mock_web(
        r"api\.github\.com/repos/genlayerlabs/genlayer-docs/commits/[0-9a-f]+",
        {"status": status, "body": json.dumps({"sha": sha})},
    )


def _mock_url(direct_vm, body="GenLayer Intelligent Contracts", status=200):
    direct_vm.mock_web(
        r"raw\.githubusercontent\.com/genlayerlabs/genlayer-docs/main/README\.md",
        {"status": status, "body": body},
    )


def test_create_locks_canonical_claims_and_funds(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    grant_id = _create_two_milestones(contract, direct_vm, direct_alice, direct_bob)

    assert grant_id == "0"
    grant = contract.get_grant("0")
    assert grant["funder"].lower() == _address_hex(direct_alice).lower()
    assert grant["grantee"].lower() == _address_hex(direct_bob).lower()
    assert grant["total"] == 300
    assert grant["locked"] == 300
    assert grant["status"] == "ACTIVE"
    assert grant["milestone_count"] == 2
    assert grant["milestones"][0]["claim_type"] == "github_commit"
    assert grant["milestones"][0]["claim_target"] == GITHUB_REF
    assert grant["milestones"][0]["claim_fingerprint"]
    assert grant["milestones"][1]["claim_type"] == "url_marker"
    assert grant["milestones"][1]["claim_target"] == PUBLIC_URL
    assert grant["milestones"][1]["claim_parameter"] == "GenLayer"


def test_malformed_claims_are_rejected_before_funding(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    direct_vm.sender = direct_alice
    direct_vm.value = 100

    with direct_vm.expect_revert("claim type must be github_commit or url_marker"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            ["arbitrary_python"],
            ["anything"],
            [""],
            [100],
        )

    with direct_vm.expect_revert("GitHub commit must be a full 40-character SHA"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            ["github_commit"],
            ["genlayerlabs/genlayer-docs@latest"],
            [""],
            [100],
        )

    with direct_vm.expect_revert("URL host is not on the claim allowlist"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            ["url_marker"],
            ["https://example.com/evidence"],
            ["marker"],
            [100],
        )

    with direct_vm.expect_revert("attached GEN must equal the sum of milestone payouts"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            ["github_commit"],
            [GITHUB_REF],
            [""],
            [101],
        )

    assert contract.get_grant_count() == 0


def test_malformed_grant_shape_and_identities_are_rejected(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    direct_vm.sender = direct_alice
    direct_vm.value = 100

    with direct_vm.expect_revert("milestone arrays must have equal lengths"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            [],
            [GITHUB_REF],
            [""],
            [100],
        )

    with direct_vm.expect_revert("milestone payouts must be positive"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            ["github_commit"],
            [GITHUB_REF],
            [""],
            [0],
        )

    with direct_vm.expect_revert("grantee is not a valid address"):
        contract.create_grant(
            "not-an-address",
            ["bad"],
            ["github_commit"],
            [GITHUB_REF],
            [""],
            [100],
        )

    with direct_vm.expect_revert("funder and grantee must be different addresses"):
        contract.create_grant(
            _address_hex(direct_alice),
            ["bad"],
            ["github_commit"],
            [GITHUB_REF],
            [""],
            [100],
        )

    with direct_vm.expect_revert("URL is malformed"):
        contract.create_grant(
            _address_hex(direct_bob),
            ["bad"],
            ["url_marker"],
            ["https://github.com:bad/evidence"],
            ["marker"],
            [100],
        )

    assert contract.get_grant_count() == 0


def test_evidence_authorization_and_matching_are_enforced(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    _create_one_milestone(contract, direct_vm, direct_alice, direct_bob)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("milestone must be submitted before review"):
        contract.review_milestone("0", 0)

    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("only the grantee may perform this action"):
        contract.submit_evidence("0", 0, GITHUB_EVIDENCE_URL)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("GitHub evidence does not match the locked claim"):
        contract.submit_evidence(
            "0",
            0,
            "https://github.com/genlayerlabs/genlayer-docs/commit/" + ("2" * 40),
        )

    contract.submit_evidence("0", 0, GITHUB_EVIDENCE_URL)
    assert contract.get_milestone("0", 0)["status"] == "SUBMITTED"
    assert contract.get_milestone("0", 0)["review_status"] == "PENDING"

    with direct_vm.expect_revert("only the grantee may perform this action"):
        direct_vm.sender = direct_charlie
        contract.review_milestone("0", 0)


def test_github_pass_is_independently_rederived(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    _create_one_milestone(contract, direct_vm, direct_alice, direct_bob)
    direct_vm.sender = direct_bob
    contract.submit_evidence("0", 0, GITHUB_EVIDENCE_URL)
    _mock_github(direct_vm)
    direct_vm.check_pickling = True

    result = contract.review_milestone("0", 0)
    assert result["verdict"] == "PASS"
    assert result["observed"] == "commit_present"
    assert direct_vm.run_validator() is True

    milestone = contract.get_milestone("0", 0)
    assert milestone["status"] in ("APPROVED", "WITHDRAWABLE")
    assert milestone["verdict"] == "PASS"
    assert milestone["payout_status"] in ("PENDING_FINALITY", "WITHDRAWABLE")
    assert contract.get_grant("0")["locked"] == 100


def test_conflicting_validator_result_is_not_accepted(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    _create_one_milestone(contract, direct_vm, direct_alice, direct_bob)
    direct_vm.sender = direct_bob
    contract.submit_evidence("0", 0, GITHUB_EVIDENCE_URL)
    _mock_github(direct_vm)

    contract.review_milestone("0", 0)
    direct_vm.clear_mocks()
    _mock_github(direct_vm, sha="2" * 40)
    assert direct_vm.run_validator() is False


def test_rejection_and_technical_source_failure_do_not_release_funds(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    _create_two_milestones(contract, direct_vm, direct_alice, direct_bob)

    direct_vm.sender = direct_bob
    contract.submit_evidence("0", 0, GITHUB_EVIDENCE_URL)
    _mock_github(direct_vm, status=404)
    rejected = contract.review_milestone("0", 0)
    assert rejected["verdict"] == "FAIL"
    assert rejected["observed"] == "commit_missing"
    assert contract.get_milestone("0", 0)["status"] == "REJECTED"
    assert contract.get_grant("0")["locked"] == 300

    direct_vm.clear_mocks()
    contract.submit_evidence("0", 1, PUBLIC_URL)
    _mock_url(direct_vm, status=503)
    unknown = contract.review_milestone("0", 1)
    assert unknown["verdict"] == "UNKNOWN"
    assert unknown["observed"] == "source_unavailable"
    assert contract.get_milestone("0", 1)["status"] == "UNDETERMINED"
    assert contract.get_grant("0")["locked"] == 300


def test_url_marker_pass_and_fail_paths(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    _create_two_milestones(contract, direct_vm, direct_alice, direct_bob)
    direct_vm.sender = direct_bob
    contract.submit_evidence("0", 1, PUBLIC_URL)
    snapshot = direct_vm.snapshot()

    _mock_url(direct_vm, body="prefix GenLayer suffix")
    result = contract.review_milestone("0", 1)
    assert result["verdict"] == "PASS"
    assert result["observed"] == "marker_present"

    # Restore the submitted state so the same locked claim can be reviewed
    # against a different source response.
    direct_vm.revert(snapshot)
    direct_vm.sender = direct_bob
    direct_vm.clear_mocks()
    _mock_url(direct_vm, body="no marker here")
    result = contract.review_milestone("0", 1)
    assert result["verdict"] == "FAIL"
    assert result["observed"] == "marker_absent"


def test_finality_callback_and_withdraw_are_guarded(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    _create_one_milestone(contract, direct_vm, direct_alice, direct_bob)
    direct_vm.sender = direct_bob
    contract.submit_evidence("0", 0, GITHUB_EVIDENCE_URL)
    _mock_github(direct_vm)
    contract.review_milestone("0", 0)

    # A user cannot invoke the internal callback or withdraw before it runs.
    with direct_vm.expect_revert("finalization callback is internal only"):
        direct_vm.sender = direct_alice
        contract._mark_milestone_finalized("0", 0)
    with direct_vm.expect_revert("milestone is not withdrawable"):
        direct_vm.sender = direct_bob
        contract.withdraw("0", 0)

    # Direct mode has no asynchronous child-message scheduler. Calling the
    # callback as the contract address isolates the business transition.
    direct_vm.sender = contract.address
    contract._mark_milestone_finalized("0", 0)
    contract._mark_milestone_finalized("0", 0)
    assert contract.get_milestone("0", 0)["status"] == "WITHDRAWABLE"
    assert contract.get_grant("0")["locked"] == 100

    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("only the grantee may perform this action"):
        contract.withdraw("0", 0)

    direct_vm.sender = direct_bob
    contract.withdraw("0", 0)
    assert contract.get_milestone("0", 0)["status"] == "WITHDRAWAL_SCHEDULED"
    assert contract.get_milestone("0", 0)["payout_status"] == "TRANSFER_EMITTED"
    assert contract.get_grant("0")["locked"] == 0

    with direct_vm.expect_revert("milestone is not withdrawable"):
        contract.withdraw("0", 0)


def test_canonicalizes_github_url_form(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/typed_grant_covenant.py")
    direct_vm.sender = direct_alice
    direct_vm.value = 100
    contract.create_grant(
        _address_hex(direct_bob),
        ["canonical"],
        ["github_commit"],
        [f"https://github.com/genlayerlabs/genlayer-docs/commit/{GITHUB_SHA.upper()}"],
        [""],
        [100],
    )
    claim = contract.get_milestone("0", 0)
    assert claim["claim_target"] == GITHUB_REF
    assert claim["claim_spec"] == f"github_commit|{GITHUB_REF}|"
