import React from 'react';
import { Shield, AlertTriangle, X } from 'lucide-react';
import PreGenesisBanner from './PreGenesisBanner';

const QuantumVault = ({ onClose, isPreGenesis = true }) => {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg max-w-xl w-full mx-4 overflow-hidden border border-gray-700">
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-purple-500" />
            <div className="text-white font-semibold">Quantum Vault</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={18} />
          </button>
        </div>
        <div className="p-5">
          {isPreGenesis ? (
            <>
              <PreGenesisBanner message="Vault operations are disabled until genesis. You can explore later for deposits, withdrawals and ghost transfers." />
              <div className="text-gray-300 text-sm">
                During pre-genesis, vault creation, deposits, withdrawals and ghost transfers are gated for network safety.
              </div>
            </>
          ) : (
            <div className="space-y-4">
              <div className="w-full p-4 rounded-lg border border-blue-500/30 bg-blue-900/30">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="h-5 w-5 text-blue-300 mt-0.5" />
                  <div>
                    <div className="text-blue-200 font-semibold">Web Vault Preview</div>
                    <div className="text-blue-100/90 text-sm">
                      The backend vault and ghost-transfer APIs are live on the test stack, but the full interactive vault workflow is not yet exposed in this web wallet. Treat this surface as preview-only in the current public-test build.
                    </div>
                  </div>
                </div>
              </div>
              <div className="text-gray-300 text-sm">
                Vault creation, deposits, withdrawals, and ghost transfers still need a dedicated web workflow before this surface should be treated as fully user-ready.
              </div>
            </div>
          )}
          <div className="mt-5 flex justify-end">
            <button onClick={onClose} className="bg-purple-600 hover:bg-purple-700 text-white font-medium px-4 py-2 rounded">Close</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default QuantumVault;
