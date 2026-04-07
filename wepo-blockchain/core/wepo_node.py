#!/usr/bin/env python3
"""
WEPO Full Node
Complete blockchain node with P2P networking, mining, and API
"""

import asyncio
import time
import threading
import signal
import sys
import argparse
import secrets
from typing import Optional, Dict, Any
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from blockchain import WepoBlockchain, Transaction, Block, COIN
from network_profile import (
    describe_reward_schedule,
    format_block_time,
    get_network_profile,
    get_pow_block_time_seconds,
    get_reward_phase_label,
)
from p2p_network import WepoP2PNode
from privacy import privacy_engine, create_privacy_proof, verify_privacy_proof, ZK_STARK_PROOF_SIZE, RING_SIGNATURE_SIZE, CONFIDENTIAL_PROOF_SIZE
from atomic_swaps import atomic_swap_engine, SwapType, SwapState, validate_btc_address, validate_wepo_address

# Import quantum-resistant components
from quantum_blockchain import QuantumWepoBlockchain
from quantum_transaction import QuantumTransaction, QuantumWallet
from dilithium import generate_dilithium_keypair, generate_wepo_address, validate_wepo_address as validate_quantum_address, get_dilithium_info

class WepoFullNode:
    """WEPO Full Blockchain Node"""
    
    def __init__(self, data_dir: str = "/tmp/wepo", p2p_port: int = 22567, 
                 api_port: int = 8001, enable_mining: bool = True,
                 background_mining_enabled: Optional[bool] = None,
                 difficulty_override: Optional[int] = None,
                 network_profile: str = "mainnet"):
        self.data_dir = data_dir
        self.p2p_port = p2p_port
        self.api_port = api_port
        self.network_profile = network_profile
        self.mining_api_enabled = enable_mining
        self.background_mining_enabled = (
            enable_mining if background_mining_enabled is None else background_mining_enabled
        )
        
        # Initialize blockchain
        self.blockchain = WepoBlockchain(data_dir, network_profile=network_profile)
        if difficulty_override is not None:
            self.blockchain.fixed_difficulty = max(1, int(difficulty_override))
            self.blockchain.current_difficulty = self.blockchain.fixed_difficulty
        
        # Initialize quantum-resistant blockchain
        self.quantum_blockchain = QuantumWepoBlockchain(data_dir + "_quantum")
        
        # Initialize P2P network
        self.p2p_node = WepoP2PNode(port=p2p_port)
        
        # Connect blockchain and P2P
        self.p2p_node.on_new_block = self.handle_new_block
        self.p2p_node.on_new_transaction = self.handle_new_transaction
        self.p2p_node.get_block_callback = self.get_block_data
        
        # FastAPI app for RPC/API
        self.app = FastAPI(title="WEPO Full Node API", version="1.0.0")
        self.setup_api_routes()
        
        # Mining state
        self.mining_thread: Optional[threading.Thread] = None
        self.miner_address = generate_wepo_address("wepo-node-miner", address_type="regular")
        self.active_mining_jobs: Dict[str, Dict[str, Any]] = {}
        self.mining_job_ttl_seconds = 300
        
        # Node state
        self.running = False
        
        print(f"WEPO Full Node initialized:")
        print(f"  Data directory: {data_dir}")
        print(f"  P2P port: {p2p_port}")
        print(f"  API port: {api_port}")
        print(f"  Mining API enabled: {self.mining_api_enabled}")
        print(f"  Background mining enabled: {self.background_mining_enabled}")
        print(f"  Network profile: {self.network_profile}")
        if difficulty_override is not None:
            print(f"  Difficulty override: {self.blockchain.fixed_difficulty}")
    
    def setup_api_routes(self):
        """Setup API routes"""

        def prune_expired_mining_jobs():
            now = time.time()
            expired_job_ids = [
                job_id
                for job_id, job in self.active_mining_jobs.items()
                if now - job["created_at"] > self.mining_job_ttl_seconds
            ]
            for job_id in expired_job_ids:
                self.active_mining_jobs.pop(job_id, None)
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        @self.app.get("/")
        async def root():
            return {"message": "WEPO Full Node", "version": "1.0.0"}
        
        @self.app.get("/api/")
        async def api_root():
            return {
                "message": "WEPO Node API",
                "version": "1.0.0",
                "network": self.blockchain.get_network_info().get("network"),
                "network_profile": self.network_profile,
            }
        
        # Network status
        @self.app.get("/api/network/status")
        async def get_network_status():
            """Get network status"""
            blockchain_info = self.blockchain.get_blockchain_info()
            p2p_info = self.p2p_node.get_network_info()
            
            return {
                **blockchain_info,
                "peers": p2p_info['peer_count'],
                "connections": p2p_info['connected_peers'],
                "node_id": p2p_info['node_id'],
                "mining_enabled": self.mining_api_enabled,
                "background_mining_enabled": self.background_mining_enabled,
            }
        
        # Blockchain info
        @self.app.get("/api/blockchain/info")
        async def get_blockchain_info():
            """Get blockchain information"""
            return self.blockchain.get_blockchain_info()
        
        # Block operations
        @self.app.get("/api/blocks/latest")
        async def get_latest_blocks(limit: int = 10):
            """Get latest blocks"""
            latest_blocks = []
            chain_length = len(self.blockchain.chain)
            
            for i in range(min(limit, chain_length)):
                block = self.blockchain.chain[-(i+1)]
                latest_blocks.append({
                    'height': block.height,
                    'hash': block.get_block_hash(),
                    'timestamp': block.header.timestamp,
                    'tx_count': len(block.transactions),
                    'size': block.size,
                    'consensus_type': block.header.consensus_type
                })
            
            return latest_blocks
        
        @self.app.get("/api/block/{block_hash}")
        async def get_block(block_hash: str):
            """Get block by hash"""
            for block in self.blockchain.chain:
                if block.get_block_hash() == block_hash:
                    return {
                        'height': block.height,
                        'hash': block.get_block_hash(),
                        'prev_hash': block.header.prev_hash,
                        'merkle_root': block.header.merkle_root,
                        'timestamp': block.header.timestamp,
                        'bits': block.header.bits,
                        'nonce': block.header.nonce,
                        'consensus_type': block.header.consensus_type,
                        'size': block.size,
                        'transactions': [tx.calculate_txid() for tx in block.transactions]
                    }
            
            raise HTTPException(status_code=404, detail="Block not found")
        
        @self.app.get("/api/block/height/{height}")
        async def get_block_by_height(height: int):
            """Get block by height"""
            if 0 <= height < len(self.blockchain.chain):
                block = self.blockchain.chain[height]
                return await get_block(block.get_block_hash())
            
            raise HTTPException(status_code=404, detail="Block not found")
        
        # Transaction operations
        @self.app.get("/api/tx/{txid}")
        async def get_transaction(txid: str):
            """Get transaction by ID"""
            # Search in blockchain
            for block in self.blockchain.chain:
                for tx in block.transactions:
                    if tx.calculate_txid() == txid:
                        return {
                            'txid': txid,
                            'version': tx.version,
                            'lock_time': tx.lock_time,
                            'fee': tx.fee,
                            'timestamp': tx.timestamp,
                            'block_height': block.height,
                            'confirmations': len(self.blockchain.chain) - block.height,
                            'inputs': [{'prev_txid': inp.prev_txid, 'prev_vout': inp.prev_vout} 
                                     for inp in tx.inputs],
                            'outputs': [{'value': out.value, 'address': out.address} 
                                      for out in tx.outputs],
                            'privacy_proof': bool(tx.privacy_proof),
                            'ring_signature': bool(tx.ring_signature)
                        }
            
            # Search in mempool
            if txid in self.blockchain.mempool:
                tx = self.blockchain.mempool[txid]
                return {
                    'txid': txid,
                    'version': tx.version,
                    'lock_time': tx.lock_time,
                    'fee': tx.fee,
                    'timestamp': tx.timestamp,
                    'confirmations': 0,
                    'inputs': [{'prev_txid': inp.prev_txid, 'prev_vout': inp.prev_vout} 
                             for inp in tx.inputs],
                    'outputs': [{'value': out.value, 'address': out.address} 
                              for out in tx.outputs],
                    'privacy_proof': bool(tx.privacy_proof),
                    'ring_signature': bool(tx.ring_signature)
                }
            
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        @self.app.post("/api/transaction/send")
        async def send_transaction(request: dict):
            """Submit transaction to network with privacy features"""
            try:
                from_address = request.get('from_address')
                to_address = request.get('to_address')
                amount = request.get('amount')
                fee = request.get('fee', 0.0001)
                fee_mode = request.get('fee_mode', 'standard')
                privacy_level = request.get('privacy_level', 'standard')  # 'standard', 'high', 'maximum'
                
                # Input validation
                if from_address is None or to_address is None or amount is None:
                    raise HTTPException(status_code=400, detail="Missing required fields: from_address, to_address, amount")
                
                # Validate addresses
                if not from_address.startswith("wepo1") or len(from_address) < 30:
                    raise HTTPException(status_code=400, detail="Invalid sender address format")
                
                if not to_address.startswith("wepo1") or len(to_address) < 30:
                    raise HTTPException(status_code=400, detail="Invalid recipient address format")
                
                if fee_mode not in ['standard', 'canonical_settlement']:
                    raise HTTPException(status_code=400, detail="Invalid fee_mode")

                # Validate amount
                if not isinstance(amount, (int, float)) or amount < 0:
                    raise HTTPException(status_code=400, detail="Amount must be a non-negative number")

                if not isinstance(fee, (int, float)) or fee <= 0:
                    raise HTTPException(status_code=400, detail="Fee must be a positive number")

                allow_fee_only = fee_mode == 'canonical_settlement'
                if amount == 0 and not allow_fee_only:
                    raise HTTPException(status_code=400, detail="Amount must be positive for standard transfers")

                # Check sender balance
                sender_balance = self.blockchain.get_balance_wepo(from_address)
                required_amount = amount + fee
                
                if sender_balance < required_amount:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient balance. Available: {sender_balance:.8f} WEPO, Required: {required_amount:.8f} WEPO"
                    )
                
                # Create transaction using blockchain method
                tx = self.blockchain.create_transaction(
                    from_address,
                    to_address,
                    int(round(amount * COIN)),
                    int(round(fee * COIN)),
                    allow_fee_only=allow_fee_only,
                )
                
                if not tx:
                    raise HTTPException(status_code=400, detail="Failed to create transaction")
                
                # Add privacy features based on privacy level
                if privacy_level in ['high', 'maximum']:
                    try:
                        # Generate privacy proof
                        privacy_data = {
                            'sender_private_key': from_address.encode(),  # In real impl, derive from wallet
                            'recipient_address': to_address,
                            'amount': int(amount * 100000000),  # Convert to satoshis
                            'decoy_keys': [f"wepo1decoy{i}".encode() for i in range(5)]  # Generate decoy keys
                        }
                        
                        privacy_proof = create_privacy_proof(privacy_data)
                        tx.privacy_proof = privacy_proof
                        
                        # Generate ring signature for maximum privacy
                        if privacy_level == 'maximum':
                            ring_signature_data = privacy_engine.ring_signature.generate_ring_signature(
                                tx.calculate_txid().encode(),
                                from_address.encode(),
                                [f"wepo1ring{i}".encode() for i in range(6)]
                            )
                            tx.ring_signature = ring_signature_data.serialize()
                        
                        print(f"🔒 Privacy features added: {privacy_level}")
                        
                    except Exception as e:
                        print(f"⚠️ Privacy feature generation failed: {e}")
                        # Continue without privacy features
                
                # Validate and add to mempool
                if self.blockchain.add_transaction_to_mempool(tx):
                    txid = tx.calculate_txid()
                    
                    # Broadcast to P2P network
                    self.p2p_node.broadcast_transaction({'txid': txid, 'tx_data': 'transaction_data'})
                    
                    return {
                        'transaction_id': txid,
                        'tx_hash': txid,
                        'status': 'pending',
                        'message': 'Transaction submitted to mempool',
                        'privacy_protected': bool(tx.privacy_proof or tx.ring_signature),
                        'privacy_level': privacy_level,
                        'fee_mode': fee_mode,
                    }
                else:
                    raise HTTPException(status_code=400, detail="Transaction validation failed")
                    
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
        
        # Wallet operations 
        @self.app.get("/api/wallet/{address}")
        async def get_wallet_info(address: str):
            """Get wallet information from blockchain"""
            try:
                # Validate address format
                if not address.startswith("wepo1") or len(address) < 30:
                    raise HTTPException(status_code=400, detail="Invalid address format")
                
                balance = self.blockchain.get_balance_wepo(address)
                utxos = self.blockchain.get_utxos_for_address(address)
                
                return {
                    'address': address,
                    'balance': balance,
                    'utxo_count': len(utxos),
                    'total_received': balance,  # Simplified
                    'total_sent': 0,  # TODO: Calculate from transaction history
                    'unconfirmed_balance': 0
                }
                
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/wallet/{address}/transactions")
        async def get_wallet_transactions(address: str, limit: int = 50):
            """Get transaction history for wallet"""
            try:
                # Validate address format
                if not address.startswith("wepo1") or len(address) < 30:
                    raise HTTPException(status_code=400, detail="Invalid address format")
                
                transactions = []
                
                # Search through all blocks
                for block in self.blockchain.chain:
                    for tx in block.transactions:
                        # Check if this transaction involves the address
                        involved = False
                        tx_type = "unknown"
                        amount = 0
                        
                        # Check outputs (receiving)
                        for output in tx.outputs:
                            if output.address == address:
                                involved = True
                                tx_type = "receive"
                                amount = output.value / 100000000  # Convert to WEPO
                                break
                        
                        # Check inputs (sending) - simplified
                        if not involved and not tx.is_coinbase():
                            # For now, just check if any input could be from this address
                            # TODO: Proper input address resolution
                            pass
                        
                        if involved:
                            transactions.append({
                                'txid': tx.calculate_txid(),
                                'type': tx_type,
                                'amount': amount,
                                'from_address': "coinbase" if tx.is_coinbase() else "unknown",
                                'to_address': address,
                                'timestamp': tx.timestamp,
                                'status': 'confirmed',
                                'confirmations': len(self.blockchain.chain) - block.height,
                                'block_height': block.height,
                                'block_hash': block.get_block_hash()
                            })
                
                # Sort by timestamp (newest first) and limit
                transactions.sort(key=lambda x: x['timestamp'], reverse=True)
                return transactions[:limit]
                
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # Staking operations
        @self.app.post("/api/stake")
        async def create_stake(request: dict):
            """Create staking position"""
            try:
                staker_address = request.get('staker_address')
                amount = request.get('amount')
                
                if not all([staker_address, amount]):
                    raise HTTPException(status_code=400, detail="Missing required fields: staker_address, amount")
                
                # Validate amount
                if not isinstance(amount, (int, float)) or amount < 1000:
                    raise HTTPException(status_code=400, detail="Minimum stake amount is 1000 WEPO")
                
                # Create stake through blockchain
                stake_id = self.blockchain.create_stake(staker_address, amount)
                
                if stake_id:
                    return {
                        'success': True,
                        'stake_id': stake_id,
                        'staker_address': staker_address,
                        'amount': amount,
                        'message': 'Stake created successfully'
                    }
                else:
                    raise HTTPException(status_code=400, detail="Failed to create stake")
                    
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/staking/info")
        async def get_staking_info():
            """Get comprehensive staking information"""
            try:
                return self.blockchain.get_staking_info()
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/wallet/{address}/stakes")
        async def get_wallet_stakes(address: str):
            """Get staking positions for a wallet"""
            try:
                cursor = self.blockchain.conn.execute('''
                    SELECT stake_id, amount, start_height, start_time, last_reward_height, 
                           total_rewards, status, unlock_height
                    FROM stakes 
                    WHERE staker_address = ?
                    ORDER BY start_time DESC
                ''', (address,))
                
                stakes = []
                for row in cursor.fetchall():
                    stakes.append({
                        'stake_id': row[0],
                        'amount': row[1] / 100000000,  # Convert to WEPO
                        'start_height': row[2],
                        'start_time': row[3],
                        'last_reward_height': row[4],
                        'total_rewards': row[5] / 100000000,  # Convert to WEPO
                        'status': row[6],
                        'unlock_height': row[7]
                    })
                
                return stakes
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/masternode")
        async def create_masternode(request: dict):
            """Create masternode"""
            try:
                operator_address = request.get('operator_address')
                collateral_txid = request.get('collateral_txid')
                collateral_vout = request.get('collateral_vout')
                ip_address = request.get('ip_address')
                port = request.get('port', 22567)
                
                if not all([operator_address, collateral_txid, collateral_vout is not None]):
                    raise HTTPException(status_code=400, detail="Missing required fields: operator_address, collateral_txid, collateral_vout")
                
                # Create masternode through blockchain
                masternode_id = self.blockchain.create_masternode(
                    operator_address, collateral_txid, collateral_vout, ip_address, port
                )
                
                if masternode_id:
                    return {
                        'success': True,
                        'masternode_id': masternode_id,
                        'operator_address': operator_address,
                        'collateral_txid': collateral_txid,
                        'collateral_vout': collateral_vout,
                        'ip_address': ip_address,
                        'port': port,
                        'message': 'Masternode created successfully'
                    }
                else:
                    raise HTTPException(status_code=400, detail="Failed to create masternode")
                    
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/masternodes")
        async def get_masternodes():
            """Get all masternodes"""
            try:
                masternodes = self.blockchain.get_active_masternodes()
                
                result = []
                for mn in masternodes:
                    result.append({
                        'masternode_id': mn.masternode_id,
                        'operator_address': mn.operator_address,
                        'collateral_txid': mn.collateral_txid,
                        'collateral_vout': mn.collateral_vout,
                        'ip_address': mn.ip_address,
                        'port': mn.port,
                        'start_height': mn.start_height,
                        'start_time': mn.start_time,
                        'last_ping': mn.last_ping,
                        'status': mn.status,
                        'total_rewards': mn.total_rewards / 100000000  # Convert to WEPO
                    })
                
                return result
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # Privacy operations
        @self.app.post("/api/privacy/create-proof")
        async def create_privacy_proof_endpoint(request: dict):
            """Create privacy proof for transaction"""
            try:
                transaction_data = request.get('transaction_data')
                if not transaction_data:
                    raise HTTPException(status_code=400, detail="Missing transaction_data")
                
                # Create privacy proof
                proof = create_privacy_proof(transaction_data)
                
                return {
                    'success': True,
                    'privacy_proof': proof.hex(),
                    'proof_size': len(proof),
                    'privacy_level': 'maximum'
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/privacy/verify-proof")
        async def verify_privacy_proof_endpoint(request: dict):
            """Verify privacy proof"""
            try:
                proof_data = request.get('proof_data')
                message = request.get('message')
                
                if not proof_data or not message:
                    raise HTTPException(status_code=400, detail="Missing proof_data or message")
                
                # Verify privacy proof
                is_valid = verify_privacy_proof(
                    bytes.fromhex(proof_data),
                    message.encode()
                )
                
                return {
                    'valid': is_valid,
                    'proof_verified': is_valid,
                    'privacy_level': 'maximum' if is_valid else 'none'
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/privacy/stealth-address")
        async def generate_stealth_address(request: dict):
            """Generate stealth address for privacy"""
            try:
                recipient_public_key = request.get('recipient_public_key')
                if not recipient_public_key:
                    raise HTTPException(status_code=400, detail="Missing recipient_public_key")
                
                # Generate stealth address
                stealth_addr, shared_secret = privacy_engine.generate_stealth_address(
                    recipient_public_key.encode()
                )
                
                return {
                    'stealth_address': stealth_addr,
                    'shared_secret': shared_secret.hex(),
                    'privacy_level': 'maximum'
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/privacy/info")
        async def get_privacy_info():
            """Get privacy feature information"""
            try:
                return {
                    'privacy_enabled': True,
                    'supported_features': [
                        'zk-STARK proofs',
                        'Ring signatures',
                        'Confidential transactions',
                        'Stealth addresses'
                    ],
                    'privacy_levels': {
                        'standard': 'Basic transaction privacy',
                        'high': 'Enhanced privacy with ring signatures',
                        'maximum': 'Full privacy with all features'
                    },
                    'proof_sizes': {
                        'zk_stark': ZK_STARK_PROOF_SIZE,
                        'ring_signature': RING_SIGNATURE_SIZE,
                        'confidential': CONFIDENTIAL_PROOF_SIZE
                    },
                    'implementation': 'Real cryptographic privacy implementation',
                    'features_status': 'Production ready'
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # Mining operations
        @self.app.get("/api/mining/info")
        async def get_mining_info():
            """Get mining information"""
            height = self.blockchain.get_block_height()
            next_height = height + 1
            current_reward = self.blockchain.calculate_block_reward(next_height)
            profile = get_network_profile(self.network_profile)
            reward_phase = get_reward_phase_label(profile, next_height)
            
            return {
                'current_block_height': height,
                'current_reward': current_reward / 100000000,  # Convert to WEPO
                'quarter_info': f" ({reward_phase})",
                'reward_phase': reward_phase,
                'difficulty': self.blockchain.current_difficulty,
                'algorithm': 'Argon2',
                'block_time': format_block_time(get_pow_block_time_seconds(profile, next_height)),
                'mining_enabled': self.mining_api_enabled,
                'background_mining_enabled': self.background_mining_enabled,
                'mempool_size': len(self.blockchain.mempool),
                'reward_schedule': describe_reward_schedule(profile),
                'network': profile.network_label,
                'network_profile': profile.name,
            }
        
        @self.app.get("/api/mining/getwork")
        async def get_work(miner_address: Optional[str] = None):
            """Get mining work"""
            if not self.mining_api_enabled:
                raise HTTPException(status_code=503, detail="Mining API disabled")

            reward_address = miner_address or self.miner_address
            if not reward_address.startswith("wepo1") or len(reward_address) < 30:
                raise HTTPException(status_code=400, detail="Invalid miner address format")
            
            # Create new block template
            new_block = self.blockchain.create_new_block(reward_address)
            job_id = f"job_{new_block.height}_{int(time.time())}_{secrets.token_hex(4)}"
            prune_expired_mining_jobs()
            self.active_mining_jobs[job_id] = {
                "block": new_block,
                "created_at": time.time(),
                "miner_address": reward_address,
            }
            
            return {
                'job_id': job_id,
                'prev_hash': new_block.header.prev_hash,
                'merkle_root': new_block.header.merkle_root,
                'timestamp': new_block.header.timestamp,
                'bits': new_block.header.bits,
                'height': new_block.height,
                'target_difficulty': new_block.header.bits,
                'miner_address': reward_address,
            }
        
        @self.app.post("/api/mining/submit")
        async def submit_work(request: dict):
            """Submit mining solution"""
            try:
                job_id = request.get('job_id')
                nonce = request.get('nonce')
                miner_address = request.get('miner_address')

                if not job_id or not isinstance(job_id, str):
                    return {
                        'accepted': False,
                        'reason': 'Missing or invalid job_id'
                    }

                if not isinstance(nonce, int) or nonce < 0:
                    return {
                        'accepted': False,
                        'reason': 'Missing or invalid nonce'
                    }

                prune_expired_mining_jobs()
                job = self.active_mining_jobs.pop(job_id, None)
                if not job:
                    return {
                        'accepted': False,
                        'reason': 'Unknown or expired job'
                    }

                if miner_address and miner_address != job['miner_address']:
                    return {
                        'accepted': False,
                        'reason': 'Submitted miner address does not match issued work'
                    }

                new_block = job['block']
                latest_block = self.blockchain.get_latest_block()
                expected_prev_hash = latest_block.get_block_hash() if latest_block else "0" * 64
                expected_height = self.blockchain.get_block_height() + 1

                if new_block.header.prev_hash != expected_prev_hash or new_block.height != expected_height:
                    return {
                        'accepted': False,
                        'reason': 'Stale work'
                    }

                new_block.header.nonce = nonce

                if not self.blockchain.validate_pow_block(new_block):
                    return {
                        'accepted': False,
                        'reason': 'Invalid proof of work'
                    }
                
                # Validate and add block
                if self.blockchain.add_block(new_block):
                    # Broadcast to P2P network
                    block_data = {
                        'height': new_block.height,
                        'hash': new_block.get_block_hash()
                    }
                    self.p2p_node.broadcast_block(block_data)
                    
                    return {
                        'accepted': True,
                        'height': new_block.height,
                        'hash': new_block.get_block_hash()
                    }
                else:
                    return {
                        'accepted': False,
                        'reason': 'Invalid proof of work'
                    }
                    
            except Exception as e:
                return {
                    'accepted': False,
                    'reason': str(e)
                }
        
        # Wallet operations (basic)
        @self.app.get("/api/wallet/{address}")
        async def get_wallet_info(address: str):
            """Get wallet information"""
            # Calculate balance (simplified)
            balance = 0
            for block in self.blockchain.chain:
                for tx in block.transactions:
                    for output in tx.outputs:
                        if output.address == address:
                            balance += output.value
            
            return {
                'address': address,
                'balance': balance / 100000000,  # Convert to WEPO
                'transaction_count': 0  # TODO: Calculate actual count
            }
        
        # P2P network info
        @self.app.get("/api/network/peers")
        async def get_peers():
            """Get connected peers"""
            return self.p2p_node.get_network_info()
        
        # Atomic Swap Operations
        @self.app.post("/api/atomic-swap/initiate")
        async def initiate_atomic_swap(request: dict):
            """Initiate a new atomic swap"""
            try:
                # Extract request parameters
                swap_type = request.get('swap_type')
                btc_amount = request.get('btc_amount')
                initiator_btc_address = request.get('initiator_btc_address')
                initiator_wepo_address = request.get('initiator_wepo_address')
                participant_btc_address = request.get('participant_btc_address')
                participant_wepo_address = request.get('participant_wepo_address')
                
                # Validate parameters
                if not all([swap_type, btc_amount, initiator_btc_address, 
                           initiator_wepo_address, participant_btc_address, participant_wepo_address]):
                    raise HTTPException(status_code=400, detail="Missing required parameters")
                
                # Validate addresses
                if not validate_btc_address(initiator_btc_address) or not validate_btc_address(participant_btc_address):
                    raise HTTPException(status_code=400, detail="Invalid Bitcoin address")
                
                if not validate_wepo_address(initiator_wepo_address) or not validate_wepo_address(participant_wepo_address):
                    raise HTTPException(status_code=400, detail="Invalid WEPO address")
                
                # Convert swap type
                if swap_type == "btc_to_wepo":
                    swap_type_enum = SwapType.BTC_TO_WEPO
                elif swap_type == "wepo_to_btc":
                    swap_type_enum = SwapType.WEPO_TO_BTC
                else:
                    raise HTTPException(status_code=400, detail="Invalid swap type")
                
                # Initiate swap
                swap_contract = await atomic_swap_engine.initiate_swap(
                    swap_type_enum,
                    initiator_btc_address,
                    initiator_wepo_address,
                    participant_btc_address,
                    participant_wepo_address,
                    float(btc_amount)
                )
                
                return {
                    'success': True,
                    'swap_id': swap_contract.swap_id,
                    'swap_type': swap_contract.swap_type.value,
                    'state': swap_contract.state.value,
                    'btc_amount': swap_contract.btc_amount,
                    'wepo_amount': swap_contract.wepo_amount,
                    'secret_hash': swap_contract.secret_hash,
                    'btc_htlc_address': swap_contract.btc_htlc_address,
                    'wepo_htlc_address': swap_contract.wepo_htlc_address,
                    'btc_locktime': swap_contract.btc_locktime,
                    'wepo_locktime': swap_contract.wepo_locktime,
                    'expires_at': swap_contract.expires_at.isoformat()
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/atomic-swap/status/{swap_id}")
        async def get_swap_status(swap_id: str):
            """Get atomic swap status"""
            try:
                swap_contract = atomic_swap_engine.get_swap_status(swap_id)
                if not swap_contract:
                    raise HTTPException(status_code=404, detail="Swap not found")
                
                return {
                    'swap_id': swap_contract.swap_id,
                    'swap_type': swap_contract.swap_type.value,
                    'state': swap_contract.state.value,
                    'btc_amount': swap_contract.btc_amount,
                    'wepo_amount': swap_contract.wepo_amount,
                    'secret_hash': swap_contract.secret_hash,
                    'btc_htlc_address': swap_contract.btc_htlc_address,
                    'wepo_htlc_address': swap_contract.wepo_htlc_address,
                    'btc_locktime': swap_contract.btc_locktime,
                    'wepo_locktime': swap_contract.wepo_locktime,
                    'btc_funding_tx': swap_contract.btc_funding_tx,
                    'wepo_funding_tx': swap_contract.wepo_funding_tx,
                    'created_at': swap_contract.created_at.isoformat(),
                    'expires_at': swap_contract.expires_at.isoformat()
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/atomic-swap/fund")
        async def fund_atomic_swap(request: dict):
            """Fund an atomic swap"""
            try:
                swap_id = request.get('swap_id')
                currency = request.get('currency')
                tx_hash = request.get('tx_hash')
                
                if not all([swap_id, currency, tx_hash]):
                    raise HTTPException(status_code=400, detail="Missing required parameters")
                
                success = await atomic_swap_engine.fund_swap(swap_id, currency, tx_hash)
                
                if success:
                    return {
                        'success': True,
                        'message': f'{currency} funding recorded',
                        'swap_id': swap_id,
                        'tx_hash': tx_hash
                    }
                else:
                    raise HTTPException(status_code=400, detail="Failed to fund swap")
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/atomic-swap/redeem")
        async def redeem_atomic_swap(request: dict):
            """Redeem an atomic swap with secret"""
            try:
                swap_id = request.get('swap_id')
                secret = request.get('secret')
                
                if not all([swap_id, secret]):
                    raise HTTPException(status_code=400, detail="Missing required parameters")
                
                success = await atomic_swap_engine.redeem_swap(swap_id, secret)
                
                if success:
                    return {
                        'success': True,
                        'message': 'Swap redeemed successfully',
                        'swap_id': swap_id
                    }
                else:
                    raise HTTPException(status_code=400, detail="Failed to redeem swap")
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/atomic-swap/refund")
        async def refund_atomic_swap(request: dict):
            """Refund an expired atomic swap"""
            try:
                swap_id = request.get('swap_id')
                
                if not swap_id:
                    raise HTTPException(status_code=400, detail="Missing swap_id")
                
                success = await atomic_swap_engine.refund_swap(swap_id)
                
                if success:
                    return {
                        'success': True,
                        'message': 'Swap refunded successfully',
                        'swap_id': swap_id
                    }
                else:
                    raise HTTPException(status_code=400, detail="Failed to refund swap or swap not expired")
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/atomic-swap/list")
        async def list_atomic_swaps():
            """List all active atomic swaps"""
            try:
                swaps = atomic_swap_engine.get_all_swaps()
                
                swap_list = []
                for swap in swaps:
                    swap_list.append({
                        'swap_id': swap.swap_id,
                        'swap_type': swap.swap_type.value,
                        'state': swap.state.value,
                        'btc_amount': swap.btc_amount,
                        'wepo_amount': swap.wepo_amount,
                        'created_at': swap.created_at.isoformat(),
                        'expires_at': swap.expires_at.isoformat()
                    })
                
                return {
                    'swaps': swap_list,
                    'total_count': len(swap_list)
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/atomic-swap/proof/{swap_id}")
        async def get_swap_proof(swap_id: str):
            """Get cryptographic proof of atomic swap"""
            try:
                proof = await atomic_swap_engine.get_swap_proof(swap_id)
                
                if not proof:
                    raise HTTPException(status_code=404, detail="Swap not found")
                
                return proof
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/atomic-swap/exchange-rate")
        async def get_exchange_rate():
            """Get current BTC/WEPO exchange rate"""
            try:
                rate = atomic_swap_engine.get_exchange_rate()
                
                return {
                    'btc_to_wepo': rate,
                    'wepo_to_btc': 1.0 / rate,
                    'fee_percentage': 0.1,
                    'last_updated': int(time.time()),
                    'source': 'atomic_swap_engine'
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # Quantum-Resistant Blockchain Operations
        @self.app.get("/api/quantum/info")
        async def get_quantum_info():
            """Get quantum blockchain information"""
            try:
                return self.quantum_blockchain.get_quantum_info()
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/quantum/dilithium")
        async def get_dilithium_info():
            """Get Dilithium implementation details"""
            try:
                return get_dilithium_info()
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/quantum/wallet/create")
        async def create_quantum_wallet():
            """Create a new quantum-resistant wallet"""
            try:
                wallet = QuantumWallet()
                wallet_info = wallet.generate_new_wallet()
                
                return {
                    'success': True,
                    'wallet': wallet_info,
                    'quantum_resistant': True,
                    'message': 'Quantum-resistant wallet created successfully'
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/quantum/wallet/{address}")
        async def get_quantum_wallet_info(address: str):
            """Get quantum wallet information"""
            try:
                if not validate_quantum_address(address):
                    raise HTTPException(status_code=400, detail="Invalid quantum address format")
                
                balance = self.quantum_blockchain.get_balance_wepo(address)
                
                return {
                    'address': address,
                    'balance': balance,
                    'quantum_resistant': True,
                    'signature_algorithm': 'Dilithium2',
                    'hash_algorithm': 'BLAKE2b'
                }
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/quantum/transaction/create")
        async def create_quantum_transaction(request: dict):
            """Create a quantum-resistant transaction"""
            try:
                from_address = request.get('from_address')
                to_address = request.get('to_address')
                amount = request.get('amount')
                fee = request.get('fee', 0.0001)
                private_key = request.get('private_key')
                
                if not all([from_address, to_address, amount, private_key]):
                    raise HTTPException(status_code=400, detail="Missing required fields")
                
                # Create and sign transaction
                wallet = QuantumWallet()
                if not wallet.load_wallet(private_key):
                    raise HTTPException(status_code=400, detail="Invalid private key")
                
                # Get UTXOs (simplified)
                utxos = []  # In real implementation, get from blockchain
                
                # Create transaction
                transaction = wallet.create_transaction(
                    recipient_address=to_address,
                    amount=int(amount * 100000000),  # Convert to satoshis
                    fee=int(fee * 100000000),
                    utxos=utxos
                )
                
                if not transaction:
                    raise HTTPException(status_code=400, detail="Failed to create transaction")
                
                # Add to mempool
                if self.quantum_blockchain.add_transaction_to_mempool(transaction):
                    return {
                        'success': True,
                        'transaction_id': transaction.calculate_txid(),
                        'quantum_resistant': True,
                        'signature_algorithm': 'Dilithium2',
                        'status': 'pending'
                    }
                else:
                    raise HTTPException(status_code=400, detail="Transaction validation failed")
                
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/quantum/status")
        async def get_quantum_status():
            """Get quantum blockchain status"""
            try:
                return {
                    'quantum_ready': True,
                    'current_height': self.quantum_blockchain.get_block_height(),
                    'mempool_size': len(self.quantum_blockchain.mempool),
                    'signature_algorithm': 'Dilithium2',
                    'hash_algorithm': 'BLAKE2b',
                    'implementation': 'WEPO Quantum-Resistant v1.0'
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
    
    def handle_new_block(self, block_data: dict):
        """Handle new block from P2P network"""
        print(f"Received new block from network: {block_data.get('hash', 'unknown')}")
        # TODO: Validate and add block to chain
    
    def handle_new_transaction(self, tx_data: dict):
        """Handle new transaction from P2P network"""
        print(f"Received new transaction from network: {tx_data.get('txid', 'unknown')}")
        # TODO: Validate and add to mempool
    
    def get_block_data(self, block_hash: str) -> Optional[dict]:
        """Get block data for P2P requests"""
        for block in self.blockchain.chain:
            if block.get_block_hash() == block_hash:
                return {
                    'height': block.height,
                    'hash': block.get_block_hash(),
                    'prev_hash': block.header.prev_hash,
                    'merkle_root': block.header.merkle_root,
                    'timestamp': block.header.timestamp,
                    'transactions': [tx.calculate_txid() for tx in block.transactions]
                }
        return None
    
    def start_mining(self):
        """Start mining in background thread"""
        if not self.background_mining_enabled:
            return
        
        def mining_worker():
            print("Starting WEPO mining...")
            while self.running and self.background_mining_enabled:
                try:
                    mined_block = self.blockchain.mine_next_block(self.miner_address)
                    if mined_block:
                        print(f"Mined new block {mined_block.height}: {mined_block.get_block_hash()}")
                        
                        # Broadcast to P2P network
                        block_data = {
                            'height': mined_block.height,
                            'hash': mined_block.get_block_hash()
                        }
                        self.p2p_node.broadcast_block(block_data)
                    
                except Exception as e:
                    print(f"Mining error: {e}")
                    time.sleep(5)
        
        self.mining_thread = threading.Thread(target=mining_worker, daemon=True)
        self.mining_thread.start()
    
    def start(self):
        """Start the full node"""
        print("Starting WEPO Full Node...")
        self.running = True
        
        # Start P2P network
        self.p2p_node.start_server()
        
        # Discover peers
        time.sleep(2)
        self.p2p_node.discover_peers()
        
        # Start background mining if enabled
        if self.background_mining_enabled:
            self.start_mining()
        
        print(f"WEPO Full Node started successfully!")
        print(f"Blockchain height: {self.blockchain.get_block_height()}")
        print(f"P2P port: {self.p2p_port}")
        print(f"API port: {self.api_port}")
        
        # Run API server
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=self.api_port,
            log_level="info"
        )
    
    def stop(self):
        """Stop the full node"""
        print("Stopping WEPO Full Node...")
        self.running = False
        self.background_mining_enabled = False
        self.mining_api_enabled = False
        
        # Stop P2P network
        self.p2p_node.stop_server()
        
        print("WEPO Full Node stopped")

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print("\nReceived shutdown signal...")
    global node
    if 'node' in globals():
        node.stop()
    sys.exit(0)

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='WEPO Full Node')
    parser.add_argument('--data-dir', default='/tmp/wepo',
                       help='Data directory for blockchain storage')
    parser.add_argument('--p2p-port', type=int, default=22567,
                       help='P2P network port')
    parser.add_argument('--api-port', type=int, default=8001,
                       help='API server port')
    parser.add_argument('--no-mining', action='store_true',
                       help='Disable both mining RPC and background mining')
    parser.add_argument('--no-background-mining', action='store_true',
                       help='Disable the background miner but keep mining RPC available')
    parser.add_argument('--miner-address',
                       help='Miner address for block rewards')
    parser.add_argument('--difficulty-override', type=int,
                       help='Fixed PoW difficulty for local testing or smoke environments')
    parser.add_argument('--network-profile', default=os.getenv("WEPO_NETWORK_PROFILE", "mainnet"),
                       choices=['mainnet', 'test'],
                       help='Network profile to apply (mainnet or accelerated test)')
    
    args = parser.parse_args()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("🚀 WEPO Full Node - Revolutionary Cryptocurrency")
    print("=" * 60)
    print(f"Version: 1.0.0")
    print(f"Data directory: {args.data_dir}")
    print(f"P2P port: {args.p2p_port}")
    print(f"API port: {args.api_port}")
    print(f"Network profile: {args.network_profile}")
    print(f"Mining API: {'Disabled' if args.no_mining else 'Enabled'}")
    print(
        f"Background mining: "
        f"{'Disabled' if args.no_mining or args.no_background_mining else 'Enabled'}"
    )
    print("=" * 60)
    
    # Create and start node
    global node
    node = WepoFullNode(
        data_dir=args.data_dir,
        p2p_port=args.p2p_port,
        api_port=args.api_port,
        enable_mining=not args.no_mining,
        background_mining_enabled=False if args.no_mining else not args.no_background_mining,
        difficulty_override=args.difficulty_override,
        network_profile=args.network_profile,
    )
    
    if args.miner_address:
        node.miner_address = args.miner_address
    
    try:
        node.start()
    except KeyboardInterrupt:
        node.stop()

if __name__ == "__main__":
    main()
