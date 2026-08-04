import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import SHA256 from 'crypto-js/sha256';
import {
  generateMnemonic as generateBip39Mnemonic,
  validateMnemonic as validateBip39Mnemonic,
} from '@scure/bip39';
import { wordlist as englishWordlist } from '@scure/bip39/wordlists/english.js';
import {
  formatWepoAtomic, parseWepoAmountToAtomic, sessionManager, secureLog,
  secureStorage, validateWepoAddress,
} from '../utils/securityUtils';
import {
  assertStandardSendIntent,
  canonicalSighashHex,
  canonicalTxidHex,
  deriveWepoKeypair,
  estimateSignedTransactionWireSize,
  signTransaction,
  signDigest,
  verifyTransactionInput,
} from '../utils/wepoSigner';
import { createGhostReceiver, deriveGhostSecretMaterial } from '../utils/wepoGhost.js';
import {
  loadGhostWalletState,
  saveGhostWalletState,
} from '../utils/ghostWalletState.js';
import {
  assertGhostTransactionPlan,
  assertGhostTransactionShape,
  createGhostTransactionPlan,
} from '../utils/ghostTransactionPlanner.js';
import { createGhostBridgeProofProducer } from '../utils/ghostProofProducer.js';
import { buildGhostBridgeWitness } from '../utils/ghostWitnessBuilder.js';
import { createGhostBridge, hasGhostBridge } from '../utils/ghostBridge.js';
import { loadGhostWasmBridge } from '../utils/ghostWasmBridge.js';
import { refreshGhostWitnessesFromNode } from '../utils/ghostWitnessRefresh.js';
import {
  deriveMessagingKeypair,
  encryptMessage,
  decryptMessage,
  keyRegistryDigest,
  fetchAuthDigest,
  randomMessagingSeed,
  signMessagingDigest,
  keyOwnerBindingDigest,
  verifyOwnerBinding,
} from '../utils/wepoMessaging';
import FEATURES, { NETWORK_PROFILE } from '../config/featureFlags';
// import { generateWepoAddress, generateBitcoinAddress, validateAddress } from '../utils/addressUtils';
// Temporarily comment out Bitcoin wallet import to prevent runtime errors
// import * as bitcoin from 'bitcoinjs-lib';
// import BIP32Factory from 'bip32';
// import * as ecc from 'tiny-secp256k1';
// import { ECPairFactory } from 'ecpair';
// const SelfCustodialBitcoinWallet = null; // not used directly

const WalletContext = createContext();
const MESSAGING_ENABLED = FEATURES.messaging;
const BTC_ENABLED = FEATURES.btc;
const ensureBtcEnabled = () => {
  if (!BTC_ENABLED) {
    throw new Error('Bitcoin functionality is disabled by this release build');
  }
};

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

  // In-memory cache of the device-local messaging identity ({ address, msg }),
  // (re)built by getMessagingIdentity below. No password / phrase involved.
  const messagingIdentityRef = useRef(null);
  const messagingReadyRef = useRef(false); // becomes true once keys are published
  const ghostBridgeRef = useRef(null);
  // Ready-to-POST, owner-bound registration body (address + keys + self-sig +
  // spend-key ownership proof). Built at login/create/recover when the spend key is
  // momentarily available, then cached (it holds only signatures, never the secret)
  // so background publishing needs no extra password prompt. Cleared on logout.
  const messagingRegistrationRef = useRef(null);

  const getWalletAddress = (walletData) => walletData?.address || walletData?.wepo?.address || '';

  const persistWalletSession = (walletData, password, authSession = null) => {
    const walletAddress = getWalletAddress(walletData);
    if (!walletAddress) {
      throw new Error('Wallet address missing from session data');
    }

    if (!secureStorage.setSecureItem('wallet_data', walletData, password)) {
      throw new Error('Failed to store encrypted wallet data');
    }

    sessionManager.createSecureSession(walletAddress, password);
    if (authSession?.token && authSession?.expiresAt) {
      if (!sessionManager.setAuthSession({
        token: authSession.token,
        expiresAt: authSession.expiresAt,
        walletAddress,
        username: walletData.username
      })) {
        throw new Error('Failed to store authenticated session');
      }
    } else {
      // A recovery phrase is sufficient to restore and spend from a self-custody
      // wallet. Backend accounts are optional UI sessions, never a recovery
      // dependency or an authority over the spend key.
      sessionManager.clearAuthSession();
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

  const generateMnemonic = () => generateBip39Mnemonic(englishWordlist, 128); // 12 words

  const validateMnemonic = (mnemonic) => {
    try {
      return validateBip39Mnemonic((mnemonic || '').trim(), englishWordlist);
    } catch (e) {
      return false;
    }
  };

  // Encrypted local store for the recovery phrase (the only spend secret).
  const MNEMONIC_KEY = 'wepo_mnemonic';
  const encryptedVaultStorageKey = (key) => `wepo_secure_${key}`;
  const captureEncryptedVault = () => ({
    mnemonic: localStorage.getItem(encryptedVaultStorageKey(MNEMONIC_KEY)),
    walletData: localStorage.getItem(encryptedVaultStorageKey('wallet_data')),
    walletExists: localStorage.getItem('wepo_wallet_exists'),
    walletUsername: localStorage.getItem('wepo_wallet_username'),
    walletVersion: localStorage.getItem('wepo_wallet_version'),
  });
  const restoreEncryptedVault = (snapshot) => {
    const restoreItem = (key, value) => {
      if (value === null) {
        localStorage.removeItem(key);
      } else {
        localStorage.setItem(key, value);
      }
    };
    restoreItem(encryptedVaultStorageKey(MNEMONIC_KEY), snapshot.mnemonic);
    restoreItem(encryptedVaultStorageKey('wallet_data'), snapshot.walletData);
    restoreItem('wepo_wallet_exists', snapshot.walletExists);
    restoreItem('wepo_wallet_username', snapshot.walletUsername);
    restoreItem('wepo_wallet_version', snapshot.walletVersion);
  };
  const storeMnemonic = (mnemonic, password) => {
    if (!secureStorage.setSecureItem(MNEMONIC_KEY, mnemonic, password)) {
      throw new Error('Failed to securely store the recovery phrase');
    }
  };
  const loadMnemonic = (password) => secureStorage.getSecureItem(MNEMONIC_KEY, password);

  const loadGhostState = useCallback(
    (password) => loadGhostWalletState(secureStorage, password, NETWORK_PROFILE),
    [],
  );
  const saveGhostState = useCallback(
    (password, state) => saveGhostWalletState(secureStorage, password, state),
    [],
  );
  const getGhostBridge = useCallback(async () => {
    if (ghostBridgeRef.current) return ghostBridgeRef.current;
    const bridge = hasGhostBridge()
      ? createGhostBridge()
      : await loadGhostWasmBridge({
        wasmUrl: `${process.env.PUBLIC_URL || ''}/ghost/wepo_zk.wasm`,
      });
    ghostBridgeRef.current = bridge;
    return bridge;
  }, []);
  const refreshGhostWalletWitnesses = useCallback(async (password) => {
    if (!password) throw new Error('Wallet password is required to refresh Ghost witnesses');
    const state = loadGhostState(password);
    const bridge = await getGhostBridge();
    const refreshed = await refreshGhostWitnessesFromNode({
      state,
      bridge,
      fetchWitness: async ({ commitment }) => {
        const response = await fetch(`${getBackendUrl()}/api/shielded/witness`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ commitment }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.detail || payload.error || 'Witness retrieval failed');
        }
        return payload;
      },
    });
    saveGhostState(password, refreshed);
    return {
      state: refreshed,
      refreshedNotes: refreshed.notes.filter((note) => !note.spent && note.witness).length,
      tip: refreshed.tip,
    };
  }, [getGhostBridge, loadGhostState, saveGhostState]);
  const createGhostReceiverAddress = useCallback(async (password) => {
    if (!password) throw new Error('Wallet password is required to create a Ghost receiver');
    const mnemonic = loadMnemonic(password);
    if (!mnemonic || !validateMnemonic(mnemonic)) {
      throw new Error('Invalid wallet password, or no recovery phrase on this device');
    }
    const bridge = await getGhostBridge();
    const secretMaterial = deriveGhostSecretMaterial(mnemonic);
    return createGhostReceiver(secretMaterial, bridge, NETWORK_PROFILE);
  }, [getGhostBridge]);

  // ===== MESSAGING IDENTITY (device-local, click-and-use) =====
  // Messaging uses a DEVICE-LOCAL messaging keypair (ML-KEM + ML-DSA), generated
  // automatically the first time you open messaging for a wallet address and then
  // kept on the device. It is INDEPENDENT of the recovery phrase and the spend/
  // funds key — so messaging needs no password, works for any wallet (even ones
  // with no phrase stored here), and never exposes funds keys. The relay
  // authenticates this messaging key directly (self-signed registration + fetch).
  //
  // Trade-off: the relay can't prove these keys belong to the address's spend
  // owner (claim-based; possible registry MITM). The trustless path is the on-chain
  // key anchor, resolved first. Messaging is gated pre-mainnet. See MESSAGING_DESIGN.md.
  const MESSAGING_SEED_PREFIX = 'wepo_msgseed_';
  // Persisted owner-bound registration body (public keys + signatures only, never a
  // secret) so publishing survives page reloads without re-entering the phrase.
  const MESSAGING_REG_PREFIX = 'wepo_msgreg_';

  // Load (or create + persist) the device messaging seed for an address, then
  // derive its keypair. Cached in memory and rebuilt automatically — never throws
  // for "not activated", so messaging is always ready when a wallet is open.
  const getMessagingIdentity = () => {
    if (!MESSAGING_ENABLED) {
      throw new Error('Private messaging is not available in this release.');
    }
    const address = wallet?.address;
    if (!address) throw new Error('Open your wallet to use messaging.');
    const cached = messagingIdentityRef.current;
    if (cached && cached.address === address) return cached;

    const key = `${MESSAGING_SEED_PREFIX}${address}`;
    let seed = null;
    try { seed = localStorage.getItem(key); } catch (e) { /* non-fatal */ }
    if (!seed) {
      seed = randomMessagingSeed();
      try { localStorage.setItem(key, seed); } catch (e) { /* non-fatal */ }
      messagingReadyRef.current = false; // brand-new key → (re)publish
    }
    const identity = { address, msg: deriveMessagingKeypair(seed) };
    messagingIdentityRef.current = identity;
    return identity;
  };

  // Messaging is available only when explicitly enabled for a staging build.
  const isMessagingActivated = () => MESSAGING_ENABLED && !!wallet?.address;

  const disarmMessagingSession = () => {
    // Drop the in-memory identity only. The per-address device seed stays in
    // localStorage so the same device keeps the same inbox across logout/login.
    messagingIdentityRef.current = null;
    messagingReadyRef.current = false;
    messagingRegistrationRef.current = null;
  };

  // fetch() with a hard timeout so a slow/half-open relay can never hang the UI
  // (the messaging "send" spinner used to spin forever on a stuck request).
  const fetchWithTimeout = async (url, options = {}, ms = 8000) => {
    const controller = new AbortController();
    // Abort with an explicit reason so callers/UI can surface something meaningful
    // instead of the opaque browser default "signal is aborted without reason".
    const timer = setTimeout(
      () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
      ms,
    );
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

    if (providedMnemonic !== null && !validateMnemonic(providedMnemonic)) {
      throw new Error('Invalid provided recovery phrase');
    }
    const previousVault = captureEncryptedVault();

    try {
      setIsLoading(true);

      // New self-custody key material (or import an existing phrase).
      const mnemonic = providedMnemonic !== null
        ? providedMnemonic.trim()
        : generateMnemonic();
      const { address } = deriveWepoKeypair(mnemonic);

      // Produce the messaging ownership proof now (spend key in hand) so receiving
      // works later with no extra step. Best-effort; never blocks wallet creation.
      prepareMessagingRegistration(mnemonic, address);


      const walletData = {
        username: (username || '').trim() || `wallet-${address.slice(-8)}`,
        address,
        createdAt: new Date().toISOString(),
        version: 'self-custody-v1',
        securityLevel: 'self_custody',
        recoveryPhraseAvailable: true,
        custodyMode: 'self_custody',
        createdLocally: true,
      };

      // Persist the phrase encrypted with the password BEFORE establishing the
      // session, so a failure here never leaves a sessioned but key-less wallet.
      storeMnemonic(mnemonic, password);

      localStorage.setItem('wepo_wallet_exists', 'true');
      localStorage.setItem('wepo_wallet_username', walletData.username);
      localStorage.setItem('wepo_wallet_version', walletData.version);

      persistWalletSession(walletData, password);
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
      try {
        restoreEncryptedVault(previousVault);
      } catch (rollbackError) {
        secureLog.error('Wallet creation rollback failed', rollbackError);
      }
      // Account registration is not part of wallet creation, so a local write
      // failure cannot strand spend authority behind a server-side identity.
      setIsLoading(false);
      secureLog.error('Wallet creation error', error);
      throw new Error('Failed to create wallet: ' + error.message);
    }
  };

  const loginWallet = async (username, password) => {
    try {
      setIsLoading(true);

      // Wallet unlock is deliberately local-only. A mistyped vault password
      // must never be sent to a legacy account endpoint, and a backend account
      // is not a recovery or spend-authority dependency.
      const localWallet = secureStorage.getSecureItem('wallet_data', password);
      const localMnemonic = loadMnemonic(password);
      if (localWallet?.address && localMnemonic && validateMnemonic(localMnemonic)) {
        const { address: derived } = deriveWepoKeypair(localMnemonic);
        if (derived !== localWallet.address) {
          throw new Error('Encrypted wallet data does not match its recovery phrase');
        }

        const walletData = {
          username: localWallet.username || username || `wallet-${derived.slice(-8)}`,
          address: derived,
          createdAt: localWallet.createdAt || new Date().toISOString(),
          version: localWallet.version || 'self-custody-v1',
          securityLevel: 'self_custody',
          recoveryPhraseAvailable: true,
          custodyMode: 'self_custody',
          recoveredLocally: !!localWallet.recoveredLocally,
        };
        prepareMessagingRegistration(localMnemonic, derived);
        persistWalletSession(walletData, password);
        setWallet(walletData);
        setBtcBalance(0.0);
        setBtcAddresses([]);
        setBtcTransactions([]);
        setBtcUtxos([]);
        await loadWalletData(derived);
        return walletData;
      }

      if (secureStorage.hasSecureItem('wallet_data')
          || secureStorage.hasSecureItem('wepo_mnemonic')) {
        throw new Error('Local wallet password is incorrect, or the encrypted vault is incomplete');
      }
      throw new Error('No local wallet vault found. Restore this wallet with its recovery phrase.');

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

    const previousVault = captureEncryptedVault();
    try {
      setIsLoading(true);
      const { address } = deriveWepoKeypair(phrase);

      // Produce the messaging ownership proof now (spend key in hand) so receiving
      // works immediately on this device with no extra step. Best-effort.
      prepareMessagingRegistration(phrase, address);

      // Store the phrase locally so this device can sign.
      storeMnemonic(phrase, password);

      // Recovery is deliberately local-only. Requiring the original backend
      // username/password would turn a server database into a hidden custody
      // dependency. Public balance/history reads and signature-authorized sends
      // are keyed by the recovered address and need no account session.
      const localLabel = (username || '').trim() || `wallet-${address.slice(-8)}`;

      const walletData = {
        username: localLabel,
        address,
        createdAt: new Date().toISOString(),
        version: 'self-custody-v1',
        securityLevel: 'self_custody',
        recoveryPhraseAvailable: true,
        custodyMode: 'self_custody',
        recoveredLocally: true,
      };

      localStorage.setItem('wepo_wallet_exists', 'true');
      localStorage.setItem('wepo_wallet_username', walletData.username);
      localStorage.setItem('wepo_wallet_version', walletData.version);

      persistWalletSession(walletData, password);
      setWallet(walletData);
      await loadWalletData(address);

      secureLog.info('Self-custody wallet recovered successfully');
      return walletData;
    } catch (error) {
      secureLog.error('Wallet recovery error', error);
      // The phrase and descriptor form one logical vault. If either encrypted
      // write fails, restore the exact previous ciphertexts rather than leaving
      // a split vault that cannot be unlocked.
      try {
        restoreEncryptedVault(previousVault);
      } catch (rollbackError) {
        secureLog.error('Wallet recovery rollback failed', rollbackError);
      }
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

    // Re-encrypt the complete local vault under the new password. The backend
    // account password is independent and unchanged here.
    const mnemonic = loadMnemonic(currentPassword);
    if (!mnemonic || !validateMnemonic(mnemonic)) {
      throw new Error('Current password is incorrect, or no recovery phrase is stored on this device');
    }
    const walletData = secureStorage.getSecureItem('wallet_data', currentPassword);
    const expectedAddress = deriveWepoKeypair(mnemonic).address;
    if (!walletData || getWalletAddress(walletData) !== expectedAddress) {
      throw new Error('Encrypted wallet data does not match the recovery phrase');
    }

    const previousVault = captureEncryptedVault();
    try {
      storeMnemonic(mnemonic, newPassword);
      if (!secureStorage.setSecureItem('wallet_data', walletData, newPassword)) {
        throw new Error('Failed to re-encrypt wallet data');
      }
      sessionManager.createSecureSession(expectedAddress, newPassword);
    } catch (error) {
      try {
        restoreEncryptedVault(previousVault);
      } catch (rollbackError) {
        secureLog.error('Password rotation rollback failed', rollbackError);
      }
      throw new Error('Password was not changed: ' + error.message);
    }
    return { success: true, message: 'Local wallet password updated' };
  };

  // Remove old generateWepoAddress - now handled by addressUtils

  // Stable identity (useCallback with no deps — it only closes over stable state
  // setters and the module-level sessionManager). Without this, every context
  // render produced a new loadWalletData reference; Dashboard's effect listed it
  // as a dependency and re-ran on every render, unbounded-polling /api/wallet/*
  // and backing up the request queue until messaging fetches timed out.
  const loadWalletData = useCallback(async (address) => {
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
  }, []);

  // ===== SELF-CUSTODIAL BITCOIN WALLET FUNCTIONS =====
  
  const initializeBitcoinWallet = async (seedPhrase) => {
    try {
      setIsBtcLoading(true);
      ensureBtcEnabled();
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
      ensureBtcEnabled();
      
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
      ensureBtcEnabled();
      // Simplified Bitcoin wallet for testing
      const seed = SHA256(mnemonic + (password || '')).toString();
      
      // Generate sample BTC addresses
      const addrs = [];
      for (let i = 0; i < 5; i++) {
        const addr = `bc1q${SHA256(seed + i).toString().substring(0, 32)}`;
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
      ensureBtcEnabled();
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
      ensureBtcEnabled();

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
      ensureBtcEnabled();
      
      if (!btcWallet || !btcWallet.accountXPrv) throw new Error('BTC wallet not initialized');
      const amountSats = Math.round(parseFloat(amountBtc) * 1e8);
      if (!amountSats || amountSats <= 0) throw new Error('Invalid amount');

      // Check for UTXOs (simplified)
      if (btcUtxos.length === 0) {
        throw new Error('No UTXOs available');
      }

      // Simulate transaction creation
      const txid = SHA256(toAddress + amountBtc + Date.now()).toString();
      
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
      ensureBtcEnabled();
      
      if (!btcWallet || !btcWallet.accountXPrv) throw new Error('BTC wallet not initialized');
      
      const i = btcWallet.nextReceive || 0;
      const seed = SHA256(btcWallet.accountXPrv + i).toString();
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

  const previewWepo = async (toAddress, amount) => {
    setIsLoading(true);
    try {
      const backendUrl = getBackendUrl();
      const walletAddress = getWalletAddress(wallet);
      if (!walletAddress) {
        throw new Error('No active wallet loaded');
      }

      const recipient = validateWepoAddress(toAddress);
      if (!recipient.isValid) {
        throw new Error(recipient.errors[0] || 'Invalid recipient address');
      }
      const amountAtomic = parseWepoAmountToAtomic(amount, { field: 'Amount' });
      const canonicalAmount = formatWepoAtomic(amountAtomic);

      // No password or private key is touched during preview. Omitting `fee`
      // asks the live node to quote against the exact fixed-size ML-DSA shape.
      const buildResp = await fetch(`${backendUrl}/api/transaction/build-unsigned`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_address: walletAddress,
          to_address: recipient.sanitizedAddress,
          amount: canonicalAmount,
        }),
      });
      const build = await buildResp.json().catch(() => ({}));
      if (!buildResp.ok) {
        throw new Error(build.detail || build.error || 'Failed to build transaction');
      }
      if (build.network !== NETWORK_PROFILE) {
        throw new Error('Node returned a transaction for the wrong WEPO network');
      }
      if (typeof build.sighash !== 'string' || !/^[0-9a-fA-F]{64}$/.test(build.sighash)) {
        throw new Error('Node returned an invalid transaction sighash');
      }
      if (!Number.isSafeInteger(build.fee_atomic) || build.fee_atomic < 0
          || !Number.isSafeInteger(build.total_atomic) || build.total_atomic <= 0
          || !Number.isSafeInteger(build.signed_canonical_size)
          || build.signed_canonical_size <= 0
          || !Number.isSafeInteger(build.minimum_relay_fee_per_kb_atomic)
          || build.minimum_relay_fee_per_kb_atomic < 0) {
        throw new Error('Node returned an incomplete or unsafe fee quote');
      }
      const feeAtomic = BigInt(build.fee_atomic);
      const totalAtomic = amountAtomic + feeAtomic;
      if (BigInt(build.total_atomic) !== totalAtomic) {
        throw new Error('Node returned a fee quote with an inconsistent total');
      }
      assertStandardSendIntent(build.unsigned_tx, {
        senderAddress: walletAddress,
        recipientAddress: recipient.sanitizedAddress,
        amountAtomic,
        feeAtomic,
      });
      const localSighash = canonicalSighashHex(build.unsigned_tx, NETWORK_PROFILE);
      if (localSighash !== build.sighash.toLowerCase()) {
        throw new Error('Node fee preview sighash does not match the transaction');
      }
      const signedSize = estimateSignedTransactionWireSize(build.unsigned_tx);
      if (signedSize !== build.signed_canonical_size) {
        throw new Error('Node fee preview canonical size does not match the wallet');
      }
      const relayRate = BigInt(build.minimum_relay_fee_per_kb_atomic);
      const requiredRelayFee = (relayRate * BigInt(signedSize) + 999n) / 1000n;
      if (feeAtomic < requiredRelayFee) {
        throw new Error('Node fee quote is below its advertised relay requirement');
      }

      return {
        schema: 'wepo-standard-send-preview-v1',
        createdAt: Date.now(),
        senderAddress: walletAddress,
        recipientAddress: recipient.sanitizedAddress,
        amountAtomic: amountAtomic.toString(),
        amount: canonicalAmount,
        feeAtomic: feeAtomic.toString(),
        fee: formatWepoAtomic(feeAtomic),
        totalAtomic: totalAtomic.toString(),
        total: formatWepoAtomic(totalAtomic),
        signedCanonicalSize: signedSize,
        relayFeeRateAtomic: build.minimum_relay_fee_per_kb_atomic,
        unsignedTx: build.unsigned_tx,
        sighash: build.sighash.toLowerCase(),
        network: build.network,
      };
    } catch (error) {
      throw new Error('Transaction preview failed: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  const sendWepo = async (preview, password) => {
    setIsLoading(true);
    try {
      const backendUrl = getBackendUrl();
      const walletAddress = getWalletAddress(wallet);
      if (!walletAddress) throw new Error('No active wallet loaded');
      if (!preview || preview.schema !== 'wepo-standard-send-preview-v1') {
        throw new Error('An approved fee preview is required before signing');
      }
      const previewAge = Date.now() - preview.createdAt;
      if (!Number.isFinite(previewAge) || previewAge < -5000 || previewAge > 120000) {
        throw new Error('Fee preview expired; request and approve a new preview');
      }
      if (preview.senderAddress !== walletAddress || preview.network !== NETWORK_PROFILE) {
        throw new Error('Fee preview does not belong to the active wallet and network');
      }
      const amountAtomic = BigInt(preview.amountAtomic);
      const feeAtomic = BigInt(preview.feeAtomic);
      assertStandardSendIntent(preview.unsignedTx, {
        senderAddress: walletAddress,
        recipientAddress: preview.recipientAddress,
        amountAtomic,
        feeAtomic,
      });
      if (canonicalSighashHex(preview.unsignedTx, NETWORK_PROFILE) !== preview.sighash
          || estimateSignedTransactionWireSize(preview.unsignedTx) !== preview.signedCanonicalSize) {
        throw new Error('Approved fee preview changed before signing');
      }

      // Recheck live relay policy before decrypting the recovery phrase. A rate
      // change invalidates the approval and requires a fresh visible quote.
      const statusResp = await fetch(`${backendUrl}/api/network/status`);
      const status = await statusResp.json().catch(() => ({}));
      if (!statusResp.ok || status.network_profile !== NETWORK_PROFILE
          || status.minimum_relay_fee_per_kb_atomic !== preview.relayFeeRateAtomic) {
        throw new Error('Relay-fee policy changed or is unavailable; approve a new preview');
      }

      const mnemonic = loadMnemonic(password);
      if (!mnemonic || !validateMnemonic(mnemonic)) {
        throw new Error('Invalid wallet password, or no recovery phrase on this device. Import your recovery phrase to send.');
      }
      const { address, publicKey, secretKey } = deriveWepoKeypair(mnemonic);
      if (address !== walletAddress) {
        throw new Error('Recovery phrase does not match the active wallet address');
      }

      const signedTx = signTransaction(
        preview.unsignedTx, secretKey, publicKey, preview.sighash, NETWORK_PROFILE,
      );
      if (!signedTx.inputs.every((_, index) => verifyTransactionInput(signedTx, index, NETWORK_PROFILE))) {
        throw new Error('Local transaction signature verification failed');
      }
      const localTxid = canonicalTxidHex(signedTx);

      const response = await fetch(`${backendUrl}/api/transaction/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signed_tx: signedTx }),
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Transaction failed');
      }
      const returnedTxid = payload.transaction_id || payload.tx_hash || payload.txid;
      if (typeof returnedTxid !== 'string' || returnedTxid.toLowerCase() !== localTxid) {
        throw new Error('Node returned a transaction ID that does not match the signed transaction');
      }

      await loadWalletData(walletAddress);
      return { ...payload, transaction_id: localTxid, tx_hash: localTxid };
    } catch (error) {
      throw new Error('Transaction failed: ' + error.message);
    } finally {
      setIsLoading(false);
    }
  };
  const previewGhostTransaction = async ({ flow, unsignedTx }) => {
    const backendUrl = getBackendUrl();
    const walletAddress = getWalletAddress(wallet);
    if (!walletAddress) throw new Error('No active wallet loaded');
    assertGhostTransactionShape(unsignedTx, flow, { allowProof: false });

    const response = await fetch(`${backendUrl}/api/transaction/build-ghost-unsigned`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        flow,
        owner_address: walletAddress,
        unsigned_tx: unsignedTx,
      }),
    });
    const build = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(build.detail || build.error || 'Failed to build Ghost transaction');
    }
    if (build.flow !== flow || build.network !== NETWORK_PROFILE
        || !build.unsigned_tx || typeof build.sighash !== 'string'
        || !/^[0-9a-f]{64}$/u.test(build.sighash)) {
      throw new Error('Node returned an invalid Ghost unsigned transaction');
    }
    const localSighash = canonicalSighashHex(build.unsigned_tx, NETWORK_PROFILE);
    if (localSighash !== build.sighash.toLowerCase()) {
      throw new Error('Node Ghost unsigned transaction failed local sighash verification');
    }
    assertGhostTransactionShape(build.unsigned_tx, flow, { allowProof: false });
    return {
      ...build,
      unsignedTx: build.unsigned_tx,
      sighash: build.sighash.toLowerCase(),
    };
  };

  const sendGhostTransaction = async ({
    flow,
    unsignedTx,
    proveBundle,
    ghostBridge,
    ghostState,
    secretMaterial,
    spendNotes,
    outputNotes,
  }, password) => {
    setIsLoading(true);
    try {
      const mnemonic = loadMnemonic(password);
      if (!mnemonic || !validateMnemonic(mnemonic)) {
        throw new Error('Invalid wallet password, or no recovery phrase on this device.');
      }
      const { address, publicKey, secretKey } = deriveWepoKeypair(mnemonic);
      const activeAddress = getWalletAddress(wallet);
      if (address !== activeAddress) {
        throw new Error('Recovery phrase does not match the active wallet address');
      }
      let localProveBundle = proveBundle;
      if (typeof localProveBundle !== 'function') {
        if (!ghostBridge) {
          throw new Error('An audited local Ghost bridge is required');
        }
        const durableState = ghostState || loadGhostState(password);
        const unlockedGhostMaterial = secretMaterial || deriveGhostSecretMaterial(mnemonic);
        localProveBundle = createGhostBridgeProofProducer(
          ghostBridge,
          ({ bundle }) => buildGhostBridgeWitness({
            state: durableState,
            bundle,
            secretMaterial: unlockedGhostMaterial,
            spendNotes,
            outputNotes,
            bridge: ghostBridge,
          }),
        );
      }
      const preview = await previewGhostTransaction({ flow, unsignedTx });
      const plan = await createGhostTransactionPlan({
        flow,
        unsignedTx: preview.unsignedTx,
        network: preview.network,
        proveBundle: localProveBundle,
      });
      if (plan.sighash !== preview.sighash) {
        throw new Error('Ghost proof plan does not match the node preview');
      }
      const signedTx = plan.transaction.inputs.length > 0
        ? signTransaction(
          plan.transaction, secretKey, publicKey, plan.sighash, NETWORK_PROFILE,
        )
        : plan.transaction;
      assertGhostTransactionPlan(plan, signedTx);
      const response = await fetch(`${getBackendUrl()}/api/transaction/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signed_tx: signedTx }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Ghost transaction rejected');
      }
      const localTxid = canonicalTxidHex(signedTx);
      const nodeTxid = payload.transaction_id || payload.tx_hash;
      if (nodeTxid && String(nodeTxid).toLowerCase() !== localTxid) {
        throw new Error('Node returned a transaction identity different from the signed Ghost transaction');
      }
      await loadWalletData(activeAddress);
      return { ...payload, transaction_id: localTxid, tx_hash: localTxid };
    } catch (error) {
      throw new Error('Ghost transaction failed: ' + error.message);
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

      if (build.network !== NETWORK_PROFILE) {
        throw new Error('Node returned a transaction for the wrong WEPO network');
      }
      // 2) Sign locally (anti-tamper sighash and network checks).
      const signedTx = signTransaction(
        build.unsigned_tx, secretKey, publicKey, build.sighash, NETWORK_PROFILE,
      );

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
  // Click-and-use: messaging uses the device-local messaging identity
  // (getMessagingIdentity) — never the password or the recovery phrase. Encryption
  // is post-quantum E2E (ML-KEM-768 + AES-256-GCM + ML-DSA-44); the relay only ever
  // sees ciphertext. Sending is free (relay store, no on-chain tx, no fee).

  // Build (and cache) this address's owner-bound messaging registration using the
  // spend key derived from `mnemonic`. Called at login/create/recover — the only
  // moments the spend key is in hand — so publishing later needs NO extra prompt.
  // The cached body holds only public keys + signatures, never the secret key.
  // Best-effort: returns null if messaging is off or the phrase can't prove
  // ownership of `address` (e.g. a read-only wallet with no local phrase).
  const prepareMessagingRegistration = (mnemonic, address) => {
    if (!MESSAGING_ENABLED || !mnemonic || !address) return null;
    try {
      const spend = deriveWepoKeypair(mnemonic);
      if (spend.address !== address) return null; // this phrase does not own the address
      // Device-local messaging identity (same per-address seed used everywhere).
      const seedKey = `${MESSAGING_SEED_PREFIX}${address}`;
      let seed = null;
      try { seed = localStorage.getItem(seedKey); } catch (e) { /* non-fatal */ }
      if (!seed) {
        seed = randomMessagingSeed();
        try { localStorage.setItem(seedKey, seed); } catch (e) { /* non-fatal */ }
      }
      const msg = deriveMessagingKeypair(seed);
      const kem_pub = msg.publicBundle.kem;
      const sig_pub = msg.publicBundle.sig;
      // (a) self-signature by the messaging key — proves we hold the inbox key.
      const sig = signMessagingDigest(keyRegistryDigest(address, kem_pub, sig_pub), msg.sigSecretKey);
      // (b) ownership proof — the SPEND key signs the owner-binding digest, and its
      // public key hashes to `address`, so the relay/senders know we own it.
      const owner_sig = signDigest(keyOwnerBindingDigest(address, kem_pub, sig_pub), spend.secretKey);
      const body = {
        address, kem_pub, sig_pub, sig,
        owner_sig_pub: spend.publicKeyHex, owner_sig,
      };
      messagingRegistrationRef.current = body;
      // Persist the proof (public keys + signatures only — NO secret key) so a
      // session restored after a page reload can still auto-publish without asking
      // for the phrase again. Safe: this is exactly what gets published publicly.
      try { localStorage.setItem(`${MESSAGING_REG_PREFIX}${address}`, JSON.stringify(body)); } catch (e) { /* non-fatal */ }
      messagingReadyRef.current = false; // (re)publish with the fresh ownership proof
      return body;
    } catch (e) {
      secureLog.warn('Messaging registration prepare deferred', e?.message);
      return null;
    }
  };

  // Publish this address's owner-bound messaging registration to the relay. Free and
  // silent (no fee, no on-chain tx, no prompt) — the ownership proof was already
  // produced at login. Called automatically when messaging opens.
  const publishMessagingKeys = async () => {
    if (!MESSAGING_ENABLED) throw new Error('Private messaging is not available in this release.');
    let body = messagingRegistrationRef.current;
    // Fall back to the persisted proof from a prior login (survives page reloads).
    if ((!body || body.address !== wallet?.address) && wallet?.address) {
      try {
        const saved = localStorage.getItem(`${MESSAGING_REG_PREFIX}${wallet.address}`);
        const parsed = saved ? JSON.parse(saved) : null;
        if (parsed && parsed.address === wallet.address && parsed.owner_sig) {
          body = parsed;
          messagingRegistrationRef.current = parsed;
        }
      } catch (e) { /* non-fatal */ }
    }
    if (!body || body.address !== wallet?.address) {
      // No ownership proof available (e.g. a read-only wallet without its recovery
      // phrase). Sending still works; to RECEIVE, open/import the phrase so the
      // wallet can prove it owns this address.
      throw new Error('Open your wallet with your recovery phrase to enable receiving messages.');
    }
    const resp = await fetchWithTimeout(`${getRelayUrl()}/api/messages/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(payload.detail || payload.error || 'Failed to publish messaging keys');
    return payload;
  };

  // Idempotently make sure our keys are published for this open session, so others
  // can always reach us. Best-effort: failures don't block opening the inbox.
  const ensureMessagingReady = async () => {
    if (!MESSAGING_ENABLED) return false;
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
    // Trustless: never trust the relay as an authority. Verify the returned keys are
    // bound to `toAddress` by that address's own spend key before encrypting to them,
    // so a forged/front-run registry entry can never redirect a message.
    if (!verifyOwnerBinding(toAddress, k.kem_pub, k.sig_pub, k.owner_sig_pub, k.owner_sig)) {
      throw new Error('Could not verify the recipient owns these messaging keys; refusing to send.');
    }
    return { kem_pub: k.kem_pub, sig_pub: k.sig_pub, source: 'registry' };
  };

  // Encrypt + send a message to a recipient address (E2E; relay stays blind). Free.
  const sendMessage = async (toAddress, plaintext) => {
    if (!MESSAGING_ENABLED) throw new Error('Private messaging is not available in this release.');
    const { address, msg } = getMessagingIdentity();
    const keys = await _resolveRecipientKeys(toAddress);
    const envelope = encryptMessage({
      plaintext,
      fromAddress: address,
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

  // Inbox fetch authenticated by the device messaging key; decrypts locally.
  const fetchMessages = async () => {
    if (!MESSAGING_ENABLED) throw new Error('Private messaging is not available in this release.');
    const { address, msg } = getMessagingIdentity();
    // Make sure our keys are registered before we try to prove ownership of the inbox.
    await ensureMessagingReady();
    const ts = Math.floor(Date.now() / 1000);
    const sig = signMessagingDigest(fetchAuthDigest(address, ts), msg.sigSecretKey);
    const resp = await fetchWithTimeout(`${getRelayUrl()}/api/messages/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address, sig_pub: msg.publicBundle.sig, sig, ts }),
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
    if (!MESSAGING_ENABLED || !wallet?.address) return;
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
    // Routine logout clears live state but leaves the encrypted device vault intact;
    // logout must never become destructive key removal.
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
    previewWepo,
    previewGhostTransaction,
    sendGhostTransaction,
    createRwaAsset,
    publishMessagingKeys,
    ensureMessagingReady,
    messagingEnabled: MESSAGING_ENABLED,
    isMessagingActivated,
    sendMessage,
    fetchMessages,
    loadWalletData,
    loadGhostState,
    saveGhostState,
    refreshGhostWalletWitnesses,
    createGhostReceiverAddress,
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
