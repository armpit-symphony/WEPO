import React, { useState } from 'react';
import { Download, ArrowLeft, Copy, QrCode } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

const ReceiveWepo = ({ onClose }) => {
  const { wallet } = useWallet();
  const [copied, setCopied] = useState(false);
  const [amount, setAmount] = useState('');
  const [label, setLabel] = useState('');

  const copyAddress = () => {
    const addr = wallet?.address || '';
    if (!addr) return;
    navigator.clipboard.writeText(addr);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const generateQRCode = () => {
    // In a real implementation, this would generate a QR code
    // For now, we'll show a placeholder
    return `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${wallet.address}${amount ? `?amount=${amount}` : ''}${label ? `&label=${encodeURIComponent(label)}` : ''}`;
  };

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
          <Download className="h-6 w-6 text-green-400" />
          <h2 className="text-xl font-semibold text-white">Receive WEPO</h2>
        </div>
      </div>

      <div className="text-center space-y-4">
        <div className="bg-white p-4 rounded-lg inline-block">
          <img 
            src={generateQRCode()} 
            alt="QR Code" 
            className="w-48 h-48 mx-auto"
          />
        </div>
        
        <p className="text-sm text-gray-400">
          Scan this QR code to send WEPO to your wallet
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Your WEPO Address
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={wallet.address}
              readOnly
              className="flex-1 px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white"
            />
            <button
              onClick={copyAddress}
              className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-3 rounded-lg transition-colors flex items-center gap-2"
            >
              <Copy size={16} />
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Amount (Optional)
          </label>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="0.0000"
            step="0.0001"
            min="0"
          />
          <p className="text-xs text-gray-400 mt-1">
            Specify an amount to request a specific payment
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Label (Optional)
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="Payment for..."
          />
          <p className="text-xs text-gray-400 mt-1">
            Add a description for this payment request
          </p>
        </div>
      </div>

      <div className="bg-gray-700/50 rounded-lg p-4 border border-green-500/30">
        <div className="flex items-center gap-2 mb-2">
          <Download className="h-4 w-4 text-green-400" />
          <span className="text-sm font-medium text-green-200">Privacy Protection</span>
        </div>
        <p className="text-sm text-gray-300">
          Your WEPO address is protected by advanced privacy features. Even when receiving payments, 
          your transaction history and balance remain completely private.
        </p>
      </div>

      <div className="bg-gray-700/30 rounded-lg p-4">
        <h3 className="text-white font-medium mb-2">Payment Request Details</h3>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Address:</span>
            <span className="text-white font-mono text-xs">{wallet?.address ? `${wallet.address.substring(0, 20)}...` : 'N/A'}</span>
          </div>
          {amount && (
            <div className="flex justify-between">
              <span className="text-gray-400">Requested Amount:</span>
              <span className="text-white">{amount} WEPO</span>
            </div>
          )}
          {label && (
            <div className="flex justify-between">
              <span className="text-gray-400">Label:</span>
              <span className="text-white">{label}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ReceiveWepo;