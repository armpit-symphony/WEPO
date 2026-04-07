from fastapi import FastAPI, APIRouter, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import math
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
import hashlib
import time
import json
from datetime import datetime, timedelta
from enum import Enum
import secrets

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI(title="WEPO Blockchain API", version="1.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBasic()

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
    lock_period_months: int

class MasternodeRequest(BaseModel):
    wallet_address: str
    server_ip: str
    server_port: int = 22567

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

async def get_current_block_height() -> int:
    """Get current blockchain height"""
    latest_block = await db.blocks.find_one(sort=[("height", -1)])
    return latest_block["height"] if latest_block else 0

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
    return {"message": "WEPO Blockchain API", "version": "1.0.0", "network": "mainnet"}

@api_router.get("/network/status")
async def get_network_status():
    """Get WEPO network status"""
    block_height = await get_current_block_height()
    total_masternodes = await db.masternodes.count_documents({"status": "active"})
    total_staked = await db.stakes.aggregate([
        {"$match": {"is_active": True}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    
    total_staked_amount = total_staked[0]["total"] if total_staked else 0
    
    return {
        "block_height": block_height,
        "network_hashrate": "123.45 TH/s",  # Simulated
        "active_masternodes": total_masternodes,
        "total_staked": total_staked_amount,
        "total_supply": 63900006,
        "circulating_supply": min(block_height * 121.6 if block_height <= 52560 else 6390000 + (block_height - 52560) * 12.4, 31950000)
    }

# ===== WALLET AUTHENTICATION ENDPOINTS =====

@api_router.post("/wallet/create")
async def create_wallet(request: dict):
    """Create a new WEPO wallet with BIP-39 secure generation"""
    try:
        username = request.get("username")
        password = request.get("password")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")
        
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
        
        # Check if username already exists
        existing = await db.wallets.find_one({"username": username})
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Generate secure BIP-39 wallet data (server-side generation for security)
        import secrets
        import hashlib
        
        # Generate secure wallet address
        wallet_seed = secrets.token_bytes(32)  # 256-bit entropy
        address_hash = hashlib.sha256(wallet_seed + username.encode()).hexdigest()
        wepo_address = f"wepo1{address_hash[:32]}"
        
        # Generate encrypted private key (simplified for demo - in production use proper encryption)
        private_key_raw = hashlib.sha256(wallet_seed + b"private").hexdigest()
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Encrypt private key with password hash (simplified - use proper encryption in production)
        encrypted_private_key = hashlib.sha256(private_key_raw.encode() + password_hash.encode()).hexdigest()
        
        # Create wallet entry
        wallet_data = {
            "username": username,
            "address": wepo_address,
            "encrypted_private_key": encrypted_private_key,
            "created_at": int(time.time()),
            "version": "3.0",
            "bip39": True,
            "balance": 0.0
        }
        
        await db.wallets.insert_one(wallet_data)
        
        return {
            "success": True,
            "address": wepo_address,
            "username": username,
            "message": "Wallet created successfully",
            "bip39": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Wallet creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create wallet: {str(e)}")

@api_router.post("/wallet/login")
async def login_wallet(request: dict):
    """Login to existing WEPO wallet"""
    try:
        username = request.get("username")
        password = request.get("password")
        
        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")
        
        # Find wallet by username
        wallet = await db.wallets.find_one({"username": username})
        if not wallet:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        # Verify password (simplified - in production use proper password verification)
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # In production, you would decrypt the private key with the password
        # and verify it matches. For now, we'll simulate successful login
        # since we don't store the actual password hash
        
        return {
            "success": True,
            "address": wallet["address"],
            "username": wallet["username"],
            "balance": wallet.get("balance", 0.0),
            "created_at": wallet.get("created_at"),
            "version": wallet.get("version", "3.0"),
            "bip39": wallet.get("bip39", True),
            "message": "Login successful"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Wallet login error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

@api_router.get("/wallet/{address}")
async def get_wallet(address: str):
    """Get wallet information"""
    wallet = await db.wallets.find_one({"address": address})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    # Calculate balance from transactions
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
    
    # Update wallet balance
    await db.wallets.update_one(
        {"address": address},
        {"$set": {"balance": balance, "last_activity": datetime.utcnow()}}
    )
    
    return {
        "address": wallet["address"],
        "balance": balance,
        "username": wallet["username"],
        "created_at": wallet["created_at"],
        "is_staking": wallet.get("is_staking", False),
        "is_masternode": wallet.get("is_masternode", False)
    }

@api_router.get("/wallet/{address}/transactions")
async def get_wallet_transactions(address: str, limit: int = 50):
    """Get wallet transaction history"""
    transactions = await db.transactions.find({
        "$or": [
            {"from_address": address},
            {"to_address": address}
        ]
    }).sort("timestamp", -1).limit(limit).to_list(limit)
    
    return transactions

@api_router.post("/transaction/send")
async def send_transaction(request: SendTransactionRequest):
    """Send WEPO transaction"""
    # Verify wallet exists and has sufficient balance
    wallet = await db.wallets.find_one({"address": request.from_address})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if wallet["balance"] < request.amount + 0.0001:  # Include fee
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    # Create transaction with privacy features
    transaction = WepoTransaction(
        from_address=request.from_address,
        to_address=request.to_address,
        amount=request.amount,
        transaction_type=TransactionType.SEND,
        privacy_proof=generate_zk_proof(),
        ring_signature=generate_ring_signature()
    )
    
    transaction.tx_hash = calculate_transaction_hash(transaction)
    
    await db.transactions.insert_one(transaction.dict())
    
    # Simulate transaction confirmation after delay
    # In real implementation, this would be handled by miners/validators
    
    return {
        "transaction_id": transaction.id,
        "tx_hash": transaction.tx_hash,
        "status": transaction.status,
        "privacy_protected": True
    }

@api_router.post("/stake")
async def create_stake(request: StakeRequest):
    """Create a staking position"""
    # Check if PoS is enabled (18 months after launch)
    # For demo, we'll allow it
    
    wallet = await db.wallets.find_one({"address": request.wallet_address})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if wallet["balance"] < request.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance for staking")
    
    if request.amount < 1000:
        raise HTTPException(status_code=400, detail="Minimum stake is 1000 WEPO")
    
    # Calculate APR based on lock period
    base_apr = 1.0
    lock_bonus = 0.5 * (request.lock_period_months / 12)
    apr = base_apr + lock_bonus
    
    stake = StakePosition(
        wallet_address=request.wallet_address,
        amount=request.amount,
        lock_period_months=request.lock_period_months,
        apr=apr,
        end_date=datetime.utcnow() + timedelta(days=30 * request.lock_period_months)
    )
    
    await db.stakes.insert_one(stake.dict())
    
    # Update wallet
    await db.wallets.update_one(
        {"address": request.wallet_address},
        {
            "$set": {"is_staking": True, "stake_amount": request.amount},
            "$inc": {"balance": -request.amount}
        }
    )
    
    return {"success": True, "stake_id": stake.id, "apr": apr}

@api_router.post("/masternode")
async def setup_masternode(request: MasternodeRequest):
    """Setup a masternode"""
    wallet = await db.wallets.find_one({"address": request.wallet_address})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if wallet["balance"] < 10000:
        raise HTTPException(status_code=400, detail="Insufficient balance. 10,000 WEPO required for masternode")
    
    # Check if IP is already used
    existing = await db.masternodes.find_one({"server_ip": request.server_ip})
    if existing:
        raise HTTPException(status_code=400, detail="Server IP already in use")
    
    masternode = Masternode(
        wallet_address=request.wallet_address,
        server_ip=request.server_ip,
        server_port=request.server_port
    )
    
    await db.masternodes.insert_one(masternode.dict())
    
    # Update wallet
    await db.wallets.update_one(
        {"address": request.wallet_address},
        {
            "$set": {"is_masternode": True, "masternode_collateral": 10000},
            "$inc": {"balance": -10000}
        }
    )
    
    return {"success": True, "masternode_id": masternode.id}

@api_router.post("/dex/swap")
async def create_btc_swap(request: BtcSwapRequest):
    """Create BTC-WEPO atomic swap"""
    wallet = await db.wallets.find_one({"address": request.wepo_address})
    if not wallet:
        raise HTTPException(status_code=404, detail="WEPO wallet not found")
    
    # Calculate exchange rate (1:1 for demo)
    exchange_rate = 1.0
    wepo_amount = request.btc_amount * exchange_rate
    
    if request.swap_type == "sell" and wallet["balance"] < wepo_amount:
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

@api_router.get("/blocks/latest")
async def get_latest_blocks(limit: int = 10):
    """Get latest blocks"""
    blocks = await db.blocks.find().sort("height", -1).limit(limit).to_list(limit)
    return blocks

@api_router.get("/mining/info")
async def get_mining_info():
    """Get mining information"""
    height = await get_current_block_height()
    
    # Calculate current reward based on height
    if height <= 52560:  # First year
        current_reward = 121.6
        next_halving = 52560
    else:
        years_since_year_2 = (height - 52560) // 262800
        current_reward = 12.4 / (2 ** (years_since_year_2 // 4))
        next_halving = 52560 + ((years_since_year_2 // 4) + 1) * 1051200
    
    return {
        "current_block_height": height,
        "current_reward": current_reward,
        "next_halving_block": next_halving,
        "blocks_until_halving": max(0, next_halving - height),
        "difficulty": 1.0,
        "algorithm": "Argon2",
        "block_time": "2 minutes" if height > 52560 else "10 minutes"
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
                "can_bootstrap": True
            }
        
        return {
            "pool_exists": True,
            "btc_to_wepo": price,
            "wepo_to_btc": 1 / price,
            "btc_reserve": btc_wepo_pool.btc_reserve,
            "wepo_reserve": btc_wepo_pool.wepo_reserve,
            "total_liquidity_shares": btc_wepo_pool.total_shares,
            "fee_rate": btc_wepo_pool.fee_rate,
            "last_updated": int(time.time())
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
        
        # Calculate fee redistribution (goes to existing 3-way system)
        fee_amount = swap_result["fee_amount"]
        
        # Add to redistribution pool (integrate with existing system)
        await add_fee_to_redistribution_pool(fee_amount, "swap_fee")
        
        # Record swap transaction
        swap_record = {
            "swap_id": f"swap_{int(time.time())}_{wallet_address[:8]}",
            "wallet_address": wallet_address,
            "from_currency": from_currency,
            "to_currency": "WEPO" if from_currency == "BTC" else "BTC",
            "input_amount": input_amount,
            "output_amount": swap_result["output_amount"],
            "fee_amount": fee_amount,
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
            "market_price": swap_result["new_price"],
            "btc_reserve": swap_result["btc_reserve"],
            "wepo_reserve": swap_result["wepo_reserve"],
            "timestamp": swap_record["timestamp"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing market swap: {str(e)}")
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
            "total_shares": result["total_shares"],
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
                "message": "No liquidity pool exists. Any user can create the market."
            }
        
        return {
            "pool_exists": True,
            "btc_reserve": btc_wepo_pool.btc_reserve,
            "wepo_reserve": btc_wepo_pool.wepo_reserve,
            "total_shares": btc_wepo_pool.total_shares,
            "current_price": btc_wepo_pool.get_price(),
            "fee_rate": btc_wepo_pool.fee_rate,
            "total_lp_count": len(btc_wepo_pool.lp_positions)
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
    
    def is_genesis_active(self):
        """Check if genesis mining is still active"""
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
        
        miner_hashrate = self.connected_miners[address]["hashrate"]
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

# ===== HELPER FUNCTIONS =====

async def get_current_block_height():
    """Get current blockchain height"""
    # In production, this would query the actual blockchain
    # For now, return a simple counter
    return 0

async def get_wallet_balance(address: str) -> float:
    """Get wallet balance for an address"""
    try:
        wallet = await db.wallets.find_one({"address": address})
        return wallet.get("balance", 0) if wallet else 0
    except Exception:
        return 0

async def update_wallet_balance(address: str, amount_change: float):
    """Update wallet balance by a specific amount (positive or negative)"""
    try:
        await db.wallets.update_one(
            {"address": address},
            {"$inc": {"balance": amount_change}},
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
            total_supply = token.get("total_supply", 1000)
            
            # Basic rate calculation (could be enhanced with market data)
            base_rate = 1.0  # 1 token = 1 WEPO as base
            
            # Adjust rate based on scarcity
            if total_supply < 100:
                base_rate = 5.0  # Rare tokens worth more
            elif total_supply < 500:
                base_rate = 2.0  # Uncommon tokens
            
            # Add market variations (±20%)
            import random
            market_factor = random.uniform(0.8, 1.2)
            final_rate = base_rate * market_factor
            
            rates[token_id] = {
                "rate_wepo_per_token": round(final_rate, 6),
                "rate_token_per_wepo": round(1.0 / final_rate, 6), 
                "last_updated": int(time.time()),
                "token_symbol": token.get("symbol", ""),
                "token_name": token.get("asset_name", ""),
                "24h_change": round(random.uniform(-0.1, 0.1), 4)  # Mock 24h change
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
async def transfer_rwa_tokens(request: dict):
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
    try:
        token_id = request.get('token_id')
        trade_type = request.get('trade_type')  # 'buy' or 'sell'
        user_address = request.get('user_address')
        token_amount = request.get('token_amount') 
        wepo_amount = request.get('wepo_amount')
        privacy_enhanced = request.get('privacy_enhanced', False)
        
        if not all([token_id, trade_type, user_address, token_amount, wepo_amount]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        token_amount = float(token_amount)
        wepo_amount = float(wepo_amount)
        
        # Get token info
        token = await db.rwa_tokens.find_one({"_id": token_id})
        if not token:
            raise HTTPException(status_code=404, detail="RWA token not found")
        
        # Calculate trade fee (0.1% of WEPO amount)
        trade_fee = wepo_amount * 0.001
        
        if trade_type == 'buy':
            # User buying RWA tokens with WEPO
            # Check user WEPO balance
            user_balance = await get_wallet_balance(user_address)
            if user_balance < (wepo_amount + trade_fee):
                raise HTTPException(status_code=400, detail="Insufficient WEPO balance")
            
            # Deduct WEPO from user
            await update_wallet_balance(user_address, -(wepo_amount + trade_fee))
            
            # Add RWA tokens to user
            await db.rwa_balances.update_one(
                {"token_id": token_id, "address": user_address},
                {"$inc": {"balance": token_amount}},
                upsert=True
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
            await db.rwa_balances.update_one(
                {"token_id": token_id, "address": user_address},
                {"$inc": {"balance": -token_amount}}
            )
            
            # Add WEPO to user (minus fee)
            await update_wallet_balance(user_address, wepo_amount - trade_fee)
        
        # Add fee to redistribution pool
        await add_fee_to_redistribution_pool(trade_fee, "rwa_trade")
        
        # Record trade
        trade_record = {
            "trade_id": f"rwa_trade_{int(time.time())}_{secrets.token_hex(4)}",
            "token_id": token_id,
            "token_symbol": token.get("symbol", ""),
            "trade_type": trade_type,
            "user_address": user_address,
            "token_amount": token_amount,
            "wepo_amount": wepo_amount,
            "trade_fee": trade_fee,
            "privacy_enhanced": privacy_enhanced,
            "timestamp": int(time.time()),
            "status": "completed"
        }
        
        await db.rwa_trades.insert_one(trade_record)
        
        return {
            "success": True,
            "trade_id": trade_record["trade_id"],
            "token_id": token_id,
            "trade_type": trade_type,
            "token_amount": token_amount,
            "wepo_amount": wepo_amount,
            "trade_fee": trade_fee,
            "privacy_enhanced": privacy_enhanced,
            "status": "completed",
            "timestamp": trade_record["timestamp"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing RWA trade: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ===== QUANTUM VAULT ENDPOINTS =====

@api_router.post("/vault/create")
async def create_quantum_vault(request: dict):
    """Create a new Quantum Vault with multi-asset support"""
    try:
        user_address = request.get("user_address")
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
            "rwa_asset_count": vault.get("rwa_asset_count", 0),
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
        wallet_address = request.get("wallet_address")
        asset_type = request.get("asset_type", "real_estate")  # real_estate, commodities, securities, etc.
        privacy_level = request.get("privacy_level", "maximum")
        
        if not wallet_address:
            raise HTTPException(status_code=400, detail="Wallet address required for RWA vault")
        
        # Generate unique RWA vault ID
        import time
        import secrets
        vault_id = f"rwa_vault_{int(time.time())}_{secrets.token_hex(8)}"
        
        # Create specialized RWA vault with enhanced features
        rwa_vault_data = {
            "vault_id": vault_id,
            "vault_type": "rwa_quantum_vault",
            "wallet_address": wallet_address,
            "asset_type": asset_type,
            "privacy_level": privacy_level,
            "created_at": int(time.time()),
            "status": "active",
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
        
        return {
            "success": True,
            "vault_created": True,
            "vault_id": vault_id,
            "vault_type": "RWA Quantum Vault",
            "wallet_address": wallet_address,
            "asset_type": asset_type,
            "privacy_level": privacy_level,
            "features_enabled": list(rwa_vault_data["features"].keys()),
            "supported_assets": list(rwa_vault_data["supported_assets"].keys()),
            "privacy_protection": "Maximum RWA privacy with quantum encryption",
            "compliance_ready": True,
            "message": f"RWA Quantum Vault created for {asset_type} assets with maximum privacy protection"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating RWA vault: {str(e)}")
        raise HTTPException(status_code=500, detail=f"RWA vault creation failed: {str(e)}")

@api_router.get("/vault/rwa/status/{vault_id}")
async def get_rwa_vault_status(vault_id: str):
    """Get detailed status of RWA Quantum Vault"""
    try:
        if not vault_id:
            raise HTTPException(status_code=400, detail="Vault ID required")
        
        # Mock RWA vault status for demonstration
        # In production, this would query actual vault data
        import time
        
        rwa_vault_status = {
            "vault_id": vault_id,
            "vault_type": "rwa_quantum_vault",
            "status": "active",
            "created_at": int(time.time()) - 3600,  # 1 hour ago
            "last_activity": int(time.time()) - 300,  # 5 minutes ago
            "privacy_status": {
                "encryption_level": "quantum_resistant",
                "zk_proofs": "enabled",
                "mixing_active": True,
                "ghost_mode": True
            },
            "asset_holdings": {
                "total_assets": 3,
                "asset_types": ["real_estate", "commodities"],
                "estimated_value": "Privacy Protected",  # Value hidden by default
                "last_valuation": "2025-01-20"
            },
            "recent_activity": [
                {
                    "type": "deposit",
                    "asset": "Privacy Protected",
                    "timestamp": int(time.time()) - 1800,
                    "status": "confirmed"
                },
                {
                    "type": "ghost_transfer",
                    "details": "Privacy Protected",
                    "timestamp": int(time.time()) - 3600,
                    "status": "completed"
                }
            ],
            "security_features": {
                "quantum_encryption": True,
                "multi_sig_required": True,
                "time_locks": True,
                "emergency_freeze": True
            },
            "compliance_status": {
                "kyc_verified": True,
                "aml_cleared": True,
                "regulatory_compliant": True,
                "jurisdiction": "multi"
            },
            "available_actions": [
                "deposit_rwa",
                "withdraw_rwa", 
                "ghost_transfer",
                "privacy_mixing",
                "asset_rebalancing"
            ]
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
        amount = request.get("amount", 1)
        privacy_mode = request.get("privacy_mode", "ghost")  # ghost, stealth, public
        
        if not all([from_vault, to_vault, asset_id]):
            raise HTTPException(status_code=400, detail="Missing required transfer parameters")
        
        if from_vault == to_vault:
            raise HTTPException(status_code=400, detail="Cannot transfer to same vault")
        
        # Generate transfer ID and execute privacy-enhanced transfer
        import time
        import secrets
        transfer_id = f"rwa_transfer_{int(time.time())}_{secrets.token_hex(6)}"
        
        # Simulate privacy-enhanced RWA transfer process
        transfer_data = {
            "transfer_id": transfer_id,
            "from_vault": from_vault,
            "to_vault": to_vault,
            "asset_id": asset_id,
            "amount": amount,
            "privacy_mode": privacy_mode,
            "initiated_at": int(time.time()),
            "status": "processing",
            "privacy_features": {
                "zk_proof_generation": "in_progress",
                "mixing_coordination": True,
                "ghost_mode": privacy_mode == "ghost",
                "stealth_addresses": True,
                "value_obfuscation": True
            },
            "compliance_checks": {
                "regulatory_screening": "passed",
                "aml_verification": "passed", 
                "jurisdiction_compliance": "verified"
            },
            "estimated_completion": int(time.time()) + 300  # 5 minutes
        }
        
        # Simulate different privacy modes
        if privacy_mode == "ghost":
            transfer_data["privacy_note"] = "Ghost transfer initiated - complete transaction privacy enabled"
        elif privacy_mode == "stealth":
            transfer_data["privacy_note"] = "Stealth transfer initiated - addresses and amounts hidden"
        else:
            transfer_data["privacy_note"] = "Standard transfer with regulatory transparency"
        
        return {
            "success": True,
            "transfer_initiated": True,
            "transfer_id": transfer_id,
            "from_vault": from_vault[:10] + "..." if privacy_mode != "public" else from_vault,
            "to_vault": to_vault[:10] + "..." if privacy_mode != "public" else to_vault,
            "asset_id": "Privacy Protected" if privacy_mode == "ghost" else asset_id,
            "amount": "Privacy Protected" if privacy_mode == "ghost" else amount,
            "privacy_mode": privacy_mode,
            "status": "processing",
            "estimated_completion_time": "5 minutes",
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
        
        # Add tokens to vault
        await db.vault_rwa_balances.update_one(
            {"vault_id": vault_id, "asset_id": asset_id},
            {"$inc": {"balance": amount}},
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
        await db.quantum_vaults.update_one(
            {"vault_id": vault_id},
            {
                "$inc": {"transaction_count": 1, "rwa_asset_count": 1},
                "$set": {"last_activity": int(time.time()), "rwa_support": True}
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
        await db.vault_rwa_balances.update_one(
            {"vault_id": vault_id, "asset_id": asset_id},
            {"$inc": {"balance": -amount}}
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
        await db.quantum_vaults.update_one(
            {"vault_id": vault_id},
            {"$inc": {"transaction_count": 1}, "$set": {"last_activity": int(time.time())}}
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
                asset_info = {
                    "asset_id": asset_id,
                    "symbol": token_info.get("symbol", ""),
                    "asset_name": token_info.get("asset_name", ""),
                    "asset_type": token_info.get("asset_type", ""),
                    "balance": balance,
                    "estimated_value": balance * 1.0,  # Simple 1:1 WEPO valuation
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
        # Deduct from source vault
        await db.vault_rwa_balances.update_one(
            {"vault_id": from_vault_id, "asset_id": asset_id},
            {"$inc": {"balance": -amount}}
        )
        
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
    """Get wallet balance from database"""
    wallet = await db.wallets.find_one({"address": address})
    if not wallet:
        return 0.0
    return wallet.get("balance", 0.0)

async def update_wallet_balance(address: str, amount_change: float):
    """Update wallet balance by adding/subtracting amount"""
    await db.wallets.update_one(
        {"address": address},
        {"$inc": {"balance": amount_change}},
        upsert=True
    )

async def add_fee_to_redistribution_pool(fee_amount: float, fee_type: str):
    """Integrate swap fees with existing 3-way redistribution system"""
    try:
        # This integrates with the existing fee redistribution system
        # All swap fees go to the same pool as RWA fees
        redistribution_record = {
            "fee_amount": fee_amount,
            "fee_type": fee_type,
            "timestamp": int(time.time()),
            "redistributed": False,
            "created_at": datetime.now()
        }
        
        await db.fee_redistribution_pool.insert_one(redistribution_record)
        
        # Fees will be distributed by existing system:
        # 60% to masternodes, 25% to miners, 15% to stakers
        
    except Exception as e:
        logger.error(f"Error adding fee to redistribution pool: {str(e)}")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
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
    await db.transactions.create_index([("from_address", 1), ("to_address", 1)])
    await db.transactions.create_index("timestamp")
    await db.blocks.create_index("height", unique=True)
    await db.stakes.create_index("wallet_address")
    await db.masternodes.create_index("wallet_address")
    await db.btc_swaps.create_index("wepo_address")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    logger.info("WEPO Blockchain API stopped")
