const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

// Backend server
let backendServer = null;

// Keep a global reference of the window object
let mainWindow;

function createWindow() {
  // Create the browser window
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 800,
    icon: path.join(__dirname, '../assets/icon.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      enableRemoteModule: false,
      preload: path.join(__dirname, 'preload.js')
    },
    titleBarStyle: 'default',
    show: false // Don't show until ready
  });

  // Set window title
  mainWindow.setTitle('WEPO Wallet - Decentralized Cryptocurrency Wallet');

  // Load the frontend
  const isDev = process.env.NODE_ENV === 'development';
  
  if (isDev) {
    // Development mode - load from local server
    mainWindow.loadURL('http://localhost:3000');
    // Open DevTools in development
    mainWindow.webContents.openDevTools();
  } else {
    // Production mode - load from built files
    const frontendPath = path.join(__dirname, '../frontend/index.html');
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
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Handle external links
  mainWindow.webContents.on('will-navigate', (event, navigationUrl) => {
    const parsedUrl = new URL(navigationUrl);
    
    if (parsedUrl.origin !== 'http://localhost:3000' && parsedUrl.origin !== 'file://') {
      event.preventDefault();
      shell.openExternal(navigationUrl);
    }
  });
}

// Start the backend server
function startBackendServer() {
  try {
    const backendPath = path.join(__dirname, 'backend/server.js');
    
    if (fs.existsSync(backendPath)) {
      backendServer = require(backendPath);
      console.log('✅ Backend server started successfully');
    } else {
      console.warn('⚠️  Backend server not found, running in frontend-only mode');
    }
  } catch (error) {
    console.error('❌ Failed to start backend server:', error);
    dialog.showErrorBox('Backend Error', 'Failed to start backend server. Some features may not work.');
  }
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
  // Start backend server first
  startBackendServer();
  
  // Create window and menu
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

app.on('before-quit', () => {
  // Clean up backend server
  if (backendServer && backendServer.close) {
    backendServer.close();
  }
});

// Security: Prevent new window creation
app.on('web-contents-created', (event, contents) => {
  contents.on('new-window', (event, navigationUrl) => {
    event.preventDefault();
    shell.openExternal(navigationUrl);
  });
});

// Handle app certificate errors
app.on('certificate-error', (event, webContents, url, error, certificate, callback) => {
  if (url.startsWith('https://localhost') || url.startsWith('http://localhost')) {
    // Allow local development certificates
    event.preventDefault();
    callback(true);
  } else {
    callback(false);
  }
});

// IPC handlers for communication with renderer process
ipcMain.handle('get-app-version', () => {
  return app.getVersion();
});

ipcMain.handle('get-app-path', () => {
  return app.getAppPath();
});

console.log('🚀 WEPO Desktop Wallet starting...');
