import React, { useEffect, useState } from 'react';
import { Eye, EyeOff, Send, Download, Settings as SettingsIcon, Pickaxe, Shield, LogOut, Bitcoin, ChevronDown, Coins, Package, Boxes } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';
import SendWepo from './SendWepo';
import ReceiveWepo from './ReceiveWepo';
import QuantumVault from './QuantumVault';
import CommunityMining from './CommunityMining';
import SettingsPanel from './SettingsPanel';
import QuantumMessaging from './QuantumMessaging';
import StakingInterface from './StakingInterface';
import RWADashboard from './RWADashboard';
import BlockExplorer from './BlockExplorer';
import { sessionManager } from '../utils/securityUtils';

const Dashboard = ({ onLogout }) => {
  const {
    wallet,
    balance,
    transactions,
    loadWalletData,
    setWallet,
    setBalance,
    setTransactions,
    logout
  } = useWallet();

  const [activeTab, setActiveTab] = useState('overview');
  const [showBalance, setShowBalance] = useState(true);
  const [isPreGenesis, setIsPreGenesis] = useState(true);
  const [showVaultModal, setShowVaultModal] = useState(false);
  const [genesisLaunchTime, setGenesisLaunchTime] = useState(null);

  const refreshMiningStatus = async () => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/mining/status`);
      if (!response.ok) {
        setIsPreGenesis(true);
        return false;
      }

      const payload = await response.json();
      const powActive = payload.genesis_status === 'found' || payload.mining_mode === 'pow';
      setIsPreGenesis(!powActive);
      if (payload.genesis_launch_time) {
        setGenesisLaunchTime(payload.genesis_launch_time);
      }
      return powActive;
    } catch {
      setIsPreGenesis(true);
      return false;
    }
  };

  useEffect(() => {
    // Restore session wallet and data
    const init = async () => {
      try {
        const authSession = sessionManager.getAuthSession();
        const isLocked = sessionManager.get('wepo_locked') === true;
        const activeWallet = wallet || (() => {
          const sw = sessionStorage.getItem('wepo_current_wallet');
          return sw ? JSON.parse(sw) : null;
        })();

        if (authSession && !isLocked && activeWallet) {
          if (!wallet) {
            setWallet(activeWallet);
          }
          await loadWalletData(activeWallet.address || activeWallet.wepo?.address);
        }
      } catch (e) {
        setBalance(0);
        setTransactions([]);
      }
    };
    init();
  }, [wallet, setWallet, setBalance, setTransactions, loadWalletData]);

  useEffect(() => {
    let isMounted = true;
    // Genesis/mining status changes on the order of minutes, not seconds, so we
    // poll lazily and only while the tab is visible. Aggressive polling on a
    // hidden tab needlessly holds browser sockets and competes with the active
    // wallet's requests (logins, messaging) under the ~6-connection per-host cap.
    const POLL_INTERVAL_MS = 30000;

    const syncMiningStatus = async () => {
      if (!isMounted || document.hidden) {
        return;
      }
      await refreshMiningStatus();
    };

    const onVisibilityChange = () => {
      // Refresh immediately when the tab comes back into view.
      if (!document.hidden) {
        syncMiningStatus();
      }
    };

    syncMiningStatus();
    const intervalId = window.setInterval(syncMiningStatus, POLL_INTERVAL_MS);
    window.addEventListener('focus', syncMiningStatus);
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
      window.removeEventListener('focus', syncMiningStatus);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  const openSendTab = async () => {
    await refreshMiningStatus();
    setActiveTab('send');
  };

  // Block explorer: open the external explorer if one is configured
  // (REACT_APP_EXPLORER_URL), otherwise use the built-in in-wallet explorer.
  const openExplorer = () => {
    const explorerUrl = process.env.REACT_APP_EXPLORER_URL;
    if (explorerUrl) {
      window.open(explorerUrl, '_blank', 'noopener,noreferrer');
    } else {
      setActiveTab('explorer');
    }
  };

  const formatBalance = (amt) => new Intl.NumberFormat('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 }).format(amt || 0);
  const short = (s) => (s && s.length > 10 ? `${s.substring(0, 10)}...${s.substring(s.length - 6)}` : s || 'N/A');

  const [showBitcoinDetails, setShowBitcoinDetails] = useState(false);

  const Overview = () => (
    <div className="space-y-6">
      <div className="rounded-2xl p-6 text-white bg-gradient-to-r from-purple-600 to-blue-600">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-purple-100 text-sm font-medium mb-2">Total Balance</div>
            <div className="flex items-center gap-3 mt-2">
              <span className="text-3xl font-bold">{showBalance ? formatBalance(balance) : '••••••••'}</span>
              <span className="text-xl text-purple-200">WEPO</span>
              <button onClick={() => setShowBalance(!showBalance)} className="text-purple-200 hover:text-white transition-colors">
                {showBalance ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>
          </div>
          <div className="text-right">
            <Shield className="h-12 w-12 text-purple-200 mb-2" />
          </div>
        </div>
        <div className="text-sm text-purple-100">Address: {short(wallet?.address || wallet?.wepo?.address)}</div>
        {!isPreGenesis && (
          <div className="text-xs text-green-200 mt-2">Network: PoW active</div>
        )}
        {isPreGenesis && (
          <div className="text-xs text-yellow-200 mt-2">Network: Pre-Genesis • Countdown to Genesis: {genesisLaunchTime ? Math.max(0, Math.floor((genesisLaunchTime*1000 - Date.now())/1000)) + 's' : 'TBA'}</div>
        )}
      </div>

      {/* BTC Wallet Section (compact) */}
      <div className="mb-6">
        <button onClick={() => setShowBitcoinDetails(!showBitcoinDetails)} className="w-full bg-gradient-to-r from-orange-900/30 to-yellow-900/30 border border-orange-500/30 rounded-xl p-4 hover:from-orange-900/40 hover:to-yellow-900/40 transition-all duration-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Bitcoin className="h-6 w-6 text-orange-400" />
              <div className="text-left">
                <h3 className="text-white font-semibold">BTC</h3>
                <div className="text-sm text-gray-300">0.00000000 BTC</div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <div className="text-yellow-300 text-sm">Preview Only</div>
                <div className="text-xs text-gray-400">Not live custody in this public test build</div>
              </div>
              <div className={`transform transition-transform duration-200 ${showBitcoinDetails ? 'rotate-180' : ''}`}>
                <ChevronDown className="h-4 w-4 text-gray-400" />
              </div>
            </div>
          </div>
        </button>
        {showBitcoinDetails && (
          <div className="mt-3 bg-gradient-to-r from-orange-900/20 to-yellow-900/20 border border-orange-500/20 rounded-xl p-6">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-sm mb-4">
              <div className="bg-black/30 rounded-lg p-3">
                <div className="text-gray-400">BTC Balance</div>
                <div className="text-orange-400 font-semibold">0.00000000 BTC</div>
                <div className="text-yellow-400 text-xs mt-1">Preview only</div>
              </div>
              <div className="bg-black/30 rounded-lg p-3">
                <div className="text-gray-400">Mode</div>
                <div className="text-white font-semibold">Public Test Preview</div>
                <div className="text-blue-400 text-xs mt-1">BTC custody not live in this build</div>
              </div>
              <div className="bg-black/30 rounded-lg p-3">
                <div className="text-gray-400">Address Type</div>
                <div className="text-white font-semibold">Not exposed</div>
              </div>
              <div className="bg-black/30 rounded-lg p-3">
                <div className="text-gray-400">Derivation</div>
                <div className="text-white font-mono">N/A in public test build</div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* 1: Send WEPO */}
        <button onClick={openSendTab} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Send className="h-6 w-6 text-purple-400 mx-auto mb-2" />
          <span className="text-white font-medium">Send WEPO</span>
        </button>
        {/* 2: Receive WEPO */}
        <button onClick={() => setActiveTab('receive')} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Download className="h-6 w-6 text-blue-400 mx-auto mb-2" />
          <span className="text-white font-medium">Receive WEPO</span>
        </button>
        {/* 3: Miner (PoW) */}
        <button onClick={() => setActiveTab('mining')} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Pickaxe className="h-6 w-6 text-yellow-400 mx-auto mb-2" />
          <span className="text-white font-medium">Community Mining (PoW)</span>
        </button>
        {/* 4: PoS */}
        <button onClick={() => setActiveTab('staking')} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Coins className="h-6 w-6 text-blue-400 mx-auto mb-2" />
          <span className="text-white font-medium">Proof of Stake (PoS)</span>
          <div className="text-xs text-gray-400 mt-1">Status / preview</div>
        </button>
        {/* 5: Quantum Vault */}
        <button onClick={() => setShowVaultModal(true)} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Shield className="h-6 w-6 text-purple-400 mx-auto mb-2" />
          <span className="text-white font-medium">Quantum Vault</span>
        </button>
        {/* 6: Quantum Messages */}
        <button onClick={() => setActiveTab('messaging')} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <span className="text-white font-medium">Quantum Messages</span>
          <div className="text-xs text-gray-400 mt-1">Experimental preview</div>
        </button>
        {/* 7: Settings */}
        <button onClick={() => setActiveTab('settings')} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <SettingsIcon className="h-6 w-6 text-gray-400 mx-auto mb-2" />
          <span className="text-white font-medium">Settings</span>
        </button>
        {/* 8: RWA / Exchange */}
        <button onClick={() => setActiveTab('rwa')} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Package className="h-6 w-6 text-emerald-400 mx-auto mb-2" />
          <span className="text-white font-medium">RWA / Exchange</span>
          <div className="text-xs text-gray-400 mt-1">Public-test preview</div>
        </button>
        {/* 9: Block Explorer */}
        <button onClick={openExplorer} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <Boxes className="h-6 w-6 text-blue-400 mx-auto mb-2" />
          <span className="text-white font-medium">Block Explorer</span>
          <div className="text-xs text-gray-400 mt-1">Blocks · tx · address</div>
        </button>
        {/* 10: Logout */}
        <button onClick={async () => { await logout(); onLogout && onLogout(); }} className="bg-gray-800/50 hover:bg-gray-700/50 border border-purple-500/30 rounded-xl p-4 text-center transition-all">
          <LogOut className="h-6 w-6 text-red-400 mx-auto mb-2" />
          <span className="text-white font-medium">Logout</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {activeTab === 'overview' && <Overview />}
      {activeTab === 'send' && <SendWepo onClose={() => setActiveTab('overview')} isPreGenesis={isPreGenesis} />}
      {activeTab === 'receive' && <ReceiveWepo onClose={() => setActiveTab('overview')} />}
      {activeTab === 'mining' && <CommunityMining onBack={() => setActiveTab('overview')} isPreGenesis={isPreGenesis} />}
      {activeTab === 'settings' && <SettingsPanel onClose={() => setActiveTab('overview')} />}
      {activeTab === 'messaging' && <QuantumMessaging onBack={() => setActiveTab('overview')} />}
      {activeTab === 'staking' && <StakingInterface onClose={() => setActiveTab('overview')} />}
      {activeTab === 'rwa' && <RWADashboard onBack={() => setActiveTab('overview')} />}
      {activeTab === 'explorer' && <BlockExplorer onBack={() => setActiveTab('overview')} />}

      {showVaultModal && (
        <QuantumVault onClose={() => setShowVaultModal(false)} isPreGenesis={isPreGenesis} />
      )}
    </div>
  );
};

export default Dashboard;
