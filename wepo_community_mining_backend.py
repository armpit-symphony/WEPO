#!/usr/bin/env python3
"""
WEPO Community Mining Software
Backend mining coordination and dual-layer mining system
"""

import asyncio
import hashlib
import time
import json
import random
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Import existing WEPO components
# import sys
# import os
# sys.path.append(os.path.join(os.path.dirname(__file__), 'wepo-blockchain'))

@dataclass
class MinerInfo:
    """Information about a connected miner"""
    address: str
    wallet_type: str  # 'regular' or 'quantum'
    mining_mode: str  # 'genesis' or 'pow'
    connected_time: float
    hash_rate: float = 0.0
    is_mining: bool = False
    last_activity: float = 0.0

@dataclass
class MiningStats:
    """Global mining statistics"""
    connected_miners: int = 0
    total_hash_rate: float = 0.0
    genesis_status: str = 'waiting'  # 'waiting', 'active', 'found'
    current_phase: str = 'Phase 1'
    block_reward: float = 52.51  # CORRECTED: Aligned with new tokenomics (was 400.0)
    difficulty: str = '0x1d00ffff'
    blocks_mined: int = 0

class DualLayerMiningEngine:
    """Implements the dual-layer mining system (60% Argon2, 40% SHA-256)"""
    
    def __init__(self):
        self.argon2_difficulty = 0x1d00ffff  # CPU/GPU friendly
        self.sha256_difficulty = 0x1d00ffff  # ASIC friendly
        self.argon2_reward_ratio = 0.6  # 60% of rewards
        self.sha256_reward_ratio = 0.4  # 40% of rewards
        
    def calculate_hash_argon2(self, data: bytes, nonce: int) -> str:
        """Calculate Argon2-style hash (CPU/GPU friendly)"""
        # Simplified Argon2-like hashing for demonstration
        # In production, use actual Argon2 implementation
        input_data = data + nonce.to_bytes(8, 'big')
        
        # Multiple rounds to simulate memory-hard computation
        hash_result = input_data
        for _ in range(100):  # Memory-hard iterations
            hash_result = hashlib.sha256(hash_result).digest()
            hash_result = hashlib.blake2b(hash_result).digest()
        
        return hash_result.hex()
    
    def calculate_hash_sha256(self, data: bytes, nonce: int) -> str:
        """Calculate SHA-256 hash (ASIC friendly)"""
        input_data = data + nonce.to_bytes(8, 'big')
        return hashlib.sha256(hashlib.sha256(input_data).digest()).hexdigest()
    
    def get_mining_algorithm(self, miner_type: str) -> str:
        """Determine which algorithm to use based on miner preference"""
        # Wallet miners default to Argon2 (CPU/GPU friendly)
        # Can be configured by miner
        return 'argon2'  # Default for wallet miners
    
    def calculate_reward_share(self, algorithm: str, hash_rate: float) -> float:
        """Calculate reward share based on algorithm and hash rate"""
        if algorithm == 'argon2':
            base_reward = self.argon2_reward_ratio
            # Wallet miners get steady rewards
            efficiency_multiplier = 1.0
        else:  # sha256
            base_reward = self.sha256_reward_ratio
            # ASIC miners get higher efficiency (4-6x advantage)
            efficiency_multiplier = 5.0
        
        # Calculate proportional share
        return base_reward * efficiency_multiplier * hash_rate

class CommunityMiningCoordinator:
    """Coordinates community mining for both genesis and post-genesis"""
    
    def __init__(self):
        self.miners: Dict[str, MinerInfo] = {}
        self.stats = MiningStats()
        self.dual_layer_engine = DualLayerMiningEngine()
        
        # genesis date 3pm EST = 8pm UTC
        launch_datetime = datetime(2025, 12, 25, 20, 0, 0, tzinfo=timezone.utc)
        self.LAUNCH_TIMESTAMP = int(launch_datetime.timestamp())
        
        # Genesis mining state
        self.genesis_found = False
        self.genesis_block = None
        self.mining_active = False
        
        # Background tasks
        self.stats_update_task = None
        
    def start_coordinator(self):
        """Start the mining coordinator"""
        print("🚀 WEPO Community Mining Coordinator Started")
        print(f"   Christmas Launch: {datetime.fromtimestamp(self.LAUNCH_TIMESTAMP, timezone.utc)}")
        
        # Don't start the async task here - it will be started when needed
        # The FastAPI app will handle the async context
        pass
    
    async def start_background_tasks(self):
        """Start background tasks when in async context"""
        if not self.stats_update_task:
            self.stats_update_task = asyncio.create_task(self._update_stats_loop())
    
    async def _update_stats_loop(self):
        """Background task to update mining statistics"""
        while True:
            try:
                await self._update_global_stats()
                await asyncio.sleep(1)  # Update every second
            except Exception as e:
                print(f"Stats update error: {e}")
                await asyncio.sleep(5)
    
    async def _update_global_stats(self):
        """Update global mining statistics"""
        current_time = time.time()
        
        # Count active miners and calculate total hash rate
        active_miners = 0
        total_hash_rate = 0.0
        
        for miner in self.miners.values():
            if miner.is_mining and (current_time - miner.last_activity < 30):
                active_miners += 1
                total_hash_rate += miner.hash_rate
        
        self.stats.connected_miners = active_miners
        self.stats.total_hash_rate = total_hash_rate
        
        # Check if genesis mining should be active
        if not self.genesis_found and current_time >= self.LAUNCH_TIMESTAMP:
            if self.stats.genesis_status == 'waiting':
                self.stats.genesis_status = 'active'
                self.mining_active = True
                print("🚀 GENESIS MINING ACTIVATED!")
    
    async def connect_miner(self, address: str, mining_mode: str, wallet_type: str) -> dict:
        """Connect a new miner to the network"""
        try:
            miner_info = MinerInfo(
                address=address,
                wallet_type=wallet_type,
                mining_mode=mining_mode,
                connected_time=time.time(),
                last_activity=time.time()
            )
            
            self.miners[address] = miner_info
            
            print(f"⛏️ Miner connected: {address[:20]}... ({wallet_type} wallet, {mining_mode} mode)")
            
            return {
                "status": "connected",
                "miner_id": address,
                "mining_mode": mining_mode,
                "genesis_status": self.stats.genesis_status,
                "launch_timestamp": self.LAUNCH_TIMESTAMP
            }
            
        except Exception as e:
            print(f"Miner connection error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def start_mining(self, address: str) -> dict:
        """Start mining for a specific miner"""
        if address not in self.miners:
            raise HTTPException(status_code=404, detail="Miner not connected")
        
        miner = self.miners[address]
        
        # Check if genesis mining is allowed
        if miner.mining_mode == 'genesis':
            if self.stats.genesis_status != 'active':
                raise HTTPException(
                    status_code=400, 
                    detail="Genesis mining not active yet. Wait for launch time."
                )
            if self.genesis_found:
                raise HTTPException(
                    status_code=400, 
                    detail="Genesis block already found. Mining has transitioned to PoW."
                )
        
        miner.is_mining = True
        miner.last_activity = time.time()
        
        # Start mining simulation
        asyncio.create_task(self._simulate_mining(address))
        
        print(f"🚀 Mining started: {address[:20]}... ({miner.mining_mode} mode)")
        
        return {
            "status": "mining_started",
            "miner_id": address,
            "mining_mode": miner.mining_mode,
            "algorithm": self.dual_layer_engine.get_mining_algorithm(miner.wallet_type)
        }
    
    async def stop_mining(self, address: str) -> dict:
        """Stop mining for a specific miner"""
        if address not in self.miners:
            raise HTTPException(status_code=404, detail="Miner not found")
        
        miner = self.miners[address]
        miner.is_mining = False
        miner.hash_rate = 0.0
        
        print(f"⏹️ Mining stopped: {address[:20]}...")
        
        return {
            "status": "mining_stopped",
            "miner_id": address
        }
    
    async def _simulate_mining(self, address: str):
        """Simulate mining activity for a miner"""
        miner = self.miners.get(address)
        if not miner:
            return
        
        try:
            while miner.is_mining:
                # Simulate hash rate based on wallet type and algorithm
                if miner.wallet_type == 'quantum':
                    # Quantum wallets might have slightly different characteristics
                    base_rate = random.uniform(1000, 5000)  # 1-5 KH/s
                else:
                    base_rate = random.uniform(800, 4000)   # 0.8-4 KH/s
                
                # Add some randomness to simulate real mining
                miner.hash_rate = base_rate * random.uniform(0.8, 1.2)
                miner.last_activity = time.time()
                
                # Simulate finding blocks (very rare for demonstration)
                if random.random() < 0.0001:  # 0.01% chance per iteration
                    await self._handle_block_found(address)
                
                await asyncio.sleep(2)  # Update every 2 seconds
                
        except Exception as e:
            print(f"Mining simulation error for {address}: {e}")
        finally:
            if miner:
                miner.is_mining = False
                miner.hash_rate = 0.0
    
    async def _handle_block_found(self, miner_address: str):
        """Handle when a miner finds a block"""
        miner = self.miners.get(miner_address)
        if not miner:
            return
        
        if miner.mining_mode == 'genesis' and not self.genesis_found:
            # Genesis block found!
            self.genesis_found = True
            self.stats.genesis_status = 'found'
            self.mining_active = False
            
            print(f"🎉 GENESIS BLOCK FOUND by {miner_address[:20]}...")
            print("🎄 WEPO BLOCKCHAIN IS NOW LIVE!")
            
            # Transition all miners to PoW mode
            for m in self.miners.values():
                m.mining_mode = 'pow'
            
        else:
            # Regular PoW block found
            self.stats.blocks_mined += 1
            reward = self.dual_layer_engine.calculate_reward_share(
                self.dual_layer_engine.get_mining_algorithm(miner.wallet_type),
                miner.hash_rate
            )
            
            print(f"⛏️ Block #{self.stats.blocks_mined} found by {miner_address[:20]}... (Reward: {reward:.4f} WEPO)")
    
    def get_mining_status(self) -> dict:
        """Get current mining status"""
        current_time = time.time()
        time_to_launch = max(0, self.LAUNCH_TIMESTAMP - current_time)
        
        return {
            "genesis_status": self.stats.genesis_status,
            "connected_miners": self.stats.connected_miners,
            "total_hash_rate": self.stats.total_hash_rate,
            "difficulty": self.stats.difficulty,
            "block_reward": self.stats.block_reward,
            "mining_phase": self.stats.current_phase,
            "blocks_mined": self.stats.blocks_mined,
            "time_to_launch": time_to_launch,
            "launch_timestamp": self.LAUNCH_TIMESTAMP,
            "mining_active": self.mining_active
        }
    
    def get_miner_stats(self, address: str) -> dict:
        """Get statistics for a specific miner"""
        if address not in self.miners:
            raise HTTPException(status_code=404, detail="Miner not found")
        
        miner = self.miners[address]
        algorithm = self.dual_layer_engine.get_mining_algorithm(miner.wallet_type)
        
        return {
            "address": address,
            "hash_rate": miner.hash_rate,
            "is_mining": miner.is_mining,
            "mining_mode": miner.mining_mode,
            "algorithm": algorithm,
            "connected_time": miner.connected_time,
            "wallet_type": miner.wallet_type,
            "estimated_time": self._estimate_block_time(miner.hash_rate),
            "connected_miners": self.stats.connected_miners
        }
    
    def _estimate_block_time(self, hash_rate: float) -> Optional[float]:
        """Estimate time to find a block based on hash rate"""
        if hash_rate <= 0:
            return None
        
        # Very rough estimation for demonstration
        # Real implementation would use network difficulty
        difficulty_factor = 1000000  # Simplified difficulty
        estimated_seconds = difficulty_factor / max(hash_rate, 1)
        
        return min(estimated_seconds, 86400)  # Cap at 24 hours

# Global mining coordinator instance
mining_coordinator = CommunityMiningCoordinator()

# Pydantic models for API
class ConnectMinerRequest(BaseModel):
    address: str
    mining_mode: str  # 'genesis' or 'pow'
    wallet_type: str  # 'regular' or 'quantum'

class StartMiningRequest(BaseModel):
    address: str

class StopMiningRequest(BaseModel):
    address: str

# API endpoints for mining integration
def setup_mining_routes(app: FastAPI):
    """Set up mining routes in the main FastAPI app"""
    
    @app.get("/api/mining/status")
    async def get_mining_status():
        """Get current mining status"""
        # Start background tasks if not already started
        if not mining_coordinator.stats_update_task:
            await mining_coordinator.start_background_tasks()
        
        return mining_coordinator.get_mining_status()
    
    @app.post("/api/mining/connect")
    async def connect_miner(request: ConnectMinerRequest):
        """Connect a miner to the network"""
        return await mining_coordinator.connect_miner(
            request.address, 
            request.mining_mode, 
            request.wallet_type
        )
    
    @app.post("/api/mining/start")
    async def start_mining(request: StartMiningRequest):
        """Start mining for a miner"""
        return await mining_coordinator.start_mining(request.address)
    
    @app.post("/api/mining/stop")
    async def stop_mining(request: StopMiningRequest):
        """Stop mining for a miner"""
        return await mining_coordinator.stop_mining(request.address)
    
    @app.get("/api/mining/stats/{address}")
    async def get_miner_stats(address: str):
        """Get mining statistics for a specific miner"""
        return mining_coordinator.get_miner_stats(address)
    
    @app.get("/api/mining/leaderboard")
    async def get_mining_leaderboard():
        """Get mining leaderboard"""
        miners = []
        for address, miner in mining_coordinator.miners.items():
            if miner.is_mining:
                miners.append({
                    "address": address[:10] + "..." + address[-6:],
                    "hash_rate": miner.hash_rate,
                    "algorithm": mining_coordinator.dual_layer_engine.get_mining_algorithm(miner.wallet_type),
                    "wallet_type": miner.wallet_type
                })
        
        miners.sort(key=lambda x: x['hash_rate'], reverse=True)
        return {"miners": miners[:20]}  # Top 20 miners

if __name__ == "__main__":
    print("🚀 WEPO Community Mining Software")
    print("=" * 50)
    
    # Initialize mining coordinator
    mining_coordinator.start_coordinator()
    
    # For testing - create a simple FastAPI app
    app = FastAPI(title="WEPO Community Mining API")
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    setup_mining_routes(app)
    
    @app.get("/")
    async def root():
        return {
            "message": "WEPO Community Mining API",
            "genesis_launch": "TBD pending production readiness",
            "status": mining_coordinator.get_mining_status()
        }
    
    uvicorn.run(app, host="0.0.0.0", port=8002)
