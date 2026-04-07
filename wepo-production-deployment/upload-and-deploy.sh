#!/bin/bash

# WEPO File Upload Script
# Run this from your local machine to upload WEPO files to production server
#
# LEGACY NOTICE:
# - This script still deploys the bridge-era `wepo-fast-test-bridge.py` path.
# - It is not the current authoritative production deployment path.
# - Verify the canonical local backend/node flow first with:
#   /home/sparky/WEPO/wepo-blockchain/scripts/run_canonical_fee_smoke.sh

set -e

# Configuration - UPDATE THESE
SERVER_IP="YOUR_SERVER_IP"           # e.g., "192.168.1.100" or "your-domain.com"
SERVER_USER="root"                   # Usually "root" for initial setup
DOMAIN="api.wepo.network"            # Your chosen domain
WEPO_DIR="/opt/wepo"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 WEPO Network Deployment - File Upload${NC}"
echo -e "${BLUE}=========================================${NC}"
echo -e "${YELLOW}⚠️  LEGACY NOTICE: this script deploys the bridge-era backend path${NC}"
echo -e "${YELLOW}⚠️  Verify the canonical backend/node path first via run_canonical_fee_smoke.sh${NC}"
echo ""

# Check if configuration is updated
if [[ "$SERVER_IP" == "YOUR_SERVER_IP" ]]; then
    echo -e "${RED}❌ Please update the configuration in this script first:${NC}"
    echo -e "   - Set SERVER_IP to your server's IP address"
    echo -e "   - Set DOMAIN to your domain name"
    echo -e "   - Set SERVER_USER (usually 'root' for initial setup)"
    exit 1
fi

echo -e "${BLUE}📋 Configuration:${NC}"
echo -e "   Server: ${SERVER_USER}@${SERVER_IP}"
echo -e "   Domain: ${DOMAIN}"
echo -e "   Remote Directory: ${WEPO_DIR}"
echo ""

# Test SSH connection
echo -e "${YELLOW}🔗 Testing SSH connection...${NC}"
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "${SERVER_USER}@${SERVER_IP}" exit 2>/dev/null; then
    echo -e "${RED}❌ Cannot connect to server. Please check:${NC}"
    echo -e "   - Server IP address is correct"
    echo -e "   - SSH key is set up (run: ssh-copy-id ${SERVER_USER}@${SERVER_IP})"
    echo -e "   - Server is running and accessible"
    exit 1
fi
echo -e "${GREEN}✅ SSH connection successful${NC}"

# Step 1: Run server deployment script
echo -e "${YELLOW}📦 Step 1: Running server setup script...${NC}"
scp deploy-server.sh "${SERVER_USER}@${SERVER_IP}:/tmp/"
ssh "${SERVER_USER}@${SERVER_IP}" "chmod +x /tmp/deploy-server.sh && /tmp/deploy-server.sh"
echo -e "${GREEN}✅ Server setup complete${NC}"

# Step 2: Upload WEPO backend files
echo -e "${YELLOW}📤 Step 2: Uploading WEPO backend files...${NC}"

# Copy main backend file
scp ../wepo-fast-test-bridge.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"

# Copy requirements file
scp ../backend/requirements.txt "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"

# Copy security utils
scp ../backend/security_utils.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"

# Copy other important files
scp ../quantum_vault_system.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"
scp ../production_zk_stark.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"
scp ../btc_privacy_mixing_service.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"
scp ../masternode_service_manager.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"
scp ../wepo_governance_system.py "${SERVER_USER}@${SERVER_IP}:${WEPO_DIR}/"

# Set correct ownership
ssh "${SERVER_USER}@${SERVER_IP}" "chown -R wepo:wepo ${WEPO_DIR}/"

echo -e "${GREEN}✅ WEPO files uploaded${NC}"

# Step 3: Install Python dependencies
echo -e "${YELLOW}🐍 Step 3: Installing Python dependencies...${NC}"
ssh "${SERVER_USER}@${SERVER_IP}" "cd ${WEPO_DIR} && pip3 install -r requirements.txt"
echo -e "${GREEN}✅ Dependencies installed${NC}"

# Step 4: Start WEPO service
echo -e "${YELLOW}⚙️  Step 4: Starting WEPO service...${NC}"
ssh "${SERVER_USER}@${SERVER_IP}" "systemctl enable wepo-api && systemctl start wepo-api"

# Wait for service to start
sleep 5

# Check service status
if ssh "${SERVER_USER}@${SERVER_IP}" "systemctl is-active --quiet wepo-api"; then
    echo -e "${GREEN}✅ WEPO service started successfully${NC}"
else
    echo -e "${RED}❌ WEPO service failed to start${NC}"
    echo -e "${YELLOW}Checking logs...${NC}"
    ssh "${SERVER_USER}@${SERVER_IP}" "journalctl -u wepo-api -n 20 --no-pager"
    exit 1
fi

# Step 5: Test API
echo -e "${YELLOW}🧪 Step 5: Testing API endpoints...${NC}"

# Test local API
if ssh "${SERVER_USER}@${SERVER_IP}" "curl -s http://localhost:8001/api/ | grep -q 'WEPO Fast Test API'"; then
    echo -e "${GREEN}✅ Local API test successful${NC}"
else
    echo -e "${RED}❌ Local API test failed${NC}"
    exit 1
fi

# Test nginx proxy
if ssh "${SERVER_USER}@${SERVER_IP}" "curl -s http://localhost/api/ | grep -q 'WEPO Fast Test API'"; then
    echo -e "${GREEN}✅ Nginx proxy test successful${NC}"
else
    echo -e "${RED}❌ Nginx proxy test failed${NC}"
    echo -e "${YELLOW}Checking nginx status...${NC}"
    ssh "${SERVER_USER}@${SERVER_IP}" "systemctl status nginx"
    exit 1
fi

# Step 6: Set up SSL certificate
echo -e "${YELLOW}🔒 Step 6: Setting up SSL certificate...${NC}"
echo -e "${BLUE}Note: This requires your domain to point to the server IP${NC}"

read -p "Is your domain ${DOMAIN} already pointing to ${SERVER_IP}? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ssh "${SERVER_USER}@${SERVER_IP}" "certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --email admin@${DOMAIN}"
    
    # Test HTTPS
    sleep 10
    if curl -s "https://${DOMAIN}/api/" | grep -q "WEPO Fast Test API"; then
        echo -e "${GREEN}✅ SSL certificate installed and HTTPS working${NC}"
    else
        echo -e "${YELLOW}⚠️  SSL installed but HTTPS test failed. May need time to propagate.${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Skipping SSL setup. Run this command on the server when DNS is ready:${NC}"
    echo -e "   certbot --nginx -d ${DOMAIN}"
fi

# Step 7: Final tests and status
echo -e "${YELLOW}🔍 Step 7: Final verification...${NC}"

echo -e "${BLUE}📊 Service Status:${NC}"
ssh "${SERVER_USER}@${SERVER_IP}" "systemctl status wepo-api --no-pager -l"

echo ""
echo -e "${GREEN}🎉 WEPO Network Deployment Complete!${NC}"
echo ""
echo -e "${BLUE}🌐 Your WEPO Network is now live at:${NC}"
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "   HTTPS: https://${DOMAIN}/api/"
    echo -e "   Test:  curl https://${DOMAIN}/api/"
else
    echo -e "   HTTP:  http://${SERVER_IP}/api/"
    echo -e "   Test:  curl http://${SERVER_IP}/api/"
fi
echo ""
echo -e "${BLUE}📱 Update Your Wallets:${NC}"
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "   Desktop Wallet: REACT_APP_BACKEND_URL=https://${DOMAIN}"
    echo -e "   Web Wallet:     REACT_APP_BACKEND_URL=https://${DOMAIN}"
else
    echo -e "   Desktop Wallet: REACT_APP_BACKEND_URL=http://${SERVER_IP}"
    echo -e "   Web Wallet:     REACT_APP_BACKEND_URL=http://${SERVER_IP}"
fi
echo ""
echo -e "${BLUE}🔧 Management Commands:${NC}"
echo -e "   Status:   ssh ${SERVER_USER}@${SERVER_IP} 'systemctl status wepo-api'"
echo -e "   Logs:     ssh ${SERVER_USER}@${SERVER_IP} 'journalctl -u wepo-api -f'"
echo -e "   Restart:  ssh ${SERVER_USER}@${SERVER_IP} 'systemctl restart wepo-api'"
echo ""
echo -e "${GREEN}🎄 Ready for genesis launch!${NC}"

# Step 8: Create wallet configuration files
echo -e "${YELLOW}📝 Step 8: Creating wallet configuration files...${NC}"

# Create updated desktop wallet .env
cat > ../wepo-desktop-wallet/src/frontend/.env << EOF
REACT_APP_BACKEND_URL=https://${DOMAIN}
REACT_APP_DESKTOP_MODE=true
GENERATE_SOURCEMAP=false
DISABLE_ESLINT_PLUGIN=true
EOF

# Create updated web wallet .env
cat > ../frontend/.env << EOF
REACT_APP_BACKEND_URL=https://${DOMAIN}
EOF

echo -e "${GREEN}✅ Wallet configuration files updated${NC}"
echo ""
echo -e "${BLUE}📦 Next Steps:${NC}"
echo -e "   1. Test your wallets with the new backend URL"
echo -e "   2. Rebuild desktop wallet: cd wepo-desktop-wallet && ./prepare-release.sh"
echo -e "   3. Upload to GitHub for users to download"
echo -e "   4. Announce your live WEPO network!"
echo ""
echo -e "${GREEN}🚀 Your WEPO blockchain network is now LIVE!${NC}"
