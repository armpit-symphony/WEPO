"""
WEPO Backend Security Utilities
Enhanced security implementation for comprehensive audit requirements
"""

import bcrypt
import secrets
import hashlib
import re
import time
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException, Request
from datetime import datetime, timedelta
import redis
import json

# Configure logging
logger = logging.getLogger(__name__)

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

class SecurityManager:
    """Centralized security management for WEPO backend"""
    
    # Security configuration
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = 300  # 5 minutes in seconds
    RATE_LIMIT_WINDOW = 60  # 1 minute
    
    # Different rate limits for different endpoints
    RATE_LIMIT_CONFIG = {
        "wallet_create": 3,      # 3 per minute
        "wallet_login": 5,       # 5 per minute  
        "transaction_send": 10,  # 10 per minute
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
        """Get client identifier for rate limiting"""
        # Try to get real IP through headers (for proxy setups)
        real_ip = (
            request.headers.get("X-Real-IP") or
            request.headers.get("X-Forwarded-For", "").split(",")[0] or
            request.client.host if request.client else "unknown"
        )
        return real_ip.strip()
    
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
        print(f"DEBUG: ENTERING record_failed_login for {username}")  # Debug log
        current_time = time.time()
        key = f"failed_login:{username}"
        
        print(f"DEBUG: Recording failed login for {username}")  # Debug log
        
        try:
            if redis_client:
                print("DEBUG: Using Redis for failed login tracking")  # Debug log
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
                print(f"DEBUG: Redis storage successful: {attempts_info}")  # Debug log
                    
            else:
                print("DEBUG: Using in-memory storage for failed login tracking")  # Debug log
                # Fallback to in-memory storage
                if username not in failed_attempts_storage:
                    failed_attempts_storage[username] = {"count": 0, "first_attempt": current_time}
                
                failed_attempts_storage[username]["count"] += 1
                failed_attempts_storage[username]["last_attempt"] = current_time
                attempts_info = failed_attempts_storage[username]
                print(f"DEBUG: In-memory storage successful: {attempts_info}")  # Debug log
            
            print(f"DEBUG: Attempts info: {attempts_info}")  # Debug log
            
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
            
            print(f"DEBUG: Returning result: {result}")  # Debug log
            return result
        
        except Exception as e:
            logger.error(f"Failed login recording error: {e}")
            print(f"DEBUG: Exception in record_failed_login: {e}")  # Debug log
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
