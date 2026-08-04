const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

// Keep a global reference of the window object
let mainWindow;
const GHOST_BRIDGE_MAX_REQUEST_BYTES = 64 * 1024;
const GHOST_BRIDGE_MAX_RESPONSE_BYTES = 1024 * 1024 + 4096;
const GHOST_BRIDGE_TIMEOUT_MS = 5000;

function ghostBridgeBinary() {
  const filename = process.platform === 'win32'
    ? 'ghost_wallet_bridge.exe'
    : 'ghost_wallet_bridge';
  return app.isPackaged
    ? path.join(process.resourcesPath, 'ghost', filename)
    : path.join(__dirname, '../../zk/target/release', filename);
}

function normalizeGhostRequest(value) {
  if (value instanceof Uint8Array) return Buffer.from(value);
  if (ArrayBuffer.isView(value)) {
    return Buffer.from(value.buffer, value.byteOffset, value.byteLength);
  }
  if (value instanceof ArrayBuffer) return Buffer.from(value);
  throw new Error('Ghost wallet bridge request is not bytes');
}

function trustedGhostRenderer(event) {
  if (!mainWindow || event.sender !== mainWindow.webContents) return false;
  const senderUrl = event.senderFrame?.url || event.sender.getURL();
  if (!app.isPackaged && process.env.NODE_ENV === 'development') {
    return senderUrl === 'http://localhost:3000/';
  }
  return senderUrl.startsWith('file://');
}

function requestGhostWallet(event, value) {
  if (!trustedGhostRenderer(event)) {
    return Promise.reject(new Error('Ghost wallet bridge renderer is not trusted'));
  }
  let request;
  try {
    request = normalizeGhostRequest(value);
  } catch (error) {
    return Promise.reject(error);
  }
  if (request.length === 0 || request.length > GHOST_BRIDGE_MAX_REQUEST_BYTES) {
    return Promise.reject(new Error('Ghost wallet bridge request is out of bounds'));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const chunks = [];
    let responseLength = 0;
    const child = spawn(ghostBridgeBinary(), [], {
      cwd: path.dirname(ghostBridgeBinary()),
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    const finish = (callback, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      callback(result);
    };
    const timeout = setTimeout(() => {
      child.kill();
      finish(reject, new Error('Ghost wallet bridge timed out'));
    }, GHOST_BRIDGE_TIMEOUT_MS);
    child.stdout.on('data', (chunk) => {
      responseLength += chunk.length;
      if (responseLength > GHOST_BRIDGE_MAX_RESPONSE_BYTES) {
        child.kill();
        finish(reject, new Error('Ghost wallet bridge response is out of bounds'));
        return;
      }
      chunks.push(chunk);
    });
    child.on('error', () => finish(reject, new Error('Ghost wallet bridge is unavailable')));
    child.on('close', (code) => {
      if (code !== 0) {
        finish(reject, new Error('Ghost wallet bridge rejected the request'));
        return;
      }
      finish(resolve, new Uint8Array(Buffer.concat(chunks)));
    });
    child.stdin.on('error', () => {
      finish(reject, new Error('Ghost wallet bridge rejected the request'));
    });
    child.stdin.end(request);
  });
}

function registerGhostBridge() {
  ipcMain.handle('ghost-wallet-request', requestGhostWallet);
}

const openExternalHttps = (target) => {
  try {
    const parsed = new URL(target);
    if (parsed.protocol === 'https:') {
      void shell.openExternal(parsed.toString());
    }
  } catch (error) {
    // Ignore malformed or non-HTTPS external navigation requests.
  }
};


function createWindow() {
  // Create the browser window
  const isDev = !app.isPackaged && process.env.NODE_ENV === 'development';
  const frontendRoot = app.isPackaged
    ? path.join(process.resourcesPath, 'frontend')
    : path.join(__dirname, '../../frontend/build');
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 800,
    icon: path.join(__dirname, '../assets/icon.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: true,
      allowRunningInsecureContent: false,
      devTools: isDev
    },
    titleBarStyle: 'default',
    show: false // Don't show until ready
  });

  // Set window title
  mainWindow.setTitle('WEPO Wallet - Decentralized Cryptocurrency Wallet');

  // Load the frontend
  if (isDev) {
    // Development mode - load from local server
    mainWindow.loadURL('http://localhost:3000');
    // Open DevTools in development
    mainWindow.webContents.openDevTools();
  } else {
    // Production mode - load from built files
    // Desktop and web ship the exact same compiled wallet client. This prevents
    // recovery/address/signature drift between the two surfaces.
    const frontendPath = path.join(frontendRoot, 'index.html');
    mainWindow.loadFile(frontendPath);
  }

  // Show window when ready to prevent visual flash
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    
    // Focus on window
    if (isDev) {
      mainWindow.focus();
    }
  });

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Prevent navigation to external URLs
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternalHttps(url);
    return { action: 'deny' };
  });

  // Handle external links
  mainWindow.webContents.on('will-navigate', (event, navigationUrl) => {
    let allowed = false;
    try {
      const parsedUrl = new URL(navigationUrl);
      if (isDev) {
        allowed = parsedUrl.origin === 'http://localhost:3000';
      } else if (parsedUrl.protocol === 'file:') {
        const candidate = path.resolve(decodeURIComponent(parsedUrl.pathname.replace(/^\/(.:\/)/, '$1')));
        const relative = path.relative(path.resolve(frontendRoot), candidate);
        allowed = relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
      }
    } catch (error) {
      allowed = false;
    }
    if (!allowed) {
      event.preventDefault();
      openExternalHttps(navigationUrl);
    }
  });
}


// Create application menu
function createMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'New Wallet',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            mainWindow.webContents.send('menu-action', 'new-wallet');
          }
        },
        {
          label: 'Import Wallet',
          accelerator: 'CmdOrCtrl+I',
          click: () => {
            mainWindow.webContents.send('menu-action', 'import-wallet');
          }
        },
        { type: 'separator' },
        {
          label: 'Exit',
          accelerator: process.platform === 'darwin' ? 'Cmd+Q' : 'Ctrl+Q',
          click: () => {
            app.quit();
          }
        }
      ]
    },
    {
      label: 'Wallet',
      submenu: [
        {
          label: 'Send WEPO',
          accelerator: 'CmdOrCtrl+S',
          click: () => {
            mainWindow.webContents.send('menu-action', 'send-wepo');
          }
        },
        {
          label: 'Receive WEPO',
          accelerator: 'CmdOrCtrl+R',
          click: () => {
            mainWindow.webContents.send('menu-action', 'receive-wepo');
          }
        },
        { type: 'separator' },
        {
          label: 'Bitcoin Wallet',
          accelerator: 'CmdOrCtrl+B',
          click: () => {
            mainWindow.webContents.send('menu-action', 'bitcoin-wallet');
          }
        },
        {
          label: 'Quantum Vault',
          accelerator: 'CmdOrCtrl+Q',
          click: () => {
            mainWindow.webContents.send('menu-action', 'quantum-vault');
          }
        }
      ]
    },
    {
      label: 'Tools',
      submenu: [
        {
          label: 'Mining',
          click: () => {
            mainWindow.webContents.send('menu-action', 'mining');
          }
        },
        {
          label: 'Staking',
          click: () => {
            mainWindow.webContents.send('menu-action', 'staking');
          }
        },
        {
          label: 'Masternodes',
          click: () => {
            mainWindow.webContents.send('menu-action', 'masternodes');
          }
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'About WEPO Wallet',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'About WEPO Wallet',
              message: 'WEPO Wallet v1.0.0',
              detail: 'Decentralized cryptocurrency wallet with privacy features, Bitcoin integration, and quantum resistance.\\n\\nPublic release timing remains under review.',
              buttons: ['OK']
            });
          }
        },
        {
          label: 'GitHub Repository',
          click: () => {
            shell.openExternal('https://github.com/wepo-project/wepo-desktop-wallet');
          }
        },
        { type: 'separator' },
        {
          label: 'Report Issue',
          click: () => {
            shell.openExternal('https://github.com/wepo-project/wepo-desktop-wallet/issues');
          }
        }
      ]
    }
  ];

  // macOS specific menu adjustments
  if (process.platform === 'darwin') {
    template.unshift({
      label: app.getName(),
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    });
  }

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// App event handlers
app.whenReady().then(() => {
  // Create window and menu
  registerGhostBridge();
  createWindow();
  createMenu();

  app.on('activate', () => {
    // On macOS, re-create window when dock icon is clicked
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  // On macOS, keep app running even when all windows are closed
  if (process.platform !== 'darwin') {
    app.quit();
  }
});



console.log('🚀 WEPO Desktop Wallet starting...');
