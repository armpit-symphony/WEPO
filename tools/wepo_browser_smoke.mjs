const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:3000';
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:18021';
const NODE_URL = process.env.NODE_URL || 'http://127.0.0.1:18212';
const CDP_URL = process.env.CDP_URL || 'http://127.0.0.1:9222';
const SETTLEMENT_ADDRESS = process.env.SETTLEMENT_ADDRESS || 'wepo1208a6064a35231e174df1750f0d983d1';

const mainUsername = `ui_main_${Date.now()}`;
const mainPassword = 'PublicTest!123A';
const recipientAddress = `wepo1${crypto.randomUUID().replace(/-/g, '').slice(0, 32)}`;
const sendAmount = 1.0;
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
  console.log(`[browser-smoke] ${message}`);
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

  on(method, handler) {
    const handlers = this.eventHandlers.get(method) || [];
    handlers.push(handler);
    this.eventHandlers.set(method, handlers);
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

async function waitForDashboardReady(client, expectedBalance, requirePow = true) {
  const formattedBalance = Number(expectedBalance).toFixed(4);
  const expression = `(() => {
    const text = document.body.innerText;
    const balanceReady = text.includes(${JSON.stringify(formattedBalance)});
    const powReady = ${requirePow ? `text.includes('Network: PoW active')` : 'true'};
    return balanceReady && powReady;
  })()`;
  await waitFor(client, expression, 20000, 500);
}

async function setInputValue(client, selector, value) {
  const expression = `(() => {
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
  })()`;
  const ok = await client.evaluate(expression);
  if (!ok) throw new Error(`Input not found: ${selector}`);
}

async function clickSelector(client, selector) {
  const ok = await client.evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return false;
    el.click();
    return true;
  })()`);
  if (!ok) throw new Error(`Element not found for click: ${selector}`);
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
    if (ok) {
      return;
    }
    await sleep(250);
  }

  const bodyText = await client.evaluate(`document.body.innerText.slice(0, 2000)`);
  throw new Error(`Button not found: ${text}\nBODY:\n${bodyText}`);
}

async function clickBackButton(client) {
  const ok = await client.evaluate(`(() => {
    const candidates = Array.from(document.querySelectorAll('button'));
    const target = candidates.find((button) => {
      const parent = button.parentElement;
      return parent && parent.classList.contains('gap-3') && parent.classList.contains('mb-6');
    });
    if (!target) return false;
    target.click();
    return true;
  })()`);
  if (!ok) throw new Error('Back button not found');
}

async function getSessionWallet(client) {
  return client.evaluate(`(() => {
    const raw = sessionStorage.getItem('wepo_current_wallet');
    return raw ? JSON.parse(raw) : null;
  })()`);
}

async function getAuthSession(client) {
  return client.evaluate(`(() => {
    const raw = sessionStorage.getItem('wepo_auth_session');
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
    const backendResult = await httpJson(`${BACKEND_URL}/api/wallet/${address}`);
    let balance = backendResult.response.ok ? Number(backendResult.payload?.balance || 0) : 0;

    if (!backendResult.response.ok && backendResult.response.status === 429) {
      const nodeResult = await httpJson(`${NODE_URL}/api/wallet/${address}`);
      balance = nodeResult.response.ok ? Number(nodeResult.payload?.balance || 0) : 0;
    }

    if (balance >= minimumBalance) {
      return balance;
    }
    await sleep(1000);
  }
  throw new Error(`Timed out waiting for wallet ${address} balance >= ${minimumBalance}`);
}

async function main() {
  logStep(`opening ${FRONTEND_URL}`);
  const client = await createPageClient(FRONTEND_URL);

  try {
    await waitFor(client, `document.readyState === 'complete'`);
    try {
      await waitFor(client, `document.body.innerText.includes('Create Your Public Test Account')`);
    } catch (error) {
      const bodyText = await client.evaluate(`document.body.innerText.slice(0, 2000)`);
      throw new Error(
        `${error.message}\nBODY:\n${bodyText}`
      );
    }

    logStep('creating main wallet through browser');
    await setInputValue(client, '[data-testid="username-input"]', mainUsername);
    await setInputValue(client, '[data-testid="password-input"]', mainPassword);
    await setInputValue(client, '[data-testid="confirm-password-input"]', mainPassword);
    await clickSelector(client, '[data-testid="terms-checkbox"]');
    await clickSelector(client, '[data-testid="create-wallet-button"]');

    try {
      await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    } catch (error) {
      const bodyText = await client.evaluate(`document.body.innerText.slice(0, 2000)`);
      const sessionWalletRaw = await client.evaluate(`sessionStorage.getItem('wepo_current_wallet')`);
      const authSessionRaw = await client.evaluate(`sessionStorage.getItem('wepo_auth_session')`);
      throw new Error(
        `${error.message}\nBODY:\n${bodyText}\nSESSION_WALLET:${sessionWalletRaw}\nAUTH_SESSION:${authSessionRaw}`
      );
    }

    const walletAfterCreate = await getSessionWallet(client);
    if (!walletAfterCreate?.address) {
      throw new Error('Browser wallet session missing address after create');
    }
    const createdAddress = walletAfterCreate.address;
    const authSessionAfterCreate = await getAuthSession(client);
    if (!authSessionAfterCreate?.token) {
      throw new Error('Browser auth session missing token after create');
    }
    logStep(`browser-created wallet ${createdAddress}`);

    logStep('refreshing dashboard to verify session restore');
    await client.send('Page.reload', { ignoreCache: true });
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    const walletAfterRefresh = await getSessionWallet(client);
    if (walletAfterRefresh?.address !== createdAddress) {
      throw new Error('Dashboard did not restore the same wallet after refresh');
    }

    const recipient = { address: recipientAddress };
    logStep(`using synthetic recipient address ${recipient.address}`);

    logStep(`funding main wallet ${createdAddress} from settlement`);
    const funding = await fundWallet(createdAddress, fundingAmount);
    const fundedBalance = await waitForBalance(createdAddress, fundingAmount);
    logStep(`funding confirmed tx=${funding.tx_hash || funding.txid || 'unknown'} balance=${fundedBalance}`);

    logStep('reloading dashboard to pick up funded balance');
    await client.send('Page.reload', { ignoreCache: true });
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    await waitForDashboardReady(client, fundingAmount);

    logStep('opening receive screen');
    await clickButtonByText(client, 'Receive WEPO');
    await waitFor(client, `document.body.innerText.includes('Receive WEPO')`);
    const receiveAddress = await client.evaluate(`(() => {
      const inputs = Array.from(document.querySelectorAll('input[readonly]'));
      return inputs.length ? inputs[0].value : null;
    })()`);
    if (receiveAddress !== createdAddress) {
      throw new Error(`Receive screen address mismatch: ${receiveAddress} !== ${createdAddress}`);
    }

    logStep('returning to dashboard and logging out');
    await clickBackButton(client);
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    await clickButtonByText(client, 'Logout');
    await waitFor(client, `document.body.innerText.includes('Access Your Wallet')`, 20000);

    logStep('logging back in through browser');
    await setInputValue(client, 'input[name="username"]', mainUsername);
    await setInputValue(client, 'input[name="password"]', mainPassword);
    await clickButtonByText(client, 'Access Wallet');
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    await waitForDashboardReady(client, fundingAmount);
    const authSessionAfterLogin = await getAuthSession(client);
    if (!authSessionAfterLogin?.token) {
      throw new Error('Browser auth session missing token after login');
    }

    logStep('sending WEPO to recipient through browser');
    await clickButtonByText(client, 'Send WEPO');
    await waitFor(client, `document.body.innerText.includes('Recipient Address')`, 20000);
    await setInputValue(client, 'input[name="toAddress"]', recipient.address);
    await setInputValue(client, 'input[name="amount"]', String(sendAmount));
    await setInputValue(client, 'input[name="password"]', mainPassword);
    await clickButtonByText(client, 'Send WEPO');
    const successText = await waitFor(
      client,
      `(() => {
        const text = document.body.innerText;
        return text.includes('Transaction sent successfully! ID:') ? text : null;
      })()`,
      20000
    );

    const recipientBalance = await waitForBalance(recipient.address, sendAmount);
    logStep(`recipient balance after browser send=${recipientBalance}`);

    logStep('logging out and confirming login screen');
    await clickBackButton(client);
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    await clickButtonByText(client, 'Logout');
    await waitFor(client, `document.body.innerText.includes('Access Your Wallet')`, 20000);

    const summary = {
      mainUsername,
      mainAddress: createdAddress,
      recipientAddress: recipient.address,
      fundedBalance,
      recipientBalance,
      successText,
      authTokenIssuedOnCreate: Boolean(authSessionAfterCreate?.token),
      authTokenIssuedOnLogin: Boolean(authSessionAfterLogin?.token),
    };

    console.log(JSON.stringify(summary, null, 2));
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(`[browser-smoke] ERROR ${error.stack || error.message}`);
  process.exit(1);
});
