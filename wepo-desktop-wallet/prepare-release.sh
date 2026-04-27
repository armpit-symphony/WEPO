#!/bin/bash

echo "🎯 WEPO Desktop Wallet - Release Preparation"
echo "============================================"
echo ""

# Check if we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Error: Please run this script from the wepo-desktop-wallet root directory"
    exit 1
fi

echo "📦 Step 1: Installing main dependencies..."
npm install

echo "📦 Step 2: Installing frontend dependencies..."
cd src/frontend
npm install
cd ../..

echo "🔨 Step 3: Building frontend..."
cd src/frontend
npm run build
cd ../..

echo "📁 Step 4: Preparing release folder..."
mkdir -p release/wepo-desktop-wallet

# Copy main files
cp -r src/ release/wepo-desktop-wallet/
cp -r node_modules/ release/wepo-desktop-wallet/
cp package.json release/wepo-desktop-wallet/
cp README.md release/wepo-desktop-wallet/
cp DEVELOPMENT.md release/wepo-desktop-wallet/
cp start-wallet.bat release/wepo-desktop-wallet/
cp .gitignore release/wepo-desktop-wallet/

# Remove frontend node_modules to save space (they're not needed in production)
rm -rf release/wepo-desktop-wallet/src/frontend/node_modules

echo "🗜️  Step 5: Creating release ZIP..."
cd release
zip -r "wepo-desktop-wallet-v1.0.0.zip" wepo-desktop-wallet/ -q
cd ..

echo ""
echo "✅ Release preparation complete!"
echo ""
echo "📋 Release package created:"
echo "   📁 Folder: release/wepo-desktop-wallet/"
echo "   📦 ZIP: release/wepo-desktop-wallet-v1.0.0.zip"
echo ""
echo "🚀 To distribute:"
echo "   1. Upload the ZIP file to GitHub Releases"
echo "   2. Users download and extract the ZIP"
echo "   3. Users run start-wallet.bat to launch"
echo ""
echo "🎄 Ready for genesis launch!"