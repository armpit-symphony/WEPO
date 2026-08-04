import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { WalletProvider, useWallet } from './WalletContext';
import {
  canonicalSighashHex,
  canonicalTxidHex,
  deriveWepoKeypair,
  estimateSignedTransactionWireSize,
  verifyTransactionInput,
} from '../utils/wepoSigner';
import { secureStorage } from '../utils/securityUtils';
import { TextDecoder, TextEncoder } from 'node:util';
import { webcrypto } from 'node:crypto';
import { vi } from 'vitest';

global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;
global.IS_REACT_ACT_ENVIRONMENT = true;

Object.defineProperty(global, 'crypto', { value: webcrypto });
const PHRASE = 'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about';
const PASSWORD = 'Correct Horse Battery 42!';
const NEW_PASSWORD = 'Rotated Local Vault 84!';

const response = (payload, ok = true) => ({
  ok,
  json: async () => payload,
});

describe('self-custody clean-device recovery', () => {
  let container;
  let root;
  let walletApi;
  let submitted;
  let buildRequest;
  let buildNetworkOverride;
  let buildMutator;
  let buildSighashOverride;
  let sendTxidOverride;

  const Harness = () => {
    walletApi = useWallet();
    return null;
  };

  beforeEach(async () => {
    localStorage.clear();
    buildNetworkOverride = null;
    sessionStorage.clear();
    submitted = null;
    buildRequest = null;
    buildMutator = null;
    buildSighashOverride = null;
    sendTxidOverride = null;
    global.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes('/api/transaction/build-unsigned')) {
        const body = JSON.parse(options.body);
        buildRequest = body;
        const recipient = deriveWepoKeypair(
          'legal winner thank year wave sausage worth useful legal winner thank yellow',
        ).address;
        const unsigned = {
          version: 1,
          lock_time: 0,
          timestamp: 1700000000,
          fee: 10000,
          tx_type: 'transfer',
          inputs: [{
            prev_txid: '11'.repeat(32),
            prev_vout: 0,
            sequence: 4294967295,
            script_sig: '7369676e61747572655f706c616365686f6c646572',
            signature_type: 'ecdsa',
            quantum_signature: null,
            quantum_public_key: null,
          }],
          outputs: [{
            value: 100000000,
            address: body.to_address || recipient,
            script_pubkey: '6f75747075745f736372697074',
          }],
          privacy_proof: null,
          ring_signature: null,
          shielded_bundle: null,
          extra_data: {},
        };
        if (buildMutator) buildMutator(unsigned, body);
        return response({
          network: buildNetworkOverride ?? 'mainnet',
          unsigned_tx: unsigned,
          sighash: buildSighashOverride ?? canonicalSighashHex(unsigned, 'mainnet'),
          fee_atomic: 10000,
          fee: '0.0001',
          total_atomic: 100010000,
          total: '1.0001',
          signed_canonical_size: estimateSignedTransactionWireSize(unsigned),
          minimum_relay_fee_per_kb_atomic: 0,
        });
      }
      if (url.includes('/api/network/status')) {
        return response({ network_profile: 'mainnet', minimum_relay_fee_per_kb_atomic: 0 });
      }
      if (url.includes('/api/transaction/send')) {
        submitted = JSON.parse(options.body).signed_tx;
        const txid = sendTxidOverride || canonicalTxidHex(submitted);
        return response({ success: true, transaction_id: txid, tx_hash: txid });
      }
      return response({}, false);
    });

    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<WalletProvider><Harness /></WalletProvider>);
    });
  });

  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    if (container) container.remove();
    vi.restoreAllMocks();
  });
  const approveAndSend = async (recipient, amount, password) => {
    const preview = await walletApi.previewWepo(recipient, amount);
    return walletApi.sendWepo(preview, password);
  };


  test('phrase restores offline, rotates atomically, unlocks offline, and signs a send', async () => {
    const expectedAddress = deriveWepoKeypair(PHRASE).address;

    await act(async () => {
      await walletApi.recoverWallet(PHRASE, PASSWORD, 'recovered-device');
    });
    expect(walletApi.wallet.address).toBe(expectedAddress);
    expect(global.fetch.mock.calls.some(([url]) => /\/api\/wallet\/(create|login)$/.test(url))).toBe(false);

    const encryptedPhrase = localStorage.getItem('wepo_secure_wepo_mnemonic');
    expect(encryptedPhrase).toBeTruthy();
    expect(encryptedPhrase).not.toContain(PHRASE);
    expect(encryptedPhrase).not.toContain(PASSWORD);
    const encryptedWallet = localStorage.getItem('wepo_secure_wallet_data');
    const realSetSecureItem = secureStorage.setSecureItem;
    const storageWrite = vi.spyOn(secureStorage, 'setSecureItem').mockImplementation(
      (key, value, password) => (
        key === 'wallet_data' ? false : realSetSecureItem(key, value, password)
      ),
    );
    await expect(
      walletApi.changePassword(PASSWORD, NEW_PASSWORD, NEW_PASSWORD),
    ).rejects.toThrow('Password was not changed');
    storageWrite.mockRestore();
    expect(localStorage.getItem('wepo_secure_wepo_mnemonic')).toBe(encryptedPhrase);
    expect(localStorage.getItem('wepo_secure_wallet_data')).toBe(encryptedWallet);
    expect(secureStorage.getSecureItem('wepo_mnemonic', PASSWORD)).toBe(PHRASE);

    await walletApi.changePassword(PASSWORD, NEW_PASSWORD, NEW_PASSWORD);
    const rotatedPhrase = localStorage.getItem('wepo_secure_wepo_mnemonic');
    expect(rotatedPhrase).not.toBe(encryptedPhrase);
    expect(secureStorage.getSecureItem('wepo_mnemonic', PASSWORD)).toBeNull();
    expect(secureStorage.getSecureItem('wepo_mnemonic', NEW_PASSWORD)).toBe(PHRASE);


    await act(async () => {
      await walletApi.logout();
    });
    expect(localStorage.getItem('wepo_secure_wepo_mnemonic')).toBe(rotatedPhrase);

    global.fetch.mockClear();
    await act(async () => {
      await walletApi.loginWallet('recovered-device', NEW_PASSWORD);
    });
    expect(walletApi.wallet.address).toBe(expectedAddress);
    expect(global.fetch.mock.calls.some(([url]) => url.endsWith('/api/wallet/login'))).toBe(false);

    const recipient = deriveWepoKeypair(
      'legal winner thank year wave sausage worth useful legal winner thank yellow',
    ).address;
    await act(async () => {
      await approveAndSend(recipient, '1.00000000', NEW_PASSWORD);
    });
    expect(buildRequest).toMatchObject({
      from_address: expectedAddress,
      to_address: recipient,
      amount: '1',
    });
    expect(submitted).toBeTruthy();
    expect(buildRequest).not.toHaveProperty('fee');
    expect(submitted.inputs[0].quantum_public_key).toBeTruthy();
    expect(submitted.inputs[0].quantum_signature).toBeTruthy();
    expect(verifyTransactionInput(submitted, 0, 'mainnet')).toBe(true);
  }, 120000);

  test('new wallet creation is local-first and rolls back a split-vault failure', async () => {
    let creationFailure;
    const realSetSecureItem = secureStorage.setSecureItem;
    const storageWrite = vi.spyOn(secureStorage, 'setSecureItem').mockImplementation(
      (key, value, password) => (
        key === 'wallet_data' ? false : realSetSecureItem(key, value, password)
      ),
    );
    await act(async () => {
      try {
        await walletApi.createWallet('new-device', PASSWORD, PASSWORD, PHRASE);
      } catch (error) {
        creationFailure = error;
      }
    });
    storageWrite.mockRestore();
    expect(creationFailure.message).toContain('Failed to create wallet');
    expect(localStorage.getItem('wepo_secure_wepo_mnemonic')).toBeNull();
    expect(localStorage.getItem('wepo_secure_wallet_data')).toBeNull();
    expect(localStorage.getItem('wepo_wallet_username')).toBeNull();

    await expect(
      walletApi.createWallet('new-device', PASSWORD, PASSWORD, 'not a recovery phrase'),
    ).rejects.toThrow('Invalid provided recovery phrase');
    expect(global.fetch).not.toHaveBeenCalled();

    let result;
    await act(async () => {
      result = await walletApi.createWallet('new-device', PASSWORD, PASSWORD, PHRASE);
    });
    expect(result.address).toBe(deriveWepoKeypair(PHRASE).address);
    expect(result.mnemonic).toBe(PHRASE);
    expect(global.fetch.mock.calls.some(([url]) => /\/api\/wallet\/(create|login)$/.test(url))).toBe(false);
    expect(secureStorage.getSecureItem('wepo_mnemonic', PASSWORD)).toBe(PHRASE);
  }, 60000);
  test('wallet unlock never sends a vault password to the network', async () => {
    await expect(
      walletApi.loginWallet('missing-device', PASSWORD),
    ).rejects.toThrow('No local wallet vault found');
    expect(global.fetch.mock.calls.some(([url]) => url.endsWith('/api/wallet/login'))).toBe(false);

    await act(async () => {
      await walletApi.recoverWallet(PHRASE, PASSWORD, 'recovered-device');
      await walletApi.logout();
    });
    global.fetch.mockClear();

    await expect(
      walletApi.loginWallet('recovered-device', 'Wrong Local Password!'),
    ).rejects.toThrow('Local wallet password is incorrect');
    expect(global.fetch.mock.calls.some(([url]) => url.endsWith('/api/wallet/login'))).toBe(false);
  }, 60000);

  test('malicious builder output and a mismatched sighash fail before submission', async () => {
    await act(async () => {
      await walletApi.recoverWallet(PHRASE, PASSWORD, 'recovered-device');
    });
    const recipient = deriveWepoKeypair(
      'legal winner thank year wave sausage worth useful legal winner thank yellow',
    ).address;

    buildMutator = (unsigned) => {
      unsigned.outputs[0].address = deriveWepoKeypair(
        'letter advice cage absurd amount doctor acoustic avoid letter advice cage above',
      ).address;
    };
    await expect(
      walletApi.previewWepo(recipient, '1'),
    ).rejects.toThrow('Refusing to sign');
    expect(submitted).toBeNull();

    buildMutator = null;
    buildSighashOverride = '00'.repeat(32);
    await expect(
      walletApi.previewWepo(recipient, '1'),
    ).rejects.toThrow('preview sighash does not match');
    expect(submitted).toBeNull();

    buildSighashOverride = null;
    buildNetworkOverride = 'test';
    await expect(
      walletApi.previewWepo(recipient, '1'),
    ).rejects.toThrow('wrong WEPO network');
    expect(submitted).toBeNull();
  }, 120000);
  test('a node txid mismatch is reported instead of false success', async () => {
    await act(async () => {
      await walletApi.recoverWallet(PHRASE, PASSWORD, 'recovered-device');
    });
    const recipient = deriveWepoKeypair(
      'legal winner thank year wave sausage worth useful legal winner thank yellow',
    ).address;
    sendTxidOverride = '22'.repeat(32);

    await expect(
      approveAndSend(recipient, '1', PASSWORD),
    ).rejects.toThrow('transaction ID that does not match');
    expect(submitted).toBeTruthy();
    expect(verifyTransactionInput(submitted, 0, 'mainnet')).toBe(true);

    await expect(walletApi.sendWepo(null, PASSWORD)).rejects.toThrow('approved fee preview');
  }, 120000);

});
