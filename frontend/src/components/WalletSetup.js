import React, { useState } from 'react';
import { Shield, Eye, EyeOff, AlertTriangle, Copy, Check } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

const WalletSetup = ({ onWalletCreated, onLoginRedirect }) => {
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    confirmPassword: ''
  });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  // Self-custody backup flow: 'form' -> create -> 'backup' (show phrase) -> done.
  const [step, setStep] = useState('form');
  const [mnemonic, setMnemonic] = useState('');
  const [copied, setCopied] = useState(false);
  const [confirmedBackup, setConfirmedBackup] = useState(false);

  // Use wallet context for proper integration
  const { createWallet } = useWallet();

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
    setError('');
  };

  const validateForm = () => {
    if (!formData.username || formData.username.length < 3) {
      setError('Username must be at least 3 characters long');
      return false;
    }
    if (!formData.password || formData.password.length < 8) {
      setError('Password must be at least 8 characters long');
      return false;
    }
    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      return false;
    }
    return true;
  };

  const handleCreateWallet = async () => {
    if (!validateForm()) return;
    if (!agreedToTerms) {
      setError('You must acknowledge the self-custody terms before creating a wallet');
      return;
    }

    setIsLoading(true);
    try {
      const result = await createWallet(formData.username, formData.password, formData.confirmPassword);
      if (result?.mnemonic) {
        // Show the recovery phrase backup screen before entering the wallet.
        setMnemonic(result.mnemonic);
        setStep('backup');
      } else {
        onWalletCreated();
      }
    } catch (error) {
      console.error('❌ Wallet creation failed:', error);
      setError('Failed to create wallet: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopyMnemonic = async () => {
    try {
      await navigator.clipboard.writeText(mnemonic);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      setError('Could not copy to clipboard — please write the phrase down manually.');
    }
  };

  const handleFinishBackup = () => {
    if (!confirmedBackup) {
      setError('Please confirm you have securely saved your recovery phrase');
      return;
    }
    // Wipe the phrase from component memory once the user continues.
    setMnemonic('');
    onWalletCreated();
  };

  if (step === 'backup') {
    const words = mnemonic.trim().split(/\s+/);
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-purple-900 to-gray-900 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-gray-800 rounded-2xl shadow-2xl border border-purple-500/20">
          <div className="p-8">
            <div className="text-center mb-6">
              <Shield className="h-12 w-12 text-purple-400 mx-auto mb-3" />
              <h1 className="text-2xl font-bold text-white mb-1">Back Up Your Recovery Phrase</h1>
              <p className="text-purple-200 text-sm">This is the ONLY way to recover your wallet and spend your funds.</p>
            </div>

            <div className="bg-red-900/30 border border-red-500/50 rounded-lg p-4 mb-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-red-400 mt-0.5 flex-shrink-0" />
                <div className="text-red-100 text-sm">
                  <p className="font-semibold mb-1">Write these 12 words down, in order.</p>
                  <ul className="space-y-1 text-xs">
                    <li>• Anyone with this phrase controls your WEPO. Never share it.</li>
                    <li>• We cannot recover it for you — it is not stored on any server.</li>
                    <li>• You will need it to restore your wallet on another device.</li>
                  </ul>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2 mb-4" data-testid="mnemonic-words">
              {words.map((word, i) => (
                <div key={i} className="bg-gray-700 rounded-lg px-3 py-2 text-sm text-white flex items-center gap-2">
                  <span className="text-purple-400 text-xs w-4">{i + 1}</span>
                  <span className="font-mono">{word}</span>
                </div>
              ))}
            </div>

            <button
              onClick={handleCopyMnemonic}
              className="w-full mb-4 flex items-center justify-center gap-2 bg-gray-700 hover:bg-gray-600 text-purple-200 py-2 px-4 rounded-lg transition-colors text-sm"
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
              {copied ? 'Copied' : 'Copy phrase'}
            </button>

            {error && (
              <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm mb-4">
                {error}
              </div>
            )}

            <label className="flex items-start gap-3 cursor-pointer select-none mb-4">
              <input
                type="checkbox"
                checked={confirmedBackup}
                onChange={(e) => { setConfirmedBackup(e.target.checked); setError(''); }}
                className="w-5 h-5 mt-0.5 text-purple-600 bg-gray-700 border-gray-600 rounded focus:ring-purple-500 focus:ring-2"
                data-testid="backup-confirm-checkbox"
              />
              <span className="text-sm text-purple-200 leading-relaxed">
                I have securely written down my 12-word recovery phrase and understand it cannot be recovered if lost.
              </span>
            </label>

            <button
              onClick={handleFinishBackup}
              disabled={!confirmedBackup}
              className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="finish-backup-button"
            >
              I've Saved It — Open My Wallet
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-purple-900 to-gray-900 flex items-center justify-center p-4">
      <div className="max-w-md w-full bg-gray-800 rounded-2xl shadow-2xl border border-purple-500/20">
        <div className="p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="flex items-center justify-center mb-4">
              <Shield className="h-12 w-12 text-purple-400" />
            </div>
            <h1 className="text-3xl font-bold text-white mb-2">WEPO Wallet</h1>
            <p className="text-purple-200">We The People - Your Financial Freedom</p>
          </div>

          <div className="space-y-6">
            <h2 className="text-xl font-semibold text-white text-center">Create Your Self-Custody Wallet</h2>

            <div className="bg-yellow-900/30 border border-yellow-500/50 rounded-lg p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                <div className="text-yellow-100 text-sm">
                  <p className="font-semibold mb-1">Self-custody wallet</p>
                  <ul className="space-y-1 text-xs">
                    <li>• You hold your keys. A 12-word recovery phrase is generated on this device.</li>
                    <li>• The phrase is the only way to recover your wallet and authorize spends.</li>
                    <li>• Your password encrypts the phrase locally; the server never sees your keys.</li>
                  </ul>
                </div>
              </div>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-purple-200 mb-2">
                  Username
                </label>
                <input
                  type="text"
                  name="username"
                  value={formData.username}
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  placeholder="Choose a username"
                  data-testid="username-input"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-purple-200 mb-2">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    value={formData.password}
                    onChange={handleInputChange}
                    className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
                    placeholder="Create a password"
                    data-testid="password-input"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-3 text-gray-400 hover:text-purple-400"
                  >
                    {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-purple-200 mb-2">
                  Confirm Password
                </label>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    name="confirmPassword"
                    value={formData.confirmPassword}
                    onChange={handleInputChange}
                    className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
                    placeholder="Confirm your password"
                    data-testid="confirm-password-input"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-3 text-gray-400 hover:text-purple-400"
                  >
                    {showConfirmPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                  </button>
                </div>
              </div>
            </div>

            {error && (
              <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">
                {error}
              </div>
            )}

            <div className="space-y-3">
              <label className="flex items-start gap-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={agreedToTerms}
                  onChange={(e) => setAgreedToTerms(e.target.checked)}
                  className="w-5 h-5 mt-0.5 text-purple-600 bg-gray-700 border-gray-600 rounded focus:ring-purple-500 focus:ring-2"
                  data-testid="terms-checkbox"
                />
                <span className="text-sm text-purple-200 leading-relaxed">
                  I understand this is a self-custody wallet: I am responsible for safely storing my recovery phrase, and it cannot be reset by anyone.
                </span>
              </label>
            </div>

            <button
              onClick={handleCreateWallet}
              disabled={isLoading || !agreedToTerms}
              className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="create-wallet-button"
            >
              {isLoading ? 'Creating Wallet...' : 'Create Self-Custody Wallet'}
            </button>

            <div className="text-center">
              <p className="text-sm text-purple-300">
                Already have an account?
                <button
                  onClick={onLoginRedirect}
                  className="text-purple-400 hover:text-purple-300 ml-1 underline"
                >
                  Sign in here
                </button>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default WalletSetup;
