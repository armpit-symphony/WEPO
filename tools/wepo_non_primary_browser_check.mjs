import crypto from 'node:crypto';

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:3100';
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:18021';
const NODE_URL = process.env.NODE_URL || 'http://127.0.0.1:18212';
const CDP_URL = process.env.CDP_URL || 'http://127.0.0.1:9222';
const SETTLEMENT_ADDRESS = process.env.SETTLEMENT_ADDRESS || 'wepo1208a6064a35231e174df1750f0d983d1';

const username = `ui_nonprimary_${Date.now()}`;
const password = 'PublicTest!123A';
const fundingAmount = 5.0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function httpJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text;
  }
  return { response, payload, text };
}

function logStep(message) {
  console.log(`[non-primary] ${message}`);
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 0;
    this.pending = new Map();
    this.eventHandlers = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Timed out connecting to DevTools')), 10000);
      this.ws.onopen = () => {
        clearTimeout(timeout);
        resolve();
      };
      this.ws.onerror = (error) => {
        clearTimeout(timeout);
        reject(error);
      };
    });

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) {
          pending.reject(new Error(message.error.message || 'CDP error'));
        } else {
          pending.resolve(message.result);
        }
        return;
      }

      const handlers = this.eventHandlers.get(message.method) || [];
      for (const handler of handlers) {
        handler(message.params || {});
      }
    };
  }

  async send(method, params = {}) {
    const id = ++this.nextId;
    const payload = JSON.stringify({ id, method, params });
    const promise = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.ws.send(payload);
    return promise;
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || 'Runtime evaluation failed');
    }
    return result.result?.value;
  }

  async close() {
    if (!this.ws) return;
    this.ws.close();
    await sleep(250);
  }
}

async function createPageClient(url) {
  const { payload: versionPayload } = await httpJson(`${CDP_URL}/json/version`);
  if (!versionPayload?.webSocketDebuggerUrl) {
    throw new Error('DevTools browser endpoint unavailable');
  }

  const browserClient = new CDPClient(versionPayload.webSocketDebuggerUrl);
  await browserClient.connect();
  const createTarget = await browserClient.send('Target.createTarget', { url });
  const targetId = createTarget.targetId;
  await browserClient.close();

  for (let attempt = 0; attempt < 40; attempt += 1) {
    const { payload: targets } = await httpJson(`${CDP_URL}/json/list`);
    const pageTarget = Array.isArray(targets)
      ? targets.find((target) => target.id === targetId || target.targetId === targetId)
      : null;
    if (pageTarget?.webSocketDebuggerUrl) {
      const pageClient = new CDPClient(pageTarget.webSocketDebuggerUrl);
      await pageClient.connect();
      await pageClient.send('Page.enable');
      await pageClient.send('Runtime.enable');
      return pageClient;
    }
    await sleep(250);
  }

  throw new Error('Timed out waiting for page target');
}

async function waitFor(client, expression, timeoutMs = 15000, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const result = await client.evaluate(expression);
      if (result) return result;
    } catch {
      // Ignore transient DOM errors while the app is loading.
    }
    await sleep(intervalMs);
  }
  throw new Error(`Timed out waiting for condition: ${expression}`);
}

async function setInputValue(client, selector, value) {
  const ok = await client.evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return false;
    el.focus();
    const prototype = Object.getPrototypeOf(el);
    const valueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    if (valueSetter) {
      valueSetter.call(el, ${JSON.stringify(value)});
    } else {
      el.value = ${JSON.stringify(value)};
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  if (!ok) {
    throw new Error(`Input not found: ${selector}`);
  }
}

async function clickSelector(client, selector) {
  const ok = await client.evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return false;
    el.click();
    return true;
  })()`);
  if (!ok) {
    throw new Error(`Element not found for click: ${selector}`);
  }
}

async function clickButtonByText(client, text) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const ok = await client.evaluate(`(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      const target = buttons.find((button) => button.innerText.replace(/\\s+/g, ' ').trim().includes(${JSON.stringify(text)}));
      if (!target) return false;
      target.click();
      return true;
    })()`);
    if (ok) return;
    await sleep(250);
  }

  const bodyText = await client.evaluate('document.body.innerText.slice(0, 3000)');
  throw new Error(`Button not found: ${text}\nBODY:\n${bodyText}`);
}

async function clickHeaderBackButton(client) {
  const ok = await client.evaluate(`(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const target = buttons.find((button) => {
      const parent = button.parentElement;
      return parent && parent.classList.contains('gap-3') && parent.classList.contains('mb-6');
    });
    if (!target) return false;
    target.click();
    return true;
  })()`);
  if (!ok) {
    throw new Error('Header back button not found');
  }
}

async function getSessionWallet(client) {
  return client.evaluate(`(() => {
    const raw = sessionStorage.getItem('wepo_current_wallet');
    return raw ? JSON.parse(raw) : null;
  })()`);
}

async function fundWallet(address, amount) {
  const { response, payload } = await httpJson(`${NODE_URL}/api/transaction/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from_address: SETTLEMENT_ADDRESS,
      to_address: address,
      amount,
      fee: 0.0001,
      privacy_level: 'standard',
    }),
  });

  if (!response.ok) {
    throw new Error(`Funding failed: ${JSON.stringify(payload)}`);
  }

  return payload;
}

async function waitForBalance(address, minimumBalance) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const { response, payload } = await httpJson(`${BACKEND_URL}/api/wallet/${address}`);
    const balance = response.ok ? Number(payload?.balance || 0) : 0;
    if (balance >= minimumBalance) {
      return balance;
    }
    await sleep(1000);
  }
  throw new Error(`Timed out waiting for wallet ${address} balance >= ${minimumBalance}`);
}

async function ensureBodyIncludes(client, text, timeoutMs = 15000) {
  await waitFor(client, `document.body.innerText.includes(${JSON.stringify(text)})`, timeoutMs, 250);
}

async function ensureBodyNotIncludes(client, text) {
  const found = await client.evaluate(`document.body.innerText.includes(${JSON.stringify(text)})`);
  if (found) {
    const body = await client.evaluate('document.body.innerText.slice(0, 3000)');
    throw new Error(`Unexpected text present: ${text}\nBODY:\n${body}`);
  }
}

async function getReturnSurface(client, timeoutMs = 15000) {
  return waitFor(client, `(() => {
    const text = document.body.innerText;
    if (text.includes('RWA Dashboard')) return 'rwa';
    if (text.includes('Total Balance')) return 'overview';
    return null;
  })()`, timeoutMs, 250);
}

async function main() {
  logStep(`opening ${FRONTEND_URL}`);
  const client = await createPageClient(FRONTEND_URL);

  try {
    await waitFor(client, `document.readyState === 'complete'`);
    await client.evaluate(`(() => {
      localStorage.removeItem('wepo_wallet_exists');
      localStorage.removeItem('wepo_wallet_username');
      localStorage.removeItem('wepo_wallet_version');
      sessionStorage.clear();
      return true;
    })()`);
    await client.send('Page.reload', { ignoreCache: true });
    await waitFor(client, `document.readyState === 'complete'`);
    await ensureBodyIncludes(client, 'Create Your Public Test Account');

    logStep('creating browser wallet for non-primary checks');
    await setInputValue(client, '[data-testid="username-input"]', username);
    await setInputValue(client, '[data-testid="password-input"]', password);
    await setInputValue(client, '[data-testid="confirm-password-input"]', password);
    await clickSelector(client, '[data-testid="terms-checkbox"]');
    await clickSelector(client, '[data-testid="create-wallet-button"]');
    await ensureBodyIncludes(client, 'Total Balance', 20000);

    const wallet = await getSessionWallet(client);
    if (!wallet?.address) {
      throw new Error('Browser wallet session missing address after create');
    }

    logStep(`funding browser wallet ${wallet.address}`);
    const funding = await fundWallet(wallet.address, fundingAmount);
    const fundedBalance = await waitForBalance(wallet.address, fundingAmount);
    logStep(`funding confirmed tx=${funding.tx_hash || funding.txid || 'unknown'} balance=${fundedBalance}`);

    await client.send('Page.reload', { ignoreCache: true });
    await ensureBodyIncludes(client, 'Total Balance', 20000);
    await ensureBodyIncludes(client, 'Network: PoW active', 20000);
    await ensureBodyIncludes(client, '5.0000', 20000);

    logStep('checking Quantum Vault preview messaging');
    await clickButtonByText(client, 'Quantum Vault');
    await ensureBodyIncludes(client, 'Quantum Vault');
    await ensureBodyIncludes(client, 'Web Vault Preview');
    await clickButtonByText(client, 'Close');
    await ensureBodyIncludes(client, 'Total Balance');

    logStep('checking RWA dashboard load');
    await clickButtonByText(client, 'RWA / Exchange');
    await ensureBodyIncludes(client, 'RWA Dashboard', 20000);
    await ensureBodyIncludes(client, 'Market Overview');
    await ensureBodyIncludes(client, 'Tradeable Tokens');
    await ensureBodyNotIncludes(client, 'Failed to load RWA data');

    logStep('checking RWA create-asset screen');
    await clickButtonByText(client, 'Create Asset');
    await ensureBodyIncludes(client, 'Step 1: Create Asset');
    await ensureBodyIncludes(client, 'RWA Creation Fee');
    await clickButtonByText(client, 'Back');
    await ensureBodyIncludes(client, 'RWA Dashboard');

    logStep('checking UnifiedExchange BTC preview surface');
    await clickButtonByText(client, 'DEX Trading');
    await ensureBodyIncludes(client, 'WEPO DEX', 20000);
    await ensureBodyIncludes(client, 'Bitcoin DEX');
    await ensureBodyIncludes(client, 'Public-test BTC swap flow for WEPO exchange validation');
    await ensureBodyIncludes(client, 'Privacy Mixing');

    logStep('checking RWA DEX tab');
    await clickButtonByText(client, 'RWA DEX');
    await ensureBodyIncludes(client, 'Select RWA Token');
    await ensureBodyIncludes(client, 'Trade Real World Asset tokens for WEPO');

    logStep('checking liquidity tab');
    await clickButtonByText(client, 'Liquidity');
    await ensureBodyIncludes(client, 'Add Liquidity');
    await waitFor(client, `(() => {
      const text = document.body.innerText;
      return text.includes('Create Market') || text.includes('Add liquidity to earn fees from trades') || text.includes('Create the market by providing initial liquidity');
    })()`, 15000, 250);

    logStep('returning from UnifiedExchange and RWA dashboard');
    await clickHeaderBackButton(client);
    const returnSurface = await getReturnSurface(client, 15000);
    if (returnSurface === 'rwa') {
      await clickHeaderBackButton(client);
      await ensureBodyIncludes(client, 'Total Balance', 15000);
    } else {
      await ensureBodyIncludes(client, 'Total Balance', 15000);
    }

    const summary = {
      username,
      address: wallet.address,
      fundedBalance,
      fundingTx: funding.tx_hash || funding.txid || null,
      returnSurface,
      checks: {
        vaultPreview: true,
        rwaDashboard: true,
        rwaCreateAsset: true,
        btcDexPreview: true,
        rwaDexTab: true,
        liquidityTab: true
      }
    };

    console.log(JSON.stringify(summary, null, 2));
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(`[non-primary] ERROR ${error.stack || error.message}`);
  process.exit(1);
});
