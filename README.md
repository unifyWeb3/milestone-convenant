# Milestone Covenant

A small public GenLayer Builder Program contribution for grant-tool builders.

The slice demonstrates one narrow, finality-aware flow:

1. A funder creates a grant with one or two immutable milestone claims.
2. The funder locks test GEN equal to the milestone payouts.
3. The grantee submits evidence matching the locked claim.
4. Validators independently re-derive a bounded result from the canonical public source.
5. A passing result schedules a grantee withdrawal; an external EVM message transfers GEN on finality.

The current implementation supports exactly two claim types:

- `github_commit`: `owner/repo@<40-character-commit-sha>`
- `url_marker`: an allow-listed HTTPS URL plus an exact marker

This is deliberately not a general AI grant reviewer. Objective claims are checked deterministically after independent web retrieval; an LLM is not allowed to override them.

## Status

- Local direct tests: **passed** (10 tests)
- Contract lint and SDK schema validation: **passed**
- Studio-dev code/schema probe: **passed** against GenVM `v0.3.0-rc7`
- Studio-dev deployment and real GitHub evidence: **passed** on the corrected EVM-transfer contract
- Studio-dev real `url_marker` evidence: **passed** on a fresh deployment of the current source; the raw genlayer-py README returned `PASS` / `marker_present` and the withdrawal moved the covenant balance `100 → 0`
- Browser UI: **manual pass, user-reported**; the user completed the wallet flow against `0xb2044176…`, and the five resulting Studio-dev transactions were independently confirmed `FINALIZED`. Automated desktop-browser verification remains unavailable.
- Builder Program submission: **not submitted**

A transaction broadcast, a passing unit test, or an LLM response is not treated as completion evidence. See [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

## Requirements

- Python 3.12+
- Node.js 18+ (for the browser client)
- GenLayer Studio-dev access for live validation
- A browser EIP-1193 wallet for the public UI
- Docker is **not** required for direct tests; it is unavailable in the current development environment

The repository pins the current Studio-dev release family:

- GenLayer Studio `v0.123.0-rc.7` (hosted target)
- GenVM `v0.3.0-rc7` runtime observed by the target
- `genlayer-js` `v2.0.0-rc.1`
- `genlayer-py` `v0.19.0-rc.2`
- `genlayer-test` `v0.30.0-rc.2`
- Contract runner `py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng`

The runner hash is part of the contract header and must stay synchronized with the hosted target. Do not substitute an alias such as `latest` or `test`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
GENVM_VERSION=v0.6.0-rc5 .venv/bin/pytest -p no:gltest -q
.venv/bin/genvm-lint check contracts/typed_grant_covenant.py
```

The direct command pins the cached GenVM release bundle because the current
contract header targets the v0.3 SDK layout. The Studio plugin is disabled for
this direct-only run; it is not needed by the mocked tests.

For the live target, use the canonical Studio-dev RPC only:

```text
https://studio-dev.genlayer.com/api
```

Do not point the stable `studionet` client at the preview endpoint. Studio-dev is temporary and may reset.

### Browser client

```bash
cd frontend
npm install
cp .env.example .env
# set VITE_CONTRACT_ADDRESS after deployment
npm run dev
```

The client uses an EIP-1193 browser wallet and the pinned `genlayer-js` release.
It displays the contract's business state separately from transaction
lifecycle state and does not treat `ACCEPTED` or a submitted hash as final.

For a repeatable Studio-dev deployment, use the helper (it never writes the
private key to disk):

```bash
GENLAYER_PRIVATE_KEY=... .venv/bin/python scripts/deploy_studio_dev.py
```

To reproduce the public `url_marker` demo end to end, including a fresh
deployment of the current source:

```bash
.venv/bin/python scripts/run_url_marker_demo.py --deploy
```

The script reads state with `latest-final`, confirms each write from the
transaction record only after the lifecycle reports `Finalized`, and writes its
raw record to the gitignored `artifacts/` directory after every step. That
directory holds public run records only and must never hold keys.

Keys come from the `GENLAYER_FUNDER_PRIVATE_KEY` and
`GENLAYER_GRANTEE_PRIVATE_KEY` environment variables, which the script never
writes to disk. Because Studio-dev regularly stalls or drops a request, an
interrupted run can be finished with the same accounts by supplying
`--account-file <path outside this checkout>` and then `--contract` and
`--grant-id`. Any account file that resolves inside the repository,
`artifacts/` included, is rejected, and so is a symlink pointing into it.

For a public reviewer deployment on Vercel, use `frontend/` as the project root
directory and set one public build-time variable:

```text
VITE_CONTRACT_ADDRESS=0xb20441769A60a501e8B47E196216f1456d7783c1
```

The public reviewer deployment is:

[https://milestone-convenant.vercel.app](https://milestone-convenant.vercel.app)

The reviewer connects their own Studio-dev wallet in the browser. No wallet
key or secret is needed for deployment.

## Repository layout

```text
contracts/typed_grant_covenant.py  Intelligent Contract
tests/direct/                     Fast mocked contract tests
frontend/                         Thin browser client
docs/                             Architecture and evidence records
docs/evidence/                    Public live evidence records
gltest.config.yaml                Studio-dev integration configuration
scripts/deploy_studio_dev.py       Repeatable Studio-dev deployment helper
scripts/run_url_marker_demo.py    Real url_marker demo and evidence collector
```

## Security boundary

- No private keys or API tokens belong in this repository.
- Keys enter the tooling only through the environment; the demo runner refuses to keep them anywhere inside the checkout and `artifacts/` is for public run records.
- The contract accepts only bounded claim schemas and an allow-listed set of public hosts.
- The grantee can submit only evidence matching the locked claim.
- A technical source failure is `UNKNOWN`, not a rejection.
- `ACCEPTED` is not finality; the UI must follow the GenLayer transaction lifecycle.
- The contract never exposes an admin override for an approved claim.
- There is no cancellation or refund path, so a grant whose grantee stops
  responding keeps its funds locked. See
  [`docs/VERIFICATION.md`](docs/VERIFICATION.md#known-limitation-stranded-preview-grants).

## License

MIT. See [`LICENSE`](LICENSE).
