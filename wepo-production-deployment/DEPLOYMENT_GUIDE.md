# WEPO Network Production Deployment Guide

## Status Notice

This deployment guide predates the current canonical backend/node hardening work.

It still reflects bridge-era assumptions and should not be treated as the authoritative production deployment runbook yet.

Before using any deployment instructions here, verify the current canonical local path first:

```bash
/home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh
```

That is the current authoritative local verification path for canonical backend-originated fee settlement.

For actual pre-release signoff, use the canonical release gate:

```bash
/home/sparky/WEPO/wepo-production-deployment/run-canonical-release-gate.sh
```

Runbook:

```text
/home/sparky/WEPO/wepo-production-deployment/CANONICAL_RELEASE_GATE.md
```

Canonical staging layout:

```text
/home/sparky/WEPO/wepo-production-deployment/CANONICAL_STAGING_DEPLOYMENT.md
```

Bootstrap script for installing the canonical staging templates:

```bash
/home/sparky/WEPO/wepo-production-deployment/bootstrap-canonical-staging.sh
```

## 🎯 Complete Deployment in 30 Minutes

This guide will get your WEPO blockchain network live on the internet in about 30 minutes.

## 📋 Prerequisites

**What You Need:**
- ✅ A VPS/Cloud server (DigitalOcean, AWS, etc.)
- ✅ A domain name (e.g., `api.wepo.network`)
- ✅ SSH access to your server
- ✅ Basic command line knowledge

**Server Requirements:**
- **OS**: Ubuntu 22.04 LTS (recommended)
- **RAM**: 4GB minimum
- **CPU**: 2 vCPU cores minimum
- **Storage**: 20GB SSD minimum
- **Network**: Good internet connection

## 🚀 Deployment Steps

### **Step 1: Get Your Server (5 minutes)**

**Option A: DigitalOcean (Recommended)**
```bash
# Create a new droplet:
# - Ubuntu 22.04 LTS
# - 4GB RAM / 2 vCPU ($24/month)
# - Choose datacenter near your users
# - Add your SSH key
```

**Option B: AWS EC2**
```bash
# Launch instance:
# - Ubuntu 22.04 LTS AMI
# - t3.medium instance
# - Configure security group (allow ports 22, 80, 443)
```

### **Step 2: Configure DNS (2 minutes)**

**Point your domain to your server:**
```bash
# Add these DNS records:
A     api.wepo.network    →  YOUR_SERVER_IP
AAAA  api.wepo.network    →  YOUR_SERVER_IPv6 (optional)
```

### **Step 3: Edit Deployment Script (1 minute)**

**Update the configuration in `upload-and-deploy.sh`:**
```bash
# Open the file and change these lines:
SERVER_IP="192.168.1.100"        # → Your actual server IP
SERVER_USER="root"               # → Usually "root" for initial setup
DOMAIN="api.wepo.network"        # → Your actual domain
```

### **Step 4: Set Up SSH Access (2 minutes)**

**Add your SSH key to the server:**
```bash
# Copy your SSH key to the server
ssh-copy-id root@YOUR_SERVER_IP
# or
ssh-copy-id ubuntu@YOUR_SERVER_IP

# Test connection
ssh root@YOUR_SERVER_IP
```

### **Step 5: Run Deployment (15 minutes)**

**Execute the deployment script:**
```bash
cd /app/wepo-production-deployment
./upload-and-deploy.sh
```

**The script will automatically:**
- ✅ Install all required packages
- ✅ Configure nginx reverse proxy
- ✅ Set up systemd service
- ✅ Upload all WEPO files
- ✅ Install Python dependencies
- ✅ Configure firewall
- ✅ Set up SSL certificate
- ✅ Start WEPO service
- ✅ Test all endpoints

### **Step 6: Update Wallets (2 minutes)**

**The script automatically updates your wallet configs:**
```bash
# Desktop wallet .env file updated to:
REACT_APP_BACKEND_URL=https://api.wepo.network

# Web wallet .env file updated to:
REACT_APP_BACKEND_URL=https://api.wepo.network
```

### **Step 7: Test Everything (3 minutes)**

**Test your live network:**
```bash
# Test API health
curl https://api.wepo.network/api/

# Test wallet creation
curl -X POST https://api.wepo.network/api/wallet/create \
  -H "Content-Type: application/json" \
  -d '{"username":"test","encrypted_seed":"test_seed"}'

# Test Bitcoin integration
curl https://api.wepo.network/api/bitcoin/network/status

# Test Quantum Vault
curl -X POST https://api.wepo.network/api/vault/create \
  -H "Content-Type: application/json" \
  -d '{"wallet_address":"wepo1test123"}'
```

## ✅ Success Checklist

After deployment, verify these work:

- [ ] **API Health**: `curl https://api.wepo.network/api/` returns success
- [ ] **SSL Certificate**: HTTPS works without warnings
- [ ] **CORS Headers**: No CORS errors in browser
- [ ] **Service Status**: `systemctl status wepo-api` shows "active (running)"
- [ ] **Logs**: `journalctl -u wepo-api -f` shows no errors
- [ ] **Firewall**: Ports 80, 443, 8001 accessible
- [ ] **DNS**: Domain resolves to server IP

## 🔧 Post-Deployment Management

**Common Commands:**
```bash
# Check service status
ssh root@YOUR_SERVER_IP 'systemctl status wepo-api'

# View live logs
ssh root@YOUR_SERVER_IP 'journalctl -u wepo-api -f'

# Restart service
ssh root@YOUR_SERVER_IP 'systemctl restart wepo-api'

# Update WEPO code
scp wepo-fast-test-bridge.py root@YOUR_SERVER_IP:/opt/wepo/
ssh root@YOUR_SERVER_IP 'systemctl restart wepo-api'

# Check API health
curl https://api.wepo.network/api/
```

**Log Locations:**
- **Service Logs**: `journalctl -u wepo-api`
- **Nginx Logs**: `/var/log/nginx/access.log`
- **SSL Logs**: `/var/log/letsencrypt/letsencrypt.log`

## 🎯 What You Get

**After successful deployment:**

✅ **Live WEPO Blockchain Network**
- Professional API endpoints with SSL
- Global accessibility from any wallet
- High availability and reliability

✅ **All Features Working**
- Wallet creation and management
- Bitcoin integration (mainnet)
- Quantum Vault privacy system
- Mining, staking, masternodes
- Complete transaction system

✅ **Operational Hardening In Scope**
- Automatic service restart
- Log rotation
- Security hardening
- Firewall protection
- SSL encryption

✅ **User Ready**
- Desktop wallet connects automatically
- Web wallet ready for browsers
- GitHub distribution ready

## Launch Planning

**Timeline:**
- **Phase 1**: Deploy network infrastructure
- **Phase 2**: Test all functionality in staging
- **Phase 3**: Complete security and operations review
- **Phase 4**: Announce public availability when release criteria are met

## 💰 Monthly Costs

**Simple Deployment:**
- **DigitalOcean 4GB Droplet**: $24/month
- **Domain Name**: $10-15/year
- **SSL Certificate**: Free (Let's Encrypt)
- **Total**: ~$25/month

## 🆘 Troubleshooting

**Common Issues:**

**Service Won't Start:**
```bash
journalctl -u wepo-api -n 50  # Check logs
systemctl status wepo-api     # Check status
```

**SSL Certificate Fails:**
```bash
# Make sure DNS is pointing to server
dig api.wepo.network

# Retry certificate
certbot --nginx -d api.wepo.network
```

**API Not Accessible:**
```bash
# Check firewall
ufw status

# Check nginx
systemctl status nginx
nginx -t
```

**Python Dependencies Missing:**
```bash
cd /opt/wepo
pip3 install -r requirements.txt
systemctl restart wepo-api
```

## 🎉 Success!

When everything is working, you'll have:

- **Live API**: `https://api.wepo.network/api/`
- **Global Access**: Wallets connect from anywhere
- **Professional Setup**: SSL, monitoring, logging
- **Christmas Ready**: Genesis launch prepared

**Your WEPO blockchain network is now LIVE! 🚀**

Users can download your desktop wallet from GitHub and immediately start using the full WEPO ecosystem with real Bitcoin integration, privacy features, and network participation!
