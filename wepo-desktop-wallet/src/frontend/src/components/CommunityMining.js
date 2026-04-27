import React, { useState, useEffect, useRef } from 'react';
import { 
  Pickaxe, 
  Users, 
  Clock, 
  Zap, 
  ArrowLeft, 
  Calendar,
  Globe,
  Award,
  TrendingUp,
  Timer,
  Play,
  Square,
  AlertTriangle,
  CheckCircle,
  Settings,
  Cpu,
  Activity
} from 'lucide-react';
import { useWallet } from '../contexts/WalletContext';

const CommunityMining = ({ onBack, miningMode = 'genesis' }) => {
  const { wallet } = useWallet();
  
  // Mining states
  const [isConnected, setIsConnected] = useState(false);
  const [isMining, setIsMining] = useState(false);
  const [miningStats, setMiningStats] = useState({
    hashRate: 0,
    difficulty: '0x1d00ffff',
    connectedMiners: 0,
    activeMiners: 0,
    timeToLaunch: null,
    blockReward: 0,
    estimatedTime: null,
    currentPhase: 'Genesis Block',
    totalHashrate: 0,
    blocksFound: 0,
    networkRank: 0
  });
  const [miningLogs, setMiningLogs] = useState([]);
  const [cpuUsage, setCpuUsage] = useState(25);
  const [personalStats, setPersonalStats] = useState({
    sharesSubmitted: 0,
    blocksFound: 0,
    uptime: 0,
    totalHashes: 0
  });
  const [showSettings, setShowSettings] = useState(false);
  
  // WebWorker refs
  const miningWorker = useRef(null);
  const statsInterval = useRef(null);
  
  // Dynamic mode detection
  const [currentMode, setCurrentMode] = useState('genesis');
  const [modeDisplay, setModeDisplay] = useState('🎄 Genesis Block Mining');
  
  // genesis date 3pm EST = 8pm UTC
  const LAUNCH_TIMESTAMP = new Date('2025-12-25T20:00:00Z').getTime();

  useEffect(() => {
    // Initialize mining worker
    initializeMiningWorker();
    
    // Load initial mining status
    loadMiningStatus();
    
    // Set up polling for real-time updates
    const interval = setInterval(() => {
      if (isConnected || isMining) {
        updateMiningStats();
        updatePersonalStats();
      }
      updateCountdown();
    }, 2000); // Poll every 2 seconds

    return () => {
      clearInterval(interval);
      if (statsInterval.current) {
        clearInterval(statsInterval.current);
      }
      if (miningWorker.current) {
        miningWorker.current.terminate();
      }
    };
  }, []);

  const initializeMiningWorker = () => {
    try {
      miningWorker.current = new Worker('/mining-worker.js');
      
      miningWorker.current.onmessage = (e) => {
        const { type, data } = e.data;
        
        switch (type) {
          case 'WORKER_READY':
            addMiningLog('⚙️ Mining engine initialized');
            break;
          case 'MINING_STARTED':
            addMiningLog('🚀 Mining started successfully');
            break;
          case 'MINING_STOPPED':
            addMiningLog(`⏹️ Mining stopped. Total hashes: ${data.totalHashes.toLocaleString()}`);
            break;
          case 'HASHRATE_UPDATE':
            setMiningStats(prev => ({ ...prev, hashRate: data.hashrate }));
            updateHashrateOnServer(data.hashrate);
            break;
          case 'SOLUTION_FOUND':
            handleSolutionFound(data);
            break;
          case 'JOB_UPDATED':
            addMiningLog(`📋 New mining job: ${data.jobId}`);
            break;
          default:
            break;
        }
      };
      
      miningWorker.current.onerror = (error) => {
        console.error('Mining worker error:', error);
        addMiningLog(`❌ Mining worker error: ${error.message}`);
      };
    } catch (error) {
      console.error('Failed to initialize mining worker:', error);
      addMiningLog('❌ Failed to initialize mining engine');
    }
  };

  const loadMiningStatus = async () => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/status`);
      
      if (response.ok) {
        const data = await response.json();
        
        // Update mode based on server response
        setCurrentMode(data.mining_mode || 'genesis');
        setModeDisplay(data.mode_display || '🎄 Genesis Block Mining');
        
        setMiningStats(prev => ({
          ...prev,
          connectedMiners: data.connected_miners || 0,
          activeMiners: data.active_miners || 0,
          totalHashrate: data.total_hashrate || 0,
          difficulty: data.network_difficulty || 1.0,
          blocksFound: data.blocks_found || 0,
          timeToLaunch: data.time_to_launch || null,
          currentPhase: data.mode_display || 'Genesis Block'
        }));
      }
    } catch (error) {
      console.error('Failed to load mining status:', error);
      addMiningLog('⚠️ Could not load network status');
    }
  };

  const updateMiningStats = async () => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/status`);
      
      if (response.ok) {
        const data = await response.json();
        
        // Check if mode changed (genesis → pow)
        if (data.mining_mode !== currentMode) {
          setCurrentMode(data.mining_mode);
          setModeDisplay(data.mode_display);
          addMiningLog(`🔄 Mining mode changed to: ${data.mode_display}`);
        }
        
        setMiningStats(prev => ({
          ...prev,
          connectedMiners: data.connected_miners || prev.connectedMiners,
          activeMiners: data.active_miners || prev.activeMiners,
          totalHashrate: data.total_hashrate || prev.totalHashrate,
          blocksFound: data.blocks_found || prev.blocksFound,
          timeToLaunch: data.time_to_launch || null
        }));
      }
    } catch (error) {
      console.error('Failed to update mining stats:', error);
    }
  };

  const updatePersonalStats = async () => {
    if (!wallet?.address) return;
    
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/stats/${wallet.address}`);
      
      if (response.ok) {
        const data = await response.json();
        if (!data.error) {
          setPersonalStats({
            sharesSubmitted: data.shares_submitted || 0,
            blocksFound: data.blocks_found || 0,
            uptime: data.uptime || 0,
            totalHashes: personalStats.totalHashes
          });
          setMiningStats(prev => ({
            ...prev,
            networkRank: data.network_rank || 0
          }));
        }
      }
    } catch (error) {
      console.error('Failed to update personal stats:', error);
    }
  };

  const updateCountdown = () => {
    const now = Date.now();
    const timeRemaining = LAUNCH_TIMESTAMP - now;
    
    if (timeRemaining > 0 && currentMode === 'genesis') {
      setMiningStats(prev => ({
        ...prev,
        timeToLaunch: timeRemaining
      }));
    }
  };

  const connectToMining = async () => {
    if (!wallet?.address) {
      addMiningLog('❌ Wallet not connected');
      return;
    }

    try {
      setIsConnected(true);
      addMiningLog('🌐 Connecting to WEPO mining network...');
      
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: wallet.address,
          mining_mode: currentMode,
          wallet_type: 'regular'
        })
      });
      
      if (response.ok) {
        const data = await response.json();
        addMiningLog('✅ Connected to mining network successfully!');
        addMiningLog(`⛏️ Network miners: ${data.network_miners}`);
        addMiningLog(`🎯 Mode: ${data.mining_mode}`);
        
        // Update stats immediately
        updateMiningStats();
      } else {
        throw new Error('Failed to connect to mining network');
      }
    } catch (error) {
      addMiningLog(`❌ Connection failed: ${error.message}`);
      setIsConnected(false);
    }
  };

  const startMining = async () => {
    if (!isConnected) {
      await connectToMining();
    }

    if (!wallet?.address) {
      addMiningLog('❌ Wallet address required');
      return;
    }

    try {
      setIsMining(true);
      addMiningLog('🚀 Starting mining operation...');
      
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: wallet.address
        })
      });
      
      if (response.ok) {
        const data = await response.json();
        addMiningLog(`✅ ${data.message}`);
        addMiningLog(`⚙️ CPU Usage: ${cpuUsage}%`);
        addMiningLog(`🎯 ${data.status}`);
        
        // Start WebWorker mining
        if (miningWorker.current && data.mining_job) {
          miningWorker.current.postMessage({
            type: 'START_MINING',
            data: data.mining_job
          });
          
          // Set CPU usage
          miningWorker.current.postMessage({
            type: 'SET_CPU_USAGE',
            data: { cpuUsage: cpuUsage }
          });
        }
        
        // Start periodic job updates
        statsInterval.current = setInterval(async () => {
          if (isMining) {
            await updateMiningJob();
          }
        }, 30000); // Update job every 30 seconds
        
      } else {
        throw new Error('Failed to start mining');
      }
    } catch (error) {
      addMiningLog(`❌ Mining start failed: ${error.message}`);
      setIsMining(false);
    }
  };

  const stopMining = async () => {
    try {
      setIsMining(false);
      addMiningLog('⏹️ Stopping mining operation...');
      
      // Stop WebWorker
      if (miningWorker.current) {
        miningWorker.current.postMessage({ type: 'STOP_MINING' });
      }
      
      // Stop job updates
      if (statsInterval.current) {
        clearInterval(statsInterval.current);
        statsInterval.current = null;
      }
      
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      await fetch(`${backendUrl}/api/mining/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: wallet.address
        })
      });
      
      addMiningLog('✅ Mining stopped successfully');
      setMiningStats(prev => ({ ...prev, hashRate: 0 }));
    } catch (error) {
      addMiningLog(`❌ Stop mining failed: ${error.message}`);
    }
  };

  const updateMiningJob = async () => {
    if (!wallet?.address) return;
    
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/work/${wallet.address}`);
      
      if (response.ok) {
        const jobData = await response.json();
        
        // Send new job to WebWorker
        if (miningWorker.current) {
          miningWorker.current.postMessage({
            type: 'UPDATE_JOB',
            data: jobData
          });
        }
      }
    } catch (error) {
      console.error('Failed to update mining job:', error);
    }
  };

  const handleSolutionFound = async (solutionData) => {
    addMiningLog(`🎉 Solution found! Hash: ${solutionData.hash.substring(0, 16)}...`);
    
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      const response = await fetch(`${backendUrl}/api/mining/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: wallet.address,
          job_id: solutionData.jobId,
          nonce: solutionData.nonce,
          hash: solutionData.hash
        })
      });
      
      if (response.ok) {
        const result = await response.json();
        
        if (result.accepted) {
          if (result.type === 'block') {
            addMiningLog(`🎉 BLOCK FOUND! ${result.message}`);
            addMiningLog(`💰 Reward: ${result.reward} WEPO`);
            
            if (result.height === 0) {
              // Genesis block found - mode will change
              addMiningLog('🎄 GENESIS BLOCK MINED! Welcome to WEPO network!');
            }
          } else {
            addMiningLog(`✅ Share accepted (${personalStats.sharesSubmitted + 1})`);
          }
          
          // Update personal stats immediately
          updatePersonalStats();
        } else {
          addMiningLog('❌ Solution rejected');
        }
      }
    } catch (error) {
      addMiningLog(`❌ Submit failed: ${error.message}`);
    }
  };

  const updateHashrateOnServer = async (hashrate) => {
    if (!wallet?.address) return;
    
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      await fetch(`${backendUrl}/api/mining/hashrate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: wallet.address,
          hashrate: hashrate
        })
      });
    } catch (error) {
      // Silently fail - not critical
    }
  };

  const updateCpuUsage = (newUsage) => {
    setCpuUsage(newUsage);
    if (miningWorker.current) {
      miningWorker.current.postMessage({
        type: 'SET_CPU_USAGE',
        data: { cpuUsage: newUsage }
      });
    }
    addMiningLog(`⚙️ CPU usage updated to ${newUsage}%`);
  };

  const addMiningLog = (message) => {
    const timestamp = new Date().toLocaleTimeString();
    const logEntry = `[${timestamp}] ${message}`;
    
    setMiningLogs(prev => {
      const newLogs = [logEntry, ...prev];
      return newLogs.slice(0, 50); // Keep last 50 logs
    });
  };

  const formatTime = (seconds) => {
    if (!seconds) return 'N/A';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours}h ${minutes}m ${secs}s`;
  };

  const formatHashrate = (hashrate) => {
    if (hashrate >= 1000000000) return `${(hashrate / 1000000000).toFixed(1)} GH/s`;
    if (hashrate >= 1000000) return `${(hashrate / 1000000).toFixed(1)} MH/s`;
    if (hashrate >= 1000) return `${(hashrate / 1000).toFixed(1)} KH/s`;
    return `${hashrate.toFixed(0)} H/s`;
  };

  const renderCountdown = () => {
    if (currentMode !== 'genesis' || !miningStats.timeToLaunch) return null;
    
    const days = Math.floor(miningStats.timeToLaunch / (1000 * 60 * 60 * 24));
    const hours = Math.floor((miningStats.timeToLaunch % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((miningStats.timeToLaunch % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((miningStats.timeToLaunch % (1000 * 60)) / 1000);
    
    return (
      <div className="bg-gradient-to-r from-green-900/30 to-red-900/30 rounded-lg p-4 border border-green-600/30">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-green-400" />
            <span className="text-green-400 font-medium">Christmas Genesis Launch</span>
          </div>
          <Timer className="w-5 h-5 text-red-400 animate-pulse" />
        </div>
        <div className="grid grid-cols-4 gap-2 text-center">
          <div className="bg-black/30 rounded p-2">
            <div className="text-2xl font-bold text-white">{days}</div>
            <div className="text-xs text-gray-400">DAYS</div>
          </div>
          <div className="bg-black/30 rounded p-2">
            <div className="text-2xl font-bold text-white">{hours}</div>
            <div className="text-xs text-gray-400">HOURS</div>
          </div>
          <div className="bg-black/30 rounded p-2">
            <div className="text-2xl font-bold text-white">{minutes}</div>
            <div className="text-xs text-gray-400">MINS</div>
          </div>
          <div className="bg-black/30 rounded p-2">
            <div className="text-2xl font-bold text-white">{seconds}</div>
            <div className="text-xs text-gray-400">SECS</div>
          </div>
        </div>
        <div className="text-center mt-2 text-sm text-yellow-400">
          Network launch timing TBD
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-900 via-blue-900 to-indigo-900">
      <div className="container mx-auto px-4 py-6 max-w-6xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-gray-300 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
            Back to Dashboard
          </button>
          <div className="flex items-center gap-2">
            <Pickaxe className="w-6 h-6 text-yellow-400" />
            <h1 className="text-2xl font-bold text-white">
              {modeDisplay}
            </h1>
          </div>
        </div>

        {/* Genesis Countdown (only for genesis mode) */}
        {currentMode === 'genesis' && renderCountdown()}

        <div className="grid md:grid-cols-2 gap-6 mt-6">
          {/* Mining Control Panel */}
          <div className="bg-gray-800/50 rounded-xl p-6 border border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-white">Mining Control</h2>
              <button
                onClick={() => setShowSettings(!showSettings)}
                className="p-2 text-gray-400 hover:text-white transition-colors"
              >
                <Settings className="w-5 h-5" />
              </button>
            </div>

            {/* Connection Status */}
            <div className="flex items-center gap-3 mb-4 p-3 bg-gray-700/50 rounded-lg">
              <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
              <span className="text-gray-300">
                {isConnected ? 'Connected to network' : 'Not connected'}
              </span>
            </div>

            {/* Mining Status */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-gray-300">Status:</span>
                <span className={`font-medium ${isMining ? 'text-green-400' : 'text-gray-400'}`}>
                  {isMining ? '⚡ Mining' : 'Stopped'}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-300">Your Hashrate:</span>
                <span className="font-medium text-yellow-400">
                  {formatHashrate(miningStats.hashRate)}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-300">CPU Usage:</span>
                <span className="font-medium text-blue-400">{cpuUsage}%</span>
              </div>

              {miningStats.networkRank > 0 && (
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Network Rank:</span>
                  <span className="font-medium text-purple-400">
                    #{miningStats.networkRank}
                  </span>
                </div>
              )}
            </div>

            {/* CPU Usage Settings */}
            {showSettings && (
              <div className="mt-4 p-4 bg-gray-700/30 rounded-lg">
                <div className="flex items-center gap-2 mb-3">
                  <Cpu className="w-4 h-4 text-blue-400" />
                  <span className="text-gray-300 font-medium">CPU Usage: {cpuUsage}%</span>
                </div>
                <div className="flex gap-2">
                  {[25, 50, 75, 100].map(usage => (
                    <button
                      key={usage}
                      onClick={() => updateCpuUsage(usage)}
                      className={`px-3 py-1 rounded text-sm transition-colors ${
                        cpuUsage === usage 
                          ? 'bg-blue-600 text-white' 
                          : 'bg-gray-600 text-gray-300 hover:bg-gray-500'
                      }`}
                    >
                      {usage}%
                    </button>
                  ))}
                </div>
                <div className="text-xs text-gray-400 mt-2">
                  Lower CPU usage saves battery but reduces hashrate
                </div>
              </div>
            )}

            {/* Control Buttons */}
            <div className="flex gap-3 mt-6">
              {!isConnected ? (
                <button
                  onClick={connectToMining}
                  disabled={!wallet?.address}
                  className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 px-4 rounded-lg font-medium transition-colors"
                >
                  <Globe className="w-5 h-5" />
                  Connect to Network
                </button>
              ) : !isMining ? (
                <button
                  onClick={startMining}
                  className="flex-1 flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 text-white py-3 px-4 rounded-lg font-medium transition-colors"
                >
                  <Play className="w-5 h-5" />
                  Start Mining
                </button>
              ) : (
                <button
                  onClick={stopMining}
                  className="flex-1 flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white py-3 px-4 rounded-lg font-medium transition-colors"
                >
                  <Square className="w-5 h-5" />
                  Stop Mining
                </button>
              )}
            </div>

            {!wallet?.address && (
              <div className="mt-4 p-3 bg-yellow-900/30 border border-yellow-600/30 rounded-lg">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-yellow-400" />
                  <span className="text-yellow-400 text-sm">
                    Wallet not connected. Please create or login to your wallet first.
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Network Statistics */}
          <div className="bg-gray-800/50 rounded-xl p-6 border border-gray-700">
            <div className="flex items-center gap-2 mb-4">
              <Activity className="w-5 h-5 text-green-400" />
              <h2 className="text-xl font-bold text-white">Network Statistics</h2>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-gray-300">Connected Miners:</span>
                <div className="flex items-center gap-2">
                  <Users className="w-4 h-4 text-blue-400" />
                  <span className="font-medium text-blue-400">
                    {miningStats.connectedMiners}
                  </span>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-300">Active Miners:</span>
                <span className="font-medium text-green-400">
                  {miningStats.activeMiners}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-300">Network Hashrate:</span>
                <span className="font-medium text-yellow-400">
                  {formatHashrate(miningStats.totalHashrate)}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-300">Blocks Found:</span>
                <span className="font-medium text-purple-400">
                  {miningStats.blocksFound}
                </span>
              </div>

              {currentMode === 'pow' && (
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Block Reward:</span>
                  <span className="font-medium text-green-400">
                    {miningStats.blockReward} WEPO
                  </span>
                </div>
              )}
            </div>

            {/* Personal Mining Stats */}
            <div className="mt-6 pt-4 border-t border-gray-600">
              <h3 className="text-lg font-bold text-white mb-3">Your Stats</h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Shares Submitted:</span>
                  <span className="font-medium text-blue-400">
                    {personalStats.sharesSubmitted}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Blocks Found:</span>
                  <span className="font-medium text-green-400">
                    {personalStats.blocksFound}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Mining Time:</span>
                  <span className="font-medium text-yellow-400">
                    {formatTime(personalStats.uptime)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Mining Activity Log */}
        <div className="mt-6 bg-gray-800/50 rounded-xl p-6 border border-gray-700">
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle className="w-5 h-5 text-green-400" />
            <h2 className="text-xl font-bold text-white">Mining Activity</h2>
          </div>

          <div className="bg-black/30 rounded-lg p-4 max-h-64 overflow-y-auto">
            {miningLogs.length === 0 ? (
              <div className="text-center text-gray-400 py-4">
                No mining activity yet. Connect to start mining.
              </div>
            ) : (
              <div className="space-y-1">
                {miningLogs.map((log, index) => (
                  <div key={index} className="text-sm text-gray-300 font-mono">
                    {log}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Community Notice */}
        <div className="mt-6 bg-gradient-to-r from-purple-900/30 to-blue-900/30 rounded-xl p-6 border border-purple-600/30">
          <div className="flex items-center gap-2 mb-2">
            <Award className="w-5 h-5 text-purple-400" />
            <h3 className="text-lg font-bold text-white">We The People Network</h3>
          </div>
          <p className="text-gray-300 text-sm">
            {currentMode === 'genesis' 
              ? '🎄 Join the genesis date genesis mining event! Be part of history as we mine the very first WEPO block together as a community.'
              : '⚡ Mining helps secure the WEPO network. Every hash counts in maintaining decentralization and financial freedom for all.'
            }
          </p>
          <p className="text-gray-400 text-xs mt-2">
            Mining from your wallet ensures network accessibility - no expensive equipment required!
          </p>
        </div>
      </div>
    </div>
  );
};

export default CommunityMining;
