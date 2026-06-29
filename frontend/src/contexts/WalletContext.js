import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import CryptoJS from 'crypto-js';
import * as bip39 from 'bip39';
import { sessionManager, secureLog, secureStorage } from '../utils/securityUtils';
import { deriveWepoKeypair, signTransaction, signDigest } from '../utils/wepoSigner';
import {
  deriveMessagingKeypair,
  encryptMessage,
  decryptMessage,
  keyRegistryDigest,
  fetchAuthDigest,
} from '../utils/wepoMessaging';
// import { generateWepoAddress, generateBitcoinAddress, validateAddress } from '../utils/addressUtils';
// Temporarily comment out Bitcoin wallet import to prevent runtime errors
// import * as bitcoin from 'bitcoinjs-lib';
// import BIP32Factory from 'bip32';
// import * as ecc from 'tiny-secp256k1';
// import { ECPairFactory } from 'ecpair';
// const SelfCustodialBitcoinWallet = null; // not used directly

const WalletContext = createContext();

export const useWallet = () => {
  const context = useContext(WalletContext);
  if (!context) {
    throw new Error('useWallet must be used within a WalletProvider');
  }
  return context;
};

export const WalletProvider = ({ children }) => {
  const [wallet, setWallet] = useState(null);
  const [balance, setBalance] = useState(0);
  const [btcBalance, setBtcBalance] = useState(0);
  const [transactions, setTransactions] = useState([]);
  const [btcTransactions, setBtcTransactions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [masternodesEnabled, setMasternodesEnabled] = useState(false);
  const [showSeedPhrase, setShowSeedPhrase] = useState(false);
  
  // Self-custodial Bitcoin wallet state
  const [btcWallet, setBtcWallet] = useState(null);
  const [btcAddresses, setBtcAddresses] = useState([]);
  const [btcUtxos, setBtcUtxos] = useState([]);
  const [btcWalletFingerprint, setBtcWalletFingerprint] = useState(null);
  const [isBtcLoading, setIsBtcLoading] = useState(false);

  // In-memory messaging identity (spend + messaging keypairs), derived once when
  // the wallet is opened so messaging never needs the password again while the
  // wallet stays open. See armMessagingSession / getMessagingIdentity below.
  const messagingIdentityRef = useRef(null);
  const messagingReadyRef = useRef(false); // becomes true once keys are published

  const getWalletAddress = (walletData) => walletData?.address || walletData?.wepo?.address || '';

  const persistWalletSession = (walletData, password, authSession) => {
    const walletAddress = getWalletAddress(walletData);
    if (!walletAddress) {
      throw new Error('Wallet address missing from session data');
    }

    if (!authSession?.token || !authSession?.expiresAt) {
      throw new Error('Authenticated session missing from login response');
    }

    if (!secureStorage.setSecureItem('wallet_data', walletData, password)) {
      throw new Error('Failed to store encrypted wallet data');
    }

    sessionManager.createSecureSession(walletAddress, password);
    if (!sessionManager.setAuthSession({
      token: authSession.token,
      expiresAt: authSession.expiresAt,
      walletAddress,
      username: walletData.username
    })) {
      throw new Error('Failed to store authenticated session');
    }
    sessionManager.set('wepo_current_wallet', walletData);
    sessionManager.remove('wepo_locked');
    sessionStorage.setItem('wepo_current_wallet', JSON.stringify(walletData));
    sessionStorage.setItem('wepo_session_active', 'true');
  };

  // Enable masternodes immediately (require 10,000 WEPO collateral)
  useEffect(() => {
    // Masternodes enabled now with 10,000 WEPO requirement
    setMasternodesEnabled(true);
  }, []);

  useEffect(() => {
    // Load any persisted session data if available
    const storedWallet = sessionManager.get('wepo_current_wallet');
    const storedBalance = sessionManager.get('wepo_balance');
    const storedTransactions = sessionManager.get('wepo_transactions');

    if (storedWallet) setWallet(storedWallet);
    if (storedBalance) setBalance(parseFloat(storedBalance));
    if (storedTransactions) setTransactions(storedTransactions);
  }, []);

  // Inactivity auto-lock (Sensitive-only, mining-aware)
  useEffect(() => {
    const timeoutMs = 15 * 60 * 1000; // 15 minutes
    let lastActivity = Date.now();
    let timer;

    const bump = () => { lastActivity = Date.now(); };

    const monitor = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const now = Date.now();
        const inactive = now - lastActivity > timeoutMs;
        // Mining-aware: do not lock if miner connected or mining tab reports connected
        const minerConnected = sessionStorage.getItem('wepo_miner_connected') === 'true';
        if (inactive && !minerConnected) {
          // Lock: clear only sensitive-capability session pieces
          sessionManager.set('wepo_locked', true);
        }
        monitor();
      }, 60 * 1000);
    };

    window.addEventListener('mousemove', bump);
    window.addEventListener('keydown', bump);
    document.addEventListener('visibilitychange', bump);
    monitor();

    return () => {
      window.removeEventListener('mousemove', bump);
      window.removeEventListener('keydown', bump);
      document.removeEventListener('visibilitychange', bump);
      clearTimeout(timer);
    };
  }, []);

  const getBackendUrl = () => process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

  // Messaging relay endpoint, resolved independently of the wallet RPC backend so
  // privacy-conscious deployments can point messaging at a Tor hidden service
  // (.onion) — reached over Tor Browser or a local SOCKS proxy — without routing
  // wallet RPC there too. Falls back to the main backend when unset.
  const getRelayUrl = () => process.env.REACT_APP_MESSAGING_RELAY_URL || getBackendUrl();

  // ===== SELF-CUSTODY KEY MANAGEMENT =====
  // The wallet holds the spend secret (a BIP-39 mnemonic) client-side; the
  // backend never sees keys. The WEPO address is derived from the mnemonic
  // (ML-DSA-44 pubkey -> "wepo1q..." via wepoSigner) and registered with the
  // backend only so balance/history reads and sessions are addressable.

  const generateMnemonic = () => bip39.generateMnemonic(128); // 12 words

  const validateMnemonic = (mnemonic) => {
    try {
      return bip39.validateMnemonic((mnemonic || '').trim());
    } catch (e) {
      return false;
    }
  };

  // Encrypted local store for the recovery phrase (the only spend secret).
  const MNEMONIC_KEY = 'wepo_mnemonic';
  const storeMnemonic = (mnemonic, password) => {
    if (!secureStorage.setSecureItem(MNEMONIC_KEY, mnemonic, password)) {
      throw new Error('Failed to securely store the recovery phrase');
    }
  };
  const loadMnemonic = (password) => secureStorage.getSecureItem(MNEMONIC_KEY, password);

  // ===== MESSAGING IDENTITY =====
  // Messaging is wired to the wallet address and must work with zero friction: no
  // password prompt and no "enable" step once activated. The messaging + spend
  // keypairs are derived from the mnemonic; to keep messaging password-free across
  // reloads and restarts we persist the seed locally for messaging only. It is
  // armed automatically at create/login/recover (when the password is in hand), or
  // via a one-time activateMessaging() for wallets that predate this feature.
  //
  // SECURITY TRADE-OFF (lab/test; messaging is gated pre-mainnet): this stores the
  // spend seed unencrypted on the device until logout. Spending WEPO still requires
  // the password every time. Revisit before enabling messaging on mainnet.
  const MESSAGING_SEED_KEY = 'wepo_messaging_seed';

  const _deriveMessagingIdentity = (mnemonic) => ({
    spend: deriveWepoKeypair(mnemonic),
    msg: deriveMessagingKeypair(mnemonic),
  });

  // Arm + persist messaging from a known-good mnemonic (password-free thereafter).
  const armMessagingSession = (mnemonic) => {
    if (!mnemonic || !validateMnemonic(mnemonic)) return;
    try { localStorage.setItem(MESSAGING_SEED_KEY, mnemonic); } catch (e) { /* non-fatal */ }
    messagingIdentityRef.current = _deriveMessagingIdentity(mnemonic);
    messagingReadyRef.current = false; // re-publish keys on next open
  };

  // True if messaging can run without asking for anything (in memory or persisted).
  const isMessagingActivated = () => {
    if (messagingIdentityRef.current) return true;
    try {
      const m = localStorage.getItem(MESSAGING_SEED_KEY);
      return !!(m && validateMnemonic(m));
    } catch (e) { return false; }
  };

  // Return the cached identity, rebuilding it from the persisted seed if needed.
  // Throws a tagged error if messaging hasn't been activated on this device yet.
  const getMessagingIdentity = () => {
    if (messagingIdentityRef.current) return messagingIdentityRef.current;
    let mnemonic = null;
    try { mnemonic = localStorage.getItem(MESSAGING_SEED_KEY); } catch (e) { /* non-fatal */ }
    if (!mnemonic || !validateMnemonic(mnemonic)) {
      const err = new Error('Messaging is not activated on this device yet.');
      err.code = 'MESSAGING_NOT_ACTIVATED';
      throw err;
    }
    messagingIdentityRef.current = _deriveMessagingIdentity(mnemonic);
    return messagingIdentityRef.current;
  };

  // One-time activation for a wallet opened before messaging existed: derive from
  // the password ONCE; afterwards messaging is password-free on this device.
  const activateMessaging = (password) => {
    const mnemonic = loadMnemonic(password);
    if (!mnemonic || !validateMnemonic(mnemonic)) {
      throw new Error('Incorrect wallet password, or no recovery phrase on this device.');
    }
    const { address } = deriveWepoKeypair(mnemonic);
    if (wallet?.address && address !== wallet.address) {
      throw new Error('Recovery phrase does not match this wallet.');
    }
    armMessagingSession(mnemonic);
    return true;
  };

  const disarmMessagingSession = () => {
    messagingIdentityRef.current = null;
    messagingReadyRef.current = false;
    try { localStorage.removeItem(MESSAGING_SEED_KEY); } catch (e) { /* non-fatal */ }
  };

  // fetch() with a hard timeout so a slow/half-open relay can never hang the UI
  // (the messaging "send" spinner used to spin forever on a stuck request).
  const fetchWithTimeout = async (url, options = {}, ms = 8000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  };

  const createWallet = async (username, password, confirmPassword, providedMnemonic = null) => {
    if (password !== confirmPassword) {
      throw new Error('Passwords do not match');
    }
    if (password.length < 8) {
      throw new Error('Password must be at least 8 characters long');
    }

    try {
      setIsLoading(true);

      // New self-custody key material (or import an existing phrase).
      const mnemonic = (providedMnemonic && validateMnemonic(providedMnemonic))
        ? providedMnemonic.trim()
        : generateMnemonic();
      const { address } = deriveWepoKeypair(mnemonic);

      // Register the client-derived address; backend mints nothing.
      const response = await fetch(`${getBackendUrl()}/api/wallet/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, address }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Wallet creation failed');
      }
      if (payload.address && payload.address !== address) {
        throw new Error('Backend returned a different address than the self-custody key');
      }

      const walletData = {
        username: payload.username || username,
        address,
        createdAt: new Date().toISOString(),
        version: payload.version || 'self-custody-v1',
        securityLevel: payload.security_level || 'self_custody',
        recoveryPhraseAvailable: true,
        custodyMode: 'self_custody',
      };

      // Persist the phrase encrypted with the password BEFORE establishing the
      // session, so a failure here never leaves a sessioned but key-less wallet.
      storeMnemonic(mnemonic, password);

      // Arm always-on messaging for this open session (no password prompt later).
      armMessagingSession(mnemonic);

      localStorage.setItem('wepo_wallet_exists', 'true');
      localStorage.setItem('wepo_wallet_username', walletData.username);
      localStorage.setItem('wepo_wallet_version', walletData.version);

      persistWalletSession(walletData, password, {
        token: payload.session_token,
        expiresAt: payload.session_expires_at
      });
      setWallet(walletData);
      await loadWalletData(walletData.address);

      setBtcBalance(0.0);
      setBtcAddresses([]);
      setBtcTransactions([]);
      setBtcUtxos([]);

      secureLog.info('Self-custody wallet created successfully');
      // Return the mnemonic ONCE so the UI can show the backup screen; it is not
      // returned again and is never logged.
      return {
        address,
        username: walletData.username,
        mnemonic,
        recoveryPhraseAvailable: true,
        custodyMode: 'self_custody',
      };

    } catch (error) {
      setIsLoading(false);
      secureLog.error('Wallet creation error', error);
      throw new Error('Failed to create wallet: ' + error.message);
    }
  };

  const loginWallet = async (username, password) => {
    try {
      setIsLoading(true);

      const response = await fetch(`${getBackendUrl()}/api/wallet/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Invalid username or password');
      }
      if (!payload.address) {
        throw new Error('Wallet is missing a WEPO address');
      }

      // The spend key lives only in the locally-stored mnemonic. Decrypt it with
      // the password and confirm it derives this account's address; if it is
      // missing (e.g. a fresh device) the wallet is read-only until the phrase is
      // imported via recoverWallet().
      const mnemonic = loadMnemonic(password);
      let recoveryAvailable = false;
      if (mnemonic && validateMnemonic(mnemonic)) {
        const { address: derived } = deriveWepoKeypair(mnemonic);
        recoveryAvailable = derived === payload.address;
        // Arm always-on messaging for this open session (no password prompt later).
        if (recoveryAvailable) armMessagingSession(mnemonic);
      }

      const walletData = {
        username: payload.username || username,
        address: payload.address,
        createdAt: payload.created_at ? new Date(payload.created_at * 1000).toISOString() : new Date().toISOString(),
        version: payload.version || 'self-custody-v1',
        securityLevel: payload.security_level || 'self_custody',
        recoveryPhraseAvailable: recoveryAvailable,
        custodyMode: payload.custody_mode || 'self_custody',
        needsRecoveryImport: !recoveryAvailable,
      };

      localStorage.setItem('wepo_wallet_exists', 'true');
      localStorage.setItem('wepo_wallet_username', walletData.username);
      localStorage.setItem('wepo_wallet_version', walletData.version);

      persistWalletSession(walletData, password, {
        token: payload.session_token,
        expiresAt: payload.session_expires_at
      });

      setWallet(walletData);
      setBtcBalance(0.0);
      setBtcAddresses([]);
      setBtcTransactions([]);
      setBtcUtxos([]);

      await loadWalletData(walletData.address);
      return walletData;

    } catch (error) {
      console.error('❌ Login error:', error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const recoverWallet = async (mnemonic, password, username) => {
    const phrase = (mnemonic || '').trim();
    if (!validateMnemonic(phrase)) {
      throw new Error('Invalid recovery phrase');
    }
    if (!password || password.length < 8) {
      throw new Error('Password must be at least 8 characters long');
    }
    if (!username) {
      throw new Error('Username is required to recover your wallet');
    }

    try {
      setIsLoading(true);
      const { address } = deriveWepoKeypair(phrase);

      // Store the phrase locally so this device can sign.
      storeMnemonic(phrase, password);

      // Arm always-on messaging for this open session (no password prompt later).
      armMessagingSession(phrase);

      // Register the address for a read session; if the username already exists,
      // fall back to login. Spends are signature-authorized off this address
      // regardless of the backend account state.
      let payload = {};
      const createResp = await fetch(`${getBackendUrl()}/api/wallet/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, address }),
      });
      payload = await createResp.json().catch(() => ({}));
      if (!createResp.ok) {
        const loginResp = await fetch(`${getBackendUrl()}/api/wallet/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        });
        payload = await loginResp.json().catch(() => ({}));
        if (!loginResp.ok) {
          throw new Error(payload.detail || payload.error || 'Recovery failed');
        }
      }

      const walletData = {
        username: payload.username || username,
        address,
        createdAt: new Date().toISOString(),
        version: payload.version || 'self-custody-v1',
        securityLevel: 'self_custody',
        recoveryPhraseAvailable: true,
        custodyMode: 'self_custody',
      };

      localStorage.setItem('wepo_wallet_exists', 'true');
      localStorage.setItem('wepo_wallet_username', walletData.username);
      localStorage.setItem('wepo_wallet_version', walletData.version);

      persistWalletSession(walletData, password, {
        token: payload.session_token,
        expiresAt: payload.session_expires_at
      });
      setWallet(walletData);
      await loadWalletData(address);

      secureLog.info('Self-custody wallet recovered successfully');
      return walletData;
    } catch (error) {
      secureLog.error('Wallet recovery error', error);
      throw new Error('Recovery failed: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  const changePassword = async (currentPassword, newPassword, confirmNewPassword) => {
    if (newPassword !== confirmNewPassword) {
      throw new Error('New passwords do not match');
    }
    if (!currentPassword) {
      throw new Error('Current password is required');
    }
    if (!newPassword || newPassword.length < 8) {
      throw new Error('New password must be at least 8 characters long');
    }

    // Re-encrypt the local recovery phrase under the new password. Note: the
    // backend login password is managed separately and unchanged here.
    const mnemonic = loadMnemonic(currentPassword);
    if (!mnemonic || !validateMnemonic(mnemonic)) {
      throw new Error('Current password is incorrect, or no recovery phrase is stored on this device');
    }
    storeMnemonic(mnemonic, newPassword);
    return { success: true, message: 'Local wallet password updated' };
  };

  // Remove old generateWepoAddress - now handled by addressUtils

  const loadWalletData = async (address) => {
    setIsLoading(true);
    try {
      // Check if we have a real backend connection
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      
      try {
        // Try to get real balance from blockchain
        const response = await fetch(`${backendUrl}/api/wallet/${address}`);
        if (response.ok) {
          const data = await response.json();
          const walletBalance = Number(data.balance || 0);
          setBalance(walletBalance);
          sessionManager.set('wepo_balance', walletBalance);
          
          // Get real transaction history
          const txResponse = await fetch(`${backendUrl}/api/wallet/${address}/transactions`);
          if (txResponse.ok) {
            const txData = await txResponse.json();
            setTransactions(txData || []);
            sessionManager.set('wepo_transactions', txData || []);
          } else {
            setTransactions([]);
            sessionManager.set('wepo_transactions', []);
          }
        } else {
          // If blockchain not available, start with zero balance
          setBalance(0);
          setTransactions([]);
          sessionManager.set('wepo_balance', 0);
          sessionManager.set('wepo_transactions', []);
        }
      } catch (error) {
        console.log('Blockchain not connected, starting with zero balance');
        // Real cryptocurrency behavior - zero balance until actual transactions
        setBalance(0);
        setTransactions([]);
        sessionManager.set('wepo_balance', 0);
        sessionManager.set('wepo_transactions', []);
      }
      
    } catch (error) {
      console.error('Failed to load wallet data:', error);
      setBalance(0);
      setTransactions([]);
      sessionManager.set('wepo_balance', 0);
      sessionManager.set('wepo_transactions', []);
    } finally {
      setIsLoading(false);
    }
  };

  // ===== SELF-CUSTODIAL BITCOIN WALLET FUNCTIONS =====
  
  const initializeBitcoinWallet = async (seedPhrase) => {
    try {
      setIsBtcLoading(true);
      console.log('🔐 Initializing Bitcoin wallet (simplified)...');
      
      // Simplified initialization to prevent crashes
      setBtcBalance(0.0);
      setBtcAddresses([]);
      setBtcTransactions([]);
      setBtcUtxos([]);
      
      console.log('✅ Bitcoin wallet initialized (simplified mode)');
      return { success: true, mode: 'simplified' };
      
    } catch (error) {
      console.error('❌ Bitcoin wallet initialization failed:', error);
      return { success: false, error: error.message };
    } finally {
      setIsBtcLoading(false);
    }
  };

  const loadExistingBitcoinWallet = async (seedPhrase) => {
    try {
      console.log('🔄 Loading existing Bitcoin wallet (placeholder)...');
      
      // Placeholder implementation to prevent crashes
      setBtcBalance(0.0);
      setBtcAddresses([]);
      setBtcTransactions([]);
      setBtcUtxos([]);
      
      console.log('✅ Bitcoin wallet placeholder loaded');
      return { success: true, restored: true, placeholder: true };
      
    } catch (error) {
      console.error('❌ Failed to load Bitcoin wallet placeholder:', error);
      return { success: false, error: error.message };
    }
  };

  const loadBitcoinWallet = async (mnemonic, password) => {
    try {
      console.log('🔄 Initializing self-custodial Bitcoin wallet (simplified)...');
      // Simplified Bitcoin wallet for testing
      const seed = CryptoJS.SHA256(mnemonic + (password || '')).toString();
      
      // Generate sample BTC addresses
      const addrs = [];
      for (let i = 0; i < 5; i++) {
        const addr = `bc1q${CryptoJS.SHA256(seed + i).toString().substring(0, 32)}`;
        addrs.push({ address: addr, index: i, change: 0 });
      }
      
      setBtcAddresses(addrs.map(a => a.address));
      setBtcBalance(0);
      setBtcTransactions([]);
      setBtcUtxos([]);
      setBtcWallet({ accountXPrv: 'simplified', nextReceive: 5, nextChange: 0 });
      setBtcWalletFingerprint('test');
      
      console.log('✅ Bitcoin wallet initialized (simplified) with 5 addresses');
      
      // Sync balances and history
      await syncBitcoinViaEsplora(addrs.map(a => a.address));
      return { success: true, restored: true, addresses: addrs.map(a => a.address) };
    } catch (error) {
      console.error('❌ Failed to init Bitcoin wallet:', error);
      setBtcBalance(0.0);
      setBtcAddresses([]);
      setBtcTransactions([]);
      setBtcUtxos([]);
      return { success: false, error: error.message };
    }
  };

  const syncBitcoinViaEsplora = async (addresses) => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';
      let total = 0;
      const txsAll = [];
      for (const addr of addresses) {
        const infoResp = await fetch(`${backendUrl}/api/bitcoin/address/${addr}`);
        if (!infoResp.ok) continue;
        const info = await infoResp.json();
        const data = info.data || {};
        const chain = data.chain_stats || {};
        const mempool = data.mempool_stats || {};
        const confirmed = (chain.funded_txo_sum || 0) - (chain.spent_txo_sum || 0);
        const unconfirmed = (mempool.funded_txo_sum || 0) - (mempool.spent_txo_sum || 0);
        const addrBal = ((confirmed + unconfirmed) / 1e8) || 0;
        total += addrBal;
        if (Array.isArray(info.txs)) txsAll.push(...info.txs);
      }
      setBtcBalance(total);
      setBtcTransactions(txsAll);
      return { success: true, balance: total, txs: txsAll };
    } catch (e) {
      console.warn('BTC Esplora sync failed', e);
      return { success: false, error: e.message };
    }
  };

  const syncBitcoinWallet = async (walletFingerprint, addresses) => {
    try {
      console.log('🔄 Syncing Bitcoin wallet with blockchain...');

      const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

      const response = await fetch(`${backendUrl}/api/bitcoin/wallet/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          wallet_fingerprint: walletFingerprint,
          addresses: addresses
        })
      });

      if (!response.ok) {
        throw new Error(`Bitcoin wallet sync failed: ${response.status}`);
      }

      const syncData = await response.json();
      
      if (syncData.success) {
        // Update balance
        setBtcBalance(syncData.total_balance_btc || 0);
        
        // Update transactions
        setBtcTransactions(syncData.transactions || []);
        
        // Update address balances
        const updatedAddresses = syncData.addresses || [];
        setBtcAddresses(updatedAddresses.map(addr => addr.address));
        
        console.log(`✅ Bitcoin wallet synced: ${syncData.total_balance_btc} BTC`);
        console.log(`📊 Found ${syncData.transactions?.length || 0} transactions`);
        
        return { success: true, balance: syncData.total_balance_btc };
      } else {
        throw new Error('Bitcoin wallet sync failed');
      }
      
    } catch (error) {
      console.error('❌ Failed to sync Bitcoin wallet:', error);
      return { success: false, error: error.message };
    }
  };

  const loadBitcoinData = async (placeholder) => {
    try {
      console.log('📊 Loading Bitcoin data (placeholder)...');
      
      // Set placeholder data to prevent crashes
      setBtcAddresses([]);
      setBtcBalance(0.0);
      setBtcTransactions([]);
      setBtcUtxos([]);
      
      console.log('✅ Bitcoin placeholder data loaded');
      
    } catch (error) {
      console.error('❌ Failed to load Bitcoin data:', error);
      setBtcBalance(0.0);
      setBtcTransactions([]);
      setBtcUtxos([]);
    }
  };

  const sendBitcoin = async (toAddress, amountBtc, password) => {
    try {
      console.log('🔄 Simplified Bitcoin send for testing...');
      
      if (!btcWallet || !btcWallet.accountXPrv) throw new Error('BTC wallet not initialized');
      const amountSats = Math.round(parseFloat(amountBtc) * 1e8);
      if (!amountSats || amountSats <= 0) throw new Error('Invalid amount');

      // Check for UTXOs (simplified)
      if (btcUtxos.length === 0) {
        throw new Error('No UTXOs available');
      }

      // Simulate transaction creation
      const txid = CryptoJS.SHA256(toAddress + amountBtc + Date.now()).toString();
      
      // Update local state
      setTransactions(prev => [{ 
        id: txid, 
        type: 'btc_send', 
        amount: amountBtc, 
        timestamp: new Date().toISOString(), 
        status: 'pending' 
      }, ...prev]);
      
      // Re-sync balances
      await syncBitcoinViaEsplora(btcAddresses);

      return { success: true, txid: txid, fee: 0.0001, path: 'simplified', peers: 1 };

    } catch (error) {
      console.error('❌ Bitcoin send failed:', error);
      return { success: false, error: error.message };
    }
  };

  const getNewBitcoinAddress = () => {
    try {
      console.log('🔄 Generating new Bitcoin address (simplified)...');
      
      if (!btcWallet || !btcWallet.accountXPrv) throw new Error('BTC wallet not initialized');
      
      const i = btcWallet.nextReceive || 0;
      const seed = CryptoJS.SHA256(btcWallet.accountXPrv + i).toString();
      const addr = `bc1q${seed.substring(0, 32)}`;
      
      const updated = [...btcAddresses, addr];
      setBtcAddresses(updated);
      setBtcWallet({ ...btcWallet, nextReceive: i + 1 });
      return addr;
    } catch (error) {
      console.error('❌ Failed to derive Bitcoin address:', error);
      return null;
    }
  };

  const getBitcoinBalance = () => {
    // Simplified for isolation testing
    return { confirmed: 0, unconfirmed: 0, total: 0 };
  };

  const exportBitcoinWalletInfo = () => {
    // Simplified for isolation testing
    return { addresses: [], balance: 0, utxoCount: 0, transactionCount: 0 };
  };

  const sendWepo = async (toAddress, amount, password) => {
    setIsLoading(true);
    try {
      const backendUrl = getBackendUrl();
      const walletAddress = getWalletAddress(wallet);
      if (!walletAddress) {
        throw new Error('No active wallet loaded');
      }

      // Re-derive the spend key from the locally-stored recovery phrase. It is
      // decrypted with the password only for the duration of this signing and is
      // never persisted in clear or sent to the backend.
      const mnemonic = loadMnemonic(password);
      if (!mnemonic || !validateMnemonic(mnemonic)) {
        throw new Error('Invalid wallet password, or no recovery phrase on this device. Import your recovery phrase to send.');
      }
      const { address, publicKey, secretKey } = deriveWepoKeypair(mnemonic);
      if (address !== walletAddress) {
        throw new Error('Recovery phrase does not match the active wallet address');
      }

      // 1) Ask the node (via backend) to build the unsigned skeleton + sighash.
      const buildResp = await fetch(`${backendUrl}/api/transaction/build-unsigned`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_address: address,
          to_address: toAddress,
          amount: parseFloat(amount),
        }),
      });
      const build = await buildResp.json().catch(() => ({}));
      if (!buildResp.ok) {
        throw new Error(build.detail || build.error || 'Failed to build transaction');
      }

      // 2) Sign locally; signTransaction refuses to sign if the node's sighash
      //    does not match our independent recomputation (anti-tamper).
      const signedTx = signTransaction(build.unsigned_tx, secretKey, publicKey, build.sighash);

      // 3) Submit the client-signed transaction. Spend authorization is the
      //    Dilithium signature, enforced by consensus — no session token needed.
      const response = await fetch(`${backendUrl}/api/transaction/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signed_tx: signedTx }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Transaction failed');
      }

      await loadWalletData(walletAddress);
      return payload;
    } catch (error) {
      throw new Error('Transaction failed: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  // Create a real on-chain RWA asset (self-custody, client-signed). The caller
  // supplies the asset_hash (sha256 commitment of the off-chain asset
  // definition); this builds -> signs -> submits exactly like sendWepo, so
  // ownership is bound to the user's key and the asset is anchored on-chain.
  const createRwaAsset = async ({ assetHash, name, assetType, metadata }, password) => {
    setIsLoading(true);
    try {
      const backendUrl = getBackendUrl();
      const walletAddress = getWalletAddress(wallet);
      if (!walletAddress) {
        throw new Error('No active wallet loaded');
      }

      const mnemonic = loadMnemonic(password);
      if (!mnemonic || !validateMnemonic(mnemonic)) {
        throw new Error('Invalid wallet password, or no recovery phrase on this device.');
      }
      const { address, publicKey, secretKey } = deriveWepoKeypair(mnemonic);
      if (address !== walletAddress) {
        throw new Error('Recovery phrase does not match the active wallet address');
      }

      // 1) Build the unsigned on-chain RWA creation + sighash.
      const buildResp = await fetch(`${backendUrl}/api/rwa/build-unsigned-create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          owner_address: address,
          asset_hash: assetHash,
          name,
          asset_type: assetType,
          metadata,
        }),
      });
      const build = await buildResp.json().catch(() => ({}));
      if (!buildResp.ok) {
        throw new Error(build.detail || build.error || 'Failed to build RWA creation');
      }

      // 2) Sign locally (anti-tamper sighash check).
      const signedTx = signTransaction(build.unsigned_tx, secretKey, publicKey, build.sighash);

      // 3) Submit the signed transaction.
      const response = await fetch(`${backendUrl}/api/transaction/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signed_tx: signedTx }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'RWA creation failed');
      }

      await loadWalletData(walletAddress);
      return { ...payload, asset_id: build.asset_id };
    } catch (error) {
      throw new Error('RWA creation failed: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  // ===== Private messaging (PQ end-to-end, blind relay) =====
  // Messaging is always on while the wallet is open: it uses the in-memory identity
  // (getMessagingIdentity) — never the password. Encryption is post-quantum E2E
  // (ML-KEM-768 + AES-256-GCM + ML-DSA-44); the relay only ever sees ciphertext.
  // Sending is free (relay store, no on-chain tx, no fee).

  // Publish (or refresh) this wallet's messaging public keys to the relay registry,
  // signed by the spend key and bound to the address so the relay can't substitute
  // keys. Free. Called automatically when the wallet opens.
  const publishMessagingKeys = async () => {
    const { spend, msg } = getMessagingIdentity();
    const digest = keyRegistryDigest(spend.address, msg.publicBundle.kem, msg.publicBundle.sig);
    const sig = signDigest(digest, spend.secretKey);
    const resp = await fetchWithTimeout(`${getRelayUrl()}/api/messages/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        address: spend.address,
        kem_pub: msg.publicBundle.kem,
        sig_pub: msg.publicBundle.sig,
        spend_pub: spend.publicKeyHex,
        sig,
      }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(payload.detail || payload.error || 'Failed to publish messaging keys');
    return payload;
  };

  // Idempotently make sure our keys are published for this open session, so others
  // can always reach us. Best-effort: failures don't block opening the inbox.
  const ensureMessagingReady = async () => {
    if (messagingReadyRef.current) return true;
    try {
      await publishMessagingKeys();
      messagingReadyRef.current = true;
      return true;
    } catch (e) {
      secureLog.warn('Messaging key publish deferred', e?.message);
      return false;
    }
  };

  // Resolve a recipient's messaging keys, preferring the trustless on-chain anchor
  // and falling back to the relay registry. The on-chain lookup is time-boxed so a
  // down/slow node can never hang a send — the registry fallback always runs.
  const _resolveRecipientKeys = async (toAddress) => {
    try {
      const onchain = await fetchWithTimeout(
        `${getBackendUrl()}/api/messages/keys/onchain/${encodeURIComponent(toAddress)}`, {}, 4000);
      if (onchain.ok) {
        const k = await onchain.json();
        if (k.kem_pub && k.sig_pub) return { kem_pub: k.kem_pub, sig_pub: k.sig_pub, source: 'on-chain' };
      }
    } catch (e) { /* fall through to relay registry */ }
    const reg = await fetchWithTimeout(`${getRelayUrl()}/api/messages/keys/${encodeURIComponent(toAddress)}`);
    const k = await reg.json().catch(() => ({}));
    if (!reg.ok) throw new Error(k.detail || 'This address has not used messaging yet, so it can\'t receive messages.');
    return { kem_pub: k.kem_pub, sig_pub: k.sig_pub, source: 'registry' };
  };

  // Encrypt + send a message to a recipient address (E2E; relay stays blind). Free.
  const sendMessage = async (toAddress, plaintext) => {
    const { spend, msg } = getMessagingIdentity();
    const keys = await _resolveRecipientKeys(toAddress);
    const envelope = encryptMessage({
      plaintext,
      fromAddress: spend.address,
      toAddress,
      recipientKemPublicKeyHex: keys.kem_pub,
      senderSigSecretKey: msg.sigSecretKey,
      senderSigPublicKey: msg.sigPublicKey,
    });
    const resp = await fetchWithTimeout(`${getRelayUrl()}/api/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ envelope }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(payload.detail || payload.error || 'Failed to send message');
    return payload;
  };

  // Owner-authenticated inbox fetch; decrypts envelopes locally.
  const fetchMessages = async () => {
    const { spend, msg } = getMessagingIdentity();
    const ts = Math.floor(Date.now() / 1000);
    const sig = signDigest(fetchAuthDigest(spend.address, ts), spend.secretKey);
    const resp = await fetchWithTimeout(`${getRelayUrl()}/api/messages/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address: spend.address, spend_pub: spend.publicKeyHex, sig, ts }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(payload.detail || payload.error || 'Failed to fetch messages');

    const out = [];
    for (const m of payload.messages || []) {
      try {
        const dec = decryptMessage(m.envelope, msg.kemSecretKey);
        out.push({ message_id: m.message_id, from: dec.from, plaintext: dec.plaintext,
                   ts: dec.ts, verified: dec.verified, stored_at: m.stored_at });
      } catch (e) {
        // Undecryptable (not for us / tampered) — skip rather than fail the batch.
      }
    }
    out.sort((a, b) => (a.stored_at || 0) - (b.stored_at || 0));
    return out;
  };

  // Auto-publish messaging keys whenever a wallet with a local identity is open, so
  // it's always reachable — no "enable" step. Best-effort; safe to re-run.
  useEffect(() => {
    if (!wallet?.address) return;
    let cancelled = false;
    (async () => { if (!cancelled) await ensureMessagingReady(); })();
    return () => { cancelled = true; };
  }, [wallet?.address]);

  const logout = async () => {
    secureLog.info('User logout initiated');

    const authSession = sessionManager.getAuthSession();
    if (authSession?.token) {
      try {
        await fetch(`${getBackendUrl()}/api/wallet/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${authSession.token}`,
          },
        });
      } catch (error) {
        secureLog.warn('Backend logout request failed; clearing local session only');
      }
    }
    
    // Clear all wallet data
    setWallet(null);
    setBalance(0);
    setTransactions([]);
    
    // Clear Bitcoin wallet data
    setBtcWallet(null);
    setBtcBalance(0);
    setBtcTransactions([]);
    setBtcAddresses([]);
    setBtcUtxos([]);
    
    // Clear secure session data
    secureStorage.removeSecureItem('wallet_data');
    secureStorage.removeSecureItem(MNEMONIC_KEY);
    disarmMessagingSession();
    sessionManager.clearAuthSession();
    sessionManager.clearSecureSession();
    sessionManager.remove('wepo_current_wallet');
    sessionManager.remove('wepo_locked');
    sessionStorage.removeItem('wepo_current_wallet');
    
    // Clear any remaining localStorage items (except wallet existence flag)
    // Keep 'wepo_wallet_exists' and 'wepo_wallet_username' for login page
    
    secureLog.info('User logout completed successfully');
  };

  const value = {
    // State
    wallet,
    balance,
    btcBalance,
    transactions,
    btcTransactions,
    isLoading,
    masternodesEnabled,
    showSeedPhrase,
    setShowSeedPhrase,
    
    // Bitcoin wallet state
    btcWallet,
    btcAddresses,
    btcUtxos,
    btcWalletFingerprint,
    isBtcLoading,
    
    // Actions
    generateMnemonic,
    createWallet,
    loginWallet,
    logout,
    sendWepo,
    createRwaAsset,
    publishMessagingKeys,
    ensureMessagingReady,
    isMessagingActivated,
    activateMessaging,
    sendMessage,
    fetchMessages,
    loadWalletData,
    changePassword,
    setWallet,
    setBalance,
    setTransactions,
    validateMnemonic,
    recoverWallet,
    
    // Bitcoin wallet actions
    sendBitcoin,
    getNewBitcoinAddress,
    getBitcoinBalance,
    exportBitcoinWalletInfo,
    initializeBitcoinWallet,
    loadExistingBitcoinWallet,
    loadBitcoinWallet,
    syncBitcoinWallet,
    
    // Legacy setters (keep for compatibility)
    setBtcBalance,
    setBtcTransactions
  };

  return (
    <WalletContext.Provider value={value}>
      {children}
    </WalletContext.Provider>
  );
};
