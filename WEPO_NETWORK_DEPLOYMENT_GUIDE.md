# WEPO Blockchain Network Deployment Guide

## 🎯 Overview

To launch the WEPO blockchain network, you need to set up the backend infrastructure that wallets will connect to. Currently, your desktop wallet uses a local simulation - you need to replace this with real blockchain nodes.

## 📋 What You Need to Deploy

### **1. Core Infrastructure**
- **WEPO Blockchain Nodes** (minimum 3 for network resilience)
- **API Endpoints** (for wallet connections)
- **Seed Nodes** (for P2P network discovery)
- **Mining Pool** (optional, for coordinated mining)

### **2. Network Architecture**

```
Internet
    │
┌───▼────┐    ┌────────────┐    ┌─────────────┐
│ Users  │    │   CDN/     │    │   Load      │
│Wallets │◄──►│  Proxy     │◄──►│  Balancer   │
└────────┘    └────────────┘    └─────┬───────┘
                                      │
                              ┌───────▼────────┐
                              │  API Gateway   │
                              └───────┬────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
   ┌────▼────┐                   ┌────▼────┐                   ┌────▼────┐
   │ Node 1  │◄─────P2P──────────►│ Node 2  │◄─────P2P──────────►│ Node 3  │
   │(Mining) │                   │(Relay)  │                   │(Archive)│
   └─────────┘                   └─────────┘                   └─────────┘
```

## 🚀 Deployment Steps

### **Step 1: Server Setup**

**Minimum Requirements per Node:**
- **CPU**: 4 vCPU cores
- **RAM**: 8GB RAM
- **Storage**: 100GB SSD
- **Network**: 1Gbps connection
- **OS**: Ubuntu 22.04 LTS

**Recommended Providers:**
- AWS EC2 (c5.xlarge)
- Google Cloud (n2-standard-4)
- DigitalOcean (4 vCPU, 8GB)
- Hetzner (CX41)

### **Step 2: Genesis Launch**

```bash
# 1. Run the genesis script on your development machine
./wepo-network-genesis.sh

# 2. This creates all necessary configuration files:
#    - genesis.json (network configuration)
#    - Docker files for deployment
#    - Systemd service files
#    - Nginx proxy configuration
```

### **Step 3: Deploy Blockchain Nodes**

**Option A: Docker Deployment (Recommended)**
```bash
# On each server:
git clone https://github.com/your-org/wepo-blockchain
cd wepo-blockchain
cp /path/to/genesis.json .
docker-compose up -d
```

**Option B: Native Installation**
```bash
# On each server:
sudo apt update && sudo apt install python3 python3-pip sqlite3
git clone https://github.com/your-org/wepo-blockchain
cd wepo-blockchain
pip3 install -r requirements.txt
sudo cp wepo-node.service /etc/systemd/system/
sudo systemctl enable wepo-node
sudo systemctl start wepo-node
```

### **Step 4: Configure Load Balancer**

**Cloudflare/AWS CloudFront Example:**
```
api.wepo.network → Load Balancer → {
  node1.wepo.network:8001
  node2.wepo.network:8001  
  node3.wepo.network:8001
}
```

### **Step 5: Update Wallet Configuration**

**Desktop Wallet Backend Update:**
```javascript
// In /app/wepo-desktop-wallet/src/backend/server.js
// Replace simulation with real API calls

const WEPO_API_ENDPOINTS = [
  'https://api1.wepo.network',
  'https://api2.wepo.network', 
  'https://api3.wepo.network'
];

// Update all endpoints to proxy to real blockchain
app.get('/api/wallet/:address', async (req, res) => {
  const response = await fetch(`${WEPO_API_ENDPOINTS[0]}/api/wallet/${req.params.address}`);
  const data = await response.json();
  res.json(data);
});
```

**Web Wallet Update:**
```bash
# Update environment variables
REACT_APP_BACKEND_URL=https://api.wepo.network
```

## 🌐 DNS Configuration

**Required DNS Records:**
```
A     api.wepo.network      → Load Balancer IP
A     node1.wepo.network    → Server 1 IP
A     node2.wepo.network    → Server 2 IP  
A     node3.wepo.network    → Server 3 IP
AAAA  api.wepo.network      → Load Balancer IPv6 (optional)
```

## 🔐 Security Configuration

**1. SSL Certificates:**
```bash
# Use Let's Encrypt for free SSL
sudo certbot --nginx -d api.wepo.network
```

**2. Firewall Rules:**
```bash
# Allow API and P2P ports
sudo ufw allow 8001/tcp   # API
sudo ufw allow 22567/tcp  # P2P
sudo ufw allow 22/tcp     # SSH
sudo ufw enable
```

**3. Rate Limiting:**
```nginx
# In nginx config
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req zone=api burst=20 nodelay;
```

## 📊 Monitoring Setup

**1. Node Health Monitoring:**
```bash
# Install monitoring tools
sudo apt install prometheus node-exporter grafana
```

**2. API Endpoint Monitoring:**
```bash
# Check node status
curl https://api.wepo.network/api/network/status

# Expected response:
{
  "success": true,
  "network": "mainnet", 
  "block_height": 1234,
  "connected_peers": 15,
  "mining_active": true
}
```

## Launch Planning

**Launch Sequence:**
1. Deploy nodes and validate the production network
2. Complete security review and operational sign-off
3. Create the genesis block after production approval
4. Announce network availability and wallet distribution

## 🚀 Estimated Costs

**Monthly Infrastructure Costs:**
- **3 Blockchain Nodes**: $150-300/month
- **Load Balancer**: $20-50/month
- **CDN/Proxy**: $10-30/month
- **Monitoring**: $20-40/month
- **SSL Certificates**: Free (Let's Encrypt)
- **Total**: ~$200-420/month

## 📱 After Network Launch

**Update All Wallets:**
1. **Desktop Wallet**: Update backend to use real APIs
2. **Web Wallet**: Update environment variables
3. **Mobile Wallet**: Update API endpoints
4. **Documentation**: Update all connection guides

## 🔧 Testing Before Launch

**Local Testing:**
```bash
# Test with local network first
cd /app/wepo-blockchain
./scripts/start_network.sh

# Test wallet connection
curl http://localhost:8001/api/network/status
```

**Production Testing:**
```bash
# Test production endpoints
curl https://api.wepo.network/api/network/status
curl https://api.wepo.network/api/blocks/latest
curl https://api.wepo.network/api/mining/info
```

## 🎯 Summary: What You Need to Do

1. **🖥️  Get 3 servers** (AWS, Google Cloud, etc.)
2. **🚀 Run the genesis script** to create configuration
3. **📦 Deploy using Docker** or systemd services
4. **🌐 Set up DNS and load balancing**
5. **🔒 Configure SSL and security**
6. **📊 Set up basic monitoring**
7. **🔧 Update wallet backends** to use real APIs
8. **🎄 Launch on genesis date!**

The blockchain code is ready - you just need to deploy the infrastructure and update the wallet connections!
