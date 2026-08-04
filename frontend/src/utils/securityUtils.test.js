import CryptoJS from 'crypto-js';
import {
  calculateMaxSendAmount,
  calculateTransactionTotal,
  formatWepoAtomic,
  parseWepoAmountToAtomic,
  secureStorage,
  validateTransactionAmount,
  validateWepoAddress,
  WEPO_DEFAULT_FEE_ATOMIC,
} from './securityUtils';

const QUANTUM_ADDRESS = `wepo1q${'a'.repeat(39)}`;

describe('canonical WEPO transaction values', () => {
  test('accepts only the shipping lowercase quantum address format', () => {
    expect(validateWepoAddress(QUANTUM_ADDRESS).isValid).toBe(true);
    expect(validateWepoAddress(`wepo1${'a'.repeat(32)}`).isValid).toBe(false);
    expect(validateWepoAddress(QUANTUM_ADDRESS.toUpperCase()).isValid).toBe(false);
    expect(validateWepoAddress(`wepo1q${'a'.repeat(38)}`).isValid).toBe(false);
    expect(validateWepoAddress(`wepo1q${'a'.repeat(40)}`).isValid).toBe(false);
    expect(validateWepoAddress(`javascript:${QUANTUM_ADDRESS}`).isValid).toBe(false);
    expect(validateWepoAddress(`<script></script>${QUANTUM_ADDRESS}`).isValid).toBe(false);
  });

  test('parses and formats atomic values without binary floating-point', () => {
    expect(parseWepoAmountToAtomic('0.00000001')).toBe(1n);
    expect(parseWepoAmountToAtomic('1.23456789')).toBe(123456789n);
    expect(formatWepoAtomic(123456789n)).toBe('1.23456789');
    expect(formatWepoAtomic(100000000n)).toBe('1');

    for (const invalid of ['1e-8', '0.000000001', '-1', '+1', '01', 'NaN', 'Infinity']) {
      expect(() => parseWepoAmountToAtomic(invalid)).toThrow();
    }
    expect(() => parseWepoAmountToAtomic(0.1)).toThrow(/decimal string/);
    expect(() => parseWepoAmountToAtomic('0')).toThrow(/greater than zero/);
    expect(() => parseWepoAmountToAtomic('69000003.00000001')).toThrow(/supply cap/);
  });

  test('computes fees, totals, and maximum spends exactly', () => {
    const validation = validateTransactionAmount('0.1', '0.3001');
    expect(validation).toMatchObject({
      isValid: true,
      sanitizedAmount: '0.1',
      amountAtomic: '10000000',
      fee: '0.0001',
      feeAtomic: WEPO_DEFAULT_FEE_ATOMIC.toString(),
      total: '0.1001',
      totalAtomic: '10010000',
    });
    expect(calculateTransactionTotal('0.1')).toBe('0.1001');
    expect(calculateMaxSendAmount('0.3001')).toBe('0.3');
    expect(calculateMaxSendAmount('0.0001')).toBe('0');
    expect(validateTransactionAmount('0.30000001', '0.3001').isValid).toBe(false);
    const quoted = validateTransactionAmount('0.1', '0.3002', 20000n);
    expect(quoted).toMatchObject({
      isValid: true,
      fee: '0.0002',
      feeAtomic: '20000',
      total: '0.1002',
      totalAtomic: '10020000',
    });
    expect(calculateMaxSendAmount('0.3002', 20000n)).toBe('0.3');
  });
});
describe('authenticated local wallet vault', () => {
  const password = 'Correct Horse Battery 42!';
  const validShapeEnvelope = () => ({
    version: 2,
    kdf: 'PBKDF2-HMAC-SHA256',
    iterations: 310000,
    salt: '0'.repeat(32),
    iv: '1'.repeat(32),
    ciphertext: 'AA==',
    mac: '2'.repeat(64),
  });

  beforeEach(() => {
    localStorage.clear();
  });

  test('round-trips encrypted data and rejects a wrong password or valid-shape ciphertext tamper', () => {
    expect(secureStorage.setSecureItem('test', { secret: 'value' }, password)).toBe(true);
    const stored = localStorage.getItem('wepo_secure_test');
    expect(stored).not.toContain('value');
    expect(stored).not.toContain(password);
    expect(secureStorage.getSecureItem('test', password)).toEqual({ secret: 'value' });
    expect(secureStorage.getSecureItem('test', 'wrong password')).toBeNull();

    const payload = JSON.parse(stored);
    payload.ciphertext = `${payload.ciphertext[0] === 'A' ? 'B' : 'A'}${payload.ciphertext.slice(1)}`;
    localStorage.setItem('wepo_secure_test', JSON.stringify(payload));
    expect(secureStorage.getSecureItem('test', password)).toBeNull();
  }, 60000);

  test('rejects attacker-selected KDF work factors before invoking PBKDF2', () => {
    const original = validShapeEnvelope();
    const pbkdf2 = vi.spyOn(CryptoJS, 'PBKDF2');
    pbkdf2.mockClear();

    for (const iterations of [309999, 310001, 2147483647]) {
      localStorage.setItem('wepo_secure_test', JSON.stringify({ ...original, iterations }));
      expect(secureStorage.getSecureItem('test', password)).toBeNull();
    }
    expect(pbkdf2).not.toHaveBeenCalled();
    pbkdf2.mockRestore();
  });

  test.each([
    ['salt', '0'.repeat(30)],
    ['iv', 'z'.repeat(32)],
    ['mac', '0'.repeat(62)],
    ['ciphertext', 'not base64!'],
  ])('rejects malformed %s before key derivation', (field, value) => {
    const payload = validShapeEnvelope();
    const pbkdf2 = vi.spyOn(CryptoJS, 'PBKDF2');
    pbkdf2.mockClear();

    payload[field] = value;
    localStorage.setItem('wepo_secure_test', JSON.stringify(payload));
    expect(secureStorage.getSecureItem('test', password)).toBeNull();
    expect(pbkdf2).not.toHaveBeenCalled();
    pbkdf2.mockRestore();
  });

  test('rejects oversized serialized vault data before key derivation', () => {
    const pbkdf2 = vi.spyOn(CryptoJS, 'PBKDF2');
    localStorage.setItem('wepo_secure_test', 'x'.repeat((2 * 1024 * 1024) + 1));
    expect(secureStorage.getSecureItem('test', password)).toBeNull();
    expect(pbkdf2).not.toHaveBeenCalled();
    pbkdf2.mockRestore();
  });
});
