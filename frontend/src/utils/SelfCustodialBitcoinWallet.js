/**
 * WEPO Self-Custodial Bitcoin Wallet Implementation
 * 
 * This module provides complete Bitcoin self-custody functionality:
 * - HD wallet generation from seed phrase (BIP32/BIP44)
 * - Private key management and derivation
 * - Bitcoin transaction creation and signing
 * - UTXO tracking and management
 * - Multi-address support with gap limit
 * - Full self-custodial capabilities
 */

import { mnemonicToSeed, validateMnemonic } from '@scure/bip39';
import { wordlist as englishWordlist } from '@scure/bip39/wordlists/english.js';
import BIP32Factory from 'bip32';
import * as ecc from 'tiny-secp256k1';
import CryptoJS from 'crypto-js';

// Initialize BIP32 with secp256k1 curve
const bip32 = BIP32Factory(ecc);

// Bitcoin network parameters
const NETWORKS = {
  bitcoin: {
    messagePrefix: '\x18Bitcoin Signed Message:\n',
    bech32: 'bc',
    bip32: {
      public: 0x0488b21e,  // xpub
      private: 0x0488ade4, // xprv
    },
    pubKeyHash: 0x00,      // P2PKH address prefix
    scriptHash: 0x05,      // P2SH address prefix
    wif: 0x80,             // WIF private key prefix
  },
  testnet: {
    messagePrefix: '\x18Bitcoin Signed Message:\n',
    bech32: 'tb',
    bip32: {
      public: 0x043587cf,  // tpub
      private: 0x04358394, // tprv
    },
    pubKeyHash: 0x6f,      // P2PKH testnet address prefix
    scriptHash: 0xc4,      // P2SH testnet address prefix
    wif: 0xef,             // WIF testnet private key prefix
  }
};

// Use mainnet for production Bitcoin functionality
const NETWORK = NETWORKS.bitcoin; // Switched to mainnet for real BTC functionality

// Bitcoin blockchain API configuration
const BLOCKCYPHER_API = {
  BASE_URL: 'https://api.blockcypher.com/v1/btc/main',
  // Free tier: 3 requests/sec, 200 requests/hour
  // For production, add API token: ?token=YOUR_TOKEN
  ENDPOINTS: {
    ADDRESS_INFO: (address) => `${BLOCKCYPHER_API.BASE_URL}/addrs/${address}`,
    ADDRESS_BALANCE: (address) => `${BLOCKCYPHER_API.BASE_URL}/addrs/${address}/balance`,
    UNSPENT_OUTPUTS: (address) => `${BLOCKCYPHER_API.BASE_URL}/addrs/${address}?unspentOnly=true`,
    BROADCAST_TX: `${BLOCKCYPHER_API.BASE_URL}/txs/push`,
    TX_INFO: (txid) => `${BLOCKCYPHER_API.BASE_URL}/txs/${txid}`
  }
};

// Bitcoin network service class
class BitcoinNetworkService {
  constructor() {
    this.rateLimitDelay = 350; // 350ms between requests to stay under 3/sec limit
    this.lastRequestTime = 0;
  }

  async rateLimitedRequest(url, options = {}) {
    // Rate limiting for free BlockCypher API
    const now = Date.now();
    const timeSinceLastRequest = now - this.lastRequestTime;
    if (timeSinceLastRequest < this.rateLimitDelay) {
      await new Promise(resolve => setTimeout(resolve, this.rateLimitDelay - timeSinceLastRequest));
    }
    
    this.lastRequestTime = Date.now();
    
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers
        }
      });
      
      if (!response.ok) {
        throw new Error(`Bitcoin API error: ${response.status} ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Bitcoin network request failed:', error);
      throw error;
    }
  }

  async getAddressInfo(address) {
    try {
      const data = await this.rateLimitedRequest(BLOCKCYPHER_API.ENDPOINTS.ADDRESS_INFO(address));
      return {
        address: data.address,
        balance: data.balance || 0, // in satoshis
        unconfirmed_balance: data.unconfirmed_balance || 0,
        final_balance: data.final_balance || 0,
        n_tx: data.n_tx || 0,
        unconfirmed_n_tx: data.unconfirmed_n_tx || 0,
        final_n_tx: data.final_n_tx || 0
      };
    } catch (error) {
      console.warn(`Failed to get address info for ${address}:`, error);
      return {
        address,
        balance: 0,
        unconfirmed_balance: 0,
        final_balance: 0,
        n_tx: 0,
        unconfirmed_n_tx: 0,
        final_n_tx: 0
      };
    }
  }

  async getAddressBalance(address) {
    try {
      const data = await this.rateLimitedRequest(BLOCKCYPHER_API.ENDPOINTS.ADDRESS_BALANCE(address));
      return {
        balance: data.balance || 0, // confirmed balance in satoshis
        unconfirmed_balance: data.unconfirmed_balance || 0,
        final_balance: data.final_balance || 0 // confirmed + unconfirmed
      };
    } catch (error) {
      console.warn(`Failed to get balance for ${address}:`, error);
      return { balance: 0, unconfirmed_balance: 0, final_balance: 0 };
    }
  }

  async getUnspentOutputs(address) {
    try {
      const data = await this.rateLimitedRequest(BLOCKCYPHER_API.ENDPOINTS.UNSPENT_OUTPUTS(address));
      return (data.txrefs || []).map(utxo => ({
        txid: utxo.tx_hash,
        vout: utxo.tx_output_n,
        value: utxo.value, // in satoshis
        confirmations: utxo.confirmations || 0,
        script: utxo.script || ''
      }));
    } catch (error) {
      console.warn(`Failed to get UTXOs for ${address}:`, error);
      return [];
    }
  }

  async broadcastTransaction(hexTx, relayOnly) {
    // Determine relay preference: default to 'relay-only', overridable via Settings
    try {
      if (typeof relayOnly === 'undefined') {
        const pref = sessionStorage.getItem('btc_relay_only');
        relayOnly = (pref === null) ? true : (pref === 'true');
      }
    } catch {}

    // Route through WEPO masternode relay to preserve network privacy
    try {
      const url = (typeof process !== 'undefined' && process.env && process.env.REACT_APP_BACKEND_URL)
        ? `${process.env.REACT_APP_BACKEND_URL}/api/bitcoin/relay/broadcast`
        : '/api/bitcoin/relay/broadcast';
      const relayOnlyPref = (sessionStorage.getItem('btc_relay_only') ?? 'true') === 'true';
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rawtx: hexTx, relay_only: relayOnlyPref })
      });
      const data = await resp.json();
      if (!resp.ok || !data.success || !data.relayed) {
        if (relayOnlyPref && (data.path === 'relay_attempt_no_peers' || data.path === 'relay_attempt_failed')) {
          throw new Error('No masternode peers available. Tip: In Settings, uncheck "Relay BTC via Masternodes only" to enable fallback broadcast.');
        }
        throw new Error(data.error || `Relay failed (HTTP ${resp.status})`);
      }

      // Persist last relay status for UI diagnostics
      try { sessionStorage.setItem('btc_last_relay_status', JSON.stringify({ ...data, ts: Date.now() })); } catch {}

      return { success: true, txid: data.txid, path: data.path, peers: data.peers, message: 'Relayed via WEPO masternodes' };
    } catch (error) {
      console.error('Failed to relay transaction:', error);
      return { success: false, error: error.message };
    }
  }

  satoshisToBTC(satoshis) {
    return satoshis / 100000000;
  }

  BTCToSatoshis(btc) {
    return Math.round(btc * 100000000);
  }
}

// BIP44 derivation paths
const BTC_DERIVATION_PATH = "m/44'/0'/0'"; // Bitcoin mainnet
const BTC_TESTNET_DERIVATION_PATH = "m/44'/1'/0'"; // Bitcoin testnet

class SelfCustodialBitcoinWallet {
  constructor() {
    this.masterSeed = null;
    this.masterNode = null;
    this.accountNode = null;
    this.addresses = [];
    this.privateKeys = {};
    this.utxos = [];
    this.transactions = [];
    this.nextReceiveIndex = 0;
    this.nextChangeIndex = 0;
    this.gapLimit = 20; // BIP44 gap limit
    this.networkService = new BitcoinNetworkService();
    this.balance = 0; // Total balance in BTC
    this.isInitialized = false;
  }

  /**
   * Sync balances with Bitcoin network in background (non-blocking)
   */
  async syncBalancesInBackground() {
    try {
      console.log('🔄 Starting background Bitcoin balance sync...');
      
      // Don't block the UI - run in background
      setTimeout(async () => {
        await this.updateAllBalances();
      }, 1000);
      
    } catch (error) {
      console.warn('⚠️ Background balance sync failed:', error);
    }
  }

  /**
   * Update balances for all addresses
   */
  async updateAllBalances() {
    if (!this.isInitialized) {
      console.warn('⚠️ Wallet not initialized, skipping balance update');
      return;
    }

    try {
      console.log('💰 Updating Bitcoin balances...');
      let totalBalance = 0;
      let totalUnconfirmed = 0;

      // Update balance for each address
      for (const addressInfo of this.addresses) {
        try {
          const balanceData = await this.networkService.getAddressBalance(addressInfo.address);
          
          // Update address info
          addressInfo.balance = balanceData.final_balance;
          addressInfo.unconfirmed_balance = balanceData.unconfirmed_balance;
          addressInfo.confirmed_balance = balanceData.balance;
          
          totalBalance += balanceData.final_balance;
          totalUnconfirmed += balanceData.unconfirmed_balance;
          
          console.log(`📍 Address ${addressInfo.address}: ${this.networkService.satoshisToBTC(balanceData.final_balance)} BTC`);
          
        } catch (error) {
          console.warn(`⚠️ Failed to update balance for ${addressInfo.address}:`, error);
        }
      }

      // Update total wallet balance
      this.balance = this.networkService.satoshisToBTC(totalBalance);
      
      console.log(`✅ Total Bitcoin balance: ${this.balance} BTC (${totalUnconfirmed} sat unconfirmed)`);
      
      // Update UTXOs if we have balance
      if (totalBalance > 0) {
        await this.updateUTXOs();
      }
      
    } catch (error) {
      console.error('❌ Failed to update Bitcoin balances:', error);
    }
  }

  /**
   * Update UTXOs for all addresses with balance
   */
  async updateUTXOs() {
    try {
      console.log('🔄 Updating UTXOs...');
      this.utxos = [];

      for (const addressInfo of this.addresses) {
        if (addressInfo.balance > 0) {
          try {
            const utxos = await this.networkService.getUnspentOutputs(addressInfo.address);
            
            // Add address info to UTXOs
            const enhancedUtxos = utxos.map(utxo => ({
              ...utxo,
              address: addressInfo.address,
              derivationPath: addressInfo.derivationPath,
              privateKey: addressInfo.privateKey
            }));
            
            this.utxos.push(...enhancedUtxos);
            console.log(`📦 Found ${utxos.length} UTXOs for ${addressInfo.address}`);
            
          } catch (error) {
            console.warn(`⚠️ Failed to get UTXOs for ${addressInfo.address}:`, error);
          }
        }
      }

      console.log(`✅ Total UTXOs: ${this.utxos.length}`);
      
    } catch (error) {
      console.error('❌ Failed to update UTXOs:', error);
    }
  }

  /**
   * Get current wallet balance
   * @returns {object} Balance information
   */
  getBalance() {
    return {
      confirmed: this.balance,
      unconfirmed: this.addresses.reduce((sum, addr) => 
        sum + this.networkService.satoshisToBTC(addr.unconfirmed_balance || 0), 0),
      total: this.balance
    };
  }

  /**
   * Get new receiving address
   * @returns {string} Bitcoin address
   */
  getNewReceivingAddress() {
    try {
      const newAddress = this.generateAddress(0, this.nextReceiveIndex);
      this.nextReceiveIndex++;
      return newAddress.address;
    } catch (error) {
      console.error('❌ Failed to generate new receiving address:', error);
      return null;
    }
  }

  /**
   * Generate new address and add to wallet
   * @returns {object} Address information
   */
  generateNewAddress() {
    return this.generateAddress(0, this.nextReceiveIndex++);
  }

  /**
   * Initialize wallet from seed phrase
   * @param {string} seedPhrase - BIP39 mnemonic seed phrase
   * @param {string} passphrase - Optional BIP39 passphrase
   * @returns {Promise<object>} Wallet initialization result
   */
  async initializeFromSeed(seedPhrase, passphrase = '') {
    try {
      console.log('🔐 Initializing Bitcoin wallet from seed...');
      
      // Validate seed phrase
      if (!validateMnemonic(seedPhrase, englishWordlist)) {
        throw new Error('Invalid seed phrase');
      }

      // Generate seed buffer from mnemonic
      this.masterSeed = await mnemonicToSeed(seedPhrase, passphrase);
      
      // Create master node from seed
      this.masterNode = bip32.fromSeed(this.masterSeed, NETWORK);
      
      // Derive account node (BIP44: m/44'/coin'/0')
      const derivationPath = NETWORK === NETWORKS.bitcoin ? 
        BTC_DERIVATION_PATH : 
        BTC_TESTNET_DERIVATION_PATH;
      
      this.accountNode = this.masterNode.derivePath(derivationPath);
      
      // Generate initial addresses (don't sync with network yet)
      await this.generateInitialAddresses();
      
      this.isInitialized = true;
      console.log('✅ Bitcoin wallet initialized successfully');
      
      // Start background balance sync (non-blocking)
      this.syncBalancesInBackground();
      
      return {
        success: true,
        masterFingerprint: this.masterNode.fingerprint.toString('hex'),
        accountXpub: this.accountNode.neutered().toBase58(),
        firstAddress: this.addresses[0]?.address,
        addressCount: this.addresses.length
      };
      
    } catch (error) {
      console.error('❌ Bitcoin wallet initialization failed:', error);
      throw new Error(`Failed to initialize Bitcoin wallet: ${error.message}`);
    }
  }

  /**
   * Generate initial receiving and change addresses
   */
  async generateInitialAddresses() {
    // Generate first 10 receiving addresses
    for (let i = 0; i < 10; i++) {
      this.generateAddress(0, i); // External chain (receiving)
    }
    
    // Generate first 5 change addresses
    for (let i = 0; i < 5; i++) {
      this.generateAddress(1, i); // Internal chain (change)
    }
  }

  /**
   * Generate a specific address and private key
   * @param {number} chain - 0 for external (receiving), 1 for internal (change)
   * @param {number} index - Address index
   * @returns {object} Address information
   */
  generateAddress(chain, index) {
    try {
      // Derive key: m/44'/0'/0'/chain/index
      const addressNode = this.accountNode.derive(chain).derive(index);
      
      // Generate P2PKH address (1...)
      const { address } = this.generateP2PKHAddress(addressNode.publicKey);
      
      // Store private key
      const privateKey = addressNode.privateKey;
      const wif = addressNode.toWIF();
      
      const addressInfo = {
        address,
        derivationPath: `m/44'/0'/0'/${chain}/${index}`,
        chain, // 0 = receiving, 1 = change
        index,
        publicKey: addressNode.publicKey.toString('hex'),
        privateKey: privateKey.toString('hex'),
        wif,
        balance: 0,
        used: false
      };
      
      // Store in arrays
      this.addresses.push(addressInfo);
      this.privateKeys[address] = {
        privateKey,
        wif,
        node: addressNode
      };
      
      return addressInfo;
      
    } catch (error) {
      throw new Error(`Failed to generate address: ${error.message}`);
    }
  }

  /**
   * Generate P2PKH (Pay-to-Public-Key-Hash) address
   * @param {Buffer} publicKey - Public key buffer
   * @returns {object} Address and script information
   */
  generateP2PKHAddress(publicKey) {
    try {
      // Hash160 of public key
      const hash160 = this.hash160(publicKey);
      
      // Add network prefix
      const payload = Buffer.concat([
        Buffer.from([NETWORK.pubKeyHash]),
        hash160
      ]);
      
      // Calculate checksum
      const checksum = this.sha256(this.sha256(payload)).slice(0, 4);
      
      // Create final address
      const addressBuffer = Buffer.concat([payload, checksum]);
      const address = this.base58Encode(addressBuffer);
      
      return {
        address,
        hash160: hash160.toString('hex'),
        script: Buffer.concat([
          Buffer.from([0x76, 0xa9, 0x14]), // OP_DUP OP_HASH160 OP_PUSHDATA(20)
          hash160,
          Buffer.from([0x88, 0xac]) // OP_EQUALVERIFY OP_CHECKSIG
        ])
      };
      
    } catch (error) {
      throw new Error(`Failed to generate P2PKH address: ${error.message}`);
    }
  }

  /**
   * Get new receiving address
   * @returns {string} New receiving address
   */
  getNewReceiveAddress() {
    const addressInfo = this.generateAddress(0, this.nextReceiveIndex);
    this.nextReceiveIndex++;
    return addressInfo.address;
  }

  /**
   * Get new change address
   * @returns {string} New change address
   */
  getNewChangeAddress() {
    const addressInfo = this.generateAddress(1, this.nextChangeIndex);
    this.nextChangeIndex++;
    return addressInfo.address;
  }

  /**
   * Get all receiving addresses
   * @returns {Array} Array of receiving addresses
   */
  getReceivingAddresses() {
    return this.addresses.filter(addr => addr.chain === 0);
  }

  /**
   * Get all change addresses
   * @returns {Array} Array of change addresses
   */
  getChangeAddresses() {
    return this.addresses.filter(addr => addr.chain === 1);
  }

  /**
   * Get wallet balance
   * @returns {object} Balance information
   */
  getBalance() {
    const confirmed = this.utxos
      .filter(utxo => utxo.confirmations >= 1)
      .reduce((sum, utxo) => sum + utxo.value, 0);
      
    const unconfirmed = this.utxos
      .filter(utxo => utxo.confirmations === 0)
      .reduce((sum, utxo) => sum + utxo.value, 0);
      
    return {
      confirmed,
      unconfirmed,
      total: confirmed + unconfirmed,
      utxoCount: this.utxos.length
    };
  }

  /**
   * Create Bitcoin transaction
   * @param {Array} outputs - Array of {address, value} objects
   * @param {number} feeRate - Fee rate in satoshis per byte
   * @returns {object} Transaction information
   */
  async createTransaction(outputs, feeRate = 10) {
    try {
      // Select UTXOs for transaction
      const totalOutput = outputs.reduce((sum, out) => sum + out.value, 0);
      const selectedUtxos = this.selectUtxos(totalOutput, feeRate);
      
      if (!selectedUtxos.success) {
        throw new Error(selectedUtxos.error);
      }

      const { utxos, totalInput, estimatedFee } = selectedUtxos;
      const changeValue = totalInput - totalOutput - estimatedFee;
      
      // Build transaction
      const transaction = {
        version: 2,
        inputs: utxos.map(utxo => ({
          txid: utxo.txid,
          vout: utxo.vout,
          scriptSig: '', // Will be filled during signing
          sequence: 0xffffffff,
          value: utxo.value,
          address: utxo.address
        })),
        outputs: [...outputs],
        locktime: 0
      };
      
      // Add change output if needed
      if (changeValue > 546) { // Dust limit
        const changeAddress = this.getNewChangeAddress();
        transaction.outputs.push({
          address: changeAddress,
          value: changeValue
        });
      }
      
      return {
        success: true,
        transaction,
        fee: estimatedFee,
        changeValue: changeValue > 546 ? changeValue : 0,
        totalInput,
        totalOutput: totalOutput + estimatedFee + (changeValue > 546 ? changeValue : 0)
      };
      
    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Sign Bitcoin transaction
   * @param {object} transaction - Unsigned transaction
   * @returns {object} Signed transaction
   */
  async signTransaction(transaction) {
    try {
      const signedTransaction = { ...transaction };
      
      for (let i = 0; i < signedTransaction.inputs.length; i++) {
        const input = signedTransaction.inputs[i];
        const privateKeyInfo = this.privateKeys[input.address];
        
        if (!privateKeyInfo) {
          throw new Error(`Private key not found for address: ${input.address}`);
        }
        
        // Create signature hash
        const sigHash = this.createSignatureHash(signedTransaction, i);
        
        // Sign with private key
        const signature = this.signHash(sigHash, privateKeyInfo.privateKey);
        
        // Create scriptSig
        const publicKey = privateKeyInfo.node.publicKey;
        input.scriptSig = this.createScriptSig(signature, publicKey);
      }
      
      return {
        success: true,
        signedTransaction,
        txHex: this.serializeTransaction(signedTransaction)
      };
      
    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Select UTXOs for spending
   * @param {number} targetValue - Target output value in satoshis
   * @param {number} feeRate - Fee rate in satoshis per byte
   * @returns {object} Selected UTXOs and fee information
   */
  selectUtxos(targetValue, feeRate) {
    try {
      // Sort UTXOs by value (largest first for now - simple selection)
      const availableUtxos = this.utxos
        .filter(utxo => utxo.confirmations >= 1)
        .sort((a, b) => b.value - a.value);
      
      if (availableUtxos.length === 0) {
        return { success: false, error: 'No confirmed UTXOs available' };
      }
      
      const selectedUtxos = [];
      let totalInput = 0;
      let estimatedSize = 10; // Base transaction size
      
      for (const utxo of availableUtxos) {
        selectedUtxos.push(utxo);
        totalInput += utxo.value;
        estimatedSize += 148; // Input size estimate
        
        const estimatedFee = estimatedSize * feeRate;
        
        if (totalInput >= targetValue + estimatedFee) {
          return {
            success: true,
            utxos: selectedUtxos,
            totalInput,
            estimatedFee,
            estimatedSize
          };
        }
      }
      
      return {
        success: false,
        error: 'Insufficient funds'
      };
      
    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  // Utility functions
  hash160(buffer) {
    return CryptoJS.RIPEMD160(
      CryptoJS.SHA256(CryptoJS.lib.WordArray.create(buffer))
    ).toString(CryptoJS.enc.Hex);
  }

  sha256(buffer) {
    const wordArray = typeof buffer === 'string' ? 
      CryptoJS.enc.Hex.parse(buffer) : 
      CryptoJS.lib.WordArray.create(buffer);
    return Buffer.from(CryptoJS.SHA256(wordArray).toString(CryptoJS.enc.Hex), 'hex');
  }

  base58Encode(buffer) {
    // Simple Base58 encoding (in production, use a proper library)
    const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
    let result = '';
    let num = 0n;
    
    // Convert buffer to big integer
    for (const byte of buffer) {
      num = num * 256n + BigInt(byte);
    }
    
    // Convert to base58
    while (num > 0) {
      const remainder = num % 58n;
      result = alphabet[Number(remainder)] + result;
      num = num / 58n;
    }
    
    // Handle leading zeros
    for (const byte of buffer) {
      if (byte === 0) {
        result = '1' + result;
      } else {
        break;
      }
    }
    
    return result;
  }

  createSignatureHash(transaction, inputIndex) {
    // Simplified signature hash - in production use proper BIP143/BIP341
    const txData = JSON.stringify({
      inputs: transaction.inputs,
      outputs: transaction.outputs,
      inputIndex
    });
    return CryptoJS.SHA256(txData).toString(CryptoJS.enc.Hex);
  }

  signHash(hash, privateKey) {
    // Simplified signing - in production use proper ECDSA
    const signature = CryptoJS.HmacSHA256(hash, privateKey.toString('hex'));
    return signature.toString(CryptoJS.enc.Hex);
  }

  createScriptSig(signature, publicKey) {
    // Create P2PKH scriptSig: <signature> <publicKey>
    return `${signature}01 ${publicKey.toString('hex')}`;
  }

  serializeTransaction(transaction) {
    // Simplified transaction serialization
    return JSON.stringify(transaction);
  }

  // Storage management
  exportWallet() {
    return {
      masterFingerprint: this.masterNode ? this.masterNode.fingerprint.toString('hex') : null,
      accountXpub: this.accountNode ? this.accountNode.neutered().toBase58() : null,
      addresses: this.addresses,
      nextReceiveIndex: this.nextReceiveIndex,
      nextChangeIndex: this.nextChangeIndex,
      utxos: this.utxos,
      transactions: this.transactions
    };
  }

  importWalletData(walletData) {
    this.addresses = walletData.addresses || [];
    this.nextReceiveIndex = walletData.nextReceiveIndex || 0;
    this.nextChangeIndex = walletData.nextChangeIndex || 0;
    this.utxos = walletData.utxos || [];
    this.transactions = walletData.transactions || [];
    
    // Rebuild private keys lookup
    this.privateKeys = {};
    for (const addr of this.addresses) {
      if (this.accountNode) {
        const addressNode = this.accountNode.derive(addr.chain).derive(addr.index);
        this.privateKeys[addr.address] = {
          privateKey: addressNode.privateKey,
          wif: addressNode.toWIF(),
          node: addressNode
        };
      }
    }
  }
}

export default SelfCustodialBitcoinWallet;