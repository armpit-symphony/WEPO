import React, { useState } from 'react';
import { Send, ArrowLeft, AlertTriangle, Eye, EyeOff, Shield } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';
import { validateSendForm, secureLog } from '../utils/securityUtils';

const SendWepo = ({ onClose, isPreGenesis = false }) => {
  const { sendWepo, balance } = useWallet();
  const [formData, setFormData] = useState({ toAddress: '', amount: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [validationErrors, setValidationErrors] = useState([]);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    setError('');
    setSuccess('');
    setValidationErrors([]);
  };

  const validateForm = () => {
    const validation = validateSendForm(formData, balance);
    if (!validation.isValid) {
      setValidationErrors(validation.errors);
      setError('Please fix the validation errors below');
      return false;
    }
    return validation.validatedData;
  };

  const handleSend = async () => {
    if (isPreGenesis) return; // block
    const validatedData = validateForm();
    if (!validatedData) return;
    setIsLoading(true);
    try {
      secureLog.info('Initiating secure transaction', { toAddress: validatedData.toAddress, amount: validatedData.amount, fee: validatedData.fee, total: validatedData.total });
      const tx = await sendWepo(validatedData.toAddress, validatedData.amount, validatedData.password);
      const txIdentifier = tx?.tx_hash || tx?.txid || tx?.id || 'pending';
      setSuccess(`✅ Transaction sent successfully! ID: ${txIdentifier}`);
      setFormData({ toAddress: '', amount: '', password: '' });
      setValidationErrors([]);
    } catch (error) {
      secureLog.error('Transaction failed', error);
      setError(`Transaction failed: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const setMaxAmount = () => {
    if (isPreGenesis) return;
    const maxAmount = Math.max(0, balance - 0.001);
    setFormData(prev => ({ ...prev, amount: maxAmount.toString() }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors"><ArrowLeft size={24} /></button>
        <div className="flex items-center gap-2"><Send className="h-6 w-6 text-purple-400" /><h2 className="text-xl font-semibold text-white">Send WEPO</h2></div>
      </div>

      {isPreGenesis && (
        <div className="bg-yellow-900/30 border border-yellow-500/30 rounded-lg p-3 text-yellow-100 text-sm">
          Pre-Genesis: Sending WEPO is disabled until launch. You can still use your BTC wallet and connect your miner.
        </div>
      )}

      <div className="bg-gray-700/50 rounded-lg p-4 border border-purple-500/30">
        <div className="flex items-center gap-2 mb-2"><AlertTriangle className="h-4 w-4 text-yellow-400" /><span className="text-sm font-medium text-yellow-200">Transparent Transaction</span></div>
        <p className="text-sm text-gray-300">This sends a standard transparent WEPO transaction. Ghost Send and Vault privacy are disabled for this release.</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">Recipient Address</label>
          <input type="text" name="toAddress" value={formData.toAddress} onChange={handleInputChange}
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500" placeholder="wepo1..." required disabled={isPreGenesis} />
        </div>
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">Amount (WEPO)</label>
          <div className="relative">
            <input type="number" name="amount" value={formData.amount} onChange={handleInputChange}
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-20" placeholder="0.0000" step="0.0001" min="0" required disabled={isPreGenesis} />
            <button type="button" onClick={setMaxAmount} className="absolute right-2 top-2 bg-purple-600 hover:bg-purple-700 text-white text-xs px-3 py-1 rounded transition-colors" disabled={isPreGenesis}>MAX</button>
          </div>
          <p className="text-xs text-gray-400 mt-1">Available: {balance.toFixed(4)} WEPO</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">Password (Required for Transaction)</label>
          <div className="relative">
            <input type={showPassword ? 'text' : 'password'} name="password" value={formData.password} onChange={handleInputChange}
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12" placeholder="Enter your wallet password" required disabled={isPreGenesis} />
            <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-3 text-gray-400 hover:text-purple-400" disabled={isPreGenesis}>{showPassword ? <EyeOff size={20} /> : <Eye size={20} />}</button>
          </div>
        </div>
      </div>

      {error && <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">{error}</div>}
      {success && <div className="bg-green-900/40 border border-green-500 rounded-lg p-3 text-green-200 text-sm">{success}</div>}
      {validationErrors.length > 0 && (
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2"><Shield className="h-4 w-4 text-red-400" /><span className="text-sm font-medium text-red-200">Security Validation Errors:</span></div>
          <ul className="text-sm text-red-200 space-y-1">{validationErrors.map((err, i) => (<li key={i} className="flex items-start gap-2"><span className="text-red-400 mt-0.5">•</span><span>{err}</span></li>))}</ul>
        </div>
      )}

      <div className="bg-gray-700/30 rounded-lg p-4">
        <h3 className="text-white font-medium mb-2">Transaction Summary</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-gray-400">Amount:</span><span className="text-white">{formData.amount || '0.0000'} WEPO</span></div>
          <div className="flex justify-between"><span className="text-gray-400">Network Fee:</span><span className="text-white">0.0001 WEPO</span></div>
          <div className="flex justify-between border-t border-gray-600 pt-2"><span className="text-purple-200 font-medium">Total:</span><span className="text-white font-medium">{formData.amount ? (parseFloat(formData.amount) + 0.0001).toFixed(4) : '0.0001'} WEPO</span></div>
        </div>
      </div>

      <button onClick={handleSend} disabled={isPreGenesis || isLoading || !formData.toAddress || !formData.amount || !formData.password}
        className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
        <Send size={20} /> {isPreGenesis ? 'Disabled until Genesis' : (isLoading ? 'Sending Transaction...' : 'Send WEPO')}
      </button>
    </div>
  );
};

export default SendWepo;
