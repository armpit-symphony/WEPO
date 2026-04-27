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
  DollarSign,
  TrendingUp,
  Users,
  ArrowRightLeft,
  Eye,
  Download,
  Plus,
  Coins,
  CheckCircle,
  AlertCircle,
  Clock
} from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';
import RWACreateAsset from './RWACreateAsset';
import UnifiedExchange from './UnifiedExchange';

const RWADashboard = ({ onBack }) => {
  const { wallet } = useWallet();
  const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
  
  const [activeTab, setActiveTab] = useState('dashboard');
  const [portfolio, setPortfolio] = useState(null);
  const [tradeableTokens, setTradeableTokens] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Get current wallet address
  const currentWallet = wallet;
  const currentAddress = currentWallet?.address;

  useEffect(() => {
    if (currentAddress) {
      loadRWAData();
    } else {
      // Try to get address from the active browser session if context is not ready
      const storedWallet = sessionStorage.getItem('wepo_current_wallet');
      
      if (storedWallet) {
        try {
          const walletData = JSON.parse(storedWallet);
          if (walletData.address) {
            loadRWAData(walletData.address);
            return;
          }
        } catch (e) {
          console.error('Error parsing stored wallet:', e);
        }
      }
      
      // If no address found, still load basic data
      setLoading(false);
      setError('No wallet address found. Please ensure you are logged in.');
    }
  }, [currentAddress, wallet]);

  const loadRWAData = async (address = currentAddress) => {
    try {
      setLoading(true);
      setError('');

      // Load portfolio if address is available
      if (address) {
        const portfolioResponse = await fetch(`${backendUrl}/api/rwa/portfolio/${address}`);
        const portfolioData = await portfolioResponse.json();
        if (portfolioData.success) {
          setPortfolio(portfolioData.portfolio);
        }
      }
      
      // Load tradeable tokens
      const tokensResponse = await fetch(`${backendUrl}/api/rwa/tokens/tradeable`);
      const tokensData = await tokensResponse.json();
      if (tokensData.success) {
        setTradeableTokens(tokensData.tokens);
      }
      
      // Load statistics
      const statsResponse = await fetch(`${backendUrl}/api/rwa/statistics`);
      const statsData = await statsResponse.json();
      if (statsData.success) {
        setStatistics(statsData.statistics);
      }
      
    } catch (err) {
      console.error('Error loading RWA data:', err);
      setError('Failed to load RWA data: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const getAssetIcon = (assetType) => {
    switch (assetType) {
      case 'document': return <FileText className="h-5 w-5" />;
      case 'image': return <Image className="h-5 w-5" />;
      case 'property': return <Home className="h-5 w-5" />;
      case 'vehicle': return <Car className="h-5 w-5" />;
      case 'artwork': return <Palette className="h-5 w-5" />;
      default: return <Package className="h-5 w-5" />;
    }
  };

  const formatTokenAmount = (amount, decimals = 8) => {
    return (amount / Math.pow(10, decimals)).toFixed(4);
  };

  const renderCreateAsset = () => (
    <RWACreateAsset 
      onBack={() => setActiveTab('dashboard')}
      userAddress={currentAddress}
      onAssetCreated={loadRWAData}
    />
  );

  const renderTokenManagement = () => (
    <RWATokenManagement 
      onBack={() => setActiveTab('dashboard')}
      userAddress={currentAddress}
      portfolio={portfolio}
      onTokenAction={loadRWAData}
    />
  );

  const renderDEXTrading = () => (
    <UnifiedExchange 
      onBack={() => setActiveTab('dashboard')}
    />
  );

  const renderDashboard = () => (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-emerald-600 to-teal-600 rounded-xl p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold flex items-center gap-2">
              <Package className="h-8 w-8" />
              RWA Portfolio
            </h2>
            <p className="text-emerald-100 mt-1">Real World Asset Management</p>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold">
              {portfolio?.total_value_wepo?.toFixed(2) || '0.00'}
            </div>
            <div className="text-emerald-100">WEPO Value</div>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button 
          onClick={() => setActiveTab('create')}
          className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-xl p-6 text-center transition-all duration-200"
        >
          <Plus className="h-8 w-8 mx-auto mb-2" />
          <div className="font-semibold">Create Asset</div>
          <div className="text-sm opacity-80">Tokenize Real World Assets</div>
        </button>

        <button 
          onClick={() => setActiveTab('tokens')}
          className="bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white rounded-xl p-6 text-center transition-all duration-200"
        >
          <Coins className="h-8 w-8 mx-auto mb-2" />
          <div className="font-semibold">Manage Tokens</div>
          <div className="text-sm opacity-80">Transfer & Monitor</div>
        </button>

        <button 
          onClick={() => setActiveTab('trading')}
          className="bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 text-white rounded-xl p-6 text-center transition-all duration-200"
        >
          <ArrowRightLeft className="h-8 w-8 mx-auto mb-2" />
          <div className="font-semibold">DEX Trading</div>
          <div className="text-sm opacity-80">Trade RWA Tokens</div>
        </button>
      </div>

      {/* Portfolio Summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Assets Created */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-600">
          <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
            <Package className="h-5 w-5 text-blue-400" />
            Assets Created ({portfolio?.assets_created?.length || 0})
          </h3>
          <div className="space-y-3">
            {portfolio?.assets_created?.slice(0, 3).map((asset, index) => (
              <div key={index} className="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="text-blue-400">
                    {getAssetIcon(asset.asset_type)}
                  </div>
                  <div>
                    <div className="text-white font-medium">{asset.name}</div>
                    <div className="text-sm text-gray-400">{asset.asset_type}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-white font-medium">
                    {asset.verification_status === 'verified' ? (
                      <CheckCircle className="h-4 w-4 text-green-400" />
                    ) : asset.verification_status === 'pending' ? (
                      <Clock className="h-4 w-4 text-yellow-400" />
                    ) : (
                      <AlertCircle className="h-4 w-4 text-red-400" />
                    )}
                  </div>
                </div>
              </div>
            ))}
            {(!portfolio?.assets_created || portfolio.assets_created.length === 0) && (
              <div className="text-center py-8">
                <Package className="h-12 w-12 text-gray-500 mx-auto mb-4" />
                <p className="text-gray-400">No assets created yet</p>
              </div>
            )}
          </div>
        </div>

        {/* Tokens Held */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-600">
          <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
            <Coins className="h-5 w-5 text-emerald-400" />
            Tokens Held ({portfolio?.tokens_held?.length || 0})
          </h3>
          <div className="space-y-3">
            {portfolio?.tokens_held?.slice(0, 3).map((token, index) => (
              <div key={index} className="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="text-emerald-400">
                    <Coins className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-white font-medium">{token.symbol}</div>
                    <div className="text-sm text-gray-400">{token.name}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-white font-medium">
                    {formatTokenAmount(token.balance)}
                  </div>
                  <div className="text-sm text-gray-400">
                    {token.value_wepo?.toFixed(2) || '0.00'} WEPO
                  </div>
                </div>
              </div>
            ))}
            {(!portfolio?.tokens_held || portfolio.tokens_held.length === 0) && (
              <div className="text-center py-8">
                <Coins className="h-12 w-12 text-gray-500 mx-auto mb-4" />
                <p className="text-gray-400">No tokens held</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Market Overview */}
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-600">
        <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-orange-400" />
          Market Overview
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-white">
              {statistics?.total_assets || 0}
            </div>
            <div className="text-sm text-gray-400">Total Assets</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-white">
              {statistics?.total_tokens || 0}
            </div>
            <div className="text-sm text-gray-400">Total Tokens</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-white">
              {statistics?.total_holders || 0}
            </div>
            <div className="text-sm text-gray-400">Token Holders</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-white">
              ${statistics?.total_asset_value_usd?.toFixed(0) || '0'}
            </div>
            <div className="text-sm text-gray-400">Total Value</div>
          </div>
        </div>
      </div>

      {/* Tradeable Tokens */}
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-600">
        <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
          <ArrowRightLeft className="h-5 w-5 text-purple-400" />
          Tradeable Tokens
        </h3>
        <div className="space-y-3">
          {tradeableTokens.slice(0, 5).map((token, index) => (
            <div key={index} className="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
              <div className="flex items-center gap-3">
                <div className="text-purple-400">
                  {getAssetIcon(token.asset_type)}
                </div>
                <div>
                  <div className="text-white font-medium">{token.symbol}</div>
                  <div className="text-sm text-gray-400">{token.asset_name}</div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-white font-medium">
                  {token.last_price ? (token.last_price / 100000000).toFixed(6) : 'N/A'} WEPO
                </div>
                <div className="text-sm text-gray-400">per token</div>
              </div>
            </div>
          ))}
          {tradeableTokens.length === 0 && (
            <div className="text-center py-8">
              <ArrowRightLeft className="h-12 w-12 text-gray-500 mx-auto mb-4" />
              <p className="text-gray-400">No tradeable tokens available</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  const renderTabContent = () => {
    switch(activeTab) {
      case 'create':
        return renderCreateAsset();
      case 'tokens':
        return renderTokenManagement();
      case 'trading':
        return renderDEXTrading();
      default:
        return renderDashboard();
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-400 mx-auto mb-4"></div>
          <p className="text-white text-lg">Loading RWA Dashboard...</p>
          <p className="text-gray-400 text-sm mt-2">
            {currentAddress ? `Address: ${currentAddress}` : 'Checking wallet status...'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={24} />
        </button>
        <div className="flex items-center gap-2">
          <Package className="h-6 w-6 text-emerald-400" />
          <h2 className="text-xl font-semibold text-white">RWA Dashboard</h2>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-3 text-red-200 text-sm">
          {error}
        </div>
      )}

      {/* Main Content */}
      {renderTabContent()}
    </div>
  );
};

// Token Management Component (simplified for now)
const RWATokenManagement = ({ onBack, userAddress, portfolio, onTokenAction }) => {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={24} />
        </button>
        <div className="flex items-center gap-2">
          <Coins className="h-6 w-6 text-emerald-400" />
          <h2 className="text-xl font-semibold text-white">Token Management</h2>
        </div>
      </div>
      
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-600">
        <h3 className="text-white font-semibold mb-4">Your RWA Tokens</h3>
        {portfolio?.tokens_held && portfolio.tokens_held.length > 0 ? (
          <div className="space-y-4">
            {portfolio.tokens_held.map((token, index) => (
              <div key={index} className="flex items-center justify-between p-4 bg-gray-700/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <Coins className="h-8 w-8 text-emerald-400" />
                  <div>
                    <div className="text-white font-medium">{token.symbol}</div>
                    <div className="text-sm text-gray-400">{token.name}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-white font-medium">
                    {(token.balance / Math.pow(10, token.decimals || 8)).toFixed(4)}
                  </div>
                  <div className="text-sm text-gray-400">
                    {token.value_wepo?.toFixed(4) || '0.0000'} WEPO
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8">
            <Coins className="h-16 w-16 text-gray-500 mx-auto mb-4" />
            <p className="text-gray-400">No RWA tokens found</p>
            <p className="text-sm text-gray-500 mt-2">Create an asset to get started</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default RWADashboard;
