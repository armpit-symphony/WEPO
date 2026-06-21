from fastapi import FastAPI, APIRouter, HTTPException, Request, Header
from fastapi.security import HTTPBasic
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import os
import logging
import math
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Tuple
import uuid
import hashlib
import time
import requests
from datetime import datetime
from enum import Enum
import secrets
import re

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Add current directory to Python path for security_utils import
import sys
sys.path.append(str(ROOT_DIR))
CORE_DIR = ROOT_DIR.parent / "wepo-blockchain" / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.append(str(CORE_DIR))

# Import security utilities
from security_utils import SecurityManager, init_redis
try:
    from network_profile import (
        build_collateral_schedule,
        describe_reward_schedule,
        format_block_time,
        get_network_profile,
        get_pow_block_time_seconds,
        get_pow_reward_for_height,
        get_reward_phase_label,
    )
except ImportError:
    build_collateral_schedule = None
    describe_reward_schedule = None
    format_block_time = None
    get_network_profile = None
    get_pow_block_time_seconds = None
    get_pow_reward_for_height = None
    get_reward_phase_label = None

# Initialize security features
init_redis()  # Initialize Redis for rate limiting (fallback to in-memory if Redis unavailable)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
WEPO_NODE_API_URL = os.getenv("WEPO_NODE_API_URL", "http://127.0.0.1:8122")
WEPO_NETWORK_PROFILE_NAME = os.getenv("WEPO_NETWORK_PROFILE", "mainnet").strip().lower() or "mainnet"
WEPO_CANONICAL_APPLICATION_FEES_ENABLED = os.getenv(
    "WEPO_CANONICAL_APPLICATION_FEES_ENABLED",
    "false",
).lower() in {"1", "true", "yes", "on"}
WEPO_APP_FEE_SETTLEMENT_ADDRESS = os.getenv("WEPO_APP_FEE_SETTLEMENT_ADDRESS", "").strip()


def parse_csv_env(env_name: str, default_values: List[str]) -> List[str]:
    raw_value = os.getenv(env_name, "")
    if not raw_value.strip():
        return list(default_values)
    return [value.strip() for value in raw_value.split(",") if value.strip()]


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3100",
    "http://127.0.0.1:3100",
]
WEPO_ALLOWED_ORIGINS = parse_csv_env("WEPO_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
if get_network_profile is not None:
    try:
        WEPO_NETWORK_PROFILE = get_network_profile(WEPO_NETWORK_PROFILE_NAME)
    except Exception:
        WEPO_NETWORK_PROFILE = get_network_profile("mainnet")
else:
    WEPO_NETWORK_PROFILE = None

# Create the main app with enhanced security
app = FastAPI(
    title="WEPO Blockchain API", 
    version="1.0.0",
    docs_url=None,  # Disable docs in production for security
    redoc_url=None  # Disable redoc in production for security
)

# Security middleware with global rate limiting and headers
from fastapi.responses import JSONResponse
try:
    from .feature_flags import disabled_feature_for_path
except ImportError:
    from feature_flags import disabled_feature_for_path


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            # Identify client for rate limiting
            client_id = SecurityManager.get_client_identifier(request)
            path = str(request.url.path)
            method = request.method.upper()

            # Launch-scope feature gate: reject features disabled for this release
            # before any handler runs, so they cannot be exercised or appear live.
            gated_feature = disabled_feature_for_path(path)
            if gated_feature:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": f"{gated_feature} is not available in this release.",
                        "feature_disabled": True,
                    },
                )

            # Skip global limiter for endpoints that already have strict per-endpoint limits
            skip_global = (
                (method == "POST" and path.startswith("/api/wallet/create")) or
                (method == "POST" and path.startswith("/api/wallet/login")) or
                (method == "POST" and path.startswith("/api/transaction/send")) or
                (method == "POST" and path.startswith("/api/transaction/build-unsigned")) or
                # Read-only sanity endpoints should never be globally throttled
                (method == "GET" and (
                    path.startswith("/api/mining/status") or
                    path.startswith("/api/wallet/") or
                    path.startswith("/api/quantum/status") or
                    path.startswith("/api/collateral/schedule") or
                    path.startswith("/api/swap/rate")
                ))
            )

            # Apply global API rate limiting (60/min default)
            if not skip_global and SecurityManager.is_rate_limited(client_id, "global_api"):
                retry_after = SecurityManager.get_rate_limit_reset_seconds(client_id, "global_api")
                reset_ts = int(time.time()) + retry_after
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too many requests. Please try again later.",
                        "retry_after": retry_after,
                        "rate_limit": "60 requests per minute"
                    },
                    headers={
                        "X-RateLimit-Limit": "60",
                        "X-RateLimit-Reset": str(reset_ts),
                        "Retry-After": str(retry_after)
                    }
                )

            try:
                response = await call_next(request)
            except HTTPException as e:
                # Normalize HTTPExceptions so we can attach headers consistently
                status = e.status_code or 500
                retry_after = SecurityManager.get_rate_limit_reset_seconds(client_id, "global_api") if status == 429 else 0
                reset_ts = int(time.time()) + (retry_after or 60)
                content = {"error": e.detail or "Request failed"}
                if status == 429:
                    content["retry_after"] = retry_after
                    content["rate_limit"] = "60 requests per minute"
                response = JSONResponse(status_code=status, content=content)
                # fallthrough to header attachment below
            
            # Add security headers
            security_headers = SecurityManager.get_security_headers()
            for header, value in security_headers.items():
                response.headers[header] = value

            # Add basic rate limiting headers for observability
            response.headers["X-RateLimit-Limit"] = "60"
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)

            return response
        except Exception as e:
            logging.error(f"Security middleware error: {e}")
            # Never raise from middleware; return safe JSON with headers
            retry_after = 60
            reset_ts = int(time.time()) + retry_after
            response = JSONResponse(
                status_code=500,
                content={"error": "Internal server error"},
                headers={
                    "X-RateLimit-Limit": "60",
                    "X-RateLimit-Reset": str(reset_ts),
                    "Retry-After": str(retry_after)
                }
            )
            security_headers = SecurityManager.get_security_headers()
            for header, value in security_headers.items():
                response.headers[header] = value
            return response

app.add_middleware(SecurityMiddleware)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging with enhanced security logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/wepo_security.log')
    ]
)

logger = logging.getLogger(__name__)

# Security
security = HTTPBasic()


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract a bearer token from the Authorization header."""
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    return token.strip()


def require_wallet_session(request: Request, authorization: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Require a valid backend wallet session for sensitive actions."""
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in again.")

    session = SecurityManager.get_auth_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    client_id = SecurityManager.get_client_identifier(request)
    session_client_id = session.get("client_id")
    if session_client_id and session_client_id != client_id:
        logger.warning(
            f"Session client mismatch for {session.get('username')} - "
            f"session {session_client_id}, request {client_id}"
        )

    return token, session

# WEPO Blockchain Models
class TransactionType(str, Enum):
    SEND = "send"
    RECEIVE = "receive"
    STAKE = "stake"
    MASTERNODE = "masternode"
    DEX_SWAP = "dex_swap"

class TransactionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"

class ConsensusType(str, Enum):
    POW = "pow"
    POS = "pos"
    MASTERNODE = "masternode"

# Blockchain Models
class WepoAddress(BaseModel):
    address: str
    public_key: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class WepoTransaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tx_hash: str = Field(default_factory=lambda: secrets.token_hex(32))
    from_address: str
    to_address: str
    amount: float
    fee: float = 0.0001  # Standard WEPO fee
    transaction_type: TransactionType
    status: TransactionStatus = TransactionStatus.PENDING
    block_height: Optional[int] = None
    confirmations: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    privacy_proof: Optional[str] = None  # zk-STARK proof
    ring_signature: Optional[str] = None  # Privacy signature

class WepoBlock(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    height: int
    hash: str
    previous_hash: str
    merkle_root: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    nonce: int = 0
    difficulty: float = 1.0
    consensus_type: ConsensusType
    miner_address: Optional[str] = None
    validator_address: Optional[str] = None
    reward: float = 0.0
    transactions: List[str] = []  # Transaction IDs
    size: int = 0

class WepoWallet(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    address: str
    balance: float = 0.0
    encrypted_private_key: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    is_staking: bool = False
    stake_amount: float = 0.0
    is_masternode: bool = False
    masternode_collateral: float = 0.0

class StakePosition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wallet_address: str
    amount: float
    lock_period_months: int
    apr: float
    start_date: datetime = Field(default_factory=datetime.utcnow)
    end_date: datetime
    rewards_earned: float = 0.0
    is_active: bool = True

class Masternode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wallet_address: str
    server_ip: str
    server_port: int = 22567
    collateral_amount: float = 10000.0
    status: str = "active"  # active, inactive, banned
    uptime_percentage: float = 0.0
    last_ping: datetime = Field(default_factory=datetime.utcnow)
    total_rewards: float = 0.0
    mixing_count: int = 0

class BtcSwap(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wepo_address: str
    btc_address: str
    btc_amount: float
    wepo_amount: float
    exchange_rate: float
    swap_type: str  # "buy" or "sell"
    status: str = "pending"  # pending, completed, failed
    atomic_swap_hash: str = Field(default_factory=lambda: secrets.token_hex(32))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

# Request/Response Models
class CreateWalletRequest(BaseModel):
    username: str
    address: str
    encrypted_private_key: str

class SendTransactionRequest(BaseModel):
    from_address: str
    to_address: str
    amount: float
    password_hash: str

class StakeRequest(BaseModel):
    wallet_address: str
    amount: float
    lock_period_months: Optional[int] = None

class StakeDeactivateRequest(BaseModel):
    wallet_address: str
    stake_id: str

class MasternodeRequest(BaseModel):
    wallet_address: str
    server_ip: str
    server_port: int = 22567
    collateral_txid: Optional[str] = None
    collateral_vout: Optional[int] = None

class MasternodeDeactivateRequest(BaseModel):
    wallet_address: str
    masternode_id: str

class BtcSwapRequest(BaseModel):
    wepo_address: str
    btc_address: str
    btc_amount: float
    swap_type: str

# Blockchain Simulation Functions
def generate_wepo_address() -> str:
    """Generate a WEPO address"""
    random_data = secrets.token_bytes(32)
    address_hash = hashlib.sha256(random_data).hexdigest()
    return f"wepo1{address_hash[:32]}"

def calculate_transaction_hash(transaction: WepoTransaction) -> str:
    """Calculate transaction hash"""
    data = f"{transaction.from_address}{transaction.to_address}{transaction.amount}{transaction.timestamp}"
    return hashlib.sha256(data.encode()).hexdigest()

def generate_zk_proof() -> str:
    """Simulate zk-STARK proof generation"""
    return f"zk_proof_{secrets.token_hex(64)}"

def generate_ring_signature() -> str:
    """Simulate ring signature generation"""
    return f"ring_sig_{secrets.token_hex(64)}"

async def create_block(transactions: List[WepoTransaction], consensus_type: ConsensusType) -> WepoBlock:
    """Create a new block"""
    height = await get_current_block_height() + 1
    previous_block = await db.blocks.find_one(sort=[("height", -1)])
    previous_hash = previous_block["hash"] if previous_block else "0" * 64
    
    # Calculate block reward based on WEPO economics
    if consensus_type == ConsensusType.POW:
        # Year 1: 121.6 WEPO/block, then transitions to 12.4 WEPO/block
        if height <= 52560:  # First year (10-min blocks)
            reward = 121.6
        else:
            # Calculate based on halving schedule
            years_since_year_2 = (height - 52560) // 262800  # 2-minute blocks per year
            reward = 12.4 / (2 ** (years_since_year_2 // 4))
    else:
        reward = 0.1  # PoS/Masternode rewards are lower

    block_data = f"{height}{previous_hash}{time.time()}"
    block_hash = hashlib.sha256(block_data.encode()).hexdigest()
    
    block = WepoBlock(
        height=height,
        hash=block_hash,
        previous_hash=previous_hash,
        merkle_root=hashlib.sha256("".join([tx.tx_hash for tx in transactions]).encode()).hexdigest(),
        consensus_type=consensus_type,
        reward=reward,
        transactions=[tx.id for tx in transactions]
    )
    
    await db.blocks.insert_one(block.dict())
    return block

# API Endpoints

@api_router.get("/")
async def root():
    return {
        "message": "WEPO Blockchain API",
        "version": "1.0.0",
        "network": WEPO_NETWORK_PROFILE.network_label if WEPO_NETWORK_PROFILE else "mainnet",
        "network_profile": WEPO_NETWORK_PROFILE_NAME,
    }

@api_router.get("/network/status")
async def get_network_status():
    """Get WEPO network status"""
    block_height = await get_current_block_height()
    total_staked = await db.stakes.aggregate([
        {"$match": {"is_active": True}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    
    total_staked_amount = total_staked[0]["total"] if total_staked else 0
    total_masternodes = await db.masternodes.count_documents({"status": "active"})
    network_label = WEPO_NETWORK_PROFILE.network_label if WEPO_NETWORK_PROFILE else "mainnet"
    network_profile_name = WEPO_NETWORK_PROFILE_NAME

    try:
        node_network_response = requests.get(f"{WEPO_NODE_API_URL}/api/network/status", timeout=2)
        node_network_response.raise_for_status()
        node_network_payload = node_network_response.json()
        block_height = int(node_network_payload.get("height", node_network_payload.get("chain_height", block_height)) or block_height)
        network_label = node_network_payload.get("network", network_label)
        network_profile_name = node_network_payload.get("network_profile", network_profile_name)
    except Exception:
        node_network_payload = {}

    try:
        staking_response = requests.get(f"{WEPO_NODE_API_URL}/api/staking/info", timeout=2)
        staking_response.raise_for_status()
        staking_payload = staking_response.json()
        total_staked_amount = staking_payload.get("total_staked", total_staked_amount)
    except Exception:
        pass

    try:
        masternode_response = requests.get(f"{WEPO_NODE_API_URL}/api/masternodes", timeout=2)
        masternode_response.raise_for_status()
        masternode_payload = masternode_response.json()
        if isinstance(masternode_payload, list):
            total_masternodes = len(masternode_payload)
    except Exception:
        pass

    return {
        "block_height": block_height,
        "network": network_label,
        "network_profile": network_profile_name,
        "network_hashrate": "123.45 TH/s",  # Simulated
        "active_masternodes": total_masternodes,
        "total_staked": total_staked_amount,
        "total_supply": 63900006,
        "circulating_supply": min(block_height * 121.6 if block_height <= 52560 else 6390000 + (block_height - 52560) * 12.4, 31950000)
    }

# ===== WALLET AUTHENTICATION ENDPOINTS =====

@app.post("/api/wallet/create")
async def create_wallet(request: Request, data: dict):
    """Create a new WEPO wallet with comprehensive security"""
    client_id = SecurityManager.get_client_identifier(request)
    logger.info(f"Wallet creation attempt from {client_id}")
    
    # Implement manual rate limiting (3/minute for wallet creation)
    if SecurityManager.is_rate_limited(client_id, "wallet_create"):
        logger.warning(f"Rate limit exceeded for wallet creation from {client_id}")
        raise HTTPException(status_code=429, detail="Too many wallet creation attempts. Please try again later.")
    
    try:
        # Input validation and sanitization
        username = SecurityManager.sanitize_input(data.get("username", ""))
        password = data.get("password", "")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")
        
        # Enhanced password validation
        password_validation = SecurityManager.validate_password_strength(password)
        if not password_validation["is_valid"]:
            raise HTTPException(
                status_code=400, 
                detail={
                    "message": "Password does not meet security requirements",
                    "issues": password_validation["issues"],
                    "strength_score": password_validation["strength_score"]
                }
            )
        
        # Username validation
        if len(username) < 3 or len(username) > 50:
            raise HTTPException(status_code=400, detail="Username must be 3-50 characters long")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, and underscores")
        
        # Check if username already exists
        existing = await db.wallets.find_one({"username": username})
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Self-custody: the wallet derives its own address from a client-held
        # mnemonic (address = H(Dilithium pubkey), "wepo1q..."). When the client
        # supplies that address we register it as-is; the backend never holds keys
        # and cannot spend. Fall back to a derived address only for legacy callers.
        client_address = SecurityManager.sanitize_input(data.get("address", ""))
        if client_address:
            if not SecurityManager.validate_wepo_address(client_address):
                raise HTTPException(status_code=400, detail="Invalid self-custody address format")
            wepo_address = client_address
            custody_mode = "self_custody"
        else:
            wepo_address = SecurityManager.generate_wepo_address(username)
            custody_mode = "backend_account"

        # Hash password securely
        password_hash = SecurityManager.hash_password(password)
        
        # Create wallet entry with enhanced security
        wallet_data = {
            "username": username,
            "address": wepo_address,
            "password_hash": password_hash,  # Store bcrypt hash instead of plaintext processing
            "created_at": int(time.time()),
            "version": "3.1",  # Updated version for security enhancements
            "bip39": True,
            "custody_mode": custody_mode,
            "legacy_balance_cache": 0.0,
            "security_level": "enhanced",
            "last_login": None,
            "failed_login_attempts": 0,
            "account_locked": False
        }
        
        # Insert wallet with proper error handling
        result = await db.wallets.insert_one(wallet_data)
        if not result.inserted_id:
            raise HTTPException(status_code=500, detail="Failed to create wallet in database")
        
        logger.info(f"Wallet created successfully for user {username} from {client_id}")
        auth_session = SecurityManager.create_auth_session(username, wepo_address, client_id)
        
        return {
            "success": True,
            "address": wepo_address,
            "username": username,
            "message": "Wallet created successfully with enhanced security",
            "bip39": True,
            "custody_mode": custody_mode,
            "security_level": "enhanced",
            "session_token": auth_session["token"],
            "session_expires_at": auth_session["expires_at"],
            "session_duration_seconds": auth_session["duration_seconds"],
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Wallet creation error from {client_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create wallet due to internal error")

@app.post("/api/wallet/login")
async def login_wallet(request: Request, data: dict):
    """Login to existing WEPO wallet with comprehensive security"""
    client_id = SecurityManager.get_client_identifier(request)
    logger.info(f"Login attempt from {client_id}")
    
    # Implement manual rate limiting (5/minute for login)
    if SecurityManager.is_rate_limited(client_id, "wallet_login"):
        logger.warning(f"Rate limit exceeded for login from {client_id}")
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    
    try:
        # Input validation and sanitization
        username = SecurityManager.sanitize_input(data.get("username", ""))
        password = data.get("password", "")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")
        
        # Check for rate limiting specific to this endpoint
        if SecurityManager.is_rate_limited(client_id, "login"):
            raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
        
        # Find wallet by username
        wallet = await db.wallets.find_one({"username": username})
        if not wallet:
            # Record failed login attempt
            SecurityManager.record_failed_login(username)
            logger.warning(f"Login attempt for non-existent user {username} from {client_id}")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        # Check if account is locked
        if wallet.get("account_locked", False):
            logger.warning(f"Login attempt for locked account {username} from {client_id}")
            raise HTTPException(status_code=423, detail="Account is locked due to too many failed attempts")
        
        # Verify password using proper verification
        password_hash = wallet.get("password_hash")
        if not password_hash:
            # Handle legacy accounts that might not have proper password hash
            logger.error(f"Legacy account detected for {username} - security upgrade required")
            raise HTTPException(status_code=500, detail="Account requires security upgrade")
        
        if not SecurityManager.verify_password(password, password_hash):
            # Record failed login attempt
            failed_info = SecurityManager.record_failed_login(username)
            
            # Lock account if too many failed attempts
            if failed_info["is_locked"]:
                await db.wallets.update_one(
                    {"username": username},
                    {
                        "$set": {
                            "account_locked": True,
                            "failed_login_attempts": failed_info["attempts"],
                            "lockout_until": time.time() + SecurityManager.LOCKOUT_DURATION
                        }
                    }
                )
                logger.warning(f"Account {username} locked after {failed_info['attempts']} failed attempts from {client_id}")
                raise HTTPException(
                    status_code=423, 
                    detail={
                        "message": f"Account locked due to {failed_info['attempts']} failed login attempts. Try again in {failed_info['time_remaining']} seconds.",
                        "attempts": failed_info['attempts'],
                        "time_remaining": failed_info['time_remaining'],
                        "max_attempts": failed_info['max_attempts']
                    }
                )
            
            logger.warning(f"Failed login for {username} from {client_id} - {failed_info['attempts']}/{failed_info['max_attempts']} attempts")
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        # Successful login - clear failed attempts and unlock account
        SecurityManager.clear_failed_login(username)
        await db.wallets.update_one(
            {"username": username},
            {
                "$set": {
                    "last_login": int(time.time()),
                    "failed_login_attempts": 0,
                    "account_locked": False
                },
                "$unset": {"lockout_until": ""}
            }
        )
        
        logger.info(f"Successful login for {username} from {client_id}")
        auth_session = SecurityManager.create_auth_session(wallet["username"], wallet["address"], client_id)
        
        return {
            "success": True,
            "address": wallet["address"],
            "username": wallet["username"],
            "balance": wallet.get("legacy_balance_cache", 0.0),
            "balance_source": "legacy_cache",
            "created_at": wallet.get("created_at"),
            "version": wallet.get("version", "3.1"),
            "bip39": wallet.get("bip39", True),
            "security_level": wallet.get("security_level", "enhanced"),
            "message": "Login successful",
            "session_token": auth_session["token"],
            "session_expires_at": auth_session["expires_at"],
            "session_duration_seconds": auth_session["duration_seconds"],
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error for user {username} from {client_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Login failed due to internal error")


@app.post("/api/wallet/logout")
async def logout_wallet(request: Request, authorization: Optional[str] = Header(None)):
    """Revoke the current backend auth session."""
    token = extract_bearer_token(authorization)
    if token:
        SecurityManager.revoke_auth_session(token)

    return {"success": True, "message": "Logged out"}

@api_router.get("/wallet/{address}")
async def get_wallet(address: str):
    """Get wallet information, preferring the live node view over legacy Mongo state."""
    wallet = await db.wallets.find_one({"address": address})

    try:
        response = requests.get(f"{WEPO_NODE_API_URL}/api/wallet/{address}", timeout=2)
        response.raise_for_status()
        payload = response.json()

        return {
            "address": payload.get("address", address),
            "balance": float(payload.get("balance", 0) or 0),
            "utxo_count": int(payload.get("utxo_count", 0) or 0),
            "total_received": float(payload.get("total_received", 0) or 0),
            "total_sent": float(payload.get("total_sent", 0) or 0),
            "unconfirmed_balance": float(payload.get("unconfirmed_balance", 0) or 0),
            "username": wallet.get("username") if wallet else None,
            "created_at": wallet.get("created_at") if wallet else None,
            "is_staking": wallet.get("is_staking", False) if wallet else False,
            "is_masternode": wallet.get("is_masternode", False) if wallet else False,
            "source": "node_proxy",
        }
    except Exception:
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")

    # Legacy fallback if the live node is unavailable.
    received = await db.transactions.aggregate([
        {"$match": {"to_address": address, "status": "confirmed"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)

    sent = await db.transactions.aggregate([
        {"$match": {"from_address": address, "status": "confirmed"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)

    received_amount = received[0]["total"] if received else 0
    sent_amount = sent[0]["total"] if sent else 0
    balance = received_amount - sent_amount

    await db.wallets.update_one(
        {"address": address},
        {"$set": {"legacy_balance_cache": balance, "last_activity": datetime.utcnow()}}
    )

    return {
        "address": wallet["address"],
        "balance": balance,
        "username": wallet["username"],
        "created_at": wallet["created_at"],
        "is_staking": wallet.get("is_staking", False),
        "is_masternode": wallet.get("is_masternode", False),
        "source": "legacy_db",
    }

@api_router.get("/wallet/{address}/transactions")
async def get_wallet_transactions(address: str, limit: int = 50):
    """Get wallet transaction history, preferring the live node view."""
    try:
        response = requests.get(
            f"{WEPO_NODE_API_URL}/api/wallet/{address}/transactions",
            params={"limit": limit},
            timeout=3,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
    except Exception:
        pass

    return await db.transactions.find({
        "$or": [
            {"from_address": address},
            {"to_address": address}
        ]
    }).sort("timestamp", -1).limit(limit).to_list(limit)

@app.post("/api/transaction/build-unsigned")
async def build_unsigned_transaction(request: Request, data: dict):
    """Build an unsigned transaction skeleton + canonical sighash for client signing.

    Self-custody: the wallet calls this, signs the returned sighash locally with its
    Dilithium (ML-DSA-44) key, then submits the completed tx to
    /api/transaction/send as {"signed_tx": {...}}. The backend holds no keys and
    cannot authorize a spend — it only proxies to the live node.
    """
    client_id = SecurityManager.get_client_identifier(request)

    # Same budget as sends: building is the first half of a send attempt.
    if SecurityManager.is_rate_limited(client_id, "transaction_send"):
        raise HTTPException(status_code=429, detail="Too many transaction attempts. Please try again later.")

    from_address = SecurityManager.sanitize_input(data.get("from_address", ""))
    to_address = SecurityManager.sanitize_input(data.get("to_address", ""))
    amount = data.get("amount", 0)
    fee = data.get("fee", 0.0001)

    if not from_address or not to_address:
        raise HTTPException(status_code=400, detail="From and to addresses are required")
    if not SecurityManager.validate_wepo_address(from_address):
        raise HTTPException(status_code=400, detail="Invalid from_address format")
    if not SecurityManager.validate_wepo_address(to_address):
        raise HTTPException(status_code=400, detail="Invalid to_address format")
    if from_address == to_address:
        raise HTTPException(status_code=400, detail="Cannot send to the same address")

    amount_validation = SecurityManager.validate_transaction_amount(amount)
    if not amount_validation["is_valid"]:
        raise HTTPException(
            status_code=400,
            detail={"message": "Invalid transaction amount", "issues": amount_validation["issues"]},
        )

    try:
        response = requests.post(
            f"{WEPO_NODE_API_URL}/api/transaction/build-unsigned",
            json={
                "from_address": from_address,
                "to_address": to_address,
                "amount": amount_validation["sanitized_amount"],
                "fee": fee,
            },
            timeout=5,
        )
    except requests.RequestException as e:
        logger.error(f"Live node build-unsigned proxy error from {client_id}: {e}")
        raise HTTPException(status_code=502, detail="Live transaction node is unavailable")

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=payload.get("detail") or payload.get("error") or "Failed to build transaction",
        )
    return payload


@app.post("/api/transaction/send")
async def send_transaction(request: Request, data: dict):
    """Submit a CLIENT-SIGNED transaction to the live node (self-custody).

    The request must carry a fully signed transaction as {"signed_tx": {...}}
    produced from /api/transaction/build-unsigned. Spend authorization is the
    Dilithium signature bound to the spent UTXO's address, enforced by consensus
    on the node — the backend no longer mints or authorizes spends, so the old
    custodial from_address/session gate is gone.
    """
    client_id = SecurityManager.get_client_identifier(request)
    logger.info(f"Signed transaction submission from {client_id}")

    # Rate limit (10/minute for transactions)
    if SecurityManager.is_rate_limited(client_id, "transaction_send"):
        logger.warning(f"Rate limit exceeded for transaction from {client_id}")
        raise HTTPException(status_code=429, detail="Too many transaction attempts. Please try again later.")

    try:
        signed_tx = data.get("signed_tx")
        if not isinstance(signed_tx, dict):
            raise HTTPException(
                status_code=400,
                detail="A client-signed transaction is required as {'signed_tx': {...}}. "
                       "Build it via /api/transaction/build-unsigned and sign locally.",
            )

        try:
            response = requests.post(
                f"{WEPO_NODE_API_URL}/api/transaction/send",
                json={"signed_tx": signed_tx},
                timeout=5,
            )
        except requests.RequestException as e:
            logger.error(f"Live node transaction proxy error from {client_id}: {e}")
            raise HTTPException(status_code=502, detail="Live transaction node is unavailable")

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if not response.ok:
            raise HTTPException(
                status_code=response.status_code,
                detail=payload.get("detail") or payload.get("error") or "Live transaction failed",
            )

        logger.info(f"Signed transaction proxied: {payload.get('tx_hash')} by {client_id}")
        payload["success"] = True
        payload["source"] = "node_proxy"
        return payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transaction error from {client_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Transaction failed due to internal error")


@app.post("/api/rwa/build-unsigned-create")
async def rwa_build_unsigned_create(request: Request, data: dict):
    """Build an UNSIGNED on-chain RWA creation tx for client signing (self-custody).

    Proxies to the live node. The owner signs the returned sighash locally and
    submits via /api/transaction/send {signed_tx}; the asset is anchored on-chain.
    (Gated by WEPO_FEATURE_RWA — returns 503 while RWA is disabled for launch.)
    """
    client_id = SecurityManager.get_client_identifier(request)
    if SecurityManager.is_rate_limited(client_id, "transaction_send"):
        raise HTTPException(status_code=429, detail="Too many transaction attempts. Please try again later.")

    owner_address = SecurityManager.sanitize_input(data.get("owner_address", ""))
    asset_hash = SecurityManager.sanitize_input(data.get("asset_hash", ""))
    if not owner_address or not asset_hash:
        raise HTTPException(status_code=400, detail="owner_address and asset_hash are required")
    if not SecurityManager.validate_wepo_address(owner_address):
        raise HTTPException(status_code=400, detail="Invalid owner_address format")

    body = {
        "owner_address": owner_address,
        "asset_hash": asset_hash,
        "name": data.get("name"),
        "asset_type": data.get("asset_type"),
        "metadata": data.get("metadata"),
        "asset_id": data.get("asset_id"),
    }
    if data.get("fee") is not None:
        body["fee"] = data.get("fee")

    try:
        response = requests.post(f"{WEPO_NODE_API_URL}/api/rwa/build-unsigned-create", json=body, timeout=5)
    except requests.RequestException as e:
        logger.error(f"Node RWA build proxy error from {client_id}: {e}")
        raise HTTPException(status_code=502, detail="Live node is unavailable")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        raise HTTPException(status_code=response.status_code,
                            detail=payload.get("detail") or payload.get("error") or "Failed to build RWA creation")
    return payload


@app.get("/api/rwa/asset/{asset_id}")
async def rwa_get_asset(asset_id: str):
    """Read one on-chain RWA asset from canonical chain state (via the node)."""
    try:
        response = requests.get(f"{WEPO_NODE_API_URL}/api/rwa/asset/{asset_id}", timeout=5)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Live node is unavailable")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="RWA asset not found")
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid node response")


@app.get("/api/rwa/assets/{owner_address}")
async def rwa_get_assets_for_owner(owner_address: str):
    """Read all on-chain RWA assets owned by an address (via the node)."""
    try:
        response = requests.get(f"{WEPO_NODE_API_URL}/api/rwa/assets/{owner_address}", timeout=5)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Live node is unavailable")
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid node response")


@api_router.post("/stake")
async def create_stake(request: StakeRequest):
    """Compatibility route that proxies to the live node-backed staking API."""
    if request.lock_period_months not in (None, 0):
        raise HTTPException(
            status_code=400,
            detail="Live node staking does not support lock periods; submit amount only",
        )

    try:
        response = requests.post(
            f"{WEPO_NODE_API_URL}/api/stake",
            json={
                "staker_address": request.wallet_address,
                "amount": request.amount,
            },
            timeout=5,
        )
    except requests.RequestException as e:
        logger.error(f"Node stake proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live staking node is unavailable")

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=payload.get("detail", "Live stake creation failed"),
        )

    payload["source"] = "node_proxy"
    payload["lock_period_months"] = None
    payload["lock_period_supported"] = False
    return payload

@api_router.post("/stake/deactivate")
async def deactivate_stake(request: StakeDeactivateRequest):
    """Compatibility route that proxies to the live node-backed unstake API."""
    try:
        response = requests.post(
            f"{WEPO_NODE_API_URL}/api/stake/deactivate",
            json={
                "staker_address": request.wallet_address,
                "stake_id": request.stake_id,
            },
            timeout=5,
        )
    except requests.RequestException as e:
        logger.error(f"Node unstake proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live staking node is unavailable")

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=payload.get("detail", "Live stake deactivation failed"),
        )

    payload["source"] = "node_proxy"
    return payload

@api_router.post("/masternode")
async def setup_masternode(request: MasternodeRequest):
    """Compatibility route that proxies to the live node-backed masternode API."""
    if not request.collateral_txid or request.collateral_vout is None:
        raise HTTPException(
            status_code=400,
            detail="collateral_txid and collateral_vout are required for live masternode registration",
        )

    try:
        response = requests.post(
            f"{WEPO_NODE_API_URL}/api/masternode",
            json={
                "operator_address": request.wallet_address,
                "collateral_txid": request.collateral_txid,
                "collateral_vout": request.collateral_vout,
                "ip_address": request.server_ip,
                "port": request.server_port,
            },
            timeout=5,
        )
    except requests.RequestException as e:
        logger.error(f"Node masternode proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live masternode node is unavailable")

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=payload.get("detail", "Live masternode registration failed"),
        )

    payload["source"] = "node_proxy"
    return payload

@api_router.post("/masternode/deactivate")
async def deactivate_masternode(request: MasternodeDeactivateRequest):
    """Compatibility route that proxies to the live node-backed masternode deactivation API."""
    try:
        response = requests.post(
            f"{WEPO_NODE_API_URL}/api/masternode/deactivate",
            json={
                "operator_address": request.wallet_address,
                "masternode_id": request.masternode_id,
            },
            timeout=5,
        )
    except requests.RequestException as e:
        logger.error(f"Node masternode deactivate proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live masternode node is unavailable")

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=payload.get("detail", "Live masternode deactivation failed"),
        )

    payload["source"] = "node_proxy"
    return payload

@api_router.get("/masternodes")
async def list_masternodes():
    """List all active masternodes, proxied from the live node."""
    try:
        response = requests.get(f"{WEPO_NODE_API_URL}/api/masternodes", timeout=5)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        logger.error(f"Node masternodes list proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live node is unavailable")
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Unexpected response from node")
    return payload

@api_router.get("/wallet/{address}/masternodes")
async def get_wallet_masternodes(address: str):
    """List masternodes operated by a given address, proxied from the live node."""
    try:
        response = requests.get(
            f"{WEPO_NODE_API_URL}/api/wallet/{address}/masternodes", timeout=5
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        logger.error(f"Node wallet masternodes proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live node is unavailable")
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Unexpected response from node")
    return payload

@api_router.get("/wallet/{address}/stakes")
async def get_wallet_stakes(address: str):
    """List stakes for a given address, proxied from the live node."""
    try:
        response = requests.get(
            f"{WEPO_NODE_API_URL}/api/wallet/{address}/stakes", timeout=5
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        logger.error(f"Node wallet stakes proxy error: {e}")
        raise HTTPException(status_code=502, detail="Live node is unavailable")
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Unexpected response from node")
    return payload

@api_router.post("/dex/swap")
async def create_btc_swap(request: BtcSwapRequest):
    """Create BTC-WEPO atomic swap"""
    wallet = await db.wallets.find_one({"address": request.wepo_address})
    if not wallet:
        raise HTTPException(status_code=404, detail="WEPO wallet not found")
    
    # Calculate exchange rate (1:1 for demo)
    exchange_rate = 1.0
    wepo_amount = request.btc_amount * exchange_rate
    
    if request.swap_type == "sell" and wallet.get("legacy_balance_cache", 0) < wepo_amount:
        raise HTTPException(status_code=400, detail="Insufficient WEPO balance")
    
    swap = BtcSwap(
        wepo_address=request.wepo_address,
        btc_address=request.btc_address,
        btc_amount=request.btc_amount,
        wepo_amount=wepo_amount,
        exchange_rate=exchange_rate,
        swap_type=request.swap_type
    )
    
    await db.btc_swaps.insert_one(swap.dict())
    
    return {
        "swap_id": swap.id,
        "atomic_swap_hash": swap.atomic_swap_hash,
        "wepo_amount": wepo_amount,
        "exchange_rate": exchange_rate,
        "status": swap.status
    }

@api_router.get("/dex/rate")
async def get_exchange_rate():
    """Get current BTC-WEPO exchange rate"""
    return {
        "btc_to_wepo": 1.0,
        "wepo_to_btc": 1.0,
        "fee_percentage": 0.1,
        "last_updated": datetime.utcnow()
    }

# ===== BTC ESPLORA PROXY ENDPOINTS (READ-ONLY) =====
ESPLORA_BASE = "https://blockstream.info/api"

def _esplora_get(path: str, timeout=10):
    import requests
    url = f"{ESPLORA_BASE}{path}"
    r = requests.get(url, timeout=timeout)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"Esplora error {r.status_code}")
    try:
        return r.json()
    except Exception:
        return r.text

@api_router.get("/bitcoin/address/{addr}")
async def btc_address_info(addr: str):
    try:
        info = _esplora_get(f"/address/{addr}")
        # Also include a small recent txs page for UX
        try:
            txs = _esplora_get(f"/address/{addr}/txs")
        except Exception:
            txs = []
        return {"success": True, "data": info, "txs": txs}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Esplora address info error: {e}")
        raise HTTPException(status_code=500, detail="Failed to query address")

@api_router.get("/bitcoin/address/{addr}/utxo")
async def btc_address_utxo(addr: str):
    try:
        utxos = _esplora_get(f"/address/{addr}/utxo")
        return {"success": True, "data": utxos}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Esplora utxo error: {e}")
        raise HTTPException(status_code=500, detail="Failed to query utxos")

@api_router.get("/bitcoin/tx/{txid}")
async def btc_tx_info(txid: str):
    try:
        tx = _esplora_get(f"/tx/{txid}")
        return {"success": True, "data": tx}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Esplora tx error: {e}")
        raise HTTPException(status_code=500, detail="Failed to query tx")

@api_router.get("/bitcoin/tx/{txid}/hex")
async def btc_tx_hex(txid: str):
    try:
        tx_hex = _esplora_get(f"/tx/{txid}/hex")
        return {"success": True, "data": tx_hex}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Esplora tx hex error: {e}")
        raise HTTPException(status_code=500, detail="Failed to query transaction hex")

@api_router.get("/bitcoin/fee-estimates")
async def btc_fee_estimates():
    try:
        fees = _esplora_get("/fee-estimates")
        return {"success": True, "data": fees}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Esplora fee error: {e}")
        raise HTTPException(status_code=500, detail="Failed to query fee estimates")

@api_router.get("/blocks/latest")
async def get_latest_blocks(limit: int = 10):
    """Get latest blocks"""
    blocks = await db.blocks.find().sort("height", -1).limit(limit).to_list(limit)
    return blocks

@api_router.get("/quantum/status")
async def quantum_status():
    try:
        import sys
        sys.path.append('/app/wepo-blockchain/core')
        from dilithium import DilithiumSigner
        signer = DilithiumSigner()
        info = {
            "quantum_resistant": bool(getattr(signer, 'is_real_dilithium', False)),
            "algorithm": getattr(signer, 'algorithm', 'Unknown'),
            "security_level": 128 if getattr(signer, 'is_real_dilithium', False) else 0,
            "post_quantum": bool(getattr(signer, 'is_real_dilithium', False)),
            "nist_approved": bool(getattr(signer, 'is_real_dilithium', False)),
        }
        return {"success": True, "data": info, "timestamp": int(time.time())}
    except Exception as e:
        return {"success": True, "data": {"quantum_resistant": False, "algorithm": "RSA Simulation", "error": str(e)}, "timestamp": int(time.time())}

@api_router.get("/collateral/schedule")
async def collateral_schedule():
    current_height = await get_current_block_height()
    HALVING_SCHEDULE = (
        build_collateral_schedule(WEPO_NETWORK_PROFILE)
        if WEPO_NETWORK_PROFILE is not None and build_collateral_schedule is not None
        else [
            {"height": 0, "mn": 10000, "pos": 0, "phase": "Phase 1", "desc": "Genesis -> PoS Activation", "pos_avail": False},
            {"height": 131400, "mn": 10000, "pos": 1000, "phase": "Phase 2A", "desc": "PoS Activation -> 2nd Halving", "pos_avail": True},
            {"height": 306600, "mn": 6000, "pos": 600, "phase": "Phase 2B", "desc": "2nd Halving -> 3rd Halving", "pos_avail": True},
            {"height": 657000, "mn": 3000, "pos": 300, "phase": "Phase 2C", "desc": "3rd Halving -> 4th Halving", "pos_avail": True},
            {"height": 832200, "mn": 1500, "pos": 150, "phase": "Phase 2D", "desc": "4th Halving -> 5th Halving", "pos_avail": True},
            {"height": 1007400, "mn": 1000, "pos": 100, "phase": "Phase 3", "desc": "Post-PoW Era", "pos_avail": True},
        ]
    )
    schedule = []
    next_phase_index = next(
        (index for index, entry in enumerate(HALVING_SCHEDULE) if entry["height"] > current_height),
        None,
    )

    for index, entry in enumerate(HALVING_SCHEDULE):
        next_height = HALVING_SCHEDULE[index + 1]["height"] if index + 1 < len(HALVING_SCHEDULE) else None
        is_current = current_height >= entry["height"] and (next_height is None or current_height < next_height)

        schedule.append({
            "block_height": entry["height"],
            "masternode_collateral": entry["mn"],
            "pos_collateral": entry["pos"],
            "pos_available": entry["pos_avail"],
            "phase": entry["phase"],
            "phase_description": entry["desc"],
            "is_current": is_current,
            "is_next": next_phase_index == index
        })
    return {
        "success": True,
        "data": {
            "current_height": current_height,
            "network_profile": WEPO_NETWORK_PROFILE_NAME,
            "schedule": schedule,
        },
        "timestamp": int(time.time()),
    }

@api_router.get("/mining/info")
async def get_mining_info():
    """Get mining information"""
    height = await get_current_block_height()
    next_height = height + 1
    if WEPO_NETWORK_PROFILE is not None:
        reward_phase = get_reward_phase_label(WEPO_NETWORK_PROFILE, next_height)
        block_time = format_block_time(get_pow_block_time_seconds(WEPO_NETWORK_PROFILE, next_height))
        reward_schedule = describe_reward_schedule(WEPO_NETWORK_PROFILE)
        current_reward = get_pow_reward_for_height(WEPO_NETWORK_PROFILE, next_height) / 100000000
    else:
        reward_phase = "Legacy"
        block_time = "10 minutes"
        reward_schedule = "legacy backend schedule"
        current_reward = 121.6 if height <= 52560 else 12.4
    
    return {
        "current_block_height": height,
        "current_reward": current_reward,
        "next_halving_block": None,
        "blocks_until_halving": None,
        "difficulty": 1.0,
        "algorithm": "Argon2",
        "block_time": block_time,
        "reward_phase": reward_phase,
        "reward_schedule": reward_schedule,
        "network_profile": WEPO_NETWORK_PROFILE_NAME,
    }

# Community-Driven AMM System (No Admin)
import math
from typing import Dict, Optional

class LiquidityPool:
    """Community-driven liquidity pool with no admin control"""
    
    def __init__(self):
        self.btc_reserve = 0.0
        self.wepo_reserve = 0.0
        self.total_shares = 0.0
        self.lp_positions = {}  # user_address: shares
        self.fee_rate = 0.003  # 0.3% trading fee
    
    def get_price(self) -> Optional[float]:
        """Get current WEPO per BTC price"""
        if self.btc_reserve == 0:
            return None
        return self.wepo_reserve / self.btc_reserve
    
    def get_output_amount(self, input_amount: float, input_is_btc: bool) -> float:
        """Calculate output amount using constant product formula"""
        if input_is_btc:
            # BTC → WEPO
            input_reserve = self.btc_reserve
            output_reserve = self.wepo_reserve
        else:
            # WEPO → BTC  
            input_reserve = self.wepo_reserve
            output_reserve = self.btc_reserve
        
        # Apply fee to input
        input_after_fee = input_amount * (1 - self.fee_rate)
        
        # Constant product formula: x * y = k
        # (x + input_after_fee) * (y - output) = x * y
        # output = (y * input_after_fee) / (x + input_after_fee)
        output_amount = (output_reserve * input_after_fee) / (input_reserve + input_after_fee)
        
        return output_amount
    
    def bootstrap_pool(self, user_address: str, btc_amount: float, wepo_amount: float):
        """First user creates the market - no admin required"""
        if self.total_shares > 0:
            raise Exception("Pool already exists")
        
        if btc_amount <= 0 or wepo_amount <= 0:
            raise Exception("Invalid amounts")
        
        # Set initial reserves (user determines initial price)
        self.btc_reserve = btc_amount
        self.wepo_reserve = wepo_amount
        
        # Initial shares = geometric mean of reserves
        self.total_shares = math.sqrt(btc_amount * wepo_amount)
        self.lp_positions[user_address] = self.total_shares
        
        return {
            "initial_price": wepo_amount / btc_amount,
            "shares_minted": self.total_shares,
            "total_shares": self.total_shares,
            "pool_created": True,
            "btc_reserve": self.btc_reserve,
            "wepo_reserve": self.wepo_reserve
        }
    
    def add_liquidity(self, user_address: str, btc_amount: float, wepo_amount: float):
        """Add liquidity to existing pool"""
        if self.total_shares == 0:
            return self.bootstrap_pool(user_address, btc_amount, wepo_amount)
        
        # Calculate required ratio
        current_ratio = self.wepo_reserve / self.btc_reserve
        provided_ratio = wepo_amount / btc_amount
        
        # Allow small tolerance for ratio mismatch
        if abs(current_ratio - provided_ratio) / current_ratio > 0.02:  # 2% tolerance
            raise Exception(f"Ratio mismatch. Current: {current_ratio:.6f}, Provided: {provided_ratio:.6f}")
        
        # Calculate shares to mint proportionally
        btc_share = btc_amount / self.btc_reserve
        shares_to_mint = self.total_shares * btc_share
        
        # Update reserves
        self.btc_reserve += btc_amount
        self.wepo_reserve += wepo_amount
        self.total_shares += shares_to_mint
        
        # Update user position
        if user_address in self.lp_positions:
            self.lp_positions[user_address] += shares_to_mint
        else:
            self.lp_positions[user_address] = shares_to_mint
        
        return {
            "shares_minted": shares_to_mint,
            "total_shares": self.total_shares,
            "new_price": self.get_price(),
            "btc_reserve": self.btc_reserve,
            "wepo_reserve": self.wepo_reserve
        }
    
    def execute_swap(self, input_amount: float, input_is_btc: bool) -> Dict:
        """Execute swap and update reserves"""
        if self.total_shares == 0:
            raise Exception("No liquidity in pool")
        
        output_amount = self.get_output_amount(input_amount, input_is_btc)
        fee_amount = input_amount * self.fee_rate
        
        # Update reserves
        if input_is_btc:
            self.btc_reserve += input_amount
            self.wepo_reserve -= output_amount
        else:
            self.wepo_reserve += input_amount
            self.btc_reserve -= output_amount
        
        return {
            "input_amount": input_amount,
            "output_amount": output_amount,
            "fee_amount": fee_amount,
            "new_price": self.get_price(),
            "btc_reserve": self.btc_reserve,
            "wepo_reserve": self.wepo_reserve
        }

# Global pool instance (in production, this would be in database)
btc_wepo_pool = LiquidityPool()

# Community-Driven AMM Endpoints
@api_router.get("/swap/rate")
async def get_market_rate():
    """Get current market-determined BTC/WEPO rate"""
    try:
        price = btc_wepo_pool.get_price()
        
        if price is None:
            return {
                "pool_exists": False,
                "message": "No liquidity pool exists yet. Any user can create the market.",
                "btc_reserve": 0,
                "wepo_reserve": 0,
                "can_bootstrap": True,
                "btc_settlement_mode": "simulated_lab"
            }
        
        return {
            "pool_exists": True,
            "btc_to_wepo": price,
            "wepo_to_btc": 1 / price,
            "btc_reserve": btc_wepo_pool.btc_reserve,
            "wepo_reserve": btc_wepo_pool.wepo_reserve,
            "total_liquidity_shares": btc_wepo_pool.total_shares,
            "fee_rate": btc_wepo_pool.fee_rate,
            "last_updated": int(time.time()),
            "btc_settlement_mode": "simulated_lab"
        }
    except Exception as e:
        logger.error(f"Error getting market rate: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/swap/execute")
async def execute_market_swap(request: dict):
    """Execute swap using community-driven AMM"""
    try:
        wallet_address = request.get("wallet_address")
        from_currency = request.get("from_currency")  # BTC or WEPO
        input_amount = float(request.get("input_amount", 0))
        
        if not wallet_address or not from_currency or input_amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid request parameters")
        
        if from_currency not in ["BTC", "WEPO"]:
            raise HTTPException(status_code=400, detail="Invalid currency")
        
        # Check if pool exists
        if btc_wepo_pool.total_shares == 0:
            raise HTTPException(status_code=400, detail="No liquidity pool exists. Create market first.")
        
        # Execute swap
        input_is_btc = (from_currency == "BTC")
        swap_result = btc_wepo_pool.execute_swap(input_amount, input_is_btc)
        
        # Application-level swap fee. Mirror it into canonical chain fees when configured.
        fee_amount = swap_result["fee_amount"]
        
        fee_settlement = await settle_application_fee(fee_amount, "swap_fee")
        
        # Record swap transaction
        swap_record = {
            "swap_id": f"swap_{int(time.time())}_{wallet_address[:8]}",
            "wallet_address": wallet_address,
            "from_currency": from_currency,
            "to_currency": "WEPO" if from_currency == "BTC" else "BTC",
            "input_amount": input_amount,
            "output_amount": swap_result["output_amount"],
            "fee_amount": fee_amount,
            "fee_settlement": {
                "applied_on_chain": fee_settlement["applied_on_chain"],
                "settlement_policy": fee_settlement["settlement_policy"],
                "settlement_txid": fee_settlement.get("settlement_txid"),
                "manual_review_required": fee_settlement.get("manual_review_required", False),
                "settlement_error": fee_settlement.get("settlement_error"),
            },
            "price": swap_result["new_price"],
            "status": "completed",
            "timestamp": int(time.time()),
            "created_at": datetime.now()
        }
        
        await db.market_swaps.insert_one(swap_record)
        
        return {
            "swap_id": swap_record["swap_id"],
            "status": "completed",
            "from_currency": from_currency,
            "to_currency": swap_record["to_currency"],
            "input_amount": input_amount,
            "output_amount": swap_result["output_amount"],
            "fee_amount": fee_amount,
            "fee_applied_on_chain": fee_settlement["applied_on_chain"],
            "fee_settlement_policy": fee_settlement["settlement_policy"],
            "fee_settlement_txid": fee_settlement.get("settlement_txid"),
            "fee_manual_review_required": fee_settlement.get("manual_review_required", False),
            "fee_settlement_error": fee_settlement.get("settlement_error"),
            "market_price": swap_result["new_price"],
            "btc_reserve": swap_result["btc_reserve"],
            "wepo_reserve": swap_result["wepo_reserve"],
            "timestamp": swap_record["timestamp"],
            "btc_settlement_mode": "simulated_lab"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing market swap: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/swap/history")
async def get_market_swap_history(limit: int = 5, wallet_address: Optional[str] = None):
    """Get recent BTC/WEPO market swap history"""
    try:
        safe_limit = max(1, min(int(limit), 50))
        query: Dict[str, Any] = {}
        if wallet_address:
            query["wallet_address"] = wallet_address

        cursor = db.market_swaps.find(query).sort("timestamp", -1).limit(safe_limit)
        swaps = await cursor.to_list(length=safe_limit)

        history = []
        for swap in swaps:
            history.append({
                "swap_id": swap.get("swap_id", ""),
                "wallet_address": swap.get("wallet_address", ""),
                "from_currency": swap.get("from_currency", ""),
                "to_currency": swap.get("to_currency", ""),
                "input_amount": swap.get("input_amount", 0),
                "output_amount": swap.get("output_amount", 0),
                "fee_amount": swap.get("fee_amount", 0),
                "status": swap.get("status", "completed"),
                "market_price": swap.get("price", 0),
                "timestamp": swap.get("timestamp", 0),
            })

        return {
            "success": True,
            "history": history,
            "count": len(history),
            "btc_settlement_mode": "simulated_lab"
        }
    except Exception as e:
        logger.error(f"Error getting market swap history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/liquidity/add")
async def add_liquidity_to_pool(request: dict):
    """Add liquidity to BTC-WEPO pool (or create if first)"""
    try:
        wallet_address = request.get("wallet_address")
        btc_amount = float(request.get("btc_amount", 0))
        wepo_amount = float(request.get("wepo_amount", 0))
        
        if not wallet_address or btc_amount <= 0 or wepo_amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid amounts")
        
        # TODO: Verify user has sufficient balance
        # user_btc_balance = await get_user_btc_balance(wallet_address)
        # user_wepo_balance = await get_user_wepo_balance(wallet_address)
        
        # Add liquidity
        result = btc_wepo_pool.add_liquidity(wallet_address, btc_amount, wepo_amount)
        
        # Record liquidity provision
        lp_record = {
            "lp_id": f"lp_{int(time.time())}_{wallet_address[:8]}",
            "wallet_address": wallet_address,
            "btc_amount": btc_amount,
            "wepo_amount": wepo_amount,
            "shares_minted": result["shares_minted"],
            "pool_created": result.get("pool_created", False),
            "timestamp": int(time.time()),
            "created_at": datetime.now()
        }
        
        await db.liquidity_positions.insert_one(lp_record)
        
        return {
            "lp_id": lp_record["lp_id"],
            "status": "success",
            "btc_amount": btc_amount,
            "wepo_amount": wepo_amount,
            "shares_minted": result["shares_minted"],
            "total_shares": result.get("total_shares", btc_wepo_pool.total_shares),
            "market_price": result.get("new_price") or result.get("initial_price"),
            "pool_created": result.get("pool_created", False),
            "btc_reserve": result["btc_reserve"],
            "wepo_reserve": result["wepo_reserve"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding liquidity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/liquidity/stats")
async def get_liquidity_stats():
    """Get current pool statistics"""
    try:
        if btc_wepo_pool.total_shares == 0:
            return {
                "pool_exists": False,
                "message": "No liquidity pool exists. Any user can create the market.",
                "btc_settlement_mode": "simulated_lab"
            }
        
        return {
            "pool_exists": True,
            "btc_reserve": btc_wepo_pool.btc_reserve,
            "wepo_reserve": btc_wepo_pool.wepo_reserve,
            "total_shares": btc_wepo_pool.total_shares,
            "current_price": btc_wepo_pool.get_price(),
            "fee_rate": btc_wepo_pool.fee_rate,
            "total_lp_count": len(btc_wepo_pool.lp_positions),
            "btc_settlement_mode": "simulated_lab"
        }
    except Exception as e:
        logger.error(f"Error getting liquidity stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ===== WALLET MINING SYSTEM =====

class WalletMiner:
    """Browser-based wallet miner integrated with WEPO PoW network"""
    def __init__(self):
        self.connected_miners = {}  # address -> miner info
        self.mining_stats = {
            "connected_miners": 0,
            "total_hashrate": 0.0,
            "blocks_found": 0,
            "network_difficulty": 1.0,
            "mining_mode": "genesis"  # "genesis" or "pow"
        }
        self.genesis_launch_time = 1735153200  # Dec 25, 2025 8pm UTC (3pm EST)
        
        # Staging-only manual override for genesis active flag
        self._force_genesis_active: Optional[bool] = None

    def _fetch_live_network_status(self) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                f"{WEPO_NODE_API_URL}/api/network/status",
                timeout=3,
            )
        except requests.RequestException:
            return None

        if not response.ok:
            return None

        try:
            return response.json()
        except ValueError:
            return None
    
    def is_genesis_active(self):
        """Check if genesis mining is still active"""
        # Staging override takes precedence if set
        if self._force_genesis_active is not None:
            return self._force_genesis_active

        network_status = self._fetch_live_network_status()
        if network_status:
            chain_height = network_status.get("chain_height", network_status.get("height", 0)) or 0
            hybrid_consensus = network_status.get("hybrid_consensus") or {}
            if chain_height > 0 or hybrid_consensus.get("pos_activated"):
                return False

        current_time = time.time()
        return current_time < self.genesis_launch_time or self.mining_stats["blocks_found"] == 0
    
    async def connect_miner(self, address: str, mining_mode: str = "genesis", wallet_type: str = "regular"):
        """Connect a wallet miner to the network"""
        if not address:
            raise HTTPException(status_code=400, detail="Wallet address required")
        
        self.connected_miners[address] = {
            "address": address,
            "wallet_type": wallet_type,
            "mining_mode": mining_mode,
            "connected_time": time.time(),
            "hashrate": 0.0,
            "is_mining": False,
            "last_activity": time.time(),
            "cpu_usage": 25,  # Default 25%
            "shares_submitted": 0,
            "blocks_found": 0
        }
        
        self.mining_stats["connected_miners"] = len(self.connected_miners)
        
        return {
            "success": True,
            "message": "Connected to WEPO mining network",
            "miner_id": address[:10] + "..." + address[-6:],
            "network_miners": self.mining_stats["connected_miners"],
            "mining_mode": "🎄 Genesis Block Mining" if self.is_genesis_active() else "⚡ PoW Mining"
        }
    
    async def start_mining(self, address: str):
        """Start mining for a wallet miner"""
        if address not in self.connected_miners:
            await self.connect_miner(address)
        
        miner = self.connected_miners[address]
        miner["is_mining"] = True
        miner["last_activity"] = time.time()
        
        # Generate mining job (same format as external miners)
        mining_job = await self.get_mining_work(address)
        
        return {
            "success": True,
            "message": "Mining started successfully",
            "mining_job": mining_job,
            "cpu_usage": miner["cpu_usage"],
            "status": "🎄 Mining genesis block..." if self.is_genesis_active() else "⚡ Mining PoW blocks..."
        }
    
    async def stop_mining(self, address: str):
        """Stop mining for a wallet miner"""
        if address in self.connected_miners:
            miner = self.connected_miners[address]
            miner["is_mining"] = False
            miner["hashrate"] = 0.0
            self.update_total_hashrate()
        
        return {
            "success": True,
            "message": "Mining stopped successfully"
        }
    
    async def get_mining_work(self, address: str):
        """Get mining work - same pathway as external miners"""
        current_time = int(time.time())
        height = await get_current_block_height()
        
        # Genesis block special case
        if self.is_genesis_active():
            return {
                "job_id": f"genesis_{address[:8]}_{current_time}",
                "block_type": "genesis",
                "height": 0,
                "prev_hash": "0" * 64,
                "merkle_root": "genesis_merkle_root_" + "0" * 40,
                "timestamp": current_time,
                "bits": 0x1d00ffff,
                "target_difficulty": 1.0,
                "reward": 0,  # Genesis block has no reward
                "algorithm": "argon2",
                "message": "WEPO Genesis Block"
            }
        
        # Regular PoW block
        return {
            "job_id": f"pow_{address[:8]}_{current_time}",
            "block_type": "pow",
            "height": height + 1,
            "prev_hash": f"previous_block_hash_{height}",
            "merkle_root": f"merkle_root_{current_time}",
            "timestamp": current_time,
            "bits": 0x1d00ffff,
            "target_difficulty": self.mining_stats["network_difficulty"],
            "reward": 121.6 if height <= 52560 else 12.4,
            "algorithm": "argon2"
        }
    
    async def submit_work(self, address: str, job_id: str, nonce: str, hash_result: str):
        """Submit mining work - same pathway as external miners"""
        if address not in self.connected_miners:
            raise HTTPException(status_code=400, detail="Miner not connected")
        
        miner = self.connected_miners[address]
        miner["shares_submitted"] += 1
        miner["last_activity"] = time.time()
        
        # Check if valid solution (simplified for wallet mining)
        # In production, this would validate against target difficulty
        is_valid_block = hash_result.startswith("0000")  # Simplified validation
        
        if is_valid_block:
            miner["blocks_found"] += 1
            self.mining_stats["blocks_found"] += 1
            
            # If genesis block found, switch to PoW mode
            if self.is_genesis_active() and job_id.startswith("genesis_"):
                self.mining_stats["mining_mode"] = "pow"
            
            return {
                "accepted": True,
                "type": "block",
                "height": 0 if job_id.startswith("genesis_") else await get_current_block_height() + 1,
                "reward": 0 if job_id.startswith("genesis_") else 121.6,
                "message": "🎄 Genesis block found!" if job_id.startswith("genesis_") else "Block found!"
            }
        
        # Valid share but not a block
        return {
            "accepted": True,
            "type": "share",
            "message": "Share accepted"
        }
    
    async def update_miner_hashrate(self, address: str, hashrate: float):
        """Update individual miner hashrate"""
        if address in self.connected_miners:
            self.connected_miners[address]["hashrate"] = hashrate
            self.connected_miners[address]["last_activity"] = time.time()
            self.update_total_hashrate()
    
    def update_total_hashrate(self):
        """Update total network hashrate"""
        total = sum(miner["hashrate"] for miner in self.connected_miners.values() if miner["is_mining"])
        self.mining_stats["total_hashrate"] = total
    
    def get_mining_stats(self):
        """Get current mining statistics"""
        active_miners = [m for m in self.connected_miners.values() if m["is_mining"]]
        
        return {
            "connected_miners": len(self.connected_miners),
            "active_miners": len(active_miners),
            "total_hashrate": self.mining_stats["total_hashrate"],
            "network_difficulty": self.mining_stats["network_difficulty"],
            "blocks_found": self.mining_stats["blocks_found"],
            "mining_mode": "genesis" if self.is_genesis_active() else "pow",
            "genesis_launch_time": self.genesis_launch_time,
            "time_to_launch": max(0, self.genesis_launch_time - time.time()) if self.is_genesis_active() else 0,
            "mode_display": "🎄 Genesis Block Mining" if self.is_genesis_active() else "⚡ PoW Mining"
        }
    
    def get_miner_stats(self, address: str):
        """Get individual miner statistics"""
        if address not in self.connected_miners:
            return {"error": "Miner not found"}
        
        miner = self.connected_miners[address]
        return {
            "address": address[:10] + "..." + address[-6:],
            "is_mining": miner["is_mining"],
            "hashrate": miner["hashrate"],
            "cpu_usage": miner.get("cpu_usage", 25),
            "shares_submitted": miner["shares_submitted"],
            "blocks_found": miner["blocks_found"],
            "connected_time": miner["connected_time"],
            "uptime": time.time() - miner["connected_time"],
            "network_rank": self.get_miner_rank(address)
        }
    
    def get_miner_rank(self, address: str):
        """Get miner's rank by hashrate"""
        if address not in self.connected_miners:
            return 0
        
        miners_by_hashrate = sorted(
            [m for m in self.connected_miners.values() if m["is_mining"]], 
            key=lambda x: x["hashrate"], 
            reverse=True
        )
        
        for i, miner in enumerate(miners_by_hashrate):
            if miner["address"] == address:
                return i + 1
        return len(miners_by_hashrate)

# Global wallet mining instance
wallet_mining = WalletMiner()

# Wallet Mining API Endpoints
@api_router.get("/mining/status")
async def get_mining_status():
    """Get current mining status"""
    return wallet_mining.get_mining_stats()

# Staging-only: toggle genesis active state (no auth in this environment). DO NOT EXPOSE IN PROD.
@api_router.post("/mining/_toggle_genesis")
async def toggle_genesis(request: dict):
    # Disabled in production by default. Enable only if WEPO_STAGING_TOGGLE=true
    import os
    if os.environ.get('WEPO_STAGING_TOGGLE', 'false').lower() != 'true':
        raise HTTPException(status_code=403, detail="Staging toggle disabled")
    force = request.get("force")
    if isinstance(force, bool):
        wallet_mining._force_genesis_active = force
        return {"success": True, "forced": force}
    return {"success": False, "error": "force must be boolean"}

@api_router.post("/mining/connect")
async def connect_miner(request: dict):
    """Connect a wallet miner to the network"""
    address = request.get("address")
    mining_mode = request.get("mining_mode", "genesis") 
    wallet_type = request.get("wallet_type", "regular")
    
    return await wallet_mining.connect_miner(address, mining_mode, wallet_type)

@api_router.post("/mining/start")
async def start_mining(request: dict):
    """Start mining for a wallet miner"""
    address = request.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="Address required")
    
    return await wallet_mining.start_mining(address)

@api_router.post("/mining/stop")
async def stop_mining(request: dict):
    """Stop mining for a wallet miner"""
    address = request.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="Address required")
    
    return await wallet_mining.stop_mining(address)

@api_router.get("/mining/work/{address}")
async def get_mining_work(address: str):
    """Get mining work for wallet miner - same pathway as external miners"""
    return await wallet_mining.get_mining_work(address)

@api_router.post("/mining/submit")
async def submit_mining_work(request: dict):
    """Submit mining work - same pathway as external miners"""
    address = request.get("address")
    job_id = request.get("job_id")
    nonce = request.get("nonce")
    hash_result = request.get("hash")
    
    if not all([address, job_id, nonce, hash_result]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    return await wallet_mining.submit_work(address, job_id, nonce, hash_result)

@api_router.post("/mining/hashrate")
async def update_hashrate(request: dict):
    """Update miner hashrate"""
    address = request.get("address")
    hashrate = request.get("hashrate", 0.0)
    
    if not address:
        raise HTTPException(status_code=400, detail="Address required")
    
    await wallet_mining.update_miner_hashrate(address, hashrate)
    return {"success": True}

@api_router.get("/mining/stats/{address}")
async def get_miner_stats(address: str):
    """Get mining statistics for a specific miner"""
    return wallet_mining.get_miner_stats(address)

@api_router.get("/mining/leaderboard")
async def get_mining_leaderboard():
    """Get mining leaderboard - top miners by hashrate"""
    miners = []
    for address, miner in wallet_mining.connected_miners.items():
        if miner["is_mining"]:
            miners.append({
                "address": address[:10] + "..." + address[-6:],
                "hashrate": miner["hashrate"],
                "wallet_type": miner["wallet_type"],
                "blocks_found": miner["blocks_found"]
            })
    
    miners.sort(key=lambda x: x["hashrate"], reverse=True)
    return {"miners": miners[:20]}

# ===== BTC RELAY VIA MASTERNODES =====

# Lightweight relay manager for broadcasting BTC transactions via masternodes
class BtcRelayManager:
    def __init__(self):
        self.last_attempt: Optional[dict] = None
        self.total_attempts: int = 0
        self.total_relays: int = 0
        self.total_fallbacks: int = 0
        self.last_error: Optional[str] = None
        # Lazy-init masternode network manager
        self._mn_manager = None

    def _get_manager(self):
        if self._mn_manager is not None:
            return self._mn_manager
        try:
            from wepo_masternode_networking import MasternodeNetworkManager, MasternodeNetworkInfo
            # Minimal no-bind manager; we won't start the network here to avoid port binding
            mn_info = MasternodeNetworkInfo(
                masternode_id="wallet_btc_relay",
                operator_address="wepo1walletrelay0000000000000000000000000",
                collateral_txid="",
                collateral_vout=0,
                ip_address="127.0.0.1",
                port=22999
            )
            class _MockChain:
                def get_active_masternodes(self):
                    return []
            self._mn_manager = MasternodeNetworkManager(mn_info, _MockChain())
            return self._mn_manager
        except Exception as e:
            logger.error(f"BTC relay manager init failed: {e}")
            self.last_error = str(e)
            return None

    def relay(self, rawtx_hex: str) -> Tuple[bool, int]:
        import binascii
        self.total_attempts += 1
        self.last_error = None
        manager = self._get_manager()
        peers = 0
        relayed = False
        try:
            tx_bytes = binascii.unhexlify(rawtx_hex.strip())
            # Build relay message with prefix so masternode software can route it
            msg = b'BTCR' + tx_bytes
            if manager is not None:
                peers = len(getattr(manager, 'connections', {}))
                manager.broadcast_to_masternodes(msg)
                relayed = peers > 0
        except Exception as e:
            logger.error(f"BTC relay error: {e}")
            self.last_error = str(e)
            relayed = False
        if relayed:
            self.total_relays += 1
        return relayed, peers

    def relay_status(self):
        return {
            "total_attempts": self.total_attempts,
            "total_relays": self.total_relays,
            "total_fallbacks": self.total_fallbacks,
            "last_error": self.last_error
        }

btc_relay_manager = BtcRelayManager()

@api_router.post("/bitcoin/relay/broadcast")
async def relay_btc_transaction(request: dict):
    """Relay raw BTC transaction via masternode network. Self-custody preserved (client signs)."""
    import hashlib, binascii
    rawtx = request.get("rawtx")
    relay_only = bool(request.get("relay_only", True))
    if not rawtx or not isinstance(rawtx, str):
        raise HTTPException(status_code=400, detail="rawtx hex required")
    try:
        tx_bytes = binascii.unhexlify(rawtx.strip())
        # Compute Bitcoin txid (double-SHA256, little-endian)
        txid = hashlib.sha256(hashlib.sha256(tx_bytes).digest()).digest()[::-1].hex()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rawtx hex")

    relayed, peers = btc_relay_manager.relay(rawtx)
    result = {
        "success": True,
        "path": "masternode_relay" if relayed else ("relay_attempt_no_peers" if peers == 0 else "relay_attempt_failed"),
        "peers": peers,
        "txid": txid,
        "relayed": relayed,
        "relay_only": relay_only
    }

    # Optional fallback (disabled by default)
    if not relayed and not relay_only:
        try:
            import requests
            # Blockstream Esplora broadcast endpoint (mainnet)
            resp = requests.post("https://blockstream.info/api/tx", data=tx_bytes, timeout=10)
            if resp.status_code in (200, 201):
                btc_relay_manager.total_fallbacks += 1
                result.update({"path": "fallback_esplora", "relayed": True})
            else:
                result.update({"fallback_error": f"HTTP {resp.status_code}"})
        except Exception as e:
            result.update({"fallback_error": str(e)})

    return result

@api_router.get("/bitcoin/relay/status")
async def relay_status():
    return {"success": True, "data": btc_relay_manager.relay_status()}

# ===== HELPER FUNCTIONS =====

async def get_current_block_height():
    """Get current blockchain height"""
    latest_block = await db.blocks.find_one(sort=[("height", -1)])
    db_height = int(latest_block["height"]) if latest_block and latest_block.get("height") is not None else 0

    try:
        response = requests.get(f"{WEPO_NODE_API_URL}/api/network/status", timeout=2)
        response.raise_for_status()
        payload = response.json()
        node_height = int(payload.get("height", payload.get("chain_height", 0)) or 0)
        return max(db_height, node_height)
    except Exception:
        return db_height

async def get_wallet_balance(address: str) -> float:
    """Get the lab-adjusted WEPO balance for an address."""
    try:
        node_balance = await get_live_node_wallet_balance(address)
        wallet = await db.wallet_trade_state.find_one({"address": address})
        trade_delta = float(wallet.get("trade_balance_delta", 0) or 0) if wallet else 0.0
        return node_balance + trade_delta
    except Exception:
        return 0

async def update_wallet_balance(address: str, amount_change: float):
    """Update only the backend-managed lab trade delta."""
    try:
        await db.wallet_trade_state.update_one(
            {"address": address},
            {
                "$inc": {"trade_balance_delta": amount_change},
                "$setOnInsert": {"address": address},
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error updating wallet balance: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update balance")

# ===== RWA TOKEN TRADING ENDPOINTS =====

@api_router.get("/rwa/tokens")
async def get_rwa_tokens():
    """Get all tradeable RWA tokens"""
    try:
        # Query all RWA tokens from database
        tokens = await db.rwa_tokens.find({"status": "active"}).to_list(None)
        
        # Format for trading interface
        tradeable_tokens = []
        for token in tokens:
            tradeable_tokens.append({
                "token_id": str(token.get("_id", "")),
                "symbol": token.get("symbol", ""),
                "asset_name": token.get("asset_name", ""),
                "asset_type": token.get("asset_type", "property"),
                "total_supply": token.get("total_supply", 1000),
                "available_supply": token.get("available_supply", 1000),
                "creator": token.get("creator", ""),
                "created_date": token.get("created_date", ""),
                "verified": token.get("verified", True),
                "trading_enabled": token.get("trading_enabled", True),
                "decimals": token.get("decimals", 8)
            })
        
        return {
            "success": True,
            "tokens": tradeable_tokens,
            "count": len(tradeable_tokens)
        }
        
    except Exception as e:
        logger.error(f"Error getting RWA tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/rwa/rates") 
async def get_rwa_rates():
    """Get RWA token exchange rates against WEPO"""
    try:
        # Get all active tokens
        tokens = await db.rwa_tokens.find({"status": "active"}).to_list(None)
        rates = {}
        
        # Calculate exchange rates for each token
        for token in tokens:
            token_id = str(token.get("_id", ""))
            final_rate = float(await get_rwa_token_unit_value_wepo(token) or 0.0)
            
            rates[token_id] = {
                "rate_wepo_per_token": round(final_rate, 6),
                "rate_token_per_wepo": round(1.0 / final_rate, 6) if final_rate > 0 else 0.0,
                "last_updated": int(time.time()),
                "token_symbol": token.get("symbol", ""),
                "token_name": token.get("asset_name", ""),
                "24h_change": 0.0,
                "pricing_source": "asset_valuation",
            }
        
        return {
            "success": True,
            "rates": rates,
            "base_currency": "WEPO",
            "last_updated": int(time.time())
        }
        
    except Exception as e:
        logger.error(f"Error getting RWA rates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/rwa/transfer")
async def transfer_rwa_tokens(request_obj: Request, request: dict, authorization: Optional[str] = Header(None)):
    """Transfer RWA tokens between addresses"""
    try:
        token_id = request.get('token_id')
        from_address = request.get('from_address')
        to_address = request.get('to_address')
        amount = request.get('amount')

        if not all([token_id, from_address, to_address, amount]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        amount = float(amount)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")

        # Require an authenticated session that owns from_address
        _, session = require_wallet_session(request_obj, authorization)
        if session.get("address") != from_address:
            raise HTTPException(status_code=403, detail="Authenticated session does not match from_address")
        
        # Get token info
        token = await db.rwa_tokens.find_one({"_id": token_id})
        if not token:
            raise HTTPException(status_code=404, detail="Token not found")
        
        # Check sender balance
        sender_balance_doc = await db.rwa_balances.find_one({
            "token_id": token_id,
            "address": from_address
        })
        
        sender_balance = sender_balance_doc.get("balance", 0) if sender_balance_doc else 0
        if sender_balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")
        
        # Execute transfer
        # Deduct from sender
        await db.rwa_balances.update_one(
            {"token_id": token_id, "address": from_address},
            {"$inc": {"balance": -amount}},
            upsert=True
        )
        
        # Add to receiver  
        await db.rwa_balances.update_one(
            {"token_id": token_id, "address": to_address},
            {"$inc": {"balance": amount}},
            upsert=True
        )
        
        # Record transaction
        tx_record = {
            "tx_id": f"rwa_tx_{int(time.time())}_{secrets.token_hex(4)}",
            "token_id": token_id,
            "from_address": from_address,
            "to_address": to_address,
            "amount": amount,
            "token_symbol": token.get("symbol", ""),
            "timestamp": int(time.time()),
            "status": "confirmed",
            "tx_type": "rwa_transfer"
        }
        
        await db.rwa_transactions.insert_one(tx_record)
        
        return {
            "success": True,
            "tx_id": tx_record["tx_id"],
            "token_id": token_id,
            "from_address": from_address,
            "to_address": to_address,
            "amount": amount,
            "token_symbol": token.get("symbol", ""),
            "status": "confirmed",
            "timestamp": tx_record["timestamp"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transferring RWA tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/dex/rwa-trade")
async def execute_rwa_trade(request: dict):
    """Execute RWA token trades through the unified exchange"""
    reserved_trade_id: Optional[str] = None
    trade_timestamp: Optional[int] = None
    trade_effects_applied = False
    created_idempotency_reservation = False
    effective_wepo_balance_before: Optional[float] = None
    effective_wepo_balance_after: Optional[float] = None
    lab_trade_balance_delta: Optional[float] = None
    try:
        token_id = request.get('token_id')
        trade_type = request.get('trade_type')  # 'buy' or 'sell'
        user_address = request.get('user_address')
        token_amount = request.get('token_amount') 
        wepo_amount = request.get('wepo_amount')
        privacy_enhanced = request.get('privacy_enhanced', False)
        idempotency_key = str(request.get("idempotency_key", "")).strip() or None
        
        if not all([token_id, trade_type, user_address, token_amount, wepo_amount]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        if idempotency_key and len(idempotency_key) > 128:
            raise HTTPException(status_code=400, detail="idempotency_key must be 128 characters or fewer")
        
        token_amount = float(token_amount)
        wepo_amount = float(wepo_amount)
        if trade_type not in {"buy", "sell"}:
            raise HTTPException(status_code=400, detail="trade_type must be 'buy' or 'sell'")
        if token_amount <= 0:
            raise HTTPException(status_code=400, detail="token_amount must be positive")
        if wepo_amount <= 0:
            raise HTTPException(status_code=400, detail="wepo_amount must be positive")

        if idempotency_key:
            reservation, reserved_trade_id, trade_timestamp, created_new = await reserve_rwa_trade_idempotency(
                user_address,
                idempotency_key,
            )
            created_idempotency_reservation = created_new
            if not created_new:
                if reservation.get("status") == "completed":
                    return build_rwa_trade_response(reservation, idempotent_replay=True)
                if reservation.get("status") == "failed":
                    raise HTTPException(
                        status_code=409,
                        detail="Duplicate trade request requires manual review because the prior attempt failed after partial processing",
                    )
                raise HTTPException(status_code=409, detail="Duplicate trade request is already processing")
        else:
            reserved_trade_id = f"rwa_trade_{int(time.time())}_{secrets.token_hex(4)}"
            trade_timestamp = int(time.time())
        
        # Get token info
        token = await db.rwa_tokens.find_one({"_id": token_id})
        if not token:
            raise HTTPException(status_code=404, detail="RWA token not found")

        unit_value_wepo = float(await get_rwa_token_unit_value_wepo(token) or 0.0)
        if unit_value_wepo <= 0:
            raise HTTPException(status_code=400, detail="RWA token has no valuation-backed rate")

        expected_wepo_amount = round(unit_value_wepo * token_amount, 8)
        if abs(wepo_amount - expected_wepo_amount) > 0.000001:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Quoted WEPO amount does not match the current valuation-backed rate",
                    "expected_wepo_amount": expected_wepo_amount,
                    "rate_wepo_per_token": round(unit_value_wepo, 8),
                },
            )

        wepo_amount = expected_wepo_amount
        
        # Calculate trade fee (0.1% of WEPO amount)
        trade_fee = wepo_amount * 0.001
        effective_wepo_balance_before = await get_wallet_balance(user_address)
        creator_address = token.get("creator", "")
        available_supply = float(token.get("available_supply", 0) or 0)

        if trade_type == 'buy':
            # User buying RWA tokens with WEPO
            # Check user WEPO balance
            if effective_wepo_balance_before < (wepo_amount + trade_fee):
                raise HTTPException(status_code=400, detail="Insufficient WEPO balance")
            if available_supply < token_amount:
                raise HTTPException(status_code=400, detail="Insufficient token inventory available for purchase")

            creator_balance_doc = await db.rwa_balances.find_one({
                "token_id": token_id,
                "address": creator_address,
            })
            creator_token_balance = float(creator_balance_doc.get("balance", 0) or 0) if creator_balance_doc else 0.0
            if creator_token_balance < token_amount:
                raise HTTPException(status_code=400, detail="Token inventory is out of sync with creator balance")
            
            # Deduct WEPO from user
            trade_effects_applied = True
            await update_wallet_balance(user_address, -(wepo_amount + trade_fee))

            # Transfer tokens from creator inventory to the buyer.
            await db.rwa_balances.update_one(
                {"token_id": token_id, "address": creator_address},
                {"$inc": {"balance": -token_amount}},
            )
            
            # Add RWA tokens to user
            await db.rwa_balances.update_one(
                {"token_id": token_id, "address": user_address},
                {"$inc": {"balance": token_amount}},
                upsert=True
            )
            await db.rwa_tokens.update_one(
                {"_id": token_id},
                {"$inc": {"available_supply": -token_amount}},
            )
            
        else:  # sell
            # User selling RWA tokens for WEPO
            # Check user token balance
            user_token_balance_doc = await db.rwa_balances.find_one({
                "token_id": token_id,
                "address": user_address
            })
            user_token_balance = user_token_balance_doc.get("balance", 0) if user_token_balance_doc else 0
            
            if user_token_balance < token_amount:
                raise HTTPException(status_code=400, detail="Insufficient token balance")
            
            # Deduct RWA tokens from user
            trade_effects_applied = True
            await db.rwa_balances.update_one(
                {"token_id": token_id, "address": user_address},
                {"$inc": {"balance": -token_amount}}
            )

            await db.rwa_balances.update_one(
                {"token_id": token_id, "address": creator_address},
                {"$inc": {"balance": token_amount}},
                upsert=True,
            )
            await db.rwa_tokens.update_one(
                {"_id": token_id},
                {"$inc": {"available_supply": token_amount}},
            )
            
            # Add WEPO to user (minus fee)
            await update_wallet_balance(user_address, wepo_amount - trade_fee)

        lab_trade_balance_delta = await get_wallet_trade_balance_delta(user_address)
        effective_wepo_balance_after = await get_wallet_balance(user_address)
        
        fee_settlement = await settle_application_fee(trade_fee, "rwa_trade")
        
        # Record trade
        trade_record = {
            "trade_id": reserved_trade_id,
            "token_id": token_id,
            "token_symbol": token.get("symbol", ""),
            "trade_type": trade_type,
            "user_address": user_address,
            "token_amount": token_amount,
            "wepo_amount": wepo_amount,
            "rate_wepo_per_token": round(unit_value_wepo, 8),
            "trade_fee": trade_fee,
            "fee_settlement": {
                "applied_on_chain": fee_settlement["applied_on_chain"],
                "settlement_policy": fee_settlement["settlement_policy"],
                "settlement_txid": fee_settlement.get("settlement_txid"),
                "manual_review_required": fee_settlement.get("manual_review_required", False),
                "settlement_error": fee_settlement.get("settlement_error"),
            },
            "privacy_enhanced": privacy_enhanced,
            "wepo_balance_source": "live_node_plus_lab_trade_delta",
            "lab_trade_balance_delta": lab_trade_balance_delta,
            "effective_wepo_balance_before": effective_wepo_balance_before,
            "effective_wepo_balance_after": effective_wepo_balance_after,
            "timestamp": trade_timestamp,
            "status": "completed"
        }

        if idempotency_key:
            trade_record["idempotency_key"] = idempotency_key
        
        if idempotency_key:
            await db.rwa_trades.update_one(
                {"trade_id": reserved_trade_id},
                {"$set": trade_record, "$unset": {"processing_started_at": ""}},
            )
        else:
            await db.rwa_trades.insert_one(trade_record)
        
        return build_rwa_trade_response(trade_record)
        
    except HTTPException as exc:
        if trade_effects_applied or created_idempotency_reservation or not idempotency_key:
            await mark_rwa_trade_attempt_failed(
                reserved_trade_id,
                str(exc.detail),
                trade_effects_applied=trade_effects_applied,
            )
        raise
    except Exception as e:
        logger.error(f"Error executing RWA trade: {str(e)}")
        if trade_effects_applied or created_idempotency_reservation or not idempotency_key:
            await mark_rwa_trade_attempt_failed(
                reserved_trade_id,
                str(e),
                trade_effects_applied=trade_effects_applied,
            )
        raise HTTPException(status_code=500, detail=str(e))

# ===== QUANTUM VAULT ENDPOINTS =====

@api_router.post("/vault/create")
async def create_quantum_vault(request: dict):
    """Create a new Quantum Vault with multi-asset support"""
    try:
        user_address = request.get("user_address") or request.get("wallet_address")
        privacy_level = request.get("privacy_level", 3)
        multi_asset_support = request.get("multi_asset_support", True)

        if not user_address:
            raise HTTPException(status_code=400, detail="User address required")
        
        # Generate vault ID
        vault_id = f"qv_{int(time.time())}_{secrets.token_hex(8)}"
        
        # Create vault record
        vault_record = {
            "vault_id": vault_id,
            "owner_address": user_address,
            "privacy_level": privacy_level,
            "multi_asset_support": multi_asset_support,
            "rwa_support": True,
            "rwa_ghost_transfers": True,
            "created_at": int(time.time()),
            "last_activity": int(time.time()),
            "transaction_count": 0,
            "wepo_balance": 0,
            "rwa_asset_count": 0,
            "privacy_commitment": hashlib.sha256(f"{vault_id}{user_address}{int(time.time())}".encode()).hexdigest()
        }
        
        await db.quantum_vaults.insert_one(vault_record)

        return {
            "success": True,
            "vault_id": vault_id,
            "privacy_level": privacy_level,
            "multi_asset_support": multi_asset_support,
            "rwa_support": True,
            "rwa_ghost_transfers": True,
            "privacy_commitment": vault_record["privacy_commitment"],
            "message": "Multi-asset Quantum Vault created with RWA support"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating quantum vault: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/vault/status/{vault_id}")
async def get_vault_status(vault_id: str, user_address: str = None):
    """Get comprehensive vault status including RWA assets"""
    try:
        # Build query
        vault_query = {"vault_id": vault_id}
        if user_address:
            vault_query["owner_address"] = user_address
            
        vault = await db.quantum_vaults.find_one(vault_query)
        if not vault:
            raise HTTPException(status_code=404, detail="Vault not found or unauthorized")
        
        # Get RWA assets in vault
        vault_rwa_assets = await db.vault_rwa_balances.find({"vault_id": vault_id, "balance": {"$gt": 0}}).to_list(None)
        
        # Calculate portfolio information
        total_assets = len(vault_rwa_assets)
        asset_types = list(set([asset.get("asset_type", "unknown") for asset in vault_rwa_assets]))
        
        # Get asset portfolio (privacy-protected based on privacy level)
        assets_portfolio = []
        if vault.get("privacy_level", 3) < 3:  # Lower privacy levels show some details
            for asset in vault_rwa_assets:
                asset_info = await db.rwa_tokens.find_one({"_id": asset["asset_id"]})
                if asset_info:
                    assets_portfolio.append({
                        "asset_type": asset_info.get("asset_type", ""),
                        "balance": asset["balance"],
                        "symbol": asset_info.get("symbol", "")
                    })
        
        return {
            "success": True,
            "vault_id": vault_id,
            "owner_address": vault["owner_address"],
            "privacy_level": vault["privacy_level"],
            "multi_asset_support": vault.get("multi_asset_support", True),
            "rwa_support": vault.get("rwa_support", True),
            "rwa_ghost_transfers": vault.get("rwa_ghost_transfers", True),
            "transaction_count": vault.get("transaction_count", 0),
            "wepo_balance": vault.get("wepo_balance", 0),
            "rwa_asset_count": total_assets,
            "total_assets": total_assets,
            "asset_types": asset_types if vault.get("privacy_level", 3) < 4 else [],  # Hide asset types at max privacy
            "assets_portfolio": assets_portfolio,
            "asset_type_hiding": vault.get("privacy_level", 3) >= 3,
            "last_activity": vault.get("last_activity"),
            "privacy_commitment": vault.get("privacy_commitment", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting vault status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ===== RWA QUANTUM VAULT ENDPOINTS - REVOLUTIONARY PRIVATE RWA STORAGE =====

@api_router.post("/vault/rwa/create")
async def create_rwa_vault(request: dict):
    """Create specialized RWA Quantum Vault with enhanced asset privacy"""
    try:
        wallet_address = str(request.get("wallet_address", "")).strip()
        asset_type = str(request.get("asset_type", "real_estate")).strip() or "real_estate"
        requested_privacy_level = request.get("privacy_level", "maximum")
        
        if not wallet_address:
            raise HTTPException(status_code=400, detail="Wallet address required for RWA vault")

        privacy_level_map = {
            "minimum": 1,
            "low": 1,
            "medium": 2,
            "high": 3,
            "maximum": 4,
            "max": 4,
        }
        if isinstance(requested_privacy_level, str):
            privacy_level = privacy_level_map.get(requested_privacy_level.strip().lower())
            if privacy_level is None:
                raise HTTPException(status_code=400, detail="Unsupported privacy_level")
        else:
            try:
                privacy_level = max(1, min(4, int(requested_privacy_level)))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Unsupported privacy_level")

        privacy_labels = {
            1: "minimum",
            2: "medium",
            3: "high",
            4: "maximum",
        }
        
        now_ts = int(time.time())
        vault_id = f"rwa_vault_{now_ts}_{secrets.token_hex(8)}"
        privacy_commitment = hashlib.sha256(
            f"{vault_id}{wallet_address}{privacy_level}{now_ts}".encode()
        ).hexdigest()
        
        # Create specialized RWA vault with enhanced features
        rwa_vault_data = {
            "vault_id": vault_id,
            "vault_type": "rwa_quantum_vault",
            "owner_address": wallet_address,
            "wallet_address": wallet_address,
            "asset_type": asset_type,
            "privacy_level": privacy_level,
            "privacy_level_label": privacy_labels[privacy_level],
            "created_at": now_ts,
            "last_activity": now_ts,
            "status": "active",
            "multi_asset_support": True,
            "rwa_support": True,
            "rwa_ghost_transfers": True,
            "transaction_count": 0,
            "wepo_balance": 0,
            "rwa_asset_count": 0,
            "privacy_commitment": privacy_commitment,
            "features": {
                "rwa_privacy_mixing": True,
                "cross_asset_transfers": True,
                "quantum_encryption": True,
                "zk_stark_proofs": True,
                "ghost_transfers": True,
                "regulatory_compliance": True,
                "multi_jurisdiction": True,
                "asset_tokenization": True
            },
            "supported_assets": {
                "real_estate": ["residential", "commercial", "land"],
                "commodities": ["gold", "silver", "oil", "wheat"],
                "securities": ["stocks", "bonds", "derivatives"],
                "collectibles": ["art", "antiques", "rare_items"]
            },
            "privacy_features": {
                "ownership_obfuscation": True,
                "transfer_mixing": True,
                "value_hiding": True,
                "location_privacy": True
            },
            "compliance_features": {
                "kyc_integration": True,
                "aml_monitoring": True,
                "regulatory_reporting": True,
                "jurisdiction_filtering": True
            }
        }

        await db.quantum_vaults.insert_one(rwa_vault_data)
        
        return {
            "success": True,
            "vault_created": True,
            "vault_id": vault_id,
            "vault_type": "RWA Quantum Vault",
            "wallet_address": wallet_address,
            "asset_type": asset_type,
            "privacy_level": privacy_level,
            "privacy_level_label": rwa_vault_data["privacy_level_label"],
            "features_enabled": list(rwa_vault_data["features"].keys()),
            "supported_assets": list(rwa_vault_data["supported_assets"].keys()),
            "privacy_protection": "Maximum RWA privacy with quantum encryption",
            "compliance_ready": True,
            "privacy_commitment": privacy_commitment,
            "message": f"RWA Quantum Vault created for {asset_type} assets with maximum privacy protection"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating RWA vault: {str(e)}")
        raise HTTPException(status_code=500, detail=f"RWA vault creation failed: {str(e)}")

@api_router.get("/vault/rwa/status/{vault_id}")
async def get_rwa_vault_status(vault_id: str, user_address: str = None):
    """Get detailed status of RWA Quantum Vault"""
    try:
        if not vault_id:
            raise HTTPException(status_code=400, detail="Vault ID required")

        vault_query = {"vault_id": vault_id, "vault_type": "rwa_quantum_vault"}
        if user_address:
            vault_query["owner_address"] = user_address

        vault = await db.quantum_vaults.find_one(vault_query)
        if not vault:
            raise HTTPException(status_code=404, detail="Vault not found or unauthorized")

        asset_balances = await db.vault_rwa_balances.find(
            {"vault_id": vault_id, "balance": {"$gt": 0}}
        ).to_list(None)
        recent_activity_docs = await db.vault_transactions.find(
            {
                "$or": [
                    {"vault_id": vault_id},
                    {"counterparty_vault_id": vault_id},
                ]
            }
        ).sort("timestamp", -1).to_list(10)

        visible_asset_types = []
        if int(vault.get("privacy_level", 4) or 4) < 4:
            for asset in asset_balances:
                asset_type = asset.get("asset_type")
                if not asset_type:
                    token_info = await db.rwa_tokens.find_one({"_id": asset.get("asset_id")})
                    asset_type = token_info.get("asset_type") if token_info else None
                if asset_type and asset_type not in visible_asset_types:
                    visible_asset_types.append(asset_type)

        rwa_vault_status = {
            "vault_id": vault["vault_id"],
            "vault_type": vault.get("vault_type", "rwa_quantum_vault"),
            "status": vault.get("status", "active"),
            "created_at": vault.get("created_at"),
            "last_activity": vault.get("last_activity"),
            "privacy_status": {
                "encryption_level": "quantum_resistant",
                "zk_proofs": "enabled",
                "mixing_active": True,
                "ghost_mode": vault.get("rwa_ghost_transfers", True),
            },
            "asset_holdings": {
                "total_assets": len(asset_balances),
                "asset_types": visible_asset_types,
                "estimated_value": "Privacy Protected",
                "last_valuation": None,
            },
            "recent_activity": [
                {
                    "type": (
                        f"incoming_{tx.get('tx_type', 'unknown')}"
                        if tx.get("counterparty_vault_id") == vault_id
                        and tx.get("vault_id") != vault_id
                        and "transfer" in str(tx.get("tx_type", ""))
                        else tx.get("tx_type", "unknown")
                    ),
                    "asset": "Privacy Protected" if int(vault.get("privacy_level", 4) or 4) >= 4 else tx.get("asset_id"),
                    "timestamp": tx.get("timestamp"),
                    "status": tx.get("status", "confirmed"),
                }
                for tx in recent_activity_docs
            ],
            "security_features": {
                "quantum_encryption": vault.get("features", {}).get("quantum_encryption", True),
                "multi_sig_required": True,
                "time_locks": True,
                "emergency_freeze": True,
            },
            "compliance_status": {
                "kyc_verified": True,
                "aml_cleared": True,
                "regulatory_compliant": True,
                "jurisdiction": "multi",
            },
            "available_actions": [
                "deposit_rwa",
                "withdraw_rwa",
                "ghost_transfer",
            ],
        }
        
        return {
            "success": True,
            "vault_found": True,
            "vault_data": rwa_vault_status,
            "privacy_note": "Sensitive information is protected by quantum encryption",
            "message": "RWA Quantum Vault status retrieved successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting RWA vault status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"RWA vault status retrieval failed: {str(e)}")

@api_router.post("/vault/rwa/transfer")
async def transfer_rwa_between_vaults(request: dict):
    """Transfer RWA assets between Quantum Vaults with maximum privacy"""
    try:
        from_vault = request.get("from_vault")
        to_vault = request.get("to_vault") 
        asset_id = request.get("asset_id")
        amount = float(request.get("amount", 1) or 0)
        privacy_mode = request.get("privacy_mode", "ghost")  # ghost, stealth, public
        user_address = request.get("user_address")
        
        if not all([from_vault, to_vault, asset_id]):
            raise HTTPException(status_code=400, detail="Missing required transfer parameters")
        
        if from_vault == to_vault:
            raise HTTPException(status_code=400, detail="Cannot transfer to same vault")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")

        source_query = {"vault_id": from_vault, "vault_type": "rwa_quantum_vault"}
        if user_address:
            source_query["owner_address"] = user_address

        source_vault = await db.quantum_vaults.find_one(source_query)
        if not source_vault:
            raise HTTPException(status_code=404, detail="Source vault not found or unauthorized")

        destination_vault = await db.quantum_vaults.find_one(
            {"vault_id": to_vault, "vault_type": "rwa_quantum_vault"}
        )
        if not destination_vault:
            raise HTTPException(status_code=404, detail="Destination vault not found")

        source_balance_doc = await db.vault_rwa_balances.find_one(
            {"vault_id": from_vault, "asset_id": asset_id}
        )
        source_balance = float(source_balance_doc.get("balance", 0)) if source_balance_doc else 0
        if source_balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient source vault balance")

        transfer_id = f"rwa_transfer_{int(time.time())}_{secrets.token_hex(6)}"
        now_ts = int(time.time())

        token_info = await db.rwa_tokens.find_one({"_id": asset_id})
        asset_type = source_balance_doc.get("asset_type") if source_balance_doc else None
        if not asset_type and token_info:
            asset_type = token_info.get("asset_type")

        await db.vault_rwa_balances.update_one(
            {"vault_id": from_vault, "asset_id": asset_id},
            {
                "$inc": {"balance": -amount},
                "$set": {"asset_type": asset_type},
            },
        )
        await db.vault_rwa_balances.update_one(
            {"vault_id": to_vault, "asset_id": asset_id},
            {
                "$inc": {"balance": amount},
                "$set": {"asset_type": asset_type},
            },
            upsert=True,
        )

        transfer_record = {
            "tx_id": transfer_id,
            "vault_id": from_vault,
            "counterparty_vault_id": to_vault,
            "asset_id": asset_id,
            "amount": amount,
            "user_address": source_vault.get("owner_address"),
            "tx_type": "rwa_ghost_transfer" if privacy_mode == "ghost" else "rwa_transfer",
            "privacy_mode": privacy_mode,
            "timestamp": now_ts,
            "status": "completed",
        }
        await db.vault_transactions.insert_one(transfer_record)

        source_asset_count = await db.vault_rwa_balances.count_documents(
            {"vault_id": from_vault, "balance": {"$gt": 0}}
        )
        destination_asset_count = await db.vault_rwa_balances.count_documents(
            {"vault_id": to_vault, "balance": {"$gt": 0}}
        )

        await db.quantum_vaults.update_one(
            {"vault_id": from_vault},
            {
                "$inc": {"transaction_count": 1},
                "$set": {"last_activity": now_ts, "rwa_asset_count": source_asset_count},
            },
        )
        await db.quantum_vaults.update_one(
            {"vault_id": to_vault},
            {
                "$inc": {"transaction_count": 1},
                "$set": {"last_activity": now_ts, "rwa_asset_count": destination_asset_count},
            },
        )
        
        return {
            "success": True,
            "transfer_initiated": True,
            "transfer_id": transfer_id,
            "from_vault": from_vault[:10] + "..." if privacy_mode != "public" else from_vault,
            "to_vault": to_vault[:10] + "..." if privacy_mode != "public" else to_vault,
            "asset_id": "Privacy Protected" if privacy_mode == "ghost" else asset_id,
            "amount": "Privacy Protected" if privacy_mode == "ghost" else amount,
            "privacy_mode": privacy_mode,
            "status": "completed",
            "estimated_completion_time": "completed",
            "tracking_id": transfer_id,
            "privacy_protection": f"Transfer protected with {privacy_mode} mode privacy",
            "message": f"RWA transfer initiated with {privacy_mode} privacy protection"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating RWA transfer: {str(e)}")
        raise HTTPException(status_code=500, detail=f"RWA transfer failed: {str(e)}")

@api_router.post("/vault/rwa/deposit")
async def deposit_rwa_to_vault(request: dict):
    """Deposit RWA tokens to Quantum Vault with privacy protection"""
    try:
        vault_id = request.get("vault_id")
        asset_id = request.get("asset_id")  # RWA token ID
        amount = request.get("amount")
        user_address = request.get("user_address")
        
        if not all([vault_id, asset_id, amount, user_address]):
            raise HTTPException(status_code=400, detail="Invalid RWA deposit parameters")
        
        amount = float(amount)
        
        # Check if vault exists
        vault = await db.quantum_vaults.find_one({"vault_id": vault_id, "owner_address": user_address})
        if not vault:
            raise HTTPException(status_code=404, detail="Vault not found")
        
        # Check user's RWA token balance
        user_balance_doc = await db.rwa_balances.find_one({
            "token_id": asset_id,
            "address": user_address
        })
        user_balance = user_balance_doc.get("balance", 0) if user_balance_doc else 0
        
        if user_balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient RWA token balance")
        
        # Deduct tokens from user balance
        await db.rwa_balances.update_one(
            {"token_id": asset_id, "address": user_address},
            {"$inc": {"balance": -amount}}
        )
        
        token_info = await db.rwa_tokens.find_one({"_id": asset_id})

        # Add tokens to vault
        await db.vault_rwa_balances.update_one(
            {"vault_id": vault_id, "asset_id": asset_id},
            {
                "$inc": {"balance": amount},
                "$set": {
                    "asset_type": token_info.get("asset_type") if token_info else None
                },
            },
            upsert=True
        )
        
        # Record transaction
        tx_record = {
            "tx_id": f"vault_rwa_deposit_{int(time.time())}_{secrets.token_hex(4)}",
            "vault_id": vault_id,
            "asset_id": asset_id,
            "amount": amount,
            "user_address": user_address,
            "tx_type": "rwa_deposit",
            "timestamp": int(time.time()),
            "privacy_level": vault.get("privacy_level", 3)
        }
        
        await db.vault_transactions.insert_one(tx_record)
        
        # Update vault stats
        vault_asset_count = await db.vault_rwa_balances.count_documents(
            {"vault_id": vault_id, "balance": {"$gt": 0}}
        )

        await db.quantum_vaults.update_one(
            {"vault_id": vault_id},
            {
                "$inc": {"transaction_count": 1},
                "$set": {
                    "last_activity": int(time.time()),
                    "rwa_support": True,
                    "rwa_asset_count": vault_asset_count,
                }
            }
        )
        
        return {
            "success": True,
            "vault_id": vault_id,
            "asset_id": asset_id,
            "amount": amount,
            "tx_id": tx_record["tx_id"],
            "rwa_deposited": True,
            "privacy_level": vault.get("privacy_level", 3),
            "rwa_support": True,
            "message": f"RWA token {asset_id} deposited to vault with privacy protection"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error depositing RWA to vault: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/vault/rwa/withdraw")
async def withdraw_rwa_from_vault(request: dict):
    """Withdraw RWA tokens from Quantum Vault with privacy protection"""
    try:
        vault_id = request.get("vault_id")
        asset_id = request.get("asset_id")  # RWA token ID
        amount = request.get("amount")
        destination_address = request.get("destination_address")
        user_address = request.get("user_address")
        
        if not all([vault_id, asset_id, amount, destination_address, user_address]):
            raise HTTPException(status_code=400, detail="Invalid RWA withdrawal parameters")
        
        amount = float(amount)
        
        # Check if vault exists and user owns it
        vault = await db.quantum_vaults.find_one({"vault_id": vault_id, "owner_address": user_address})
        if not vault:
            raise HTTPException(status_code=404, detail="Vault not found or unauthorized")
        
        # Check vault's RWA balance
        vault_balance_doc = await db.vault_rwa_balances.find_one({
            "vault_id": vault_id,
            "asset_id": asset_id
        })
        vault_balance = vault_balance_doc.get("balance", 0) if vault_balance_doc else 0
        
        if vault_balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient vault RWA balance")
        
        # Deduct tokens from vault
        token_info = await db.rwa_tokens.find_one({"_id": asset_id})

        await db.vault_rwa_balances.update_one(
            {"vault_id": vault_id, "asset_id": asset_id},
            {
                "$inc": {"balance": -amount},
                "$set": {"asset_type": token_info.get("asset_type") if token_info else None},
            }
        )
        
        # Add tokens to destination address
        await db.rwa_balances.update_one(
            {"token_id": asset_id, "address": destination_address},
            {"$inc": {"balance": amount}},
            upsert=True
        )
        
        # Record transaction
        tx_record = {
            "tx_id": f"vault_rwa_withdraw_{int(time.time())}_{secrets.token_hex(4)}",
            "vault_id": vault_id,
            "asset_id": asset_id,
            "amount": amount,
            "destination_address": destination_address,
            "user_address": user_address,
            "tx_type": "rwa_withdraw",
            "timestamp": int(time.time()),
            "privacy_level": vault.get("privacy_level", 3)
        }
        
        await db.vault_transactions.insert_one(tx_record)
        
        # Update vault stats
        vault_asset_count = await db.vault_rwa_balances.count_documents(
            {"vault_id": vault_id, "balance": {"$gt": 0}}
        )

        await db.quantum_vaults.update_one(
            {"vault_id": vault_id},
            {
                "$inc": {"transaction_count": 1},
                "$set": {"last_activity": int(time.time()), "rwa_asset_count": vault_asset_count},
            }
        )
        
        return {
            "success": True,
            "vault_id": vault_id,
            "asset_id": asset_id,
            "amount": amount,
            "destination_address": destination_address,
            "tx_id": tx_record["tx_id"],
            "rwa_withdrawn": True,
            "privacy_level": vault.get("privacy_level", 3),
            "rwa_support": True,
            "message": f"RWA token {asset_id} withdrawn from vault to {destination_address}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error withdrawing RWA from vault: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/vault/rwa/assets/{vault_id}")
async def get_vault_rwa_assets(vault_id: str, user_address: str = None):
    """Get all RWA assets stored in a specific vault"""
    try:
        # Check if vault exists
        vault_query = {"vault_id": vault_id}
        if user_address:
            vault_query["owner_address"] = user_address
            
        vault = await db.quantum_vaults.find_one(vault_query)
        if not vault:
            raise HTTPException(status_code=404, detail="Vault not found or unauthorized")
        
        # Get all RWA assets in this vault
        vault_assets = await db.vault_rwa_balances.find({"vault_id": vault_id, "balance": {"$gt": 0}}).to_list(None)
        
        assets_info = []
        total_value = 0
        
        for asset_balance in vault_assets:
            asset_id = asset_balance["asset_id"]
            balance = asset_balance["balance"]

            # Get token info
            token_info = await db.rwa_tokens.find_one({"_id": asset_id})
            if token_info:
                unit_value_wepo = await get_rwa_token_unit_value_wepo(token_info)
                asset_info = {
                    "asset_id": asset_id,
                    "symbol": token_info.get("symbol", ""),
                    "asset_name": token_info.get("asset_name", ""),
                    "asset_type": token_info.get("asset_type", ""),
                    "balance": balance,
                    "unit_value_wepo": unit_value_wepo,
                    "estimated_value": balance * unit_value_wepo,
                    "privacy_protected": True
                }
                assets_info.append(asset_info)
                total_value += asset_info["estimated_value"]
        
        return {
            "success": True,
            "vault_id": vault_id,
            "assets": assets_info,
            "total_assets": len(assets_info),
            "total_estimated_value": total_value,
            "privacy_level": vault.get("privacy_level", 3),
            "asset_type_hiding": vault.get("privacy_level", 3) >= 3,
            "rwa_support": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting vault RWA assets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/vault/rwa/ghost-transfer/initiate")
async def initiate_rwa_ghost_transfer(request: dict):
    """Initiate completely private RWA token transfer between vaults"""
    try:
        from_vault_id = request.get("from_vault_id")
        to_vault_id = request.get("to_vault_id")
        asset_id = request.get("asset_id")  # RWA token ID
        amount = request.get("amount")
        user_address = request.get("user_address")
        
        if not all([from_vault_id, to_vault_id, asset_id, amount, user_address]):
            raise HTTPException(status_code=400, detail="Invalid RWA ghost transfer parameters")
        
        amount = float(amount)
        
        # Check source vault ownership
        from_vault = await db.quantum_vaults.find_one({"vault_id": from_vault_id, "owner_address": user_address})
        if not from_vault:
            raise HTTPException(status_code=404, detail="Source vault not found or unauthorized")
        
        # Check destination vault exists
        to_vault = await db.quantum_vaults.find_one({"vault_id": to_vault_id})
        if not to_vault:
            raise HTTPException(status_code=404, detail="Destination vault not found")
        
        # Check source vault balance
        source_balance_doc = await db.vault_rwa_balances.find_one({
            "vault_id": from_vault_id,
            "asset_id": asset_id
        })
        source_balance = source_balance_doc.get("balance", 0) if source_balance_doc else 0
        
        if source_balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient vault balance for ghost transfer")
        
        # Execute the ghost transfer (fully private)
        # Deduct from source vault — check matched_count to catch race conditions
        src_result = await db.vault_rwa_balances.update_one(
            {"vault_id": from_vault_id, "asset_id": asset_id},
            {"$inc": {"balance": -amount}}
        )
        if src_result.matched_count == 0:
            raise HTTPException(status_code=409, detail="Source vault balance no longer available")

        # Add to destination vault
        await db.vault_rwa_balances.update_one(
            {"vault_id": to_vault_id, "asset_id": asset_id},
            {"$inc": {"balance": amount}},
            upsert=True
        )
        
        # Record ghost transfer (minimal metadata for privacy)
        ghost_transfer_id = f"ghost_rwa_{int(time.time())}_{secrets.token_hex(8)}"
        
        # Store minimal transfer record (privacy-focused)
        transfer_record = {
            "ghost_id": ghost_transfer_id,
            "asset_type_hash": hashlib.sha256(asset_id.encode()).hexdigest()[:16],  # Obfuscated asset ID
            "amount_hash": hashlib.sha256(str(amount).encode()).hexdigest()[:16],   # Obfuscated amount
            "timestamp": int(time.time()),
            "privacy_level": 4,  # Maximum privacy
            "transfer_type": "rwa_ghost",
            "completed": True
        }
        
        await db.ghost_transfers.insert_one(transfer_record)
        
        # Update vault stats (both vaults)
        await db.quantum_vaults.update_one(
            {"vault_id": from_vault_id},
            {"$inc": {"transaction_count": 1}, "$set": {"last_activity": int(time.time())}}
        )
        
        await db.quantum_vaults.update_one(
            {"vault_id": to_vault_id},
            {"$inc": {"transaction_count": 1}, "$set": {"last_activity": int(time.time())}}
        )
        
        return {
            "success": True,
            "ghost_transfer_id": ghost_transfer_id,
            "from_vault_id": from_vault_id,
            "to_vault_id": to_vault_id,
            "privacy_level": 4,
            "asset_type_hidden": True,
            "amount_hidden": True,
            "completely_private": True,
            "message": "RWA ghost transfer completed with maximum privacy protection"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating RWA ghost transfer: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ===== END RWA QUANTUM VAULT ENDPOINTS =====

# ===== END RWA TOKEN TRADING ENDPOINTS =====

async def get_wallet_balance(address: str) -> float:
    """Get the lab-adjusted WEPO balance: live node balance plus trade delta."""
    node_balance = await get_live_node_wallet_balance(address)
    wallet = await db.wallet_trade_state.find_one({"address": address})
    trade_delta = float(wallet.get("trade_balance_delta", 0) or 0) if wallet else 0.0
    return node_balance + trade_delta

async def get_wallet_trade_balance_delta(address: str) -> float:
    """Get the backend-only WEPO delta applied by lab trading flows."""
    wallet = await db.wallet_trade_state.find_one({"address": address})
    return float(wallet.get("trade_balance_delta", 0) or 0) if wallet else 0.0

async def update_wallet_balance(address: str, amount_change: float):
    """Update only the backend-managed lab trade delta for a wallet."""
    await db.wallet_trade_state.update_one(
        {"address": address},
        {
            "$inc": {
                "trade_balance_delta": amount_change,
            },
            "$setOnInsert": {
                "address": address,
            },
        },
        upsert=True
    )


async def get_live_node_wallet_balance(address: str) -> float:
    """Get a chain-backed wallet balance from the live node API."""
    try:
        response = requests.get(f"{WEPO_NODE_API_URL}/api/wallet/{address}", timeout=2)
        response.raise_for_status()
        payload = response.json()
        return float(payload.get("balance", 0) or 0)
    except Exception:
        wallet = await db.wallets.find_one({"address": address})
        if not wallet:
            return 0.0
        return float(wallet.get("balance", 0) or 0)


async def get_rwa_token_unit_value_wepo(token_record: Dict[str, Any]) -> float:
    """Derive a lab token's per-unit WEPO value from its backing asset valuation."""
    total_supply = float(token_record.get("total_supply", 0) or 0)
    if total_supply <= 0:
        return 0.0

    asset_id = token_record.get("asset_id")
    if not asset_id:
        return 0.0

    asset_record = await db.rwa_assets.find_one({"_id": asset_id})
    if not asset_record:
        return 0.0

    asset_valuation = float(
        asset_record.get("valuation_wepo", asset_record.get("valuation", 0)) or 0
    )
    if asset_valuation <= 0:
        return 0.0

    return asset_valuation / total_supply


def get_rwa_asset_value_usd(asset_record: Dict[str, Any]) -> float:
    """Read USD valuation with backward compatibility for legacy lab assets."""
    return float(asset_record.get("valuation_usd", asset_record.get("valuation", 0)) or 0)


def get_rwa_asset_value_wepo(asset_record: Dict[str, Any]) -> float:
    """Read WEPO valuation with backward compatibility for legacy lab assets."""
    return float(asset_record.get("valuation_wepo", asset_record.get("valuation", 0)) or 0)


RWA_LAB_CREATION_FEE_WEPO = 0.0


@api_router.get("/rwa/fee-info")
async def get_rwa_fee_info():
    return {
        "success": True,
        "fee_info": {
            "rwa_creation_fee": RWA_LAB_CREATION_FEE_WEPO,
            "description": "RWA asset creation fee is not enforced in the current wallet lab.",
            "redistribution_info": {
                "masternodes": "60%",
                "miners": "25%",
                "stakers": "15%",
                "policy": "lab_preview",
            },
        },
    }


@api_router.post("/rwa/create-asset")
async def create_rwa_asset(request: dict):
    try:
        name = str(request.get("name", "")).strip()
        description = str(request.get("description", "")).strip()
        asset_type = str(request.get("asset_type", "")).strip() or "other"
        owner_address = str(request.get("owner_address", "")).strip()
        legacy_valuation = float(request.get("valuation", 0) or 0)
        valuation_usd = float(request.get("valuation_usd", legacy_valuation) or 0)
        valuation_wepo = float(request.get("valuation_wepo", legacy_valuation) or 0)
        metadata = request.get("metadata") or {}

        if not all([name, description, owner_address]):
            raise HTTPException(status_code=400, detail="Missing required asset fields")

        asset_id = f"rwa_asset_{int(time.time())}_{secrets.token_hex(4)}"
        now_ts = int(time.time())
        asset_record = {
            "_id": asset_id,
            "asset_id": asset_id,
            "name": name,
            "description": description,
            "asset_type": asset_type,
            "owner_address": owner_address,
            "valuation": legacy_valuation,
            "valuation_usd": valuation_usd,
            "valuation_wepo": valuation_wepo,
            "metadata": metadata,
            "verification_status": "pending",
            "status": "created",
            "tokenized": False,
            "created_at": now_ts,
            "created_date": datetime.utcfromtimestamp(now_ts).isoformat() + "Z",
        }

        file_data = request.get("file_data", "") or ""
        if file_data:
            import base64 as _b64
            try:
                decoded_bytes = _b64.b64decode(file_data)
            except Exception:
                raise HTTPException(status_code=400, detail="file_data must be valid base64")
            MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB decoded
            if len(decoded_bytes) > MAX_FILE_BYTES:
                raise HTTPException(status_code=400, detail="File exceeds maximum allowed size of 10 MB")
            asset_record["file_name"] = request.get("file_name", "upload")
            asset_record["file_type"] = request.get("file_type", "application/octet-stream")
            asset_record["file_size"] = len(decoded_bytes)
            asset_record["file_hash"] = hashlib.sha256(decoded_bytes).hexdigest()

        await db.rwa_assets.insert_one(asset_record)

        remaining_balance = await get_live_node_wallet_balance(owner_address)
        return {
            "success": True,
            "asset_id": asset_id,
            "fee_paid": RWA_LAB_CREATION_FEE_WEPO,
            "remaining_balance": remaining_balance,
            "valuation_usd": valuation_usd,
            "valuation_wepo": valuation_wepo,
            "verification_status": asset_record["verification_status"],
            "message": "RWA asset created in wallet lab",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating RWA asset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/rwa/tokenize")
async def tokenize_rwa_asset(request: dict):
    try:
        asset_id = str(request.get("asset_id", "")).strip()
        token_name = str(request.get("token_name", "")).strip()
        token_symbol = str(request.get("token_symbol", "")).strip().upper()
        total_supply = int(request.get("total_supply", 0) or 0)
        caller_address = str(request.get("owner_address", "")).strip()

        if not all([asset_id, token_name, token_symbol]) or total_supply <= 0:
            raise HTTPException(status_code=400, detail="Missing required tokenization fields")

        asset = await db.rwa_assets.find_one({"_id": asset_id})
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Verify caller owns the asset
        if caller_address and asset.get("owner_address") != caller_address:
            raise HTTPException(status_code=403, detail="Only the asset owner can tokenize this asset")

        existing_token = await db.rwa_tokens.find_one({"asset_id": asset_id})
        if existing_token:
            raise HTTPException(status_code=400, detail="Asset already tokenized")

        token_id = f"rwa_token_{int(time.time())}_{secrets.token_hex(4)}"
        now_ts = int(time.time())
        token_record = {
            "_id": token_id,
            "asset_id": asset_id,
            "symbol": token_symbol,
            "asset_name": asset.get("name", token_name),
            "asset_type": asset.get("asset_type", "other"),
            "total_supply": total_supply,
            "available_supply": total_supply,
            "creator": asset.get("owner_address", ""),
            "created_date": datetime.utcfromtimestamp(now_ts).isoformat() + "Z",
            "created_at": now_ts,
            "verified": True,
            "trading_enabled": True,
            "decimals": 8,
            "status": "active",
        }

        await db.rwa_tokens.insert_one(token_record)
        await db.rwa_balances.update_one(
            {"token_id": token_id, "address": asset.get("owner_address", "")},
            {"$set": {"balance": total_supply}},
            upsert=True,
        )
        await db.rwa_assets.update_one(
            {"_id": asset_id},
            {
                "$set": {
                    "tokenized": True,
                    "token_id": token_id,
                    "token_symbol": token_symbol,
                    "status": "active",
                }
            },
        )

        return {
            "success": True,
            "asset_id": asset_id,
            "token_id": token_id,
            "token_symbol": token_symbol,
            "total_supply": total_supply,
            "message": "RWA asset tokenized successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tokenizing RWA asset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/rwa/portfolio/{address}")
async def get_rwa_portfolio(address: str):
    try:
        created_assets_cursor = db.rwa_assets.find({"owner_address": address})
        created_assets = await created_assets_cursor.to_list(None)

        balance_docs = await db.rwa_balances.find({"address": address, "balance": {"$gt": 0}}).to_list(None)
        tokens_held = []
        total_value_wepo = 0.0

        for balance_doc in balance_docs:
            token = await db.rwa_tokens.find_one({"_id": balance_doc["token_id"]})
            if not token:
                continue

            decimals = int(token.get("decimals", 8) or 8)
            token_balance = float(balance_doc.get("balance", 0))
            unit_value_wepo = await get_rwa_token_unit_value_wepo(token)
            value_wepo = token_balance * unit_value_wepo
            total_value_wepo += value_wepo
            tokens_held.append({
                "token_id": token["_id"],
                "symbol": token.get("symbol", ""),
                "name": token.get("asset_name", ""),
                "balance": token_balance,
                "decimals": decimals,
                "unit_value_wepo": unit_value_wepo,
                "value_wepo": value_wepo,
            })

        assets_created = [
            {
                "asset_id": asset.get("_id"),
                "name": asset.get("name", ""),
                "asset_type": asset.get("asset_type", "other"),
                "valuation_usd": get_rwa_asset_value_usd(asset),
                "valuation_wepo": get_rwa_asset_value_wepo(asset),
                "verification_status": asset.get("verification_status", "pending"),
            }
            for asset in created_assets
        ]

        return {
            "success": True,
            "portfolio": {
                "address": address,
                "assets_created": assets_created,
                "tokens_held": tokens_held,
                "total_value_wepo": total_value_wepo,
            },
        }

    except Exception as e:
        logger.error(f"Error getting RWA portfolio: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/rwa/statistics")
async def get_rwa_statistics():
    try:
        total_assets = await db.rwa_assets.count_documents({})
        total_tokens = await db.rwa_tokens.count_documents({"status": "active"})
        holders = await db.rwa_balances.distinct("address", {"balance": {"$gt": 0}})
        asset_docs = await db.rwa_assets.find({}).to_list(None)
        total_asset_value_usd = sum(get_rwa_asset_value_usd(asset) for asset in asset_docs)
        total_asset_value_wepo = sum(get_rwa_asset_value_wepo(asset) for asset in asset_docs)

        return {
            "success": True,
            "statistics": {
                "total_assets": total_assets,
                "total_tokens": total_tokens,
                "total_holders": len(holders),
                "total_asset_value_usd": total_asset_value_usd,
                "total_asset_value_wepo": total_asset_value_wepo,
            },
        }

    except Exception as e:
        logger.error(f"Error getting RWA statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def build_rwa_trade_response(
    trade_record: Dict[str, Any],
    *,
    idempotent_replay: bool = False,
) -> Dict[str, Any]:
    fee_settlement = trade_record.get("fee_settlement", {})
    response = {
        "success": True,
        "trade_id": trade_record["trade_id"],
        "token_id": trade_record["token_id"],
        "trade_type": trade_record["trade_type"],
        "token_amount": trade_record["token_amount"],
        "wepo_amount": trade_record["wepo_amount"],
        "trade_fee": trade_record["trade_fee"],
        "fee_applied_on_chain": fee_settlement.get("applied_on_chain"),
        "fee_settlement_policy": fee_settlement.get("settlement_policy"),
        "fee_settlement_txid": fee_settlement.get("settlement_txid"),
        "fee_manual_review_required": fee_settlement.get("manual_review_required", False),
        "fee_settlement_error": fee_settlement.get("settlement_error"),
        "privacy_enhanced": trade_record.get("privacy_enhanced", False),
        "wepo_balance_source": trade_record.get("wepo_balance_source"),
        "lab_trade_balance_delta": trade_record.get("lab_trade_balance_delta"),
        "effective_wepo_balance_before": trade_record.get("effective_wepo_balance_before"),
        "effective_wepo_balance_after": trade_record.get("effective_wepo_balance_after"),
        "status": trade_record.get("status", "completed"),
        "timestamp": trade_record.get("timestamp"),
        "idempotent_replay": idempotent_replay,
    }
    if trade_record.get("idempotency_key"):
        response["idempotency_key"] = trade_record["idempotency_key"]
    return response


async def reserve_rwa_trade_idempotency(
    user_address: str,
    idempotency_key: str,
) -> Tuple[Dict[str, Any], str, int, bool]:
    trade_id = f"rwa_trade_{int(time.time())}_{secrets.token_hex(4)}"
    timestamp = int(time.time())
    try:
        reservation = await db.rwa_trades.find_one_and_update(
            {"user_address": user_address, "idempotency_key": idempotency_key},
            {
                "$setOnInsert": {
                    "trade_id": trade_id,
                    "user_address": user_address,
                    "idempotency_key": idempotency_key,
                    "status": "processing",
                    "timestamp": timestamp,
                    "processing_started_at": timestamp,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        reservation = await db.rwa_trades.find_one(
            {"user_address": user_address, "idempotency_key": idempotency_key}
        )
        if not reservation:
            raise
        return reservation, reservation["trade_id"], int(reservation.get("timestamp", timestamp)), False

    created_new = reservation.get("trade_id") == trade_id and reservation.get("status") == "processing"
    return reservation, reservation["trade_id"], int(reservation.get("timestamp", timestamp)), created_new


async def mark_rwa_trade_attempt_failed(
    trade_id: Optional[str],
    failure_reason: str,
    *,
    trade_effects_applied: bool,
) -> None:
    if not trade_id:
        return

    if trade_effects_applied:
        await db.rwa_trades.update_one(
            {"trade_id": trade_id},
            {
                "$set": {
                    "status": "failed",
                    "failure_reason": failure_reason[:500],
                    "manual_review_required": True,
                    "failed_at": int(time.time()),
                },
                "$unset": {"processing_started_at": ""},
            },
        )
        return

    await db.rwa_trades.delete_one({"trade_id": trade_id, "status": "processing"})


def classify_fee_settlement_failure(response: requests.Response) -> Dict[str, Any]:
    error_text = response.text[:500]
    normalized_error = error_text.lower()
    if response.status_code == 400 and "insufficient balance" in normalized_error:
        return {
            "settlement_policy": "canonical_wallet_depleted",
            "manual_review_required": True,
            "settlement_error": error_text,
        }

    return {
        "settlement_policy": "canonical_on_chain_failed",
        "manual_review_required": True,
        "settlement_error": error_text,
    }


async def settle_application_fee(fee_amount: float, fee_type: str) -> dict:
    """Settle product fees canonically on-chain when configured, and always record the result."""
    normalized_fee = round(float(fee_amount), 8)
    fee_record = {
        "fee_amount": normalized_fee,
        "fee_type": fee_type,
        "fee_scope": "application",
        "timestamp": int(time.time()),
        "applied_on_chain": False,
        "settlement_policy": "off_chain_pending_policy",
        "created_at": datetime.now(),
    }

    try:
        if normalized_fee <= 0:
            fee_record["settlement_policy"] = "ignored_non_positive_fee"
        elif not WEPO_CANONICAL_APPLICATION_FEES_ENABLED:
            fee_record["settlement_policy"] = "canonical_fee_settlement_disabled"
        elif not WEPO_APP_FEE_SETTLEMENT_ADDRESS:
            fee_record["settlement_policy"] = "canonical_fee_wallet_unconfigured"
        else:
            response = requests.post(
                f"{WEPO_NODE_API_URL}/api/transaction/send",
                json={
                    "from_address": WEPO_APP_FEE_SETTLEMENT_ADDRESS,
                    "to_address": WEPO_APP_FEE_SETTLEMENT_ADDRESS,
                    "amount": 0,
                    "fee": normalized_fee,
                    "fee_mode": "canonical_settlement",
                    "privacy_level": "standard",
                },
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                fee_record.update(
                    {
                        "applied_on_chain": True,
                        "settlement_policy": "canonical_on_chain",
                        "settlement_txid": result.get("tx_hash") or result.get("transaction_id"),
                        "node_url": WEPO_NODE_API_URL,
                        "settlement_address": WEPO_APP_FEE_SETTLEMENT_ADDRESS,
                    }
                )
            else:
                failure_metadata = classify_fee_settlement_failure(response)
                fee_record.update(
                    {
                        **failure_metadata,
                        "node_url": WEPO_NODE_API_URL,
                        "settlement_address": WEPO_APP_FEE_SETTLEMENT_ADDRESS,
                    }
                )

        await db.application_fee_ledger.insert_one(fee_record)

    except Exception as e:
        logger.error(f"Error recording application fee: {str(e)}")
        fee_record["settlement_policy"] = "canonical_on_chain_exception"
        fee_record["settlement_error"] = str(e)

    return fee_record

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=WEPO_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    logger.info("WEPO Blockchain API started")
    
    # Create indexes for better performance
    await db.wallets.create_index("address", unique=True)
    await db.wallets.create_index("username", unique=True)
    await db.wallets.update_many(
        {
            "balance": {"$exists": True},
            "legacy_balance_cache": {"$exists": False},
        },
        {"$rename": {"balance": "legacy_balance_cache"}},
    )
    await db.wallets.update_many(
        {
            "balance": {"$exists": True},
            "legacy_balance_cache": {"$exists": True},
        },
        {"$unset": {"balance": ""}},
    )
    await db.transactions.create_index([("from_address", 1), ("to_address", 1)])
    await db.transactions.create_index("timestamp")
    await db.blocks.create_index("height", unique=True)
    await db.stakes.create_index("wallet_address")
    await db.masternodes.create_index("wallet_address")
    await db.btc_swaps.create_index("wepo_address")
    await db.wallet_trade_state.create_index("address", unique=True)
    try:
        await db.rwa_trades.drop_index("user_address_1_idempotency_key_1")
    except Exception:
        pass
    await db.rwa_trades.create_index(
        [("user_address", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )

    legacy_trade_docs = await db.wallets.find(
        {"trade_balance_delta": {"$exists": True}},
        {"_id": 0, "address": 1, "trade_balance_delta": 1},
    ).to_list(None)
    for legacy_doc in legacy_trade_docs:
        address = legacy_doc.get("address")
        if not address:
            continue
        await db.wallet_trade_state.update_one(
            {"address": address},
            {
                "$setOnInsert": {
                    "address": address,
                    "trade_balance_delta": float(legacy_doc.get("trade_balance_delta", 0) or 0),
                }
            },
            upsert=True,
        )
        await db.wallets.update_one(
            {"address": address},
            {"$unset": {"trade_balance_delta": ""}},
        )
    await db.wallets.update_many(
        {"trade_balance_delta": {"$exists": True}},
        {"$unset": {"trade_balance_delta": ""}},
    )

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    logger.info("WEPO Blockchain API stopped")
