"""
WEPO Backend Security Utilities
Enhanced security implementation for comprehensive audit requirements
"""

import os
import bcrypt
import secrets
import hashlib
import re
import time
import logging
from typing import Dict, Any
from fastapi import HTTPException, Request
import redis
import json

# Configure logging
logger = logging.getLogger(__name__)

# Only honor client-supplied forwarding headers (X-Real-IP / X-Forwarded-For)
# for rate-limit identity when explicitly running behind a trusted reverse
# proxy. Otherwise these headers are attacker-controllable and let a single
# host rotate identities to bypass rate limiting. Set WEPO_TRUST_PROXY_HEADERS=1
# in deployments where a proxy (e.g. nginx with `proxy_set_header X-Real-IP
# $remote_addr`) overwrites these headers with the true peer address.
TRUST_PROXY_HEADERS = os.environ.get("WEPO_TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes", "on")

# Redis for rate limiting and session storage
redis_client = None

def init_redis(redis_url: str = "redis://localhost:6379"):
    """Initialize Redis connection for rate limiting"""
    global redis_client
    try:
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connection established for security features")
        return True
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
        redis_client = None  # Set to None so we use in-memory fallback
        return False

# In-memory fallback for rate limiting when Redis is not available
rate_limit_storage = {}
failed_attempts_storage = {}
auth_session_storage = {}

class SecurityManager:
    """Centralized security management for WEPO backend"""
    
    # Security configuration
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = 300  # 5 minutes in seconds
    RATE_LIMIT_WINDOW = 60  # 1 minute
    SESSION_DURATION = 30 * 60  # 30 minutes in seconds
    
    # Different rate limits for different endpoints
    RATE_LIMIT_CONFIG = {
        "wallet_create": 3,      # 3 per minute
        "wallet_login": 5,       # 5 per minute
        "transaction_send": 10,  # 10 per minute
        # Messaging is free/interactive: opening the tab publishes keys and normal
        # chat activity issues bursts of sends/fetches, so the default of 10/min
        # trips within seconds (429). Give messaging its own generous buckets.
        "messaging_keys": 60,    # key publish/lookup
        "messaging_send": 60,    # send encrypted envelope
        "messaging_fetch": 120,  # inbox fetch/ack polling
        "global_api": 60,        # General API traffic
        "default": 10           # Default rate limit
    }
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using bcrypt with secure salt"""
        salt = bcrypt.gensalt(rounds=12)  # High cost for security
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Verify password against hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False
    
    @staticmethod
    def validate_password_strength(password: str) -> Dict[str, Any]:
        """Validate password strength for wallet security"""
        issues = []
        
        if len(password) < 12:
            issues.append("Password must be at least 12 characters long")
        
        if not re.search(r'[A-Z]', password):
            issues.append("Password must contain at least one uppercase letter")
        
        if not re.search(r'[a-z]', password):
            issues.append("Password must contain at least one lowercase letter")
        
        if not re.search(r'\d', password):
            issues.append("Password must contain at least one number")
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            issues.append("Password must contain at least one special character")
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "strength_score": max(0, 100 - len(issues) * 20)
        }
    
    @staticmethod
    def sanitize_input(input_value: str) -> str:
        """Sanitize user input to prevent XSS and injection attacks"""
        if not isinstance(input_value, str):
            return str(input_value)
        
        # Remove potential XSS patterns
        dangerous_patterns = [
            r'<script.*?>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',
            r'<iframe',
            r'<object',
            r'<embed',
            r'eval\(',
            r'document\.cookie',
            r'window\.location'
        ]
        
        sanitized = input_value
        for pattern in dangerous_patterns:
            sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
        
        # Remove potential path traversal
        sanitized = sanitized.replace('../', '').replace('..\\', '')
        
        return sanitized.strip()
    
    @staticmethod
    def validate_wepo_address(address: str) -> bool:
        """Validate WEPO address format"""
        if not address or not isinstance(address, str):
            return False
        
        # WEPO addresses should start with 'wepo1' followed by 32 hex characters
        pattern = r'^wepo1[a-f0-9]{32}$'
        return bool(re.match(pattern, address.lower()))
    
    @staticmethod
    def validate_transaction_amount(amount: float) -> Dict[str, Any]:
        """Validate transaction amount"""
        issues = []
        
        if not isinstance(amount, (int, float)):
            issues.append("Amount must be a number")
        elif amount <= 0:
            issues.append("Amount must be greater than 0")
        elif amount > 1000000:  # Max transaction limit
            issues.append("Amount exceeds maximum transaction limit (1,000,000 WEPO)")
        elif str(amount).count('.') > 1:
            issues.append("Invalid amount format")
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "sanitized_amount": max(0, float(amount)) if not issues else 0
        }
    
    @staticmethod
    def get_client_identifier(request: Request) -> str:
        """Get client identifier for rate limiting.

        Uses the real socket peer address by default. Client-supplied
        forwarding headers are only trusted when WEPO_TRUST_PROXY_HEADERS is set
        (i.e. behind a proxy that overwrites them), otherwise an attacker could
        rotate those headers to get a fresh rate-limit bucket per request.
        """
        peer_ip = request.client.host if request.client else "unknown"

        if TRUST_PROXY_HEADERS:
            forwarded = (
                request.headers.get("X-Real-IP")
                or request.headers.get("X-Forwarded-For", "").split(",")[0]
                or peer_ip
            )
            return (forwarded or peer_ip or "unknown").strip()

        return peer_ip.strip()
    
    @staticmethod
    def is_rate_limited(client_id: str, endpoint: str) -> bool:
        """Check if client is rate limited"""
        current_time = time.time()
        key = f"rate_limit:{client_id}:{endpoint}"
        
        # Get endpoint-specific rate limit
        rate_limit = SecurityManager.RATE_LIMIT_CONFIG.get(endpoint, SecurityManager.RATE_LIMIT_CONFIG["default"])
        
        try:
            if redis_client:
                # Use Redis for distributed rate limiting
                pipe = redis_client.pipeline()
                pipe.incr(key)
                pipe.expire(key, SecurityManager.RATE_LIMIT_WINDOW)
                results = pipe.execute()
                
                request_count = results[0]
                return request_count > rate_limit
            else:
                # Fallback to in-memory storage
                if key not in rate_limit_storage:
                    rate_limit_storage[key] = []
                
                # Clean old entries
                rate_limit_storage[key] = [
                    timestamp for timestamp in rate_limit_storage[key]
                    if current_time - timestamp < SecurityManager.RATE_LIMIT_WINDOW
                ]
                
                # Check rate limit
                if len(rate_limit_storage[key]) >= rate_limit:
                    return True
                
                # Add current request
                rate_limit_storage[key].append(current_time)
                return False
        
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            return False  # Fail open for availability

    @staticmethod
    def get_rate_limit_reset_seconds(client_id: str, endpoint: str) -> int:
        """Return seconds until the current rate-limit window resets"""
        current_time = time.time()
        key = f"rate_limit:{client_id}:{endpoint}"

        try:
            if redis_client:
                ttl = redis_client.ttl(key)
                return max(0, int(ttl)) if ttl and ttl > 0 else 0

            timestamps = rate_limit_storage.get(key, [])
            if not timestamps:
                return 0

            valid_timestamps = [
                timestamp for timestamp in timestamps
                if current_time - timestamp < SecurityManager.RATE_LIMIT_WINDOW
            ]
            rate_limit_storage[key] = valid_timestamps

            if not valid_timestamps:
                return 0

            oldest_timestamp = min(valid_timestamps)
            remaining = SecurityManager.RATE_LIMIT_WINDOW - (current_time - oldest_timestamp)
            return max(0, int(remaining))
        except Exception as e:
            logger.error(f"Rate limit reset lookup error: {e}")
            return 0
    
    @staticmethod
    def record_failed_login(username: str) -> Dict[str, Any]:
        """Record failed login attempt and check for lockout"""
        current_time = time.time()
        key = f"failed_login:{username}"

        try:
            if redis_client:
                # Use Redis for persistent storage
                attempts_data = redis_client.get(key)
                if attempts_data:
                    attempts_info = json.loads(attempts_data)
                else:
                    attempts_info = {"count": 0, "first_attempt": current_time}
                
                attempts_info["count"] += 1
                attempts_info["last_attempt"] = current_time
                
                # Store for lockout duration
                redis_client.setex(key, SecurityManager.LOCKOUT_DURATION, json.dumps(attempts_info))
                    
            else:
                # Fallback to in-memory storage
                if username not in failed_attempts_storage:
                    failed_attempts_storage[username] = {"count": 0, "first_attempt": current_time}
                
                failed_attempts_storage[username]["count"] += 1
                failed_attempts_storage[username]["last_attempt"] = current_time
                attempts_info = failed_attempts_storage[username]
            
            is_locked = attempts_info["count"] >= SecurityManager.MAX_LOGIN_ATTEMPTS
            time_remaining = SecurityManager.LOCKOUT_DURATION  # Default to full duration
            
            if is_locked:
                # For a fresh lockout, give full duration
                time_remaining = SecurityManager.LOCKOUT_DURATION
            
            result = {
                "is_locked": is_locked,
                "attempts": attempts_info["count"],
                "time_remaining": int(time_remaining),
                "max_attempts": SecurityManager.MAX_LOGIN_ATTEMPTS
            }
            return result
        
        except Exception as e:
            logger.error(f"Failed login recording error: {e}")
            return {"is_locked": False, "attempts": 1, "time_remaining": 0, "max_attempts": SecurityManager.MAX_LOGIN_ATTEMPTS}
    
    @staticmethod
    def clear_failed_login(username: str) -> None:
        """Clear failed login attempts after successful login"""
        try:
            key = f"failed_login:{username}"
            if redis_client:
                redis_client.delete(key)
            elif username in failed_attempts_storage:
                del failed_attempts_storage[username]
        except Exception as e:
            logger.error(f"Failed to clear login attempts: {e}")

    @staticmethod
    def create_auth_session(username: str, address: str, client_id: str) -> Dict[str, Any]:
        """Create a short-lived backend auth session for wallet actions."""
        issued_at = int(time.time())
        expires_at = issued_at + SecurityManager.SESSION_DURATION
        token = SecurityManager.generate_secure_token()
        session_data = {
            "username": username,
            "address": address,
            "client_id": client_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        key = f"auth_session:{token}"

        try:
            if redis_client:
                redis_client.setex(key, SecurityManager.SESSION_DURATION, json.dumps(session_data))
            else:
                auth_session_storage[key] = session_data
        except Exception as e:
            logger.error(f"Auth session creation error: {e}")
            raise

        return {
            "token": token,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "duration_seconds": SecurityManager.SESSION_DURATION,
        }

    @staticmethod
    def get_auth_session(token: str) -> Dict[str, Any] | None:
        """Load and validate a backend auth session."""
        if not token:
            return None

        key = f"auth_session:{token}"
        current_time = int(time.time())

        try:
            if redis_client:
                raw_session = redis_client.get(key)
                if not raw_session:
                    return None
                session_data = json.loads(raw_session)
            else:
                session_data = auth_session_storage.get(key)
                if not session_data:
                    return None

            if current_time >= int(session_data.get("expires_at", 0)):
                SecurityManager.revoke_auth_session(token)
                return None

            return session_data
        except Exception as e:
            logger.error(f"Auth session lookup error: {e}")
            return None

    @staticmethod
    def revoke_auth_session(token: str) -> None:
        """Revoke a backend auth session."""
        if not token:
            return

        key = f"auth_session:{token}"
        try:
            if redis_client:
                redis_client.delete(key)
            else:
                auth_session_storage.pop(key, None)
        except Exception as e:
            logger.error(f"Auth session revoke error: {e}")
    
    @staticmethod
    def generate_secure_token() -> str:
        """Generate cryptographically secure token"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def generate_wepo_address(username: str, additional_entropy: bytes = None) -> str:
        """Generate secure WEPO address"""
        # Use cryptographically secure random bytes
        entropy = secrets.token_bytes(32)
        if additional_entropy:
            entropy += additional_entropy
        
        # Create address hash with username and entropy
        address_hash = hashlib.sha256(entropy + username.encode()).hexdigest()
        return f"wepo1{address_hash[:32]}"
    
    @staticmethod
    def get_security_headers() -> Dict[str, str]:
        """Get security headers for HTTP responses"""
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https:; font-src 'self' https:; object-src 'none'; media-src 'self'; frame-src 'none';",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }

# Security middleware function
def security_middleware_handler(request: Request, call_next):
    """Security middleware for requests"""
    try:
        # Add security headers to all responses
        response = call_next(request)
        
        # Add security headers
        security_headers = SecurityManager.get_security_headers()
        for header, value in security_headers.items():
            response.headers[header] = value
        
        return response
    except Exception as e:
        logger.error(f"Security middleware error: {e}")
        raise HTTPException(status_code=500, detail="Security middleware error")
