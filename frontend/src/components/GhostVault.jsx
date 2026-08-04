import React, { useState } from 'react';
import { AlertTriangle, Copy, RefreshCw, Shield, X } from 'lucide-react';
import PreGenesisBanner from './PreGenesisBanner';
import { useWallet } from '../contexts/WalletContext.jsx';

const GhostVault = ({ onClose, isPreGenesis = true }) => {
  const { refreshGhostWalletWitnesses, createGhostReceiverAddress } = useWallet();
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState(null);
  const [receiver, setReceiver] = useState('');

  const run = async (operation) => {
    setBusy(true);
    setError('');
    try {
      const result = await operation();
      setStatus(result);
    } catch (cause) {
      setError(cause?.message || 'Ghost operation failed');
    } finally {
      setBusy(false);
    }
  };

  const refresh = () => run(async () => {
    const result = await refreshGhostWalletWitnesses(password);
    return {
      kind: 'refresh',
      message: `${result.refreshedNotes} unspent note(s) verified at height ${result.tip.height}.`,
    };
  });

  const createReceiver = () => run(async () => {
    const address = await createGhostReceiverAddress(password);
    setReceiver(address);
    return { kind: 'receiver', message: 'Receiver created by the audited local bridge.' };
  });

  const copyReceiver = async () => {
    if (!receiver || !navigator.clipboard) return;
    await navigator.clipboard.writeText(receiver);
    setStatus({ kind: 'receiver', message: 'Receiver copied to the clipboard.' });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg max-w-xl w-full mx-4 overflow-hidden border border-purple-500/30">
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-purple-400" />
            <div className="text-white font-semibold">Ghost wallet</div>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-white" aria-label="Close Ghost wallet">
            <X size={18} />
          </button>
        </div>
        <div className="p-5 space-y-4">
          {isPreGenesis && (
            <PreGenesisBanner message="Ghost transfers remain disabled until mainnet activation and independent audit sign-off." />
          )}
          <div className="rounded-lg border border-purple-500/30 bg-purple-950/30 p-4 text-sm text-purple-100">
            Witness refresh is a local-verification control. Node data is never persisted until the native/WASM bridge accepts every path at one chain tip.
          </div>
          <label className="block text-sm text-gray-300">
            Wallet password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded bg-gray-900 border border-gray-600 px-3 py-2 text-white"
              autoComplete="current-password"
            />
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              type="button"
              onClick={refresh}
              disabled={busy || isPreGenesis || !password}
              className="flex items-center justify-center gap-2 rounded bg-purple-600 px-3 py-2 text-white disabled:opacity-50"
            >
              <RefreshCw size={16} /> Refresh witnesses
            </button>
            <button
              type="button"
              onClick={createReceiver}
              disabled={busy || isPreGenesis || !password}
              className="rounded border border-purple-400/50 px-3 py-2 text-purple-100 disabled:opacity-50"
            >
              Generate receive address
            </button>
          </div>
          {receiver && (
            <div className="rounded border border-gray-600 bg-gray-900 p-3">
              <div className="text-xs text-gray-400 mb-1">Ghost receiver</div>
              <div className="break-all text-sm text-white">{receiver}</div>
              <button type="button" onClick={copyReceiver} className="mt-2 inline-flex items-center gap-2 text-xs text-purple-300 hover:text-purple-200">
                <Copy size={14} /> Copy receiver
              </button>
            </div>
          )}
          {status && <div className="text-sm text-green-300">{status.message}</div>}
          {error && (
            <div className="flex gap-2 text-sm text-red-300" role="alert">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {error}
            </div>
          )}
          <div className="flex justify-end">
            <button type="button" onClick={onClose} className="rounded bg-gray-700 px-4 py-2 text-white">Close</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default GhostVault;
