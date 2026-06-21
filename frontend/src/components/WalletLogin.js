import React, { useState } from 'react';
import { Shield, Eye, EyeOff, LogIn, AlertTriangle } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';
import { validateTransactionPassword, secureLog } from '../utils/securityUtils';

const WalletLogin = ({ onWalletLoaded, onCreateNew }) => {
  const [formData, setFormData] = useState({
    username: '',
    password: ''
  });
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [validationErrors, setValidationErrors] = useState([]);
  const [mode, setMode] = useState('login'); // 'login' | 'recover'
  const [recoveryPhrase, setRecoveryPhrase] = useState('');
  const { loginWallet, recoverWallet, validateMnemonic } = useWallet();

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
    setError('');
    setValidationErrors([]);
  };

  const validateLoginForm = () => {
    const errors = [];
    
    if (!formData.username || formData.username.trim().length === 0) {
      errors.push('Username is required');
    }
    
    if (formData.username.length > 50) {
      errors.push('Username too long');
    }
    
    const passwordValidation = validateTransactionPassword(formData.password);
    if (!passwordValidation.isValid) {
      errors.push(...passwordValidation.errors);
    }
    
    return {
      isValid: errors.length === 0,
      errors
    };
  };

  const handleLogin = async () => {
    const validation = validateLoginForm();
    
    if (!validation.isValid) {
      setValidationErrors(validation.errors);
      setError('Please fix the validation errors below');
      return;
    }

    setIsLoading(true);
    try {
      secureLog.info('Login attempt initiated', { username: formData.username });
      
      await loginWallet(formData.username, formData.password);
      secureLog.info('Login successful');

      onWalletLoaded();
      
    } catch (error) {
      secureLog.error('Login error', error);
      setError(error.message || 'Login failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRecover = async () => {
    const errors = [];
    if (!formData.username || !formData.username.trim()) errors.push('Username is required');
    const passwordValidation = validateTransactionPassword(formData.password);
    if (!passwordValidation.isValid) errors.push(...passwordValidation.errors);
    if (!validateMnemonic(recoveryPhrase)) errors.push('Recovery phrase is not a valid 12/24-word phrase');
    if (errors.length) {
      setValidationErrors(errors);
      setError('Please fix the validation errors below');
      return;
    }
    setIsLoading(true);
    try {
      secureLog.info('Wallet recovery initiated', { username: formData.username });
      await recoverWallet(recoveryPhrase, formData.password, formData.username);
      secureLog.info('Recovery successful');
      setRecoveryPhrase('');
      onWalletLoaded();
    } catch (error) {
      secureLog.error('Recovery error', error);
      setError(error.message || 'Recovery failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && mode === 'login') {
      handleLogin();
    }
  };

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

          {/* Login Form */}
          <div className="space-y-6">
            <h2 className="text-xl font-semibold text-white text-center">
              {mode === 'recover' ? 'Restore From Recovery Phrase' : 'Access Your Wallet'}
            </h2>

            {mode === 'recover' && (
              <div>
                <label className="block text-sm font-medium text-purple-200 mb-2">Recovery Phrase</label>
                <textarea
                  name="recoveryPhrase"
                  value={recoveryPhrase}
                  onChange={(e) => { setRecoveryPhrase(e.target.value); setError(''); setValidationErrors([]); }}
                  rows={3}
                  className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
                  placeholder="Enter your 12-word recovery phrase, separated by spaces"
                />
                <p className="text-xs text-gray-400 mt-1">Your phrase is encrypted on this device with your password and never sent to the server.</p>
              </div>
            )}

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
                  onKeyPress={handleKeyPress}
                  className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  placeholder="Enter your username"
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
                    onKeyPress={handleKeyPress}
                    className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
                    placeholder="Enter your password"
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
            </div>

            {error && (
              <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">
                {error}
              </div>
            )}

            {validationErrors.length > 0 && (
              <div className="bg-red-900/50 border border-red-500 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="h-4 w-4 text-red-400" />
                  <span className="text-sm font-medium text-red-200">Security Validation Errors:</span>
                </div>
                <ul className="text-sm text-red-200 space-y-1">
                  {validationErrors.map((error, index) => (
                    <li key={index} className="flex items-start gap-2">
                      <span className="text-red-400 mt-0.5">•</span>
                      <span>{error}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <button
              onClick={mode === 'recover' ? handleRecover : handleLogin}
              disabled={isLoading}
              className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <LogIn size={20} />
              {isLoading
                ? (mode === 'recover' ? 'Restoring...' : 'Logging in...')
                : (mode === 'recover' ? 'Restore Wallet' : 'Access Wallet')}
            </button>

            <div className="text-center">
              <button
                onClick={() => { setMode(mode === 'recover' ? 'login' : 'recover'); setError(''); setValidationErrors([]); }}
                className="text-sm text-purple-400 hover:text-purple-300 underline"
              >
                {mode === 'recover' ? 'Back to sign in' : 'Restore from recovery phrase'}
              </button>
            </div>

            <div className="text-center">
              <p className="text-sm text-purple-300">
                Don't have a wallet?
                <button
                  onClick={onCreateNew}
                  className="text-purple-400 hover:text-purple-300 ml-1 underline"
                >
                  Create one here
                </button>
              </p>
            </div>
          </div>

          {/* Security Note */}
          <div className="mt-8 p-4 bg-gray-700/50 rounded-lg border border-purple-500/30">
            <p className="text-xs text-purple-200 text-center">
              Self-custody: your recovery phrase is encrypted on this device and authorizes spends locally. The server never holds your keys. On a new device, use "Restore from recovery phrase".
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default WalletLogin;
