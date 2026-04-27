const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:3100';
const CDP_URL = process.env.CDP_URL || 'http://127.0.0.1:9222';
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:18021';

const username = `ui_spotcheck_${Date.now()}`;
const password = 'PublicTest!123A';

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
  console.log(`[spotcheck] ${message}`);
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 0;
    this.pending = new Map();
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
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) {
        pending.reject(new Error(message.error.message || 'CDP error'));
      } else {
        pending.resolve(message.result);
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

async function findExistingPageClientWithText(text) {
  const { payload: targets } = await httpJson(`${CDP_URL}/json/list`);
  if (!Array.isArray(targets)) {
    return null;
  }

  for (const target of targets) {
    if (!target.webSocketDebuggerUrl || target.type !== 'page') {
      continue;
    }

    const client = new CDPClient(target.webSocketDebuggerUrl);
    await client.connect();
    await client.send('Runtime.enable');
    const bodyText = await client.evaluate('document.body.innerText.slice(0, 4000)');
    if (typeof bodyText === 'string' && bodyText.includes(text)) {
      return client;
    }
    await client.close();
  }

  return null;
}

async function waitFor(client, expression, timeoutMs = 15000, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const result = await client.evaluate(expression);
      if (result) return result;
    } catch {
      // ignore transient DOM load errors
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
    if (ok) return;
    await sleep(250);
  }
  throw new Error(`Button not found: ${text}`);
}

async function clickHeaderBackButton(client) {
  const ok = await client.evaluate(`(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const target = buttons.find((button) => {
      const parent = button.parentElement;
      return parent && parent.classList.contains('gap-3') && !parent.classList.contains('justify-between');
    });
    if (!target) return false;
    target.click();
    return true;
  })()`);
  if (!ok) throw new Error('Header back button not found');
}

async function createBackendAccount() {
  const response = await fetch(`${BACKEND_URL}/api/wallet/create`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      username,
      password
    })
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Failed to create backend account for spot-check');
  }

  return payload;
}

async function main() {
  logStep(`opening ${FRONTEND_URL}`);
  let client = await createPageClient(FRONTEND_URL);

  try {
    await createBackendAccount();
    await waitFor(client, `document.readyState === 'complete'`);
    await client.evaluate(`(() => {
      localStorage.removeItem('wepo_wallet_exists');
      localStorage.removeItem('wepo_wallet_username');
      localStorage.removeItem('wepo_wallet_version');
      sessionStorage.clear();
      return true;
    })()`);
    await client.send('Page.reload', { ignoreCache: true });
    await client.evaluate(`(() => {
      localStorage.setItem('wepo_wallet_exists', 'true');
      localStorage.setItem('wepo_wallet_username', ${JSON.stringify(username)});
      localStorage.setItem('wepo_wallet_version', 'public-test');
      return true;
    })()`);
    await client.send('Page.reload', { ignoreCache: true });
    await waitFor(client, `document.body.innerText.includes('Access Your Wallet')`, 15000);

    logStep('logging into fresh browser account');
    await setInputValue(client, 'input[name="username"]', username);
    await setInputValue(client, 'input[name="password"]', password);
    await clickButtonByText(client, 'Access Wallet');
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 20000);
    await waitFor(client, `document.body.innerText.includes('Network: PoW active')`, 20000);

    logStep('checking Community Mining copy');
    await clickButtonByText(client, 'Community Mining');
    const miningText = await waitFor(client, `(() => {
      const text = document.body.innerText;
      if (text.includes('Public-test mining controls')) return text;
      return null;
    })()`, 20000);
    if (miningText.includes('Pre-Genesis limitations')) {
      throw new Error('Mining screen still shows pre-genesis limitations on active PoW stack');
    }
    await clickHeaderBackButton(client);
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 15000);

    logStep('checking Settings network label');
    await clickButtonByText(client, 'Settings');
    await waitFor(client, `document.body.innerText.includes('Wallet Info')`, 20000);
    await clickButtonByText(client, 'Wallet Info');
    const settingsText = await waitFor(client, `(() => {
      const text = document.body.innerText;
      if (text.includes('WEPO Public Test')) return text;
      return null;
    })()`, 20000);
    if (settingsText.includes('WEPO Mainnet')) {
      throw new Error('Settings screen still shows WEPO Mainnet on public-test stack');
    }
    await clickHeaderBackButton(client);
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 15000);

    logStep('checking Staking preview label');
    await clickButtonByText(client, 'Proof of Stake');
    const stakingText = await waitFor(client, `(() => {
      const text = document.body.innerText;
      if (text.includes('Web Staking Preview')) return text;
      return null;
    })()`, 20000);
    if (stakingText.includes('Staking Rewards Calculator') || stakingText.includes('Lock Period')) {
      throw new Error('Staking screen still shows the old mock staking workflow');
    }
    await clickHeaderBackButton(client);
    await waitFor(client, `document.body.innerText.includes('Total Balance')`, 15000);

    logStep('checking Messaging preview label');
    await clickButtonByText(client, 'Quantum Messages');
    const messagingText = await waitFor(client, `(() => {
      const text = document.body.innerText;
      if (text.includes('Experimental public-test messaging preview')) return text;
      return null;
    })()`, 20000);
    if (messagingText.includes('Universal Quantum') || messagingText.includes('End-to-end quantum encryption')) {
      throw new Error('Messaging screen still shows overstated production messaging claims');
    }

    console.log(JSON.stringify({
      username,
      checks: {
        miningCopy: true,
        settingsLabel: true,
        stakingPreview: true,
        messagingPreview: true
      }
    }, null, 2));
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  console.error(`[spotcheck] ERROR ${error.stack || error.message}`);
  process.exit(1);
});
