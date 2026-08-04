import React, { useEffect, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';

const PreGenesisBanner = ({ compact = false, message, storageKey = 'wepo_pre_genesis_banner_dismissed' }) => {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    try {
      const dismissed = sessionStorage.getItem(storageKey);
      if (dismissed === 'true') setVisible(false);
    } catch {}
  }, [storageKey]);

  const dismiss = () => {
    try { sessionStorage.setItem(storageKey, 'true'); } catch {}
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className={`w-full ${compact ? 'p-3' : 'p-4'} mb-4 rounded-lg border border-yellow-500/30 bg-yellow-900/30`}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-yellow-300 mt-0.5" />
        <div className="flex-1">
          <div className="text-yellow-200 font-semibold">Pre-Genesis Network</div>
          <div className="text-yellow-100/90 text-sm">
            {message || 'The WEPO network has not launched yet. All state-changing actions are disabled until genesis.'}
          </div>
        </div>
        <button onClick={dismiss} className="text-yellow-200/80 hover:text-yellow-200" aria-label="Dismiss banner">
          <X size={16} />
        </button>
      </div>
    </div>
  );
};

export default PreGenesisBanner;