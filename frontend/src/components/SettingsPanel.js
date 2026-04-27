import React, { useState, useEffect } from 'react';
import { Settings, ArrowLeft, Key, Eye, EyeOff, Shield, AlertTriangle } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

const SettingsPanel = ({ onClose }) => {
  const { changePassword } = useWallet();
  const [activeSection, setActiveSection] = useState('security');
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmNewPassword: ''
  });
  const [showPasswords, setShowPasswords] = useState({
    current: false,
    new: false,
    confirm: false
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handlePasswordChange = (e) => {
    const { name, value } = e.target;
    setPasswordForm(prev => ({
      ...prev,
      [name]: value
    }));
    setError('');
    setSuccess('');
  };

  const togglePasswordVisibility = (field) => {
    setShowPasswords(prev => ({
      ...prev,
      [field]: !prev[field]
    }));
  };

  const handleChangePassword = async () => {
    if (!passwordForm.currentPassword) {
      setError('Please enter your current password');
      return;
    }

    if (!passwordForm.newPassword || passwordForm.newPassword.length < 8) {
      setError('New password must be at least 8 characters long');
      return;
    }

    if (passwordForm.newPassword !== passwordForm.confirmNewPassword) {
      setError('New passwords do not match');
      return;
    }

    if (passwordForm.currentPassword === passwordForm.newPassword) {
      setError('New password must be different from current password');
      return;
    }

    setIsLoading(true);
    try {
      await changePassword(
        passwordForm.currentPassword, 
        passwordForm.newPassword, 
        passwordForm.confirmNewPassword
      );
      
      setSuccess('Password changed successfully!');
      setPasswordForm({
        currentPassword: '',
        newPassword: '',
        confirmNewPassword: ''
      });
    } catch (error) {
      setError(error.message);
    } finally {
      setIsLoading(false);
    }
  };

  const renderSecuritySettings = () => (
    <div className="space-y-6">
      <div className="bg-gray-700/50 rounded-lg p-4 border border-purple-500/30">
        <div className="flex items-center gap-2 mb-2">
          <Shield className="h-4 w-4 text-purple-400" />
          <span className="text-sm font-medium text-purple-200">Account Security</span>
        </div>
        <p className="text-sm text-gray-300">
          This public test build uses backend-managed WEPO test accounts. Sign-in is live, but password rotation is not exposed in the current UI build.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Current Password
          </label>
          <div className="relative">
            <input
              type={showPasswords.current ? 'text' : 'password'}
              name="currentPassword"
              value={passwordForm.currentPassword}
              onChange={handlePasswordChange}
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
              placeholder="Enter current password"
              required
            />
            <button
              type="button"
              onClick={() => togglePasswordVisibility('current')}
              className="absolute right-3 top-3 text-gray-400 hover:text-purple-400"
            >
              {showPasswords.current ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            New Password
          </label>
          <div className="relative">
            <input
              type={showPasswords.new ? 'text' : 'password'}
              name="newPassword"
              value={passwordForm.newPassword}
              onChange={handlePasswordChange}
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
              placeholder="Enter new password"
              required
            />
            <button
              type="button"
              onClick={() => togglePasswordVisibility('new')}
              className="absolute right-3 top-3 text-gray-400 hover:text-purple-400"
            >
              {showPasswords.new ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Confirm New Password
          </label>
          <div className="relative">
            <input
              type={showPasswords.confirm ? 'text' : 'password'}
              name="confirmNewPassword"
              value={passwordForm.confirmNewPassword}
              onChange={handlePasswordChange}
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
              placeholder="Confirm new password"
              required
            />
            <button
              type="button"
              onClick={() => togglePasswordVisibility('confirm')}
              className="absolute right-3 top-3 text-gray-400 hover:text-purple-400"
            >
              {showPasswords.confirm ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">
          {error}
        </div>
      )}

      {success && (
        <div className="bg-green-900/50 border border-green-500 rounded-lg p-3 text-green-200 text-sm">
          {success}
        </div>
      )}

      <button
        onClick={handleChangePassword}
        disabled={true}
        className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        <Key size={20} />
        Password Change Not Yet Available
      </button>

      <div className="bg-yellow-900/30 rounded-lg p-4 border border-yellow-500/30">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="h-4 w-4 text-yellow-400" />
          <span className="text-sm font-medium text-yellow-200">Security Reminder</span>
        </div>
        <ul className="text-sm text-gray-300 space-y-1">
          <li>• Use a strong, unique password for your wallet</li>
          <li>• Never share your password with anyone</li>
          <li>• This public test build does not provide recovery phrase export or import</li>
          <li>• Treat this environment as a test network and do not rely on it for production custody</li>
        </ul>
      </div>
    </div>
  );

  const [networkInfo, setNetworkInfo] = useState({
    mode: 'pre-genesis',
    mode_display: 'Pre-Genesis (Not connected)',
    network_label: 'WEPO Public Test',
    block_height: 0,
    total_hashrate: 0,
    active_masternodes: 0,
    total_staked: 0
  });

  useEffect(() => {
    const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
    const fetchStatus = async () => {
      try {
        const resp = await fetch(`${backendUrl}/api/mining/status`);
        if (resp.ok) {
          const data = await resp.json();
          setNetworkInfo({
            mode: data.mining_mode || 'pre-genesis',
            mode_display: data.mode_display || 'Pre-Genesis (Not connected)',
            network_label: data.mining_mode === 'pow' ? 'WEPO Public Test' : 'Pre-Genesis',
            block_height: data.block_height || 0,
            total_hashrate: data.total_hashrate || 0,
            active_masternodes: data.active_masternodes || 0,
            total_staked: data.total_staked || 0
          });
        }
      } catch (e) {
        // keep defaults
      }
    };
    fetchStatus();
  }, []);

  const formatHashrate = (h) => {
    if (!h) return '0 H/s';
    if (h >= 1e12) return `${(h/1e12).toFixed(2)} TH/s`;
    if (h >= 1e9) return `${(h/1e9).toFixed(2)} GH/s`;
    if (h >= 1e6) return `${(h/1e6).toFixed(2)} MH/s`;
    if (h >= 1e3) return `${(h/1e3).toFixed(2)} kH/s`;
    return `${h} H/s`;
  };

  const renderWalletInfo = () => (
    <div className="space-y-6">
      <div className="bg-gray-700/50 rounded-lg p-4">
        <h3 className="text-white font-medium mb-4">Wallet Information</h3>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Wallet Version:</span>
            <span className="text-white">WEPO v1.0.0</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Network:</span>
            <span className={networkInfo.mode === 'pre-genesis' ? 'text-yellow-400' : 'text-green-400'}>
              {networkInfo.network_label}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Status:</span>
            <span className="text-purple-400">{networkInfo.mode_display}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Consensus:</span>
            <span className="text-blue-400">Hybrid PoW/PoS</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Last Block:</span>
            <span className="text-white">{networkInfo.block_height?.toLocaleString() || 'N/A'}</span>
          </div>
        </div>
      </div>

      <div className="bg-gray-700/50 rounded-lg p-4">
        <h3 className="text-white font-medium mb-4">Network Status</h3>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {/* Staging-only genesis toggles removed for production */}
          <div className="hidden" />
          <div className="h-4 w-px bg-gray-700 mx-1" />
          <label className="text-xs text-gray-300 flex items-center gap-2">
            <input type="checkbox" defaultChecked onChange={(e) => {
              try { sessionStorage.setItem('btc_relay_only', e.target.checked ? 'true' : 'false'); } catch {}
            }} />
            Relay BTC via Masternodes only (no fallback)
          </label>
          <button onClick={() => {
            try {
              const st = sessionStorage.getItem('btc_last_relay_status');
              alert(st ? st : 'No relay yet');
            } catch { alert('No relay yet'); }
          }} className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-3 py-1 rounded">Show Last BTC Relay</button>
        </div>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Block Height:</span>
            <span className="text-white">{networkInfo.block_height || 'N/A'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Network Hash Rate:</span>
            <span className="text-white">{formatHashrate(networkInfo.total_hashrate)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Active Masternodes:</span>
            <span className="text-white">{networkInfo.active_masternodes || 0}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Total Staked:</span>
            <span className="text-white">{networkInfo.total_staked ? `${networkInfo.total_staked} WEPO` : '0 WEPO'}</span>
          </div>
        </div>
      </div>

      <div className="bg-purple-900/30 rounded-lg p-4 border border-purple-500/30">
        <h3 className="text-white font-medium mb-2">About WEPO</h3>
        <p className="text-sm text-gray-300">
          WEPO (We The People) is a revolutionary privacy-focused cryptocurrency designed to bring 
          financial freedom back to the people. With advanced cryptographic protection, hybrid consensus, 
          and built-in BTC exchange, WEPO represents the future of truly private digital money.
        </p>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={24} />
        </button>
        <div className="flex items-center gap-2">
          <Settings className="h-6 w-6 text-gray-400" />
          <h2 className="text-xl font-semibold text-white">Settings</h2>
        </div>
      </div>

      {/* Section Tabs */}
      <div className="flex bg-gray-700 rounded-lg p-1">
        <button
          onClick={() => setActiveSection('security')}
          className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
            activeSection === 'security' 
              ? 'bg-purple-600 text-white' 
              : 'text-gray-300 hover:text-white'
          }`}
        >
          Security
        </button>
        <button
          onClick={() => setActiveSection('info')}
          className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
            activeSection === 'info' 
              ? 'bg-purple-600 text-white' 
              : 'text-gray-300 hover:text-white'
          }`}
        >
          Wallet Info
        </button>
      </div>

      {/* Section Content */}
      {activeSection === 'security' && renderSecuritySettings()}
      {activeSection === 'info' && renderWalletInfo()}
    </div>
  );
};

export default SettingsPanel;
