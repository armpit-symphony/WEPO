const express = require('express');
const helmet = require('helmet');
const compression = require('compression');
const path = require('path');

const app = express();
const parseCsvEnv = (value, defaultValues) => {
  if (!value || !value.trim()) {
    return [...defaultValues];
  }
  return value.split(',').map((entry) => entry.trim()).filter(Boolean);
};

const DEFAULT_CONNECT_SRC = [
  "'self'",
  "https:",
  "wss:",
  "http://localhost:8011",
  "http://127.0.0.1:8011",
  "http://localhost:8122",
  "http://127.0.0.1:8122"
];
const CSP_CONNECT_SRC = parseCsvEnv(process.env.WEPO_FRONTEND_CONNECT_SRC, DEFAULT_CONNECT_SRC);

// Enable compression for better performance
app.use(compression());

// Comprehensive security headers using Helmet
app.use(helmet({
  // Content Security Policy
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: [
        "'self'", 
        "'unsafe-inline'", 
        "https://us.i.posthog.com",
        "https://app.emergent.sh",
        "https://d33sy5i8bnduwe.cloudfront.net"
      ],
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: [
        "'self'", 
        "data:", 
        "https:",
        "https://avatars.githubusercontent.com"
      ],
      connectSrc: [
        ...CSP_CONNECT_SRC
      ],
      fontSrc: ["'self'", "https:"],
      objectSrc: ["'none'"],
      mediaSrc: ["'self'"],
      frameSrc: ["'none'"],
      childSrc: ["'none'"],
      workerSrc: ["'self'"],
      manifestSrc: ["'self'"]
    },
  },
  
  // Cross-Origin Embedder Policy
  crossOriginEmbedderPolicy: false, // Allow for external resources
  
  // DNS Prefetch Control
  dnsPrefetchControl: { allow: false },
  
  // Frame Options
  frameguard: { action: 'deny' },
  
  // Hide X-Powered-By
  hidePoweredBy: true,
  
  // HTTP Strict Transport Security
  hsts: {
    maxAge: 31536000, // 1 year
    includeSubDomains: true,
    preload: true
  },
  
  // IE No Open
  ieNoOpen: true,
  
  // Don't Sniff Mimetype
  noSniff: true,
  
  // Origin Agent Cluster
  originAgentCluster: true,
  
  // Permitted Cross-Domain Policies
  permittedCrossDomainPolicies: false,
  
  // Referrer Policy
  referrerPolicy: { 
    policy: "strict-origin-when-cross-origin" 
  },
  
  // X-XSS-Protection
  xssFilter: true
}));

// Additional custom security headers
app.use((req, res, next) => {
  // Security headers for WEPO cryptocurrency application
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Permissions-Policy', 'geolocation=(), microphone=(), camera=()');
  res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains; preload');
  
  // WEPO-specific security headers
  res.setHeader('X-WEPO-Security', 'enabled');
  res.setHeader('X-Crypto-Wallet', 'secure');
  
  next();
});

// Rate limiting for security
const rateLimit = {};
const RATE_LIMIT_WINDOW = 60000; // 1 minute
const RATE_LIMIT_MAX_REQUESTS = 100;

app.use((req, res, next) => {
  const clientIp = req.ip || req.connection.remoteAddress;
  const now = Date.now();
  
  if (!rateLimit[clientIp]) {
    rateLimit[clientIp] = { count: 1, resetTime: now + RATE_LIMIT_WINDOW };
  } else if (now > rateLimit[clientIp].resetTime) {
    rateLimit[clientIp] = { count: 1, resetTime: now + RATE_LIMIT_WINDOW };
  } else {
    rateLimit[clientIp].count++;
  }
  
  if (rateLimit[clientIp].count > RATE_LIMIT_MAX_REQUESTS) {
    return res.status(429).json({
      error: 'Too many requests',
      message: 'Rate limit exceeded. Please try again later.',
      retryAfter: Math.ceil((rateLimit[clientIp].resetTime - now) / 1000)
    });
  }
  
  // Add rate limit headers
  res.setHeader('X-RateLimit-Limit', RATE_LIMIT_MAX_REQUESTS);
  res.setHeader('X-RateLimit-Remaining', Math.max(0, RATE_LIMIT_MAX_REQUESTS - rateLimit[clientIp].count));
  res.setHeader('X-RateLimit-Reset', Math.ceil(rateLimit[clientIp].resetTime / 1000));
  
  next();
});

// Serve static files from the React build directory
app.use(express.static(path.join(__dirname, 'build'), {
  // Security settings for static files
  dotfiles: 'deny',
  etag: true,
  extensions: ['html', 'js', 'css', 'png', 'jpg', 'jpeg', 'gif', 'ico', 'svg'],
  index: false,
  maxAge: '1d',
  redirect: false,
  setHeaders: (res, path, stat) => {
    // Additional security headers for static files
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Cache-Control', 'public, max-age=86400'); // 1 day cache
  }
}));

// Security middleware for API routes
app.use('/api/*', (req, res, next) => {
  // Enhanced security for API routes
  res.setHeader('X-API-Security', 'enhanced');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  next();
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    security: 'enabled',
    headers: 'comprehensive'
  });
});

// Security test endpoint
app.get('/security-test', (req, res) => {
  res.json({
    message: 'WEPO Frontend Security Active',
    headers: {
      'content-security-policy': res.getHeader('content-security-policy') ? 'present' : 'missing',
      'x-frame-options': res.getHeader('x-frame-options') ? 'present' : 'missing',
      'x-xss-protection': res.getHeader('x-xss-protection') ? 'present' : 'missing',
      'x-content-type-options': res.getHeader('x-content-type-options') ? 'present' : 'missing',
      'strict-transport-security': res.getHeader('strict-transport-security') ? 'present' : 'missing'
    },
    security_score: 'enhanced',
    wepo_security: 'active'
  });
});

// Catch all handler: send back React's index.html file for SPA routing
app.get('*', (req, res) => {
  // Avoid issues with path-to-regexp by being more specific
  if (req.path.startsWith('/static/') || req.path.startsWith('/api/')) {
    return res.status(404).json({ error: 'Not found' });
  }
  
  res.sendFile(path.join(__dirname, 'build', 'index.html'), {
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Cache-Control': 'no-cache, no-store, must-revalidate'
    }
  });
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Server error:', err);
  
  // Don't expose error details in production
  const isDevelopment = process.env.NODE_ENV === 'development';
  
  res.status(500).json({
    error: 'Internal server error',
    message: isDevelopment ? err.message : 'Something went wrong',
    timestamp: new Date().toISOString()
  });
});

const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || '0.0.0.0';

app.listen(PORT, HOST, () => {
  console.log(`🔒 WEPO Secure Frontend Server running on ${HOST}:${PORT}`);
  console.log(`🛡️  Security headers: ENABLED`);
  console.log(`🚀 Environment: ${process.env.NODE_ENV || 'development'}`);
  console.log(`⚡ Features: Helmet, Compression, Rate Limiting`);
});
