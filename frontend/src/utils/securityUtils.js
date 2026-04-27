/**
 * WEPO Frontend Security Utilities
 * Emergency security fixes for critical vulnerabilities
 */

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
  
  // Sanitize input first
  const cleanAddress = sanitizeInput(address);
  
  // Check basic format
  if (!cleanAddress.startsWith('wepo1')) {
    errors.push('Address must start with "wepo1"');
  }
  
  // Check length (wepo1 + 32 hex characters = 37 total)
  if (cleanAddress.length !== 37) {
    errors.push('Invalid address length (must be 37 characters)');
  }
  
  // Check hex pattern after wepo1
  const hexPart = cleanAddress.slice(5);
  if (!/^[a-f0-9]{32}$/i.test(hexPart)) {
    errors.push('Invalid address format (must contain only hexadecimal characters after wepo1)');
  }
  
  // Check for common attack patterns
  const attackPatterns = [
    /\.\./,  // Path traversal
    /[<>]/,  // HTML/XML injection
    /['";]/,  // SQL injection attempts
    /\${/,   // Template injection
    /eval|script|alert|confirm|prompt/i // Script injection
  ];
  
  attackPatterns.forEach(pattern => {
    if (pattern.test(address)) {
      errors.push('Address contains invalid characters');
    }
  });
  
  return {
    isValid: errors.length === 0,
    errors,
    sanitizedAddress: errors.length === 0 ? cleanAddress : null
  };
};

// Comprehensive amount validation
export const validateTransactionAmount = (amount, balance = 0) => {
  const errors = [];
  
  // Convert to string for validation
  const amountStr = typeof amount === 'number' ? amount.toString() : amount;
  
  if (!amountStr || amountStr.trim() === '') {
    errors.push('Amount is required');
    return { isValid: false, errors, sanitizedAmount: 0 };
  }
  
  // Sanitize input
  const cleanAmount = sanitizeInput(amountStr.trim());
  
  // Check for scientific notation attacks
  if (/[eE]/i.test(cleanAmount)) {
    errors.push('Scientific notation not allowed');
  }
  
  // Check for invalid characters
  if (!/^[0-9]+\.?[0-9]*$/.test(cleanAmount)) {
    errors.push('Amount must contain only numbers and decimal point');
  }
  
  // Parse as number
  const numAmount = parseFloat(cleanAmount);
  
  // Check for NaN
  if (isNaN(numAmount)) {
    errors.push('Amount must be a valid number');
    return { isValid: false, errors, sanitizedAmount: 0 };
  }
  
  // Check for negative amounts
  if (numAmount < 0) {
    errors.push('Amount cannot be negative');
  }
  
  // Check for zero amounts
  if (numAmount === 0) {
    errors.push('Amount must be greater than zero');
  }
  
  // Check for extremely large amounts (anti-overflow)
  const MAX_AMOUNT = 69000003; // WEPO total supply
  if (numAmount > MAX_AMOUNT) {
    errors.push(`Amount cannot exceed ${MAX_AMOUNT} WEPO (total supply)`);
  }
  
  // Check for decimal precision attacks (max 8 decimal places like Bitcoin)
  const decimalPart = cleanAmount.split('.')[1];
  if (decimalPart && decimalPart.length > 8) {
    errors.push('Amount cannot have more than 8 decimal places');
  }
  
  // Check minimum amount (prevent dust attacks)
  const MIN_AMOUNT = 0.00000001; // 1 satoshi equivalent
  if (numAmount > 0 && numAmount < MIN_AMOUNT) {
    errors.push(`Amount must be at least ${MIN_AMOUNT} WEPO`);
  }
  
  // Check sufficient balance
  if (numAmount > balance) {
    errors.push(`Insufficient balance. Available: ${balance} WEPO`);
  }
  
  // Check for transaction fee coverage
  const TX_FEE = 0.0001;
  if (numAmount + TX_FEE > balance) {
    errors.push(`Insufficient balance for amount + fee. Required: ${(numAmount + TX_FEE).toFixed(8)} WEPO`);
  }
  
  return {
    isValid: errors.length === 0,
    errors,
    sanitizedAmount: errors.length === 0 ? numAmount : 0,
    fee: TX_FEE,
    total: errors.length === 0 ? numAmount + TX_FEE : 0
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
export const validateSendForm = (formData, balance = 0) => {
  const addressValidation = validateWepoAddress(formData.toAddress);
  const amountValidation = validateTransactionAmount(formData.amount, balance);
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
export const secureStorage = {
  // Encrypt sensitive data before storing
  setSecureItem: (key, value, password) => {
    try {
      const CryptoJS = require('crypto-js');
      const encrypted = CryptoJS.AES.encrypt(JSON.stringify(value), password).toString();
      localStorage.setItem(`wepo_secure_${key}`, encrypted);
      return true;
    } catch (error) {
      console.error('Secure storage encryption failed:', error);
      return false;
    }
  },
  
  // Decrypt data when retrieving
  getSecureItem: (key, password) => {
    try {
      const CryptoJS = require('crypto-js');
      const encrypted = localStorage.getItem(`wepo_secure_${key}`);
      if (!encrypted) return null;
      
      const decrypted = CryptoJS.AES.decrypt(encrypted, password);
      return JSON.parse(decrypted.toString(CryptoJS.enc.Utf8));
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
    const CryptoJS = require('crypto-js');
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
      const CryptoJS = require('crypto-js');
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
