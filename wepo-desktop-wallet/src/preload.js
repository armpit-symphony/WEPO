const { contextBridge, ipcRenderer } = require('electron');

// The canonical client receives one narrow, byte-only Ghost crypto operation.
// No filesystem, shell, wallet export, or generic IPC capability is exposed.
contextBridge.exposeInMainWorld('electronAPI', {
  ghostWalletRequest: (request) => {
    if (!(request instanceof Uint8Array)) {
      throw new TypeError('Ghost wallet bridge request must be Uint8Array');
    }
    return ipcRenderer.invoke('ghost-wallet-request', request);
  },
  isElectron: true,
  platform: process.platform,
});
