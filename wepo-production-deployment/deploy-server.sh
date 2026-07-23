#!/bin/bash

# WEPO Network Production Deployment Script
# Run this on your production server
#
# LEGACY NOTICE:
# - This script predates the canonical backend/node hardening path.
# - It still provisions the bridge-era deployment model and should not be treated
#   as the authoritative production runbook.
# - Verify the canonical local backend/node flow first with:
#   wepo-blockchain/scripts/run_canonical_fee_smoke.sh

set -e

LEGACY_DEPLOY_RETIRED=1
if [[ "${WEPO_ALLOW_LEGACY_BRIDGE_DEPLOY:-}" != "I_UNDERSTAND_THIS_DEPLOYS_RETIRED_PLACEHOLDER_CODE" ]]; then
    echo "ERROR: This legacy bridge deployment path is retired and must not be used for public launch."
    echo "Use the canonical backend plus full-node deployment runbook instead."
    exit 1
fi

echo "🚀 WEPO Network Production Deployment"
echo "====================================="
echo "⚠️  LEGACY NOTICE: this script provisions the bridge-era deployment path"
echo "⚠️  Verify the canonical backend/node path first via run_canonical_fee_smoke.sh"
echo ""

# Configuration
DOMAIN="api.wepo.network"  # Change this to your domain
WEPO_USER="wepo"
WEPO_DIR="/opt/wepo"
SERVICE_NAME="wepo-api"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}📋 Configuration:${NC}"
echo -e "   Domain: ${DOMAIN}"
echo -e "   Install Directory: ${WEPO_DIR}"
echo -e "   Service User: ${WEPO_USER}"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}❌ This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Step 1: System Updates
echo -e "${YELLOW}📦 Step 1: Updating system packages...${NC}"
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git curl wget unzip sqlite3

echo -e "${GREEN}✅ System packages updated${NC}"

# Step 2: Create WEPO user
echo -e "${YELLOW}👤 Step 2: Creating WEPO user...${NC}"
if ! id "$WEPO_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$WEPO_USER"
    echo -e "${GREEN}✅ User $WEPO_USER created${NC}"
else
    echo -e "${BLUE}ℹ️  User $WEPO_USER already exists${NC}"
fi

# Step 3: Create directories
echo -e "${YELLOW}📁 Step 3: Setting up directories...${NC}"
mkdir -p "$WEPO_DIR"
chown "$WEPO_USER:$WEPO_USER" "$WEPO_DIR"
echo -e "${GREEN}✅ Directories created${NC}"

# Step 4: Install Python dependencies globally
echo -e "${YELLOW}🐍 Step 4: Installing Python dependencies...${NC}"
pip3 install --upgrade pip

# Install required packages
pip3 install \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    python-multipart \
    requests \
    cryptography \
    sqlite3 \
    passlib \
    bcrypt \
    python-jose \
    python-dotenv

echo -e "${GREEN}✅ Python dependencies installed${NC}"

# Step 5: Configure Nginx
echo -e "${YELLOW}🌐 Step 5: Configuring Nginx...${NC}"

# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Create WEPO site configuration
cat > /etc/nginx/sites-available/wepo-api << EOF
server {
    listen 80;
    server_name ${DOMAIN};
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    
    # Rate limiting
    limit_req_zone \$binary_remote_addr zone=api:10m rate=30r/m;
    limit_req zone=api burst=10 nodelay;
    
    location / {
        proxy_pass http://localhost:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # CORS headers for wallet access
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type, Authorization, X-Requested-With";
        
        # Handle preflight requests
        if (\$request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin *;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
            add_header Access-Control-Allow-Headers "Content-Type, Authorization, X-Requested-With";
            add_header Content-Length 0;
            add_header Content-Type text/plain;
            return 200;
        }
        
        # Timeout settings
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        return 200 "WEPO Network OK\n";
        add_header Content-Type text/plain;
    }
}
EOF

# Enable site
ln -sf /etc/nginx/sites-available/wepo-api /etc/nginx/sites-enabled/

# Test nginx configuration
nginx -t

echo -e "${GREEN}✅ Nginx configured${NC}"

# Step 6: Create systemd service
echo -e "${YELLOW}⚙️  Step 6: Creating systemd service...${NC}"

cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=WEPO Blockchain Network API
After=network.target
Wants=network.target

[Service]
Type=simple
User=${WEPO_USER}
Group=${WEPO_USER}
WorkingDirectory=${WEPO_DIR}
ExecStart=/usr/bin/python3 ${WEPO_DIR}/wepo-fast-test-bridge.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment variables
Environment=PYTHONPATH=${WEPO_DIR}
Environment=WEPO_ENV=production

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${WEPO_DIR}

# Resource limits
LimitNOFILE=8192
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

echo -e "${GREEN}✅ Systemd service created${NC}"

# Step 7: Create deployment directory structure
echo -e "${YELLOW}📂 Step 7: Creating deployment structure...${NC}"

# Create log directory
mkdir -p /var/log/wepo
chown "$WEPO_USER:$WEPO_USER" /var/log/wepo

# Create data directory for blockchain data
mkdir -p /var/lib/wepo
chown "$WEPO_USER:$WEPO_USER" /var/lib/wepo

# Create backup directory
mkdir -p /var/backups/wepo
chown "$WEPO_USER:$WEPO_USER" /var/backups/wepo

echo -e "${GREEN}✅ Directory structure created${NC}"

# Step 8: Configure firewall
echo -e "${YELLOW}🔥 Step 8: Configuring firewall...${NC}"

# Install and configure ufw
apt install -y ufw

# Reset firewall rules
ufw --force reset

# Allow SSH (important!)
ufw allow ssh

# Allow HTTP and HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Allow WEPO API port (for direct access if needed)
ufw allow 8001/tcp

# Enable firewall
ufw --force enable

echo -e "${GREEN}✅ Firewall configured${NC}"

# Step 9: Setup log rotation
echo -e "${YELLOW}📝 Step 9: Setting up log rotation...${NC}"

cat > /etc/logrotate.d/wepo << EOF
/var/log/wepo/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    create 644 ${WEPO_USER} ${WEPO_USER}
    postrotate
        systemctl reload ${SERVICE_NAME}
    endscript
}
EOF

echo -e "${GREEN}✅ Log rotation configured${NC}"

echo ""
echo -e "${GREEN}🎉 WEPO Production Server Setup Complete!${NC}"
echo ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo -e "   1. Upload your WEPO files to ${WEPO_DIR}/"
echo -e "   2. Run: systemctl enable ${SERVICE_NAME}"
echo -e "   3. Run: systemctl start ${SERVICE_NAME}"
echo -e "   4. Get SSL certificate: certbot --nginx -d ${DOMAIN}"
echo -e "   5. Update DNS: Point ${DOMAIN} to this server's IP"
echo ""
echo -e "${BLUE}📊 Status Commands:${NC}"
echo -e "   systemctl status ${SERVICE_NAME}     # Check service status"
echo -e "   journalctl -u ${SERVICE_NAME} -f    # View live logs"
echo -e "   curl http://localhost:8001/api/     # Test API"
echo ""
echo -e "${YELLOW}⚠️  Don't forget to:${NC}"
echo -e "   - Update your domain DNS settings"
echo -e "   - Upload your WEPO blockchain files"
echo -e "   - Test the API before announcing"
echo ""
echo -e "${GREEN}🎄 Ready for genesis launch!${NC}"
