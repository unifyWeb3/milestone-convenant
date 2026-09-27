# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }

"""A small, finality-aware grant covenant for the Studio-dev slice.

The contract deliberately supports only two fixed, auditable claim types:

* ``github_commit``: an immutable public GitHub commit reference
* ``url_marker``: an allow-listed HTTPS URL containing an exact marker

The release decision is a validator re-derivation of a bounded, normalized
observation.  There is no LLM authority over an objective claim and there is
no arbitrary expression language in the claim format.
"""

import json
import re
from urllib.parse import urlsplit, urlunsplit

import genlayer as gl
from genlayer import Keccak256


MAX_MILESTONES = 2
MAX_URL_LENGTH = 512
MAX_MARKER_LENGTH = 256
MAX_RESPONSE_BYTES = 200_000

CLAIM_GITHUB_COMMIT = "github_commit"
CLAIM_URL_MARKER = "url_marker"


@gl.evm.contract_interface
class _NativeRecipient:
    class View:
        pass

    class Write:
        pass


ALLOWED_URL_HOSTS = (
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "genlayer.com",
    "www.genlayer.com",
)

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"

MILESTONE_LOCKED = "LOCKED"
MILESTONE_SUBMITTED = "SUBMITTED"
MILESTONE_APPROVED = "APPROVED"
MILESTONE_REJECTED = "REJECTED"
MILESTONE_UNDETERMINED = "UNDETERMINED"
MILESTONE_WITHDRAWABLE = "WITHDRAWABLE"
MILESTONE_WITHDRAWAL_SCHEDULED = "WITHDRAWAL_SCHEDULED"

PAYOUT_NOT_SCHEDULED = "NOT_SCHEDULED"
PAYOUT_PENDING_FINALITY = "PENDING_FINALITY"
PAYOUT_WITHDRAWABLE = "WITHDRAWABLE"
PAYOUT_TRANSFER_EMITTED = "TRANSFER_EMITTED"


def _github_api_url(github_ref: str) -> str:
    repository, commit_sha = github_ref.rsplit("@", 1)
    owner, repo = repository.split("/", 1)
    return f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"


def _response_status(response) -> int:
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(response, "status", 0)
    try:
        return int(status)
    except (TypeError, ValueError):
        return 0


def _response_text(response) -> str:
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        if len(body) > MAX_RESPONSE_BYTES:
            return ""
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        if len(body.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return ""
        return body
    return ""


class TypedGrantCovenant(gl.contract.Contract):
    """A bounded grant escrow with immutable, typed milestone claims."""

    grant_count: gl.u32

    # Grant-level accounting and authorization.
    grant_funder: gl.storage.TreeMap[str, gl.Address]
    grant_grantee: gl.storage.TreeMap[str, gl.Address]
    grant_total: gl.storage.TreeMap[str, gl.u256]
    grant_locked: gl.storage.TreeMap[str, gl.u256]
    grant_status: gl.storage.TreeMap[str, str]
    grant_milestone_count: gl.storage.TreeMap[str, gl.u32]

    # Milestone-level immutable terms and mutable workflow state.
    milestone_title: gl.storage.TreeMap[str, str]
    milestone_payout: gl.storage.TreeMap[str, gl.u256]
    milestone_claim_type: gl.storage.TreeMap[str, str]
    milestone_claim_target: gl.storage.TreeMap[str, str]
    milestone_claim_parameter: gl.storage.TreeMap[str, str]
    milestone_claim_spec: gl.storage.TreeMap[str, str]
    milestone_claim_fingerprint: gl.storage.TreeMap[str, str]
    milestone_evidence: gl.storage.TreeMap[str, str]
    milestone_status: gl.storage.TreeMap[str, str]
    milestone_review_status: gl.storage.TreeMap[str, str]
    milestone_verdict: gl.storage.TreeMap[str, str]
    milestone_observed: gl.storage.TreeMap[str, str]
    milestone_reason: gl.storage.TreeMap[str, str]
    milestone_payout_status: gl.storage.TreeMap[str, str]

    def __init__(self):
        self.grant_count = gl.u32(0)

    # ------------------------------------------------------------------
    # Validation and canonicalization
    # ------------------------------------------------------------------

    def _field(self, grant_id: str, index: int, name: str) -> str:
        return f"{grant_id}:{index}:{name}"

    def _fail(self, message: str) -> None:
        raise gl.vm.UserError(f"[EXPECTED] {message}")

    def _require_grant(self, grant_id: str) -> None:
        if grant_id not in self.grant_funder:
            self._fail("unknown grant")

    def _require_milestone(self, grant_id: str, index: int) -> None:
        self._require_grant(grant_id)
        if index < 0 or index >= int(self.grant_milestone_count[grant_id]):
            self._fail("unknown milestone")

    def _require_grantee(self, grant_id: str) -> None:
        if gl.message.sender_address != self.grant_grantee[grant_id]:
            self._fail("only the grantee may perform this action")

    def _canonical_github_ref(self, raw: str) -> str:
        value = raw.strip()
        if value.startswith("https://github.com/"):
            path = value[len("https://github.com/") :].strip("/")
            if "/commit/" in path:
                repository, commit_sha = path.split("/commit/", 1)
                value = f"{repository}@{commit_sha}"
        elif value.startswith("https://api.github.com/repos/"):
            path = value[len("https://api.github.com/repos/") :].strip("/")
            if "/commits/" in path:
                repository, commit_sha = path.split("/commits/", 1)
                value = f"{repository}@{commit_sha}"

        value = value.strip("/")
        if value.count("@") != 1:
            self._fail("GitHub claim must be owner/repo@40-character-commit-sha")

        repository, commit_sha = value.rsplit("@", 1)
        parts = repository.split("/")
        if len(parts) != 2:
            self._fail("GitHub repository must be owner/repo")
        owner, repo = parts
        name_pattern = r"[A-Za-z0-9_.-]+"
        if re.fullmatch(name_pattern, owner) is None or re.fullmatch(name_pattern, repo) is None:
            self._fail("GitHub repository contains an invalid name")
        if re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha) is None:
            self._fail("GitHub commit must be a full 40-character SHA")

        return f"{owner}/{repo}@{commit_sha.lower()}"

    def _canonical_url(self, raw: str) -> str:
        value = raw.strip()
        if len(value) == 0 or len(value) > MAX_URL_LENGTH:
            self._fail("URL length is outside the allowed range")

        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            self._fail("URL is malformed")
        if parsed.scheme.lower() != "https" or hostname is None:
            self._fail("URL claims must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            self._fail("URL credentials are not allowed")
        if port not in (None, 443):
            self._fail("URL claims must use the default HTTPS port")
        if parsed.fragment:
            self._fail("URL fragments are not canonical evidence")

        host = hostname.lower()
        if host not in ALLOWED_URL_HOSTS:
            self._fail("URL host is not on the claim allowlist")

        netloc = host
        path = parsed.path or "/"
        return urlunsplit(("https", netloc, path, parsed.query, ""))

    def _canonical_claim(
        self, claim_type: str, target: str, parameter: str
    ) -> tuple[str, str, str]:
        normalized_type = claim_type.strip().lower()
        if normalized_type == CLAIM_GITHUB_COMMIT:
            if parameter.strip():
                self._fail("GitHub commit claims do not accept a parameter")
            return normalized_type, self._canonical_github_ref(target), ""

        if normalized_type == CLAIM_URL_MARKER:
            normalized_parameter = parameter.strip()
            if not normalized_parameter or len(normalized_parameter) > MAX_MARKER_LENGTH:
                self._fail("URL marker must contain 1-256 characters")
            if any(ord(character) < 32 for character in normalized_parameter):
                self._fail("URL marker contains a control character")
            return normalized_type, self._canonical_url(target), normalized_parameter

        self._fail("claim type must be github_commit or url_marker")

    def _fingerprint(self, claim_spec: str) -> str:
        return Keccak256(claim_spec.encode("utf-8")).hexdigest()

    def _github_evidence_url(self, github_ref: str) -> str:
        repository, commit_sha = github_ref.rsplit("@", 1)
        return f"https://github.com/{repository}/commit/{commit_sha}"

    def _canonical_evidence(
        self, claim_type: str, claim_target: str, evidence_url: str
    ) -> str:
        if claim_type == CLAIM_GITHUB_COMMIT:
            candidate = evidence_url.strip()
            if not candidate.startswith("https://github.com/"):
                self._fail("GitHub evidence must be a GitHub commit URL")
            path = candidate[len("https://github.com/") :].strip("/")
            if "/commit/" not in path:
                self._fail("GitHub evidence must point to a commit")
            repository, commit_sha = path.split("/commit/", 1)
            if len(repository.split("/")) != 2:
                self._fail("GitHub evidence repository is invalid")
            canonical = self._canonical_github_ref(f"{repository}@{commit_sha}")
            if canonical != claim_target:
                self._fail("GitHub evidence does not match the locked claim")
            return self._github_evidence_url(canonical)

        canonical = self._canonical_url(evidence_url)
        if canonical != claim_target:
            self._fail("URL evidence does not match the locked claim")
        return canonical

    # ------------------------------------------------------------------
    # External evidence evaluation
    # ------------------------------------------------------------------

    def _evaluate_claim(
        self, claim_type: str, claim_target: str, claim_parameter: str
    ) -> dict[str, str]:
        """Re-derive a bounded result from an external source.

        This function is called only inside a non-deterministic block. The
        validator calls the same function independently and compares the
        normalized decision fields, not a free-form explanation.
        """

        def leader_fn() -> dict[str, str]:
            if claim_type == CLAIM_GITHUB_COMMIT:
                response = gl.nondet.web.get(_github_api_url(claim_target))
                status = _response_status(response)
                if status == 404:
                    return {
                        "verdict": "FAIL",
                        "observed": "commit_missing",
                        "reason": "github_commit_not_found",
                    }
                if status != 200:
                    return {
                        "verdict": "UNKNOWN",
                        "observed": "source_unavailable",
                        "reason": "github_source_unavailable",
                    }

                text = _response_text(response)
                if not text:
                    return {
                        "verdict": "UNKNOWN",
                        "observed": "invalid_source",
                        "reason": "github_response_too_large_or_empty",
                    }
                try:
                    payload = json.loads(text)
                except (TypeError, ValueError):
                    return {
                        "verdict": "UNKNOWN",
                        "observed": "invalid_source",
                        "reason": "github_response_not_json",
                    }
                if not isinstance(payload, dict):
                    return {
                        "verdict": "UNKNOWN",
                        "observed": "invalid_source",
                        "reason": "github_response_shape_invalid",
                    }

                expected_sha = claim_target.rsplit("@", 1)[1].lower()
                observed_sha = str(payload.get("sha", "")).lower()
                if observed_sha == expected_sha:
                    return {
                        "verdict": "PASS",
                        "observed": "commit_present",
                        "reason": "github_commit_matches_locked_sha",
                    }
                return {
                    "verdict": "FAIL",
                    "observed": "commit_mismatch",
                    "reason": "github_commit_sha_mismatch",
                }

            response = gl.nondet.web.get(claim_target)
            status = _response_status(response)
            if status == 404:
                return {
                    "verdict": "FAIL",
                    "observed": "url_missing",
                    "reason": "evidence_url_not_found",
                }
            if status != 200:
                return {
                    "verdict": "UNKNOWN",
                    "observed": "source_unavailable",
                    "reason": "url_source_unavailable",
                }

            text = _response_text(response)
            if not text:
                return {
                    "verdict": "UNKNOWN",
                    "observed": "invalid_source",
                    "reason": "url_response_too_large_or_empty",
                }
            if claim_parameter in text:
                return {
                    "verdict": "PASS",
                    "observed": "marker_present",
                    "reason": "url_marker_found",
                }
            return {
                "verdict": "FAIL",
                "observed": "marker_absent",
                "reason": "url_marker_not_found",
            }

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            validator_result = leader_fn()
            return (
                leader_result.calldata.get("verdict") == validator_result.get("verdict")
                and leader_result.calldata.get("observed") == validator_result.get("observed")
            )

        return gl.vm.run_nondet(leader_fn, validator_fn)

    # ------------------------------------------------------------------
    # Grant lifecycle
    # ------------------------------------------------------------------

    def _refresh_grant_status(self, grant_id: str) -> None:
        count = int(self.grant_milestone_count[grant_id])
        for index in range(count):
            status = self.milestone_status[self._field(grant_id, index, "status")]
            if status not in (MILESTONE_WITHDRAWAL_SCHEDULED, MILESTONE_REJECTED):
                self.grant_status[grant_id] = STATUS_ACTIVE
                return
        self.grant_status[grant_id] = STATUS_COMPLETED

    @gl.public.write.payable
    def create_grant(
        self,
        grantee: str,
        milestone_titles: list[str],
        claim_types: list[str],
        claim_targets: list[str],
        claim_parameters: list[str],
        payouts: list[int],
    ) -> str:
        count = len(milestone_titles)
        if count < 1 or count > MAX_MILESTONES:
            self._fail("a grant must contain one or two milestones")
        if not (
            len(claim_types) == count
            and len(claim_targets) == count
            and len(claim_parameters) == count
            and len(payouts) == count
        ):
            self._fail("milestone arrays must have equal lengths")

        try:
            grantee_address = gl.Address(grantee)
        except Exception:
            self._fail("grantee is not a valid address")
        if grantee_address == gl.Address("0x0000000000000000000000000000000000000000"):
            self._fail("grantee cannot be the zero address")
        if grantee_address == gl.message.sender_address:
            self._fail("funder and grantee must be different addresses")

        total = 0
        normalized_claims: list[tuple[str, str, str]] = []
        for index in range(count):
            title = milestone_titles[index].strip()
            if not title or len(title) > 160:
                self._fail("milestone titles must contain 1-160 characters")
            payout = int(payouts[index])
            if payout <= 0:
                self._fail("milestone payouts must be positive")
            total += payout
            normalized_claims.append(
                self._canonical_claim(
                    claim_types[index], claim_targets[index], claim_parameters[index]
                )
            )

        received = int(gl.message.value)
        if received != total:
            self._fail("attached GEN must equal the sum of milestone payouts")

        grant_id = str(int(self.grant_count))
        self.grant_count = self.grant_count + gl.u32(1)
        self.grant_funder[grant_id] = gl.message.sender_address
        self.grant_grantee[grant_id] = grantee_address
        self.grant_total[grant_id] = gl.u256(total)
        self.grant_locked[grant_id] = gl.u256(total)
        self.grant_status[grant_id] = STATUS_ACTIVE
        self.grant_milestone_count[grant_id] = gl.u32(count)

        for index, (claim_type, claim_target, claim_parameter) in enumerate(normalized_claims):
            claim_spec = f"{claim_type}|{claim_target}|{claim_parameter}"
            self.milestone_title[self._field(grant_id, index, "title")] = milestone_titles[
                index
            ].strip()
            self.milestone_payout[self._field(grant_id, index, "payout")] = gl.u256(
                int(payouts[index])
            )
            self.milestone_claim_type[self._field(grant_id, index, "claim_type")] = claim_type
            self.milestone_claim_target[self._field(grant_id, index, "claim_target")] = (
                claim_target
            )
            self.milestone_claim_parameter[self._field(grant_id, index, "claim_parameter")] = (
                claim_parameter
            )
            self.milestone_claim_spec[self._field(grant_id, index, "claim_spec")] = claim_spec
            self.milestone_claim_fingerprint[self._field(grant_id, index, "fingerprint")] = (
                self._fingerprint(claim_spec)
            )
            self.milestone_evidence[self._field(grant_id, index, "evidence")] = ""
            self.milestone_status[self._field(grant_id, index, "status")] = MILESTONE_LOCKED
            self.milestone_review_status[self._field(grant_id, index, "review_status")] = (
                "NOT_REVIEWED"
            )
            self.milestone_verdict[self._field(grant_id, index, "verdict")] = ""
            self.milestone_observed[self._field(grant_id, index, "observed")] = ""
            self.milestone_reason[self._field(grant_id, index, "reason")] = ""
            self.milestone_payout_status[self._field(grant_id, index, "payout_status")] = (
                PAYOUT_NOT_SCHEDULED
            )

        return grant_id

    @gl.public.write
    def submit_evidence(self, grant_id: str, milestone_index: int, evidence_url: str) -> None:
        self._require_milestone(grant_id, milestone_index)
        self._require_grantee(grant_id)
        status = self.milestone_status[self._field(grant_id, milestone_index, "status")]
        if status not in (MILESTONE_LOCKED, MILESTONE_REJECTED, MILESTONE_UNDETERMINED):
            self._fail("milestone is not accepting a new evidence submission")

        claim_type = self.milestone_claim_type[
            self._field(grant_id, milestone_index, "claim_type")
        ]
        claim_target = self.milestone_claim_target[
            self._field(grant_id, milestone_index, "claim_target")
        ]
        canonical_evidence = self._canonical_evidence(claim_type, claim_target, evidence_url)

        self.milestone_evidence[self._field(grant_id, milestone_index, "evidence")] = (
            canonical_evidence
        )
        self.milestone_status[self._field(grant_id, milestone_index, "status")] = (
            MILESTONE_SUBMITTED
        )
        self.milestone_review_status[self._field(grant_id, milestone_index, "review_status")] = (
            "PENDING"
        )
        self.milestone_verdict[self._field(grant_id, milestone_index, "verdict")] = ""
        self.milestone_observed[self._field(grant_id, milestone_index, "observed")] = ""
        self.milestone_reason[self._field(grant_id, milestone_index, "reason")] = ""

    @gl.public.write
    def review_milestone(self, grant_id: str, milestone_index: int) -> dict[str, str]:
        self._require_milestone(grant_id, milestone_index)
        self._require_grantee(grant_id)
        status = self.milestone_status[self._field(grant_id, milestone_index, "status")]
        if status != MILESTONE_SUBMITTED:
            self._fail("milestone must be submitted before review")

        claim_type = self.milestone_claim_type[
            self._field(grant_id, milestone_index, "claim_type")
        ]
        claim_target = self.milestone_claim_target[
            self._field(grant_id, milestone_index, "claim_target")
        ]
        claim_parameter = self.milestone_claim_parameter[
            self._field(grant_id, milestone_index, "claim_parameter")
        ]
        result = self._evaluate_claim(claim_type, claim_target, claim_parameter)
        if not isinstance(result, dict):
            result = {
                "verdict": "UNKNOWN",
                "observed": "invalid_source",
                "reason": "evaluator_result_invalid",
            }
        verdict = result.get("verdict", "UNKNOWN")
        if verdict not in ("PASS", "FAIL", "UNKNOWN"):
            self._fail("evidence evaluator returned an invalid verdict")

        self.milestone_review_status[self._field(grant_id, milestone_index, "review_status")] = (
            "DECIDED"
        )
        self.milestone_verdict[self._field(grant_id, milestone_index, "verdict")] = verdict
        self.milestone_observed[self._field(grant_id, milestone_index, "observed")] = result.get(
            "observed", "invalid_source"
        )
        self.milestone_reason[self._field(grant_id, milestone_index, "reason")] = result.get(
            "reason", "unknown"
        )

        if verdict == "PASS":
            self.milestone_status[self._field(grant_id, milestone_index, "status")] = (
                MILESTONE_APPROVED
            )
            self.milestone_payout_status[self._field(grant_id, milestone_index, "payout_status")] = (
                PAYOUT_PENDING_FINALITY
            )
            # The child message runs only after the review transaction is final.
            contract = gl.contract.get_at(gl.message.contract_address)
            contract.emit(on="finalized")._mark_milestone_finalized(grant_id, milestone_index)
        elif verdict == "FAIL":
            self.milestone_status[self._field(grant_id, milestone_index, "status")] = (
                MILESTONE_REJECTED
            )
            self.milestone_payout_status[self._field(grant_id, milestone_index, "payout_status")] = (
                PAYOUT_NOT_SCHEDULED
            )
            self._refresh_grant_status(grant_id)
        else:
            self.milestone_status[self._field(grant_id, milestone_index, "status")] = (
                MILESTONE_UNDETERMINED
            )
            self.milestone_payout_status[self._field(grant_id, milestone_index, "payout_status")] = (
                PAYOUT_NOT_SCHEDULED
            )

        return result

    @gl.public.write
    def _mark_milestone_finalized(self, grant_id: str, milestone_index: int) -> None:
        """Internal idempotent callback scheduled by an approved review."""
        self._require_milestone(grant_id, milestone_index)
        if gl.message.sender_address != gl.message.contract_address:
            self._fail("finalization callback is internal only")
        status = self.milestone_status[self._field(grant_id, milestone_index, "status")]
        payout_status = self.milestone_payout_status[
            self._field(grant_id, milestone_index, "payout_status")
        ]
        if status != MILESTONE_APPROVED or payout_status != PAYOUT_PENDING_FINALITY:
            return
        self.milestone_status[self._field(grant_id, milestone_index, "status")] = (
            MILESTONE_WITHDRAWABLE
        )
        self.milestone_payout_status[self._field(grant_id, milestone_index, "payout_status")] = (
            PAYOUT_WITHDRAWABLE
        )
        self._refresh_grant_status(grant_id)

    @gl.public.write
    def withdraw(self, grant_id: str, milestone_index: int) -> None:
        """Schedule a finality-safe external GEN transfer to the grantee."""
        self._require_milestone(grant_id, milestone_index)
        self._require_grantee(grant_id)
        status = self.milestone_status[self._field(grant_id, milestone_index, "status")]
        payout_status = self.milestone_payout_status[
            self._field(grant_id, milestone_index, "payout_status")
        ]
        if status != MILESTONE_WITHDRAWABLE or payout_status != PAYOUT_WITHDRAWABLE:
            self._fail("milestone is not withdrawable")

        payout_key = self._field(grant_id, milestone_index, "payout")
        payout = int(self.milestone_payout[payout_key])
        locked = int(self.grant_locked[grant_id])
        if payout <= 0 or payout > locked:
            self._fail("payout accounting is inconsistent")

        self.grant_locked[grant_id] = gl.u256(locked - payout)
        self.milestone_status[self._field(grant_id, milestone_index, "status")] = (
            MILESTONE_WITHDRAWAL_SCHEDULED
        )
        self.milestone_payout_status[self._field(grant_id, milestone_index, "payout_status")] = (
            PAYOUT_TRANSFER_EMITTED
        )
        self._refresh_grant_status(grant_id)

        # EOAs live on the GenLayer chain layer. The EVM interface emits an
        # external message, which Studio can execute on finalization; a plain
        # GenVM contract proxy produces an internal message that is skipped.
        recipient = _NativeRecipient(self.grant_grantee[grant_id])
        recipient.emit_transfer(value=gl.u256(payout))

    # ------------------------------------------------------------------
    # Read-only interface
    # ------------------------------------------------------------------

    def _milestone_view(self, grant_id: str, index: int) -> dict:
        return {
            "index": index,
            "title": self.milestone_title[self._field(grant_id, index, "title")],
            "payout": int(self.milestone_payout[self._field(grant_id, index, "payout")]),
            "claim_type": self.milestone_claim_type[
                self._field(grant_id, index, "claim_type")
            ],
            "claim_target": self.milestone_claim_target[
                self._field(grant_id, index, "claim_target")
            ],
            "claim_parameter": self.milestone_claim_parameter[
                self._field(grant_id, index, "claim_parameter")
            ],
            "claim_spec": self.milestone_claim_spec[self._field(grant_id, index, "claim_spec")],
            "claim_fingerprint": self.milestone_claim_fingerprint[
                self._field(grant_id, index, "fingerprint")
            ],
            "evidence": self.milestone_evidence[self._field(grant_id, index, "evidence")],
            "status": self.milestone_status[self._field(grant_id, index, "status")],
            "review_status": self.milestone_review_status[
                self._field(grant_id, index, "review_status")
            ],
            "verdict": self.milestone_verdict[self._field(grant_id, index, "verdict")],
            "observed": self.milestone_observed[self._field(grant_id, index, "observed")],
            "reason": self.milestone_reason[self._field(grant_id, index, "reason")],
            "payout_status": self.milestone_payout_status[
                self._field(grant_id, index, "payout_status")
            ],
        }

    @gl.public.view
    def get_grant_count(self) -> int:
        return int(self.grant_count)

    @gl.public.view
    def get_grant(self, grant_id: str) -> dict:
        self._require_grant(grant_id)
        count = int(self.grant_milestone_count[grant_id])
        milestones = [self._milestone_view(grant_id, index) for index in range(count)]
        return {
            "id": grant_id,
            "funder": self.grant_funder[grant_id].as_hex,
            "grantee": self.grant_grantee[grant_id].as_hex,
            "total": int(self.grant_total[grant_id]),
            "locked": int(self.grant_locked[grant_id]),
            "status": self.grant_status[grant_id],
            "milestone_count": count,
            "milestones": milestones,
        }

    @gl.public.view
    def get_milestone(self, grant_id: str, milestone_index: int) -> dict:
        self._require_milestone(grant_id, milestone_index)
        return self._milestone_view(grant_id, milestone_index)

    @gl.public.view
    def get_contract_balance(self) -> int:
        return int(self.balance)
