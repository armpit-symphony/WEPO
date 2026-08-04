import React, { useState, useEffect } from 'react';
import { Server, ArrowLeft, Shield, TrendingUp, AlertCircle, Clock, Globe, Smartphone, Monitor, Settings, Activity, Zap } from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

const MasternodeInterface = ({ onClose }) => {
  const { balance, masternodesEnabled } = useWallet();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [masternodeActive, setMasternodeActive] = useState(false);
  const [deviceType, setDeviceType] = useState('computer');
  const [selectedServices, setSelectedServices] = useState([]);
  const [masternodeStats, setMasternodeStats] = useState({
    uptime: 0,
    dailyEarnings: 0,
    servicesActive: 0,
    lastReward: 0,
    totalEarned: 0
  });

  // Device detection
  useEffect(() => {
    const detectDevice = () => {
      const userAgent = navigator.userAgent || navigator.vendor || window.opera;
      const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(userAgent);
      const isTablet = /iPad|Android/i.test(userAgent) && window.innerWidth > 768;
      
      if (isMobile && !isTablet) {
        setDeviceType('mobile');
      } else {
        setDeviceType('computer');
      }
    };
    
    detectDevice();
    window.addEventListener('resize', detectDevice);
    return () => window.removeEventListener('resize', detectDevice);
  }, []);

  // Auto-select services based on device type
  useEffect(() => {
    if (deviceType === 'computer') {
      // Auto-select 4 most suitable services for computers including Bitcoin mixing
      setSelectedServices(['network_relay', 'mixing_service', 'dex_relay', 'btc_mixing']);
    } else {
      // Auto-select 2 least resource-intensive services for mobile
      setSelectedServices(['network_relay', 'governance']);
    }
  }, [deviceType]);

  // Mock masternode data with new specifications
  const collateralRequired = 10000;
  const deviceRequirements = {
    computer: {
      uptime: 9,
      services: 3,
      gracePeriod: 48,
      maxEarnings: 4.2
    },
    mobile: {
      uptime: 6,
      services: 2,
      gracePeriod: 24,
      maxEarnings: 2.8
    }
  };

  const availableServices = [
    {
      id: 'mixing_service',
      name: 'Transaction Mixing',
      icon: '🔀',
      description: 'Anonymous transaction routing',
      resourceUsage: 'Medium',
      recommended: true
    },
    {
      id: 'dex_relay',
      name: 'DEX Relay',
      icon: '🏪',
      description: 'Facilitate P2P trades',
      resourceUsage: 'High',
      recommended: deviceType === 'computer'
    },
    {
      id: 'network_relay',
      name: 'Network Relay',
      icon: '🌐',
      description: 'Forward messages/transactions',
      resourceUsage: 'Low',
      recommended: true
    },
    {
      id: 'governance',
      name: 'Governance',
      icon: '🗳️',
      description: 'Vote on network proposals',
      resourceUsage: 'Low',
      recommended: true
    },
    {
      id: 'vault_relay',
      name: 'Vault Relay',
      icon: '📡',
      description: 'Route Quantum Vault transfers',
      resourceUsage: 'Medium',
      recommended: deviceType === 'computer'
    },
    {
      id: 'btc_mixing',
      name: 'Bitcoin Privacy Mixing',
      icon: '🔐',
      description: 'Anonymize Bitcoin transactions through mixing pools',
      resourceUsage: 'High',
      recommended: deviceType === 'computer'
    }
  ];

  const currentReq = deviceRequirements[deviceType];

  const handleLaunchMasternode = async () => {
    if (!masternodesEnabled) {
      setError('Masternodes are not yet enabled. Wait for 18 months after first PoW block.');
      return;
    }

    if (balance < collateralRequired) {
      setError(`Insufficient balance. ${collateralRequired} WEPO required for masternode collateral.`);
      return;
    }

    if (selectedServices.length < currentReq.services) {
      setError(`Please select at least ${currentReq.services} services for ${deviceType} masternode.`);
      return;
    }

    setIsLoading(true);
    setError('');
    
    try {
      // Simulate masternode launch process
      await new Promise(resolve => setTimeout(resolve, 3000));
      
      setMasternodeActive(true);
      setSuccess(`${deviceType === 'computer' ? 'Computer' : 'Mobile'} masternode launched successfully!`);
      
      // Start mock stats tracking
      setMasternodeStats({
        uptime: 0.5,
        dailyEarnings: 0.2,
        servicesActive: selectedServices.length,
        lastReward: 0.1,
        totalEarned: 0.2
      });
      
    } catch (error) {
      setError('Masternode launch failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleStopMasternode = async () => {
    setIsLoading(true);
    try {
      await new Promise(resolve => setTimeout(resolve, 1500));
      setMasternodeActive(false);
      setSuccess('Masternode stopped successfully.');
      setMasternodeStats({
        uptime: 0,
        dailyEarnings: 0,
        servicesActive: 0,
        lastReward: 0,
        totalEarned: masternodeStats.totalEarned
      });
    } catch (error) {
      setError('Failed to stop masternode.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleServiceToggle = (serviceId) => {
    if (selectedServices.includes(serviceId)) {
      if (selectedServices.length > currentReq.services) {
        setSelectedServices(selectedServices.filter(id => id !== serviceId));
      }
    } else {
      setSelectedServices([...selectedServices, serviceId]);
    }
  };

  if (!masternodesEnabled) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-700 rounded-full transition-colors"
          >
            <ArrowLeft size={24} />
          </button>
          <div className="flex items-center gap-2">
            <Server className="h-6 w-6 text-purple-400" />
            <h2 className="text-xl font-semibold text-white">Masternode Services</h2>
          </div>
        </div>

        <div className="bg-yellow-900/30 rounded-lg p-4 border border-yellow-500/30">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="h-4 w-4 text-yellow-400" />
            <span className="text-sm font-medium text-yellow-200">Service Activation Pending</span>
          </div>
          <p className="text-sm text-gray-300">
            Masternode services will be activated 18 months after the first PoW block. 
            This ensures network stability before enabling advanced features.
          </p>
        </div>

        <div className="bg-purple-900/30 rounded-lg p-4 border border-purple-500/30">
          <div className="flex items-center gap-2 mb-2">
            <Shield className="h-4 w-4 text-purple-400" />
            <span className="text-sm font-medium text-purple-200">Planned Services</span>
          </div>
          <p className="text-sm text-gray-300 mb-3">
            When activated, masternodes will provide essential network services:
          </p>
          <ul className="text-sm text-gray-300 space-y-1">
            <li>• 🔀 Transaction mixing for enhanced privacy</li>
            <li>• 🏪 DEX relay for decentralized trading</li>
            <li>• 🌐 P2P network infrastructure</li>
            <li>• 🗳️ Governance voting and execution</li>
            <li>• 📡 Quantum Vault relay services</li>
          </ul>
        </div>

        <div className="bg-green-900/30 rounded-lg p-4 border border-green-500/30">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="h-4 w-4 text-green-400" />
            <span className="text-sm font-medium text-green-200">Reward Structure</span>
          </div>
          <p className="text-sm text-gray-300 mb-2">
            Masternodes earn 60% of all network transaction fees.
          </p>
          <div className="text-sm text-gray-300 space-y-1">
            <div className="flex justify-between">
              <span>Collateral Required:</span>
              <span className="font-medium">10,000 WEPO</span>
            </div>
            <div className="flex justify-between">
              <span>Revenue Share:</span>
              <span className="font-medium">60% of all fees</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onClose}
          className="p-2 hover:bg-gray-700 rounded-full transition-colors"
        >
          <ArrowLeft size={24} />
        </button>
        <div className="flex items-center gap-2">
          <Server className="h-6 w-6 text-purple-400" />
          <h2 className="text-xl font-semibold text-white">Decentralized Masternode</h2>
        </div>
      </div>

      {/* Device Detection */}
      <div className="bg-blue-900/30 rounded-lg p-4 border border-blue-500/30">
        <div className="flex items-center gap-2 mb-2">
          {deviceType === 'computer' ? (
            <Monitor className="h-4 w-4 text-blue-400" />
          ) : (
            <Smartphone className="h-4 w-4 text-blue-400" />
          )}
          <span className="text-sm font-medium text-blue-200">
            Device: {deviceType === 'computer' ? 'Computer' : 'Mobile'}
          </span>
        </div>
        <div className="text-sm text-gray-300 space-y-1">
          <div className="flex justify-between">
            <span>Minimum Uptime:</span>
            <span className="font-medium">{currentReq.uptime} hours/day</span>
          </div>
          <div className="flex justify-between">
            <span>Services Required:</span>
            <span className="font-medium">{currentReq.services} of 5</span>
          </div>
          <div className="flex justify-between">
            <span>Grace Period:</span>
            <span className="font-medium">{currentReq.gracePeriod} hours</span>
          </div>
          <div className="flex justify-between">
            <span>Max Earnings:</span>
            <span className="font-medium">{currentReq.maxEarnings} WEPO/day</span>
          </div>
        </div>
      </div>

      {/* Masternode Status */}
      {masternodeActive && (
        <div className="bg-green-900/30 rounded-lg p-4 border border-green-500/30">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="h-4 w-4 text-green-400" />
            <span className="text-sm font-medium text-green-200">
              🟢 Masternode Status: ACTIVE
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-400">Uptime Today:</span>
              <div className="text-white font-medium">{masternodeStats.uptime.toFixed(1)} hours</div>
            </div>
            <div>
              <span className="text-gray-400">Daily Earnings:</span>
              <div className="text-green-400 font-medium">{masternodeStats.dailyEarnings.toFixed(3)} WEPO</div>
            </div>
            <div>
              <span className="text-gray-400">Services Active:</span>
              <div className="text-white font-medium">{masternodeStats.servicesActive}/5</div>
            </div>
            <div>
              <span className="text-gray-400">Last Reward:</span>
              <div className="text-purple-400 font-medium">{masternodeStats.lastReward.toFixed(3)} WEPO</div>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-green-500/30">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Requirements:</span>
              <span className="text-green-400 font-medium">✅ Met</span>
            </div>
          </div>
        </div>
      )}

      {/* Requirements Check */}
      <div className="bg-gray-700/30 rounded-lg p-4">
        <h3 className="text-white font-medium mb-3">Masternode Requirements</h3>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Collateral Required:</span>
            <span className="text-white font-medium">{collateralRequired.toLocaleString()} WEPO</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Your Balance:</span>
            <span className={`font-medium ${balance >= collateralRequired ? 'text-green-400' : 'text-red-400'}`}>
              {balance.toLocaleString()} WEPO
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Network Type:</span>
            <span className="text-green-400 font-medium">Decentralized P2P</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Server Required:</span>
            <span className="text-green-400 font-medium">No - Local Only</span>
          </div>
        </div>
      </div>

      {/* Service Selection */}
      <div className="bg-purple-900/30 rounded-lg p-4 border border-purple-500/30">
        <div className="flex items-center gap-2 mb-3">
          <Settings className="h-4 w-4 text-purple-400" />
          <span className="text-sm font-medium text-purple-200">
            Service Selection ({selectedServices.length}/{currentReq.services} required)
          </span>
        </div>
        <div className="space-y-3">
          {availableServices.map((service) => (
            <div
              key={service.id}
              className={`p-3 rounded-lg border cursor-pointer transition-all ${
                selectedServices.includes(service.id)
                  ? 'bg-purple-800/50 border-purple-400'
                  : 'bg-gray-700/30 border-gray-600 hover:border-purple-400'
              }`}
              onClick={() => handleServiceToggle(service.id)}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{service.icon}</span>
                  <div>
                    <div className="text-white font-medium text-sm">{service.name}</div>
                    <div className="text-gray-400 text-xs">{service.description}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {service.recommended && (
                    <span className="text-xs bg-blue-600 text-white px-2 py-1 rounded">
                      Recommended
                    </span>
                  )}
                  <span className={`text-xs px-2 py-1 rounded ${
                    service.resourceUsage === 'Low' ? 'bg-green-600' :
                    service.resourceUsage === 'Medium' ? 'bg-yellow-600' : 'bg-red-600'
                  } text-white`}>
                    {service.resourceUsage}
                  </span>
                  <div className={`w-4 h-4 rounded border-2 ${
                    selectedServices.includes(service.id)
                      ? 'bg-purple-400 border-purple-400'
                      : 'border-gray-400'
                  }`}>
                    {selectedServices.includes(service.id) && (
                      <div className="w-full h-full flex items-center justify-center">
                        <div className="w-2 h-2 bg-white rounded-full"></div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Error/Success Messages */}
      {error && (
        <div className="bg-red-900/30 rounded-lg p-4 border border-red-500/30">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm text-red-200">{error}</span>
          </div>
        </div>
      )}

      {success && (
        <div className="bg-green-900/30 rounded-lg p-4 border border-green-500/30">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-green-400" />
            <span className="text-sm text-green-200">{success}</span>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex gap-3">
        {!masternodeActive ? (
          <button
            onClick={handleLaunchMasternode}
            disabled={isLoading || balance < collateralRequired}
            className={`flex-1 py-3 px-4 rounded-lg font-medium transition-all ${
              isLoading || balance < collateralRequired
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-purple-600 hover:bg-purple-700 text-white'
            }`}
          >
            {isLoading ? 'Launching...' : 'Launch Masternode'}
          </button>
        ) : (
          <button
            onClick={handleStopMasternode}
            disabled={isLoading}
            className={`flex-1 py-3 px-4 rounded-lg font-medium transition-all ${
              isLoading
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-red-600 hover:bg-red-700 text-white'
            }`}
          >
            {isLoading ? 'Stopping...' : 'Stop Masternode'}
          </button>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-blue-900/30 rounded-lg p-4 border border-blue-500/30">
        <div className="flex items-center gap-2 mb-2">
          <Globe className="h-4 w-4 text-blue-400" />
          <span className="text-sm font-medium text-blue-200">Network Benefits</span>
        </div>
        <ul className="text-sm text-gray-300 space-y-1">
          <li>• Earn 60% of all network transaction fees</li>
          <li>• No dedicated server required - runs locally</li>
          <li>• Automatic service management and monitoring</li>
          <li>• Contribute to network decentralization and privacy</li>
        </ul>
      </div>
    </div>
  );
};

export default MasternodeInterface;