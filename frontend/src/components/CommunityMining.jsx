import React, { useEffect, useState } from 'react';
import { Pickaxe, Users, Activity, PlugZap, AlertTriangle, ArrowLeft } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';
import PreGenesisBanner from './PreGenesisBanner';

const CommunityMining = ({ onBack, miningMode = 'genesis', isPreGenesis = true }) => {
  const { wallet } = useWallet();
  const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

  const [stats, setStats] = useState({
    connected_miners: 0,
    total_hashrate: 0,
    mining_mode: miningMode,
    mode_display: isPreGenesis ? 'Pre-Genesis (Not connected)' : 'PoW Mining',
    genesis_status: isPreGenesis ? 'pending' : 'found'
  });
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const fetchStatus = async () => {
    try {
      const r = await fetch(`${backendUrl}/api/mining/status`);
      if (r.ok) {
        const data = await r.json();
        setStats({
          connected_miners: data.connected_miners ?? data.connectedMiners ?? 0,
          total_hashrate: data.total_hashrate || 0,
          mining_mode: data.mining_mode || miningMode,
          mode_display: data.mode_display || (isPreGenesis ? 'Pre-Genesis (Not connected)' : 'PoW Mining'),
          genesis_status: data.genesis_status || (isPreGenesis ? 'pending' : 'found')
        });
        if (data.connected_miners > 0) sessionStorage.setItem('wepo_miner_connected', 'true');
      }
    } catch (e) {
      // ignore, keep defaults
    }
  };

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 8000);
    return () => clearInterval(t);
  }, []);

  const connectMiner = async () => {
    if (!wallet?.address) {
      setError('No wallet address found');
      return;
    }
    setError('');
    setSuccess('');
    setConnecting(true);
    try {
      const r = await fetch(`${backendUrl}/api/mining/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: wallet.address, mining_mode: isPreGenesis ? 'genesis' : 'pow', wallet_type: 'regular' })
      });
      if (r.ok) {
        setConnected(true);
        setSuccess(isPreGenesis ? 'Connected to genesis queue!' : 'Connected to community PoW mining.');
        await fetchStatus();
      } else {
        const msg = await r.text();
        setError(msg || 'Failed to connect miner');
      }
    } catch (e) {
      setError('Failed to connect miner');
    } finally {
      setConnecting(false);
    }
  };

  const disabledStart = isPreGenesis || !connected;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-gray-400 hover:text-white"><ArrowLeft size={22} /></button>
        <div className="text-white font-semibold flex items-center gap-2">
          <Pickaxe className="h-5 w-5 text-yellow-400" /> Community Mining
        </div>
      </div>

      {isPreGenesis && (
        <PreGenesisBanner message="You can connect now to the genesis queue. Mining jobs will start automatically at genesis." />
      )}

      {error && (
        <div className="bg-red-900/40 border border-red-600/40 text-red-200 p-3 rounded">{error}</div>
      )}
      {success && (
        <div className="bg-green-900/30 border border-green-600/30 text-green-200 p-3 rounded">{success}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-300 text-sm">Connected Miners</div>
          <div className="text-2xl text-yellow-400 font-bold">{stats.connected_miners}</div>
        </div>
        <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-300 text-sm">Mode</div>
          <div className="text-lg text-purple-300 font-semibold">{stats.mining_mode === 'pow' ? 'PoW' : 'Genesis'}</div>
        </div>
        <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-300 text-sm">Status</div>
          <div className="text-lg text-blue-300 font-semibold">{stats.mode_display}</div>
        </div>
      </div>

      <div className="bg-gray-800/60 border border-gray-700 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-3">
          <PlugZap className="h-5 w-5 text-green-400" />
          <div className="text-white font-medium">Connect your miner</div>
        </div>
        <p className="text-gray-300 text-sm mb-3">
          {isPreGenesis ? 'Connect now to be counted for genesis launch. Mining starts when genesis block is found.' : 'Connect to start PoW mining.'}
        </p>
        <button onClick={connectMiner} disabled={connecting || connected}
          className="bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium px-4 py-2 rounded">
          {connected ? 'Connected' : (connecting ? 'Connecting...' : 'Connect Miner')}
        </button>
      </div>

      <div className="bg-gray-800/40 border border-gray-700 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="h-4 w-4 text-yellow-400" />
          <div className="text-white font-medium">
            {isPreGenesis ? 'Pre-Genesis limitations' : 'Public-test mining controls'}
          </div>
        </div>
        <ul className="text-gray-300 text-sm list-disc pl-6 space-y-1">
          {isPreGenesis ? (
            <>
              <li>Start/Stop mining and work submissions are disabled until genesis</li>
              <li>Your early connection still counts toward the connected miners count</li>
            </>
          ) : (
            <>
              <li>Miner connection status is live on this public-test stack</li>
              <li>Dedicated start/stop mining work controls are not yet exposed in this web UI</li>
            </>
          )}
        </ul>
        <div className="mt-3">
          <button disabled className="bg-gray-600 text-gray-300 px-4 py-2 rounded mr-2 cursor-not-allowed">
            {isPreGenesis ? 'Start Mining' : 'Mining Controls Preview'}
          </button>
          <button disabled className="bg-gray-600 text-gray-300 px-4 py-2 rounded cursor-not-allowed">
            {isPreGenesis ? 'Submit Work' : 'Work Submission Preview'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default CommunityMining;
