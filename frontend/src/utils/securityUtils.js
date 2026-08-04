/**
 * WEPO Frontend Security Utilities
 * Emergency security fixes for critical vulnerabilities
 */

import CryptoJS from 'crypto-js/core';
import 'crypto-js/aes';
import 'crypto-js/enc-base64';
import 'crypto-js/hmac-sha256';
import 'crypto-js/pbkdf2';
import 'crypto-js/sha256';
// Enhanced input sanitization
export const sanitizeInput = (input) => {
  if (typeof input !== 'string') return '';
  
  // Remove dangerous patterns
  const dangerous = [
    /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
    /javascript:/gi,
    /on\w+\s*=/gi,
    /<iframe/gi,
    /<object/gi,
    /<embed/gi,
    /eval\(/gi,
    /document\.cookie/gi,
    /window\.location/gi
  ];
  
  let sanitized = input;
  dangerous.forEach(pattern => {
    sanitized = sanitized.replace(pattern, '');
  });
  
  return sanitized.trim();
};

// Comprehensive WEPO address validation
export const validateWepoAddress = (address) => {
  const errors = [];

  if (!address || typeof address !== 'string') {
    errors.push('Address is required');
    return { isValid: false, errors };
  }

  // Addresses are identifiers, not free-form display text. Never delete a
  // malicious prefix and then validate the remainder as if it were submitted.
  const cleanAddress = address.trim();

  // Shipping spend authorization is ML-DSA only:
  // "wepo1q" + 39 lowercase hexadecimal characters.
  if (!/^wepo1q[a-f0-9]{39}$/.test(cleanAddress)) {
    errors.push('Invalid quantum address (expected wepo1q plus 39 lowercase hexadecimal characters)');
  }

  return {
    isValid: errors.length === 0,
    errors,
    sanitizedAddress: errors.length === 0 ? cleanAddress : null
  };
};

export const WEPO_ATOMIC_UNITS = 100000000n;
export const WEPO_MAX_SUPPLY_ATOMIC = 69000003n * WEPO_ATOMIC_UNITS;
export const WEPO_DEFAULT_FEE_ATOMIC = 10000n;

export const parseWepoAmountToAtomic = (value, { allowZero = false, field = 'Amount' } = {}) => {
  if (typeof value !== 'string') {
    throw new Error(`${field} must be entered as a decimal string`);
  }
  const clean = value.trim();
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?$/.test(clean)) {
    throw new Error(`${field} must be a plain decimal with at most 8 fractional digits`);
  }
  const [whole, fraction = ''] = clean.split('.');
  const atomic = (BigInt(whole) * WEPO_ATOMIC_UNITS)
    + BigInt((fraction + '00000000').slice(0, 8));
  if (!allowZero && atomic === 0n) {
    throw new Error(`${field} must be greater than zero`);
  }
  if (atomic > WEPO_MAX_SUPPLY_ATOMIC) {
    throw new Error(`${field} exceeds the WEPO supply cap`);
  }
  return atomic;
};

export const formatWepoAtomic = (atomic) => {
  const value = BigInt(atomic);
  const whole = value / WEPO_ATOMIC_UNITS;
  const fraction = (value % WEPO_ATOMIC_UNITS).toString().padStart(8, '0').replace(/0+$/, '');
  return fraction ? `${whole}.${fraction}` : whole.toString();
};

const balanceToAtomic = (balance) => {
  if (typeof balance === 'string') {
    return parseWepoAmountToAtomic(balance, { allowZero: true, field: 'Balance' });
  }
  if (typeof balance === 'number' && Number.isFinite(balance) && balance >= 0) {
    return parseWepoAmountToAtomic(balance.toFixed(8), { allowZero: true, field: 'Balance' });
  }
  throw new Error('Balance is unavailable');
};

const normalizeFeeAtomic = (feeAtomic) => {
  const fee = BigInt(feeAtomic);
  if (fee < 0n || fee > WEPO_MAX_SUPPLY_ATOMIC) {
    throw new Error('Network fee is outside the valid WEPO range');
  }
  return fee;
};

export const calculateMaxSendAmount = (balance, feeAtomic = WEPO_DEFAULT_FEE_ATOMIC) => {
  const balanceAtomic = balanceToAtomic(balance);
  const fee = normalizeFeeAtomic(feeAtomic);
  const spendable = balanceAtomic > fee ? balanceAtomic - fee
    : 0n;
  return formatWepoAtomic(spendable);
};

export const calculateTransactionTotal = (amount, feeAtomic = WEPO_DEFAULT_FEE_ATOMIC) => {
  const amountAtomic = parseWepoAmountToAtomic(amount, { field: 'Amount' });
  return formatWepoAtomic(amountAtomic + normalizeFeeAtomic(feeAtomic));
};

export const formatWepoBalance = (balance) => formatWepoAtomic(balanceToAtomic(balance));

// Comprehensive amount validation
export const validateTransactionAmount = (
  amount,
  balance = 0,
  feeAtomic = WEPO_DEFAULT_FEE_ATOMIC,
) => {
  const errors = [];
  let amountAtomic = 0n;
  let balanceAtomic = 0n;
  try {
    amountAtomic = parseWepoAmountToAtomic(amount, { field: 'Amount' });
  } catch (error) {
    errors.push(error.message);
  }
  try {
    balanceAtomic = balanceToAtomic(balance);
  } catch (error) {
    errors.push(error.message);
  }
  let fee = WEPO_DEFAULT_FEE_ATOMIC;
  try {
    fee = normalizeFeeAtomic(feeAtomic);
  } catch (error) {
    errors.push(error.message);
  }
  const totalAtomic = amountAtomic + fee;
  if (errors.length === 0 && totalAtomic > balanceAtomic) {
    errors.push(
      `Insufficient balance for amount + fee. Required: ${formatWepoAtomic(totalAtomic)} WEPO`,
    );
  }

  return {
    isValid: errors.length === 0,
    errors,
    sanitizedAmount: errors.length === 0 ? formatWepoAtomic(amountAtomic) : '',
    amountAtomic: errors.length === 0 ? amountAtomic.toString() : '',
    fee: formatWepoAtomic(fee),
    feeAtomic: fee.toString(),
    total: errors.length === 0 ? formatWepoAtomic(totalAtomic) : '',
    totalAtomic: errors.length === 0 ? totalAtomic.toString() : '',
  };
};

// Password validation for transactions
export const validateTransactionPassword = (password) => {
  const errors = [];
  
  if (!password || typeof password !== 'string') {
    errors.push('Password is required to authorize transaction');
    return { isValid: false, errors };
  }
  
  // Sanitize password input
  const cleanPassword = sanitizeInput(password);
  
  if (cleanPassword.length === 0) {
    errors.push('Password cannot be empty');
  }
  
  // Basic length check
  if (cleanPassword.length < 8) {
    errors.push('Password too short for security verification');
  }
  
  // Check for obvious attacks
  const attackPatterns = [
    /[<>]/,  // HTML injection
    /script|eval|alert/i, // Script injection
    /\${/,   // Template injection
  ];
  
  attackPatterns.forEach(pattern => {
    if (pattern.test(password)) {
      errors.push('Password contains invalid characters');
    }
  });
  
  return {
    isValid: errors.length === 0,
    errors,
    sanitizedPassword: errors.length === 0 ? cleanPassword : null
  };
};

// Secure form validation
export const validateSendForm = (formData, balance = 0, feeAtomic = WEPO_DEFAULT_FEE_ATOMIC) => {
  const addressValidation = validateWepoAddress(formData.toAddress);
  const amountValidation = validateTransactionAmount(formData.amount, balance, feeAtomic);
  const passwordValidation = validateTransactionPassword(formData.password);
  
  const allErrors = [
    ...addressValidation.errors,
    ...amountValidation.errors,
    ...passwordValidation.errors
  ];
  
  return {
    isValid: allErrors.length === 0,
    errors: allErrors,
    validatedData: allErrors.length === 0 ? {
      toAddress: addressValidation.sanitizedAddress,
      amount: amountValidation.sanitizedAmount,
      password: passwordValidation.sanitizedPassword,
      fee: amountValidation.fee,
      total: amountValidation.total
    } : null
  };
};

// Secure localStorage wrapper (encrypted storage)
const SECURE_STORAGE_VERSION = 2;
const SECURE_STORAGE_KDF_ITERATIONS = 310000;

const SECURE_STORAGE_MAX_SERIALIZED_BYTES = 2 * 1024 * 1024;
const STORAGE_HEX_16_BYTES = /^[0-9a-f]{32}$/;
const STORAGE_HEX_32_BYTES = /^[0-9a-f]{64}$/;
const STORAGE_BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const timingSafeHexEqual = (a, b) => {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
};

const deriveStorageKeys = (CryptoJS, password, saltHex, iterations = SECURE_STORAGE_KDF_ITERATIONS) => {
  const material = CryptoJS.PBKDF2(password, CryptoJS.enc.Hex.parse(saltHex), {
    keySize: 512 / 32,
    iterations,
    hasher: CryptoJS.algo.SHA256,
  });
  return {
    encKey: CryptoJS.lib.WordArray.create(material.words.slice(0, 8), 32),
    macKey: CryptoJS.lib.WordArray.create(material.words.slice(8, 16), 32),
  };
};

const encodeStorageMacPayload = (payload) => [
  payload.version,
  payload.kdf,
  payload.iterations,
  payload.salt,
  payload.iv,
  payload.ciphertext,
].join('|');

export const secureStorage = {
  // Encrypt sensitive data before storing. Version 2 uses explicit PBKDF2 plus
  // encrypt-then-MAC so wrong passwords or tampering fail before JSON parsing.
  setSecureItem: (key, value, password) => {
    try {
      const salt = CryptoJS.lib.WordArray.random(16).toString(CryptoJS.enc.Hex);
      const iv = CryptoJS.lib.WordArray.random(16);
      const { encKey, macKey } = deriveStorageKeys(CryptoJS, password, salt);
      const encrypted = CryptoJS.AES.encrypt(JSON.stringify(value), encKey, {
        iv,
        mode: CryptoJS.mode.CBC,
        padding: CryptoJS.pad.Pkcs7,
      });
      const payload = {
        version: SECURE_STORAGE_VERSION,
        kdf: 'PBKDF2-HMAC-SHA256',
        iterations: SECURE_STORAGE_KDF_ITERATIONS,
        salt,
        iv: iv.toString(CryptoJS.enc.Hex),
        ciphertext: encrypted.ciphertext.toString(CryptoJS.enc.Base64),
      };
      payload.mac = CryptoJS.HmacSHA256(encodeStorageMacPayload(payload), macKey).toString(CryptoJS.enc.Hex);
      localStorage.setItem(`wepo_secure_${key}`, JSON.stringify(payload));
      return true;
    } catch (error) {
      console.error('Secure storage encryption failed:', error);
      return false;
    }
  },
  
  // Decrypt data when retrieving. Legacy passphrase-format blobs are accepted once
  // and immediately migrated to the authenticated versioned format.
  getSecureItem: (key, password) => {
    try {
      const stored = localStorage.getItem(`wepo_secure_${key}`);
      if (!stored) return null;
      if (stored.length > SECURE_STORAGE_MAX_SERIALIZED_BYTES) return null;

      let payload = null;
      try { payload = JSON.parse(stored); } catch (e) { payload = null; }

      if (payload?.version === SECURE_STORAGE_VERSION) {
        if (
          payload.kdf !== 'PBKDF2-HMAC-SHA256' ||
          !STORAGE_HEX_16_BYTES.test(payload.salt) ||
          !STORAGE_HEX_16_BYTES.test(payload.iv) ||
          typeof payload.ciphertext !== 'string' ||
          payload.ciphertext.length === 0 ||
          payload.ciphertext.length % 4 !== 0 ||
          !STORAGE_BASE64.test(payload.ciphertext) ||
          !STORAGE_HEX_32_BYTES.test(payload.mac)
        ) {
          return null;
        }
        const iterations = Number(payload.iterations);
        // Version 2 has one fixed, audited work factor. Reject attacker-chosen
        // iteration counts before PBKDF2 to prevent a localStorage CPU DoS.
        if (iterations !== SECURE_STORAGE_KDF_ITERATIONS) return null;

        const { encKey, macKey } = deriveStorageKeys(CryptoJS, password, payload.salt, iterations);
        const expectedMac = CryptoJS.HmacSHA256(encodeStorageMacPayload(payload), macKey).toString(CryptoJS.enc.Hex);
        if (!timingSafeHexEqual(expectedMac, payload.mac)) return null;

        const cipherParams = CryptoJS.lib.CipherParams.create({
          ciphertext: CryptoJS.enc.Base64.parse(payload.ciphertext),
        });
        const decrypted = CryptoJS.AES.decrypt(cipherParams, encKey, {
          iv: CryptoJS.enc.Hex.parse(payload.iv),
          mode: CryptoJS.mode.CBC,
          padding: CryptoJS.pad.Pkcs7,
        });
        const plaintext = decrypted.toString(CryptoJS.enc.Utf8);
        return plaintext ? JSON.parse(plaintext) : null;
      }

      const legacy = CryptoJS.AES.decrypt(stored, password);
      const legacyText = legacy.toString(CryptoJS.enc.Utf8);
      if (!legacyText) return null;
      const parsed = JSON.parse(legacyText);
      secureStorage.setSecureItem(key, parsed, password);
      return parsed;
    } catch (error) {
      console.error('Secure storage decryption failed:', error);
      return null;
    }
  },
  
  // Remove secure item
  removeSecureItem: (key) => {
    localStorage.removeItem(`wepo_secure_${key}`);
  },
  
  // Check if secure item exists
  hasSecureItem: (key) => {
    return localStorage.getItem(`wepo_secure_${key}`) !== null;
  }
};

// Session management utilities
export const sessionManager = {
  // Create secure session token
  createSecureSession: (userAddress, password) => {
    const timestamp = Date.now();
    const sessionData = {
      address: userAddress,
      timestamp,
      expires: timestamp + (30 * 60 * 1000) // 30 minutes
    };
    
    const sessionToken = CryptoJS.AES.encrypt(JSON.stringify(sessionData), password).toString();
    sessionStorage.setItem('wepo_secure_session', sessionToken);
    
    return sessionToken;
  },
  
  // Validate and get session
  getSecureSession: (password) => {
    try {
      const sessionToken = sessionStorage.getItem('wepo_secure_session');
      if (!sessionToken) return null;
      
      const decrypted = CryptoJS.AES.decrypt(sessionToken, password);
      const sessionData = JSON.parse(decrypted.toString(CryptoJS.enc.Utf8));
      
      // Check expiration
      if (Date.now() > sessionData.expires) {
        sessionStorage.removeItem('wepo_secure_session');
        return null;
      }
      
      return sessionData;
    } catch (error) {
      console.error('Session validation failed:', error);
      sessionStorage.removeItem('wepo_secure_session');
      return null;
    }
  },
  
  // Clear session
  clearSecureSession: () => {
    sessionStorage.removeItem('wepo_secure_session');
    sessionStorage.removeItem('wepo_session_active');
  },

  setAuthSession: ({ token, expiresAt, walletAddress, username }) => {
    if (!token || !expiresAt) {
      return false;
    }

    try {
      sessionStorage.setItem('wepo_auth_session', JSON.stringify({
        token,
        expiresAt,
        walletAddress,
        username
      }));
      sessionStorage.setItem('wepo_session_active', 'true');
      return true;
    } catch (error) {
      console.error('Auth session set failed:', error);
      return false;
    }
  },

  getAuthSession: () => {
    try {
      const raw = sessionStorage.getItem('wepo_auth_session');
      if (!raw) return null;

      const session = JSON.parse(raw);
      const expiresAtMs = Number(session?.expiresAt) * 1000;
      if (!session?.token || !Number.isFinite(expiresAtMs)) {
        sessionManager.clearAuthSession();
        return null;
      }

      if (Date.now() >= expiresAtMs) {
        sessionManager.clearAuthSession();
        return null;
      }

      return session;
    } catch (error) {
      console.error('Auth session get failed:', error);
      sessionManager.clearAuthSession();
      return null;
    }
  },

  clearAuthSession: () => {
    sessionStorage.removeItem('wepo_auth_session');
    sessionStorage.removeItem('wepo_session_active');
  },
  
  // Check if session is valid
  isSessionValid: (password) => {
    const session = sessionManager.getSecureSession(password);
    return session !== null;
  },
  
  // Basic session storage methods
  get: (key) => {
    try {
      const value = sessionStorage.getItem(key);
      return value ? JSON.parse(value) : null;
    } catch (error) {
      console.error('Session get failed:', error);
      return null;
    }
  },
  
  set: (key, value) => {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      console.error('Session set failed:', error);
      return false;
    }
  },
  
  remove: (key) => {
    sessionStorage.removeItem(key);
  }
};

// Log sanitization (remove sensitive data from console logs)
export const secureLog = {
  info: (message, data = null) => {
    // Only log in development, and sanitize sensitive data
    if (process.env.NODE_ENV === 'development') {
      if (data) {
        const sanitizedData = { ...data };
        // Remove sensitive fields
        delete sanitizedData.password;
        delete sanitizedData.privateKey;
        delete sanitizedData.mnemonic;
        delete sanitizedData.seed;
        console.log(`[WEPO] ${message}`, sanitizedData);
      } else {
        console.log(`[WEPO] ${message}`);
      }
    }
  },
  
  error: (message, error = null) => {
    // Always log errors but sanitize sensitive data
    if (error) {
      const sanitizedError = {
        message: error.message,
        stack: error.stack
      };
      console.error(`[WEPO ERROR] ${message}`, sanitizedError);
    } else {
      console.error(`[WEPO ERROR] ${message}`);
    }
  },
  
  warn: (message) => {
    console.warn(`[WEPO WARNING] ${message}`);
  }
};

export default {
  sanitizeInput,
  validateWepoAddress,
  validateTransactionAmount,
  validateTransactionPassword,
  validateSendForm,
  secureStorage,
  sessionManager,
  secureLog
};
