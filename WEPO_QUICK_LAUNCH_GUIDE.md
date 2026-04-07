# WEPO Network Launch - Quick Start Guide

## Status Notice

This document is legacy bridge-era guidance and is not the current canonical path.

Do not treat `wepo-fast-test-bridge.py` as the authoritative production backend.

For the current local backend/node verification path, use:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh
```

That path exercises the canonical FastAPI backend plus the canonical WEPO node and verifies on-chain fee settlement directly.

## 🎯 Current Situation

You have:
- ✅ **Working wallet (desktop + web)** with all features
- ✅ **Complete backend API** (`wepo-fast-test-bridge.py`) 
- ✅ **Blockchain infrastructure** in `/wepo-blockchain/`
- ❌ **Need deployed network nodes** for wallets to connect to

## 🚀 Immediate Launch Steps

### **Option 1: Simple Production Launch (Recommended)**

**Step 1: Deploy Your Working Backend**
```bash
# Your current working backend is wepo-fast-test-bridge.py
# This already includes all wallet functionality:
# - Wallet creation/management
# - Bitcoin integration  
# - Quantum Vault
# - Mining/Staking/Masternodes
# - Complete API endpoints

# Deploy this to production servers:
scp wepo-fast-test-bridge.py user@your-server.com:/opt/wepo/
scp backend/requirements.txt user@your-server.com:/opt/wepo/
```

**Step 2: Production Server Setup**
```bash
# On your server (Ubuntu 22.04):
sudo apt update
sudo apt install python3 python3-pip nginx

# Install dependencies
cd /opt/wepo
pip3 install -r requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/wepo-api.service << EOF
[Unit]
Description=WEPO Blockchain API
After=network.target

[Service]
Type=simple
User=wepo
WorkingDirectory=/opt/wepo
ExecStart=/usr/bin/python3 wepo-fast-test-bridge.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl daemon-reload
sudo systemctl enable wepo-api
sudo systemctl start wepo-api
```

**Step 3: Configure Nginx Reverse Proxy**
```bash
# Create nginx config
sudo tee /etc/nginx/sites-available/wepo-api << EOF
server {
    listen 80;
    server_name api.wepo.network;
    
    location / {
        proxy_pass http://localhost:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        
        # CORS headers
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type";
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/wepo-api /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**Step 4: Get SSL Certificate**
```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get free SSL certificate
sudo certbot --nginx -d api.wepo.network
```

**Step 5: Update Wallet Configuration**

**Desktop Wallet:**
```javascript
// Update /app/wepo-desktop-wallet/src/frontend/.env
REACT_APP_BACKEND_URL=https://api.wepo.network
```

**Web Wallet:**
```javascript
// Update /app/frontend/.env  
REACT_APP_BACKEND_URL=https://api.wepo.network
```

### **Option 2: Enhanced Multi-Node Setup**

If you want multiple nodes for redundancy:

**Deploy to 3 servers:**
- api1.wepo.network
- api2.wepo.network  
- api3.wepo.network

**Use load balancer:**
```nginx
upstream wepo_backend {
    server api1.wepo.network:8001;
    server api2.wepo.network:8001;
    server api3.wepo.network:8001;
}

server {
    listen 443 ssl;
    server_name api.wepo.network;
    
    location / {
        proxy_pass http://wepo_backend;
    }
}
```

## 💰 Cost Estimate

**Simple Single Server:**
- **DigitalOcean Droplet (4GB RAM)**: $24/month
- **Domain + SSL**: Free (Let's Encrypt)
- **Total**: $24/month

**Multi-Node Setup:**
- **3 Servers**: $72/month
- **Load Balancer**: $12/month
- **Total**: $84/month

## Launch Timeline

**Week 1 (Now)**: Deploy to production server
**Week 2**: Test all wallet functionality
**Week 3**: Announce network availability
**Final Approval**: Official genesis launch announcement

## ✅ What This Gives You

**Immediate Benefits:**
- ✅ **Live WEPO network** accessible from anywhere
- ✅ **All wallet features working** (Bitcoin, Quantum Vault, Mining, etc.)
- ✅ **Professional API endpoints** with SSL
- ✅ **Scalable infrastructure** ready for users

**User Experience:**
- Users download desktop wallet from GitHub
- Wallet automatically connects to your live network
- All features work immediately (mining, Bitcoin, privacy)
- genesis date ready!

## 🔧 Quick Test Commands

After deployment, test your network:

```bash
# Test API health
curl https://api.wepo.network/api/

# Test wallet creation
curl -X POST https://api.wepo.network/api/wallet/create \
  -H "Content-Type: application/json" \
  -d '{"username":"test","encrypted_seed":"test_seed"}'

# Test Bitcoin integration
curl https://api.wepo.network/api/bitcoin/network/status

# Test mining
curl -X POST https://api.wepo.network/api/mining/start \
  -H "Content-Type: application/json" \
  -d '{"wallet_address":"wepo1test"}'
```

## 🎯 Bottom Line

**Your blockchain is already complete and working!** You just need to:

1. **Deploy `wepo-fast-test-bridge.py` to a server** (30 minutes)
2. **Set up SSL and domain** (30 minutes)  
3. **Update wallet config files** (5 minutes)
4. **Test everything works** (15 minutes)

**Total time to live network: ~1 hour**

Your users can then download the desktop wallet from GitHub and immediately start using the full WEPO network with all features working!

🎄 **Ready for genesis launch!**
