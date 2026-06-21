import React, { useState, useEffect } from 'react';
import {
  Upload,
  FileText,
  Image,
  Home,
  Car,
  Palette,
  Package,
  ArrowLeft,
  AlertCircle,
  CheckCircle,
  DollarSign,
  Coins,
  X
} from 'lucide-react';
import { sha256 } from '@noble/hashes/sha2.js';
import { useWallet } from '../contexts/WalletContext';
import { bytesToHex } from '../utils/wepoSigner';

// Commit the off-chain asset definition (incl. the file's own hash) to a single
// sha256 digest. Only this 64-hex commitment is anchored on-chain; the document
// itself stays off-chain.
const computeAssetHash = (form, file) => {
  let fileHashHex = '';
  if (file?.data) {
    const bin = atob(file.data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    fileHashHex = bytesToHex(sha256(bytes));
  }
  const definition = JSON.stringify({
    name: form.name,
    description: form.description,
    asset_type: form.asset_type,
    valuation: form.valuation || '',
    file_hash: fileHashHex,
  });
  return bytesToHex(sha256(new TextEncoder().encode(definition)));
};

const RWACreateAsset = ({ onBack, userAddress, onAssetCreated }) => {
  const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
  const { createRwaAsset } = useWallet();
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    asset_type: 'document',
    valuation: '',
    metadata: {}
  });
  const [password, setPassword] = useState('');
  const [file, setFile] = useState(null);
  const [filePreview, setFilePreview] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [assetId, setAssetId] = useState('');
  const [txHash, setTxHash] = useState('');
  const [assetHash, setAssetHash] = useState('');
  const [feeInfo, setFeeInfo] = useState(null);
  const [userBalance, setUserBalance] = useState(0);

  useEffect(() => {
    // Load fee info and user balance
    loadFeeInfoAndBalance();
  }, [userAddress]);

  const loadFeeInfoAndBalance = async () => {
    try {
      // Get fee info
      const feeResponse = await fetch(`${backendUrl}/api/rwa/fee-info`);
      const feeData = await feeResponse.json();
      if (feeData.success) {
        setFeeInfo(feeData.fee_info);
      }

      // Get user balance (from wallet context or API)
      const balanceResponse = await fetch(`${backendUrl}/api/wallet/${userAddress}`);
      const balanceData = await balanceResponse.json();
      if (balanceData.balance !== undefined) {
        setUserBalance(balanceData.balance);
      }
    } catch (err) {
      console.error('Error loading fee info:', err);
    }
  };

  const assetTypes = [
    { value: 'document', label: 'Document', icon: FileText, description: 'Legal documents, contracts, certificates' },
    { value: 'image', label: 'Image', icon: Image, description: 'Photos, artwork, digital images' },
    { value: 'property', label: 'Property', icon: Home, description: 'Real estate, land, buildings' },
    { value: 'vehicle', label: 'Vehicle', icon: Car, description: 'Cars, boats, aircraft' },
    { value: 'artwork', label: 'Artwork', icon: Palette, description: 'Paintings, sculptures, collectibles' },
    { value: 'other', label: 'Other', icon: Package, description: 'Other physical assets' }
  ];

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleFileUpload = (e) => {
    const uploadedFile = e.target.files[0];
    if (!uploadedFile) return;

    // Validate file size (10MB limit)
    if (uploadedFile.size > 10 * 1024 * 1024) {
      setError('File size must be less than 10MB');
      return;
    }

    // Validate file type
    const allowedTypes = [
      'image/jpeg', 'image/png', 'image/gif', 'image/bmp',
      'application/pdf', 'application/msword', 
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/plain', 'text/csv'
    ];

    if (!allowedTypes.includes(uploadedFile.type)) {
      setError('Unsupported file type. Please upload images, PDFs, or documents.');
      return;
    }

    // Convert to base64
    const reader = new FileReader();
    reader.onload = (event) => {
      const base64String = event.target.result.split(',')[1]; // Remove data URL prefix
      setFile({
        data: base64String,
        name: uploadedFile.name,
        type: uploadedFile.type,
        size: uploadedFile.size
      });
      setFilePreview(event.target.result);
    };
    reader.readAsDataURL(uploadedFile);
    setError('');
  };

  const removeFile = () => {
    setFile(null);
    setFilePreview('');
    const fileInput = document.getElementById('file-upload');
    if (fileInput) fileInput.value = '';
  };

  const handleCreateAsset = async () => {
    try {
      setLoading(true);
      setError('');

      // Validate required fields
      if (!formData.name || !formData.description || !formData.asset_type) {
        setError('Please fill in all required fields');
        return;
      }
      if (!password) {
        setError('Enter your wallet password to sign the on-chain creation');
        return;
      }

      // Commit the asset definition (+ file) to an on-chain hash.
      const computedHash = computeAssetHash(formData, file);

      // Build -> sign -> submit a real on-chain rwa_create transaction. The
      // off-chain file/metadata never leave the client; only the hash is anchored.
      const result = await createRwaAsset(
        {
          assetHash: computedHash,
          name: formData.name,
          assetType: formData.asset_type,
          metadata: {
            description: formData.description,
            valuation: formData.valuation || '',
            file_name: file ? file.name : '',
            created_via: 'WEPO_RWA_Dashboard',
          },
        },
        password,
      );

      setAssetId(result.asset_id || '');
      setTxHash(result.tx_hash || result.txid || result.transaction_id || '');
      setAssetHash(computedHash);
      setSuccess('Asset created on-chain. Ownership is bound to your wallet key; the asset hash is anchored on the WEPO chain.');
      setPassword('');
      setStep(2);

      if (onAssetCreated) {
        onAssetCreated();
      }
    } catch (err) {
      setError(err.message || 'Failed to create asset');
    } finally {
      setLoading(false);
    }
  };

  const renderStep1 = () => (
    <div className="space-y-6">
      <div className="bg-blue-900/30 rounded-lg p-4 border border-blue-500/30">
        <div className="flex items-center gap-2 mb-2">
          <Package className="h-4 w-4 text-blue-400" />
          <span className="text-sm font-medium text-blue-200">Step 1: Create Asset</span>
        </div>
        <p className="text-sm text-gray-300">
          Upload and describe your real world asset. This will create a digital representation on the blockchain.
        </p>
      </div>

      {/* Fee Information */}
      {feeInfo && (
        <div className="bg-yellow-900/30 rounded-lg p-4 border border-yellow-500/30">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="h-4 w-4 text-yellow-400" />
            <span className="text-sm font-medium text-yellow-200">RWA Creation Fee</span>
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-300">Creation Fee:</span>
              <span className="text-yellow-200 font-medium">{feeInfo.rwa_creation_fee} WEPO</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-300">Your Balance:</span>
              <span className={`font-medium ${userBalance >= feeInfo.rwa_creation_fee ? 'text-green-400' : 'text-red-400'}`}>
                {userBalance.toFixed(8)} WEPO
              </span>
            </div>
            <div className="text-xs text-gray-400 mt-2">
              {feeInfo.description}
            </div>
            <div className="bg-blue-900/50 border border-blue-500/50 rounded p-2 mt-2">
              <div className="text-blue-200 text-xs">
                💡 <strong>3-Way Fee Distribution:</strong> Your fee supports ALL network participants!
                {feeInfo.redistribution_info && (
                  <>
                    <br />• <strong>Masternodes (60%):</strong> {feeInfo.redistribution_info.masternodes}
                    <br />• <strong>Miners (25%):</strong> {feeInfo.redistribution_info.miners}
                    <br />• <strong>Stakers (15%):</strong> {feeInfo.redistribution_info.stakers}
                    <br />• <strong>Policy:</strong> {feeInfo.redistribution_info.policy}
                  </>
                )}
              </div>
            </div>
            {userBalance < feeInfo.rwa_creation_fee && (
              <div className="bg-red-900/50 border border-red-500/50 rounded p-2 mt-2">
                <div className="text-red-200 text-xs">
                  ⚠️ Insufficient WEPO balance. You need at least {feeInfo.rwa_creation_fee} WEPO to create an RWA asset.
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Asset Type Selection */}
      <div>
        <label className="block text-sm font-medium text-purple-200 mb-3">
          Asset Type *
        </label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {assetTypes.map((type) => {
            const Icon = type.icon;
            return (
              <button
                key={type.value}
                onClick={() => setFormData(prev => ({ ...prev, asset_type: type.value }))}
                className={`p-4 rounded-lg border-2 transition-all duration-200 text-left ${
                  formData.asset_type === type.value
                    ? 'border-purple-500 bg-purple-900/30 text-purple-200'
                    : 'border-gray-600 bg-gray-700/30 text-gray-300 hover:border-purple-400'
                }`}
              >
                <Icon className="h-6 w-6 mb-2" />
                <div className="font-medium">{type.label}</div>
                <div className="text-xs opacity-80">{type.description}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Basic Information */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Asset Name *
          </label>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleInputChange}
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="Enter asset name"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-purple-200 mb-2">
            Estimated Value (USD)
          </label>
          <input
            type="number"
            name="valuation"
            value={formData.valuation}
            onChange={handleInputChange}
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
            placeholder="0.00"
            step="0.01"
            min="0"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-purple-200 mb-2">
          Description *
        </label>
        <textarea
          name="description"
          value={formData.description}
          onChange={handleInputChange}
          rows={4}
          className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
          placeholder="Describe your asset in detail..."
          required
        />
      </div>

      {/* File Upload */}
      <div>
        <label className="block text-sm font-medium text-purple-200 mb-2">
          Upload File (Optional)
        </label>
        <div className="border-2 border-dashed border-gray-600 rounded-lg p-6 text-center hover:border-purple-400 transition-colors">
          {!file ? (
            <div>
              <Upload className="h-12 w-12 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-300 mb-2">Click to upload or drag and drop</p>
              <p className="text-sm text-gray-500">
                Supports: Images (JPG, PNG, GIF), Documents (PDF, DOC, DOCX), Text files
              </p>
              <p className="text-xs text-gray-500 mt-1">Maximum file size: 10MB</p>
              <input
                id="file-upload"
                type="file"
                onChange={handleFileUpload}
                className="hidden"
                accept=".jpg,.jpeg,.png,.gif,.bmp,.pdf,.doc,.docx,.txt,.csv"
              />
              <button
                type="button"
                onClick={() => document.getElementById('file-upload').click()}
                className="mt-4 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg transition-colors"
              >
                Choose File
              </button>
            </div>
          ) : (
            <div className="text-left">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-5 w-5 text-green-400" />
                  <span className="text-white font-medium">File Uploaded</span>
                </div>
                <button
                  onClick={removeFile}
                  className="text-gray-400 hover:text-white transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="text-sm text-gray-300">
                <div>Name: {file.name}</div>
                <div>Type: {file.type}</div>
                <div>Size: {(file.size / 1024 / 1024).toFixed(2)} MB</div>
              </div>
              {filePreview && file.type.startsWith('image/') && (
                <img
                  src={filePreview}
                  alt="Preview"
                  className="mt-4 max-h-40 max-w-full rounded-lg object-contain"
                />
              )}
            </div>
          )}
        </div>
      </div>

      {/* Wallet password (required to sign the on-chain creation) */}
      <div>
        <label className="block text-sm font-medium text-purple-200 mb-2">
          Wallet Password *
        </label>
        <input
          type="password"
          name="rwa_password"
          value={password}
          onChange={(e) => { setPassword(e.target.value); setError(''); }}
          className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-500"
          placeholder="Enter your wallet password to sign"
        />
        <p className="text-xs text-gray-400 mt-1">
          Creation is signed locally with your key and recorded on-chain. The file/metadata stay on your device — only their hash is anchored.
        </p>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">
          {error}
        </div>
      )}

      <div className="flex justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={20} />
          Back
        </button>
        <button
          onClick={handleCreateAsset}
          disabled={loading || !formData.name || !formData.description || !password || (feeInfo && userBalance < feeInfo.rwa_creation_fee)}
          className="bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {loading ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              Creating...
            </>
          ) : (
            <>
              <Package size={20} />
              {feeInfo && userBalance < feeInfo.rwa_creation_fee 
                ? `Insufficient Balance (${feeInfo.rwa_creation_fee} WEPO required)`
                : 'Create Asset'
              }
            </>
          )}
        </button>
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="space-y-6">
      <div className="bg-green-900/30 rounded-lg p-4 border border-green-500/30">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle className="h-4 w-4 text-green-400" />
          <span className="text-sm font-medium text-green-200">Asset Created On-Chain 🎉</span>
        </div>
        <p className="text-sm text-gray-300">
          {success || 'Your asset is now anchored on the WEPO blockchain and owned by your wallet key.'}
        </p>
      </div>

      <div className="bg-gray-800 rounded-lg p-6 border border-gray-600">
        <h3 className="text-white font-semibold mb-4">On-Chain Record</h3>
        <div className="space-y-3 text-sm">
          <div>
            <span className="text-gray-400">Asset ID:</span>
            <div className="text-green-300 font-mono break-all">{assetId || '—'}</div>
          </div>
          <div>
            <span className="text-gray-400">Transaction:</span>
            <div className="text-green-300 font-mono break-all">{txHash || 'pending'}</div>
          </div>
          <div>
            <span className="text-gray-400">Asset Hash (anchored commitment):</span>
            <div className="text-purple-300 font-mono break-all">{assetHash || '—'}</div>
          </div>
        </div>
      </div>

      <div className="bg-gray-800 rounded-lg p-6 border border-gray-600">
        <h3 className="text-white font-semibold mb-4">Asset Summary</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-400">Name:</span>
            <div className="text-white font-medium">{formData.name}</div>
          </div>
          <div>
            <span className="text-gray-400">Type:</span>
            <div className="text-white font-medium capitalize">{formData.asset_type}</div>
          </div>
          <div>
            <span className="text-gray-400">Valuation:</span>
            <div className="text-white font-medium">
              {formData.valuation ? `$${formData.valuation}` : 'Not specified'}
            </div>
          </div>
          <div>
            <span className="text-gray-400">File:</span>
            <div className="text-white font-medium">
              {file ? file.name : 'No file uploaded'}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-blue-900/30 border border-blue-500/30 rounded-lg p-3 text-blue-200 text-xs">
        Tradeable tokenization of RWA assets is a separate, post-launch feature and is not enabled yet.
      </div>

      <div className="flex justify-center gap-4">
        <button
          onClick={() => {
            setStep(1);
            setFormData({ name: '', description: '', asset_type: 'document', valuation: '', metadata: {} });
            setFile(null);
            setFilePreview('');
            setAssetId('');
            setTxHash('');
            setAssetHash('');
            setError('');
            setSuccess('');
          }}
          className="bg-gray-600 hover:bg-gray-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
        >
          Create Another Asset
        </button>
        <button
          onClick={onBack}
          className="bg-purple-600 hover:bg-purple-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
        >
          Back to Dashboard
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Progress Indicator */}
      <div className="flex items-center justify-center space-x-4 mb-8">
        <div className={`flex items-center justify-center w-8 h-8 rounded-full ${
          step >= 1 ? 'bg-purple-600 text-white' : 'bg-gray-600 text-gray-400'
        }`}>
          1
        </div>
        <div className={`h-0.5 w-8 ${step >= 2 ? 'bg-purple-600' : 'bg-gray-600'}`}></div>
        <div className={`flex items-center justify-center w-8 h-8 rounded-full ${
          step >= 2 ? 'bg-purple-600 text-white' : 'bg-gray-600 text-gray-400'
        }`}>
          2
        </div>
      </div>

      {/* Step Content */}
      {step === 1 && renderStep1()}
      {step === 2 && renderStep2()}
    </div>
  );
};

export default RWACreateAsset;
