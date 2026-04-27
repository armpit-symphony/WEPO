#!/bin/bash

# WEPO Blockchain Network Genesis Launch Script
# This script creates the genesis block and launches the initial network

set -e

echo "🎄 WEPO Blockchain Genesis Launch - genesis date Ready!"
echo "============================================================"

# Network Configuration
GENESIS_DATE="2025-12-25"
NETWORK_NAME="wepo-mainnet"
GENESIS_SUPPLY="69000003"
PREMINE_ADDRESS="wepo1genesis0000000000000000000000000"

# Server Configuration (Update these for your servers)
SEED_NODES=(
    # "node1.wepo.network:22567"
    # "node2.wepo.network:22567" 
    # "node3.wepo.network:22567"
    "localhost:22567"  # For local testing
)

API_ENDPOINTS=(
    # "https://api1.wepo.network"
    # "https://api2.wepo.network"
    "http://localhost:8001"  # For local testing
)

echo "📅 Genesis Date: $GENESIS_DATE"
echo "🌐 Network: $NETWORK_NAME"
echo "💰 Genesis Supply: $GENESIS_SUPPLY WEPO"
echo ""

# Step 1: Create genesis configuration
echo "⚙️  Step 1: Creating genesis configuration..."
cat > genesis.json << EOF
{
  "network_name": "$NETWORK_NAME",
  "genesis_date": "$GENESIS_DATE",
  "genesis_supply": "$GENESIS_SUPPLY",
  "premine_address": "$PREMINE_ADDRESS",
  "consensus": {
    "algorithm": "hybrid_pow_pos",
    "block_time": 60,
    "difficulty_adjustment": 2016,
    "staking_minimum": 100,
    "masternode_collateral": 10000
  },
  "tokenomics": {
    "total_supply": "$GENESIS_SUPPLY",
    "mining_reward": 50,
    "staking_reward_rate": 0.12,
    "masternode_reward_rate": 0.60,
    "fee_redistribution": {
      "masternodes": 0.60,
      "miners": 0.25,
      "stakers": 0.15
    }
  },
  "features": {
    "quantum_resistance": true,
    "privacy_transactions": true,
    "bitcoin_integration": true,
    "smart_contracts": false,
    "rwa_tokens": true
  },
  "seed_nodes": [
$(printf '    "%s"' "${SEED_NODES[@]}" | sed 's/$/,/' | sed '$ s/,$//')
  ],
  "api_endpoints": [
$(printf '    "%s"' "${API_ENDPOINTS[@]}" | sed 's/$/,/' | sed '$ s/,$//')
  ]
}
EOF

echo "✅ Genesis configuration created"

# Step 2: Initialize blockchain data
echo "🗄️  Step 2: Initializing blockchain data..."
mkdir -p data/genesis
cp genesis.json data/genesis/

# Create genesis block
python3 << 'EOF'
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'wepo-blockchain', 'core'))

from blockchain import WepoBlockchain, Transaction
from quantum_blockchain import QuantumWepoBlockchain
from dilithium import generate_dilithium_keypair, generate_wepo_address
import json
import time

print("🔨 Creating genesis block...")

# Load genesis config
with open('genesis.json', 'r') as f:
    config = json.load(f)

# Initialize blockchain
blockchain = WepoBlockchain("data/genesis")

# Create genesis transaction (premine)
genesis_keypair = generate_dilithium_keypair()
genesis_address = generate_wepo_address(genesis_keypair['public_key'])

genesis_tx = Transaction(
    sender="0x0000000000000000000000000000000000000000",
    recipient=genesis_address,
    amount=float(config['genesis_supply']),
    fee=0.0,
    transaction_type="genesis",
    metadata={
        "genesis": True,
        "network": config['network_name'],
        "date": config['genesis_date'],
        "message": "WEPO Genesis Block - Financial Freedom for All"
    }
)

# Create and add genesis block
genesis_block = blockchain.create_block([genesis_tx], "0" * 64)
blockchain.add_block(genesis_block)

print(f"✅ Genesis block created: {genesis_block.hash}")
print(f"🏠 Genesis address: {genesis_address}")
print(f"💰 Genesis supply: {config['genesis_supply']} WEPO")

# Save genesis info
genesis_info = {
    "block_hash": genesis_block.hash,
    "genesis_address": genesis_address,
    "genesis_keypair": genesis_keypair,
    "timestamp": genesis_block.timestamp,
    "network": config['network_name']
}

with open('data/genesis/genesis_info.json', 'w') as f:
    json.dump(genesis_info, f, indent=2)

print("✅ Genesis block initialization complete")
EOF

echo "✅ Genesis block created successfully"

# Step 3: Create network configuration for nodes
echo "🌐 Step 3: Creating network node configurations..."

# Create systemd service file for deployment review
cat > wepo-node.service << 'EOF'
[Unit]
Description=WEPO Blockchain Node
After=network.target
Wants=network.target

[Service]
Type=simple
User=wepo
Group=wepo
WorkingDirectory=/opt/wepo-blockchain
ExecStart=/usr/bin/python3 core/wepo_node.py --data-dir /var/lib/wepo --p2p-port 22567 --api-port 8001
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/wepo /var/log/wepo

# Resource limits
LimitNOFILE=8192
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
EOF

# Create nginx configuration for API endpoints
cat > wepo-api.nginx << 'EOF'
server {
    listen 80;
    server_name api.wepo.network;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.wepo.network;
    
    # SSL configuration (add your certificates)
    ssl_certificate /path/to/ssl/certificate.crt;
    ssl_certificate_key /path/to/ssl/private.key;
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req zone=api burst=20 nodelay;
    
    # Proxy to WEPO node
    location /api/ {
        proxy_pass http://localhost:8001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type, Authorization";
        
        # Timeout settings
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
EOF

echo "✅ Network configuration files created"

# Step 4: Create Docker configuration for easy deployment
echo "🐳 Step 4: Creating Docker deployment configuration..."

cat > Dockerfile << 'EOF'
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create wepo user
RUN useradd -m -s /bin/bash wepo

# Set working directory
WORKDIR /app

# Copy requirements
COPY wepo-blockchain/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY wepo-blockchain/ .
COPY genesis.json .
COPY data/genesis/ ./data/genesis/

# Create data directory
RUN mkdir -p /var/lib/wepo && chown wepo:wepo /var/lib/wepo

# Switch to wepo user
USER wepo

# Expose ports
EXPOSE 8001 22567

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/api/network/status || exit 1

# Start node
CMD ["python3", "core/wepo_node.py", "--data-dir", "/var/lib/wepo", "--p2p-port", "22567", "--api-port", "8001"]
EOF

cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  wepo-node-1:
    build: .
    container_name: wepo-node-1
    ports:
      - "8001:8001"
      - "22567:22567"
    volumes:
      - wepo-data-1:/var/lib/wepo
      - ./logs:/var/log/wepo
    environment:
      - WEPO_NODE_ID=node-1
      - WEPO_NETWORK=mainnet
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/api/network/status"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  wepo-node-2:
    build: .
    container_name: wepo-node-2
    ports:
      - "8002:8001"
      - "22568:22567"
    volumes:
      - wepo-data-2:/var/lib/wepo
      - ./logs:/var/log/wepo
    environment:
      - WEPO_NODE_ID=node-2
      - WEPO_NETWORK=mainnet
    restart: unless-stopped
    depends_on:
      - wepo-node-1
    
  nginx:
    image: nginx:alpine
    container_name: wepo-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./wepo-api.nginx:/etc/nginx/conf.d/default.conf
      - ./ssl:/etc/ssl/certs
    depends_on:
      - wepo-node-1
      - wepo-node-2
    restart: unless-stopped

volumes:
  wepo-data-1:
  wepo-data-2:
EOF

echo "✅ Docker configuration created"

# Step 5: Create launch commands
echo "🚀 Step 5: Creating launch commands..."

cat > launch-local-network.sh << 'EOF'
#!/bin/bash

echo "🌐 Launching Local WEPO Network..."

# Start local network using existing script
cd ../wepo-blockchain
chmod +x scripts/start_network.sh
./scripts/start_network.sh
EOF

cat > launch-production-network.sh << 'EOF'
#!/bin/bash

echo "🌐 Launching Production WEPO Network..."

# Option 1: Docker deployment
echo "🐳 Using Docker deployment..."
docker-compose up -d

# Option 2: Systemd service deployment
echo "⚙️  Or install as system service:"
echo "1. Copy wepo-node.service to /etc/systemd/system/"
echo "2. sudo systemctl daemon-reload"
echo "3. sudo systemctl enable wepo-node"
echo "4. sudo systemctl start wepo-node"
EOF

chmod +x launch-local-network.sh launch-production-network.sh

echo ""
echo "🎉 WEPO Network Launch Configuration Complete!"
echo "=============================================="
echo ""
echo "📁 Files created:"
echo "  ✅ genesis.json - Network genesis configuration"
echo "  ✅ wepo-node.service - Systemd service file"
echo "  ✅ wepo-api.nginx - Nginx API proxy configuration"
echo "  ✅ Dockerfile - Docker container configuration"
echo "  ✅ docker-compose.yml - Multi-node deployment"
echo "  ✅ launch-local-network.sh - Local testing"
echo "  ✅ launch-production-network.sh - Production deployment"
echo ""
echo "🚀 Next Steps:"
echo "  1. Test locally: ./launch-local-network.sh"
echo "  2. Deploy to servers: ./launch-production-network.sh"
echo "  3. Update wallet backends to use your API endpoints"
echo ""
echo "🎄 Ready for genesis launch!"