import React, { useState, useEffect } from 'react';
import WalletLogin from './components/WalletLogin';
import WalletSetup from './components/WalletSetup';
import Dashboard from './components/Dashboard';
import { WalletProvider, useWallet } from './contexts/WalletContext';
import { sessionManager } from './utils/securityUtils';
import './App.css';

// Main App Component that handles wallet state
const MainApp = () => {
  const [currentView, setCurrentView] = useState('setup');
  const [isInitialized, setIsInitialized] = useState(false);
  const { setWallet } = useWallet();

  const clearTransientSession = () => {
    sessionManager.clearAuthSession();
    sessionManager.clearSecureSession();
    sessionManager.remove('wepo_current_wallet');
    sessionManager.remove('wepo_locked');
    sessionStorage.removeItem('wepo_current_wallet');
  };

  useEffect(() => {
    const initializeApp = async () => {
      try {
        const sessionWallet = sessionStorage.getItem('wepo_current_wallet');
        const authSession = sessionManager.getAuthSession();
        const walletExists = localStorage.getItem('wepo_wallet_exists');
        const isLocked = sessionManager.get('wepo_locked') === true;

        if (!isLocked && sessionWallet && authSession) {
          const wallet = JSON.parse(sessionWallet);
          setWallet(wallet);
          setCurrentView('dashboard');
        } else if (sessionWallet || isLocked) {
          clearTransientSession();
          setWallet(null);
          setCurrentView(walletExists === 'true' ? 'login' : 'setup');
        } else if (walletExists === 'true') {
          setCurrentView('login');
        } else {
          setCurrentView('setup');
        }
      } catch (error) {
        console.error('Failed to initialize app:', error);
        setCurrentView('setup');
      } finally {
        setIsInitialized(true);
      }
    };

    initializeApp();
  }, [setWallet]);

  useEffect(() => {
    if (currentView !== 'dashboard') {
      return undefined;
    }

    const reconcileSession = () => {
      const walletExists = localStorage.getItem('wepo_wallet_exists');
      const sessionWallet = sessionStorage.getItem('wepo_current_wallet');
      const authSession = sessionManager.getAuthSession();
      const isLocked = sessionManager.get('wepo_locked') === true;

      if (!sessionWallet || !authSession || isLocked) {
        clearTransientSession();
        setWallet(null);
        setCurrentView(walletExists === 'true' ? 'login' : 'setup');
      }
    };

    const intervalId = window.setInterval(reconcileSession, 15000);
    window.addEventListener('focus', reconcileSession);
    document.addEventListener('visibilitychange', reconcileSession);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener('focus', reconcileSession);
      document.removeEventListener('visibilitychange', reconcileSession);
    };
  }, [currentView, setWallet]);

  if (!isInitialized) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-purple-900 flex items-center justify-center">
        <div className="text-white text-xl">Loading WEPO...</div>
      </div>
    );
  }

  const handleViewChange = (view) => {
    setCurrentView(view);
  };

  return (
    <div className="App">
      {currentView === 'setup' && (
        <WalletSetup 
          onWalletCreated={() => handleViewChange('dashboard')} 
          onLoginRedirect={() => handleViewChange('login')} 
        />
      )}
      {currentView === 'login' && (
        <WalletLogin 
          onWalletLoaded={() => handleViewChange('dashboard')}
          onCreateNew={() => handleViewChange('setup')}
        />
      )}
      {currentView === 'dashboard' && (
        <Dashboard onLogout={() => handleViewChange('login')} />
      )}
    </div>
  );
};

// Wrap the app with WalletProvider
function App() {
  return (
    <WalletProvider>
      <MainApp />
    </WalletProvider>
  );
}

export default App;
