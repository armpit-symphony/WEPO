import React, { useEffect, useState } from 'react';
import { Coins, ArrowLeft, AlertCircle, Shield, Activity } from 'lucide-react';

const StakingInterface = ({ onClose }) => {
  const nodeUrl = process.env.REACT_APP_NODE_URL || 'http://127.0.0.1:18212';
  const [networkStatus, setNetworkStatus] = useState({
    loading: true,
    chainHeight: null,
    networkProfile: 'unknown',
    posActivated: false,
    posActivationHeight: null,
    activeValidators: 0,
    totalStakedRaw: 0
  });

  useEffect(() => {
    let isMounted = true;

    const loadStatus = async () => {
      try {
        const response = await fetch(`${nodeUrl}/api/network/status`);
        if (!response.ok) {
          throw new Error('Failed to load node status');
        }

        const payload = await response.json();
        if (!isMounted) {
          return;
        }

        setNetworkStatus({
          loading: false,
          chainHeight: payload.chain_height ?? payload.height ?? null,
          networkProfile: payload.network_profile || payload.network || 'unknown',
          posActivated: Boolean(payload.hybrid_consensus?.pos_activated),
          posActivationHeight: payload.hybrid_consensus?.pos_activation_height ?? null,
          activeValidators: payload.hybrid_consensus?.active_validators ?? 0,
          totalStakedRaw: payload.hybrid_consensus?.total_staked ?? 0
        });
      } catch {
        if (!isMounted) {
          return;
        }

        setNetworkStatus((current) => ({
          ...current,
          loading: false
        }));
      }
    };

    loadStatus();
    return () => {
      isMounted = false;
    };
  }, [nodeUrl]);

  const totalStakedWepo = (networkStatus.totalStakedRaw || 0) / 100000000;

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
          <Coins className="h-6 w-6 text-blue-400" />
          <h2 className="text-xl font-semibold text-white">Proof of Stake</h2>
        </div>
        <div className="text-xs text-gray-400 ml-2">Status / preview</div>
      </div>

      <div className="bg-blue-900/30 rounded-lg p-4 border border-blue-500/30">
        <div className="flex items-center gap-2 mb-2">
          <Shield className="h-4 w-4 text-blue-300" />
          <span className="text-sm font-medium text-blue-200">Web Staking Preview</span>
        </div>
        <p className="text-sm text-gray-300">
          The backend and node staking paths have been validated on the accelerated public-test network, but the full interactive web staking workflow is not yet exposed here. Treat this screen as live status plus release-scope guidance, not a finished staking product flow.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Network Profile</div>
          <div className="text-white font-semibold mt-1">{networkStatus.networkProfile}</div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Chain Height</div>
          <div className="text-white font-semibold mt-1">
            {networkStatus.loading ? 'Loading...' : (networkStatus.chainHeight ?? 'Unavailable')}
          </div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-400 text-sm">PoS Status</div>
          <div className={`font-semibold mt-1 ${networkStatus.posActivated ? 'text-green-400' : 'text-yellow-400'}`}>
            {networkStatus.loading ? 'Loading...' : (networkStatus.posActivated ? 'Active on test stack' : 'Not active')}
          </div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Activation Height</div>
          <div className="text-white font-semibold mt-1">
            {networkStatus.loading ? 'Loading...' : (networkStatus.posActivationHeight ?? 'Unavailable')}
          </div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Active Validators</div>
          <div className="text-white font-semibold mt-1">
            {networkStatus.loading ? 'Loading...' : networkStatus.activeValidators}
          </div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-gray-400 text-sm">Total Staked</div>
          <div className="text-white font-semibold mt-1">
            {networkStatus.loading ? 'Loading...' : `${totalStakedWepo.toFixed(4)} WEPO`}
          </div>
        </div>
      </div>

      <div className="bg-gray-800/40 border border-gray-700 rounded-lg p-5">
        <div className="flex items-center gap-2 mb-2">
          <Activity className="h-4 w-4 text-purple-400" />
          <div className="text-white font-medium">Current public-test scope</div>
        </div>
        <ul className="text-gray-300 text-sm list-disc pl-6 space-y-1">
          <li>Validator rewards and PoS persistence were validated on the accelerated test network</li>
          <li>Reward visibility is now reconciled through the backend reward summaries</li>
          <li>Interactive stake/unstake controls are not yet exposed in this web wallet build</li>
        </ul>
      </div>

      <div className="bg-yellow-900/30 rounded-lg p-4 border border-yellow-500/30">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-4 w-4 text-yellow-400" />
          <span className="text-sm font-medium text-yellow-200">Broader test guidance</span>
        </div>
        <p className="text-sm text-gray-300">
          Outside testers should use this surface for visibility only. If interactive staking is needed for a later round, it should be implemented against the live test-node APIs instead of the old mock calculator flow.
        </p>
      </div>
    </div>
  );
};

export default StakingInterface;
