import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import "./style.css";

const CHAIN_ID = 61997;
const CHAIN_ID_HEX = `0x${CHAIN_ID.toString(16)}`;
const EXPLORER = "https://explorer-studio-dev.genlayer.com";
const STORAGE_KEY = "typed-grant-covenant.contract";

const state = {
  provider: null,
  client: null,
  account: null,
  contractAddress: window.localStorage.getItem(STORAGE_KEY) || import.meta.env.VITE_CONTRACT_ADDRESS || window.__CONTRACT_ADDRESS__ || "",
  grantId: "0",
  milestoneIndex: "0",
  busy: false,
};

const app = document.querySelector("#app");
app.innerHTML = `
  <header class="topbar">
    <div>
      <p class="eyebrow">GENLAYER BUILDER PROGRAM · STUDIO-DEV PREVIEW</p>
      <h1>Typed Grant Covenant</h1>
      <p class="lede">Machine-checkable milestones. Validator-backed evidence. Finality-aware test GEN.</p>
    </div>
    <div class="network-pill"><span class="dot"></span> Studio-dev · chain 61997</div>
  </header>

  <main class="shell">
    <section class="notice">
      <strong>Test GEN only.</strong> This preview does not represent real value or production settlement.
      A transaction hash is not a payout: the app follows the GenLayer lifecycle through finalization.
    </section>

    <section class="panel connection">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">STEP 0</p>
          <h2>Connect and configure</h2>
        </div>
        <button id="connect" class="primary">Connect wallet</button>
      </div>
      <div class="connection-grid">
        <label>Wallet account <output id="account">Not connected</output></label>
        <label>Deployed contract address
          <input id="contract" placeholder="0x…" autocomplete="off" />
        </label>
      </div>
      <p class="hint">The contract address is public configuration. Never enter a private key.</p>
    </section>

    <div class="columns">
      <section class="panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">STEP 1 · FUNDER</p>
            <h2>Create a typed grant</h2>
          </div>
        </div>
        <form id="create-form" class="form">
          <label>Grantee address <input id="grantee" placeholder="0x…" required /></label>
          <label>Milestone title <input id="title" value="Ship the first covenant slice" required /></label>
          <label>Claim type
            <select id="claim-type">
              <option value="github_commit">github_commit</option>
              <option value="url_marker">url_marker</option>
            </select>
          </label>
          <label>Locked target <input id="target" value="genlayerlabs/genlayer-docs@1111111111111111111111111111111111111111" required /></label>
          <label>Marker / parameter <input id="parameter" value="" placeholder="Required for url_marker" /></label>
          <label>Payout (test GEN units) <input id="payout" type="number" min="1" value="100" required /></label>
          <button class="primary" type="submit">Create and lock grant</button>
        </form>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">STEP 2 · GRANTEE</p>
            <h2>Submit, review, withdraw</h2>
          </div>
        </div>
        <form id="action-form" class="form">
          <div class="two-up">
            <label>Grant ID <input id="grant-id" value="0" /></label>
            <label>Milestone index <input id="milestone-index" type="number" min="0" value="0" /></label>
          </div>
          <label>Evidence URL <input id="evidence" placeholder="https://github.com/owner/repo/commit/<sha>" required /></label>
          <div class="button-row">
            <button class="secondary" type="button" data-action="submit">Submit evidence</button>
            <button class="secondary" type="button" data-action="review">Review evidence</button>
            <button class="secondary" type="button" data-action="withdraw">Withdraw</button>
          </div>
        </form>
        <div class="divider"></div>
        <div class="inline-actions">
          <button id="refresh" class="ghost">Refresh grant state</button>
          <span id="grant-summary" class="summary">No grant loaded.</span>
        </div>
      </section>
    </div>

    <section class="panel state-panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">OBSERVABLE STATE</p>
          <h2>Milestone ledger</h2>
        </div>
        <span id="lifecycle" class="lifecycle">Idle</span>
      </div>
      <div id="milestones" class="milestones"><p class="empty">Connect a wallet and refresh a grant.</p></div>
    </section>

    <section class="panel activity-panel">
      <p class="eyebrow">TRANSACTION ACTIVITY</p>
      <div id="activity" class="activity"><p class="empty">No transactions from this browser yet.</p></div>
    </section>
  </main>

  <footer>
    <span>Typed Grant Covenant · Studio-dev preview</span>
    <a href="${EXPLORER}" target="_blank" rel="noreferrer">Open explorer ↗</a>
  </footer>
`;

const $ = (id) => document.getElementById(id);
const activity = [];

function setMessage(message, kind = "info") {
  const node = $("lifecycle");
  node.textContent = message;
  node.dataset.kind = kind;
}

function addActivity(entry) {
  activity.unshift(entry);
  $("activity").innerHTML = activity
    .slice(0, 8)
    .map(
      (item) => `<div class="activity-row">
        <span class="activity-kind">${escapeHtml(item.kind)}</span>
        <span>${escapeHtml(item.message)}</span>
        ${item.hash ? `<a href="${EXPLORER}/transaction/${item.hash}" target="_blank" rel="noreferrer">${shortHash(item.hash)}</a>` : ""}
      </div>`,
    )
    .join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[character]);
}

function shortHash(hash) {
  return hash.length > 18 ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : hash;
}

function setConnectedView() {
  $("account").textContent = state.account || "Not connected";
  $("connect").textContent = state.account ? "Wallet connected" : "Connect wallet";
  $("contract").value = state.contractAddress;
}

function getProvider() {
  if (!window.ethereum) {
    throw new Error("No EIP-1193 wallet found. Install a browser wallet and try again.");
  }
  return window.ethereum;
}

async function connectWallet() {
  const provider = getProvider();
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  if (!accounts?.[0]) throw new Error("The wallet returned no account.");

  let chainId = await provider.request({ method: "eth_chainId" });
  if (chainId !== CHAIN_ID_HEX) {
    try {
      await provider.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: CHAIN_ID_HEX }],
      });
    } catch (error) {
      if (error?.code !== 4902) throw error;
      await provider.request({
        method: "wallet_addEthereumChain",
        params: [{
          chainId: CHAIN_ID_HEX,
          chainName: "GenLayer Studio Devnet",
          rpcUrls: [studioDevnet.rpcUrls.default.http[0]],
          nativeCurrency: studioDevnet.nativeCurrency,
        }],
      });
      await provider.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: CHAIN_ID_HEX }],
      });
    }
    chainId = await provider.request({ method: "eth_chainId" });
  }
  if (chainId !== CHAIN_ID_HEX) throw new Error(`Wallet is on chain ${chainId}; expected ${CHAIN_ID_HEX}.`);

  state.provider = provider;
  state.account = accounts[0];
  state.client = createClient({ chain: studioDevnet, account: state.account, provider });
  setConnectedView();
  setMessage("Wallet connected", "good");
  addActivity({ kind: "WALLET", message: state.account });
}

function requireClient() {
  if (!state.client || !state.account) throw new Error("Connect a wallet first.");
  const address = $("contract").value.trim();
  if (!/^0x[0-9a-fA-F]{40}$/.test(address)) throw new Error("Enter a valid deployed contract address.");
  state.contractAddress = address;
  window.localStorage.setItem(STORAGE_KEY, address);
  return { client: state.client, address };
}

function walletAccount() {
  return { address: state.account, type: "json-rpc" };
}

async function waitForFinalizedLifecycle(client, hash) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const lifecycle = await client.request({
      method: "gen_getTransactionLifecycle",
      params: [{ txId: hash }],
    });
    if (lifecycle.storedStatus === "Finalized") return lifecycle;
    if (lifecycle.storedStatus === "Canceled" || lifecycle.storedStatus === "Undetermined") {
      throw new Error(`Transaction reached ${lifecycle.storedStatus}.`);
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  throw new Error(`Transaction ${hash} did not finalize in time.`);
}

async function writeAndWait(functionName, args, value = 0n) {
  const { client, address } = requireClient();
  setMessage("Estimating fees…");
  const estimate = await client.estimateTransactionFeesForWrite({
    account: walletAccount(),
    address,
    functionName,
    args,
    value,
    rotations: [1],
  });
  const fees = {
    distribution: estimate.distribution,
    feeValue: estimate.feeValue,
    ...(estimate.messageAllocations ? { messageAllocations: estimate.messageAllocations } : {}),
  };
  setMessage("Waiting for wallet signature…");
  const hash = await client.writeContract({
    address,
    functionName,
    args,
    value,
    account: walletAccount(),
    consensusMaxRotations: 1,
    fees,
  });
  addActivity({ kind: functionName, message: "submitted", hash });
  setMessage("Submitted · waiting for finality");
  const lifecycle = await waitForFinalizedLifecycle(client, hash);
  addActivity({ kind: functionName, message: `finalized · ${lifecycle.storedStatus}`, hash });
  setMessage(`Finalized · ${lifecycle.storedStatus}`, "good");
  return lifecycle;
}

async function createGrant(event) {
  event.preventDefault();
  if (state.busy) return;
  state.busy = true;
  try {
    const payout = BigInt($("payout").value);
    await writeAndWait(
      "create_grant",
      [
        $("grantee").value.trim(),
        [$("title").value.trim()],
        [$("claim-type").value],
        [$("target").value.trim()],
        [$("parameter").value],
        [payout],
      ],
      payout,
    );
    $("grant-id").value = "0";
    await refreshGrant();
  } catch (error) {
    setMessage(error?.shortMessage || error?.message || String(error), "bad");
  } finally {
    state.busy = false;
  }
}

async function runAction(action) {
  if (state.busy) return;
  state.busy = true;
  try {
    const grantId = $("grant-id").value.trim();
    const milestoneIndex = Number($("milestone-index").value);
    const args = [grantId, milestoneIndex];
    if (action === "submit") args.push($("evidence").value.trim());
    await writeAndWait(
      action === "submit" ? "submit_evidence" : action === "review" ? "review_milestone" : "withdraw",
      args,
    );
    await refreshGrant();
  } catch (error) {
    setMessage(error?.shortMessage || error?.message || String(error), "bad");
  } finally {
    state.busy = false;
  }
}

async function refreshGrant() {
  try {
    const { client, address } = requireClient();
    const grantId = $("grant-id").value.trim();
    const grant = await client.readContract({
      address,
      functionName: "get_grant",
      args: [grantId],
      account: walletAccount(),
    });
    $("grant-summary").textContent = `Grant ${grant.id} · ${grant.status} · ${grant.locked}/${grant.total} locked`;
    $("milestones").innerHTML = grant.milestones.map((milestone) => `
      <article class="milestone">
        <div class="milestone-top">
          <span class="milestone-index">#${milestone.index}</span>
          <span class="badge" data-status="${escapeHtml(milestone.status)}">${escapeHtml(milestone.status)}</span>
        </div>
        <h3>${escapeHtml(milestone.title)}</h3>
        <p class="mono">${escapeHtml(milestone.claim_type)} · ${escapeHtml(milestone.claim_target)}</p>
        <dl>
          <div><dt>Evidence</dt><dd>${escapeHtml(milestone.evidence || "—")}</dd></div>
          <div><dt>Verdict</dt><dd>${escapeHtml(milestone.verdict || "—")}</dd></div>
          <div><dt>Observed</dt><dd>${escapeHtml(milestone.observed || "—")}</dd></div>
          <div><dt>Payout</dt><dd>${escapeHtml(milestone.payout_status)} · ${escapeHtml(milestone.payout)}</dd></div>
        </dl>
      </article>
    `).join("");
    setMessage("State refreshed", "good");
  } catch (error) {
    $("grant-summary").textContent = "Grant state unavailable.";
    setMessage(error?.shortMessage || error?.message || String(error), "bad");
  }
}

$("connect").addEventListener("click", () => connectWallet().catch((error) => setMessage(error.message, "bad")));
$("create-form").addEventListener("submit", createGrant);
$("refresh").addEventListener("click", refreshGrant);
document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => runAction(button.dataset.action));
});
$("contract").addEventListener("change", () => {
  state.contractAddress = $("contract").value.trim();
  if (/^0x[0-9a-fA-F]{40}$/.test(state.contractAddress)) {
    window.localStorage.setItem(STORAGE_KEY, state.contractAddress);
  }
});

setConnectedView();
setMessage("Connect a wallet to begin");
