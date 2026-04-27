# WEPO iOS Wallet - TestFlight Setup Guide

## 🚀 Quick Start for TestFlight

This guide will help you get the WEPO iOS Wallet ready for TestFlight distribution.

### Prerequisites ✅
- [x] Apple Developer Account ($99/year)
- [x] Xcode 15+
- [x] iOS 16+ test devices
- [x] WEPO backend API running

### Step 1: Apple Developer Account Setup

1. **Sign up for Apple Developer Program**:
   - Visit [developer.apple.com](https://developer.apple.com)
   - Enroll in Apple Developer Program
   - Wait for approval (1-2 business days)

2. **Create App Store Connect Record**:
   - Go to [appstoreconnect.apple.com](https://appstoreconnect.apple.com)
   - Click "My Apps" → "+" → "New App"
   - Fill in app information:
     - **Platform**: iOS
     - **Name**: WEPO Wallet
     - **Primary Language**: English
     - **Bundle ID**: com.wepo.wallet (or your custom identifier)
     - **SKU**: wepo-wallet-ios

### Step 2: Xcode Configuration

1. **Open the project**:
   ```bash
   cd /app/wepo-ios-wallet
   open WepoWallet.xcodeproj
   ```

2. **Configure Team & Signing**:
   - Select WepoWallet target
   - Go to "Signing & Capabilities"
   - Select your Apple Developer team
   - Ensure "Automatically manage signing" is checked
   - Update Bundle Identifier if needed

3. **Add Required Capabilities**:
   - Face ID/Touch ID: Already configured
   - Keychain Sharing: Already configured
   - Network permissions: Already configured

### Step 3: App Store Connect Configuration

1. **App Information**:
   - **Category**: Finance
   - **Age Rating**: 17+ (Unrestricted Web Access)
   - **Content Rights**: Check if you own/license content

2. **Privacy Policy** (Required):
   Create a privacy policy at `https://yourwebsite.com/privacy` covering:
   - No data collection policy
   - Local-only storage
   - Self-custodial nature
   - No third-party analytics

3. **App Description**:
   ```
   WEPO Wallet is a self-custodial cryptocurrency wallet designed for privacy and security. 
   
   Key Features:
   • Self-custodial WEPO and Bitcoin wallet
   • BIP-39 compliant seed phrase generation
   • Quantum-resistant privacy features
   • Mobile mining and staking
   • No fees, no tracking, complete privacy
   
   IMPORTANT: This is a self-custodial wallet. You are responsible for securely storing your recovery phrase. Lost recovery phrases cannot be recovered.
   
   Cryptocurrency investments carry risk. Only invest what you can afford to lose.
   ```

### Step 4: Required Screenshots

Create screenshots for these device sizes:
- **iPhone 6.7"** (iPhone 15 Pro Max): 1290 x 2796 pixels
- **iPhone 6.5"** (iPhone 14 Plus): 1242 x 2688 pixels  
- **iPhone 5.5"** (iPhone 8 Plus): 1242 x 2208 pixels

Screenshot the following screens:
1. Welcome/Login screen
2. Dashboard with balance
3. Send transaction screen
4. Bitcoin integration screen
5. Mining interface

### Step 5: Build and Upload

1. **Archive the App**:
   - In Xcode: Product → Archive
   - Wait for build to complete
   - Click "Distribute App"
   - Select "App Store Connect"
   - Follow upload wizard

2. **Alternative CLI Method**:
   ```bash
   # Build archive
   xcodebuild archive \
     -project WepoWallet.xcodeproj \
     -scheme WepoWallet \
     -configuration Release \
     -archivePath WepoWallet.xcarchive

   # Export for App Store
   xcodebuild -exportArchive \
     -archivePath WepoWallet.xcarchive \
     -exportPath ./build \
     -exportOptionsPlist ExportOptions.plist
   ```

### Step 6: TestFlight Setup

1. **Internal Testing** (Immediate):
   - Add up to 25 internal testers
   - Internal testers can install immediately
   - Use for initial testing and team review

2. **External Testing** (Requires Review):
   - Add up to 10,000 external testers
   - Requires Apple review (24-48 hours)
   - Provide test information:
     ```
     Test Information:
     - Create a test wallet or import existing one
     - Test sending/receiving WEPO tokens
     - Test Bitcoin wallet integration
     - Test mining and staking features
     - Verify security features work properly
     
     Test Credentials:
     - No special credentials needed
     - App generates test wallets automatically
     ```

### Step 7: Beta Testing Instructions

**For Beta Testers**:

1. **Install TestFlight**:
   - Download TestFlight from App Store
   - Accept beta testing invitation

2. **First Time Setup**:
   - Open WEPO Wallet
   - Choose "Create New Wallet"
   - Securely store the 12-word recovery phrase
   - Complete wallet setup

3. **Testing Checklist**:
   - [ ] Create new wallet successfully
   - [ ] Import existing wallet with seed phrase
   - [ ] Send test WEPO tokens
   - [ ] Receive WEPO tokens
   - [ ] View Bitcoin balance and address
   - [ ] Test mining interface
   - [ ] Verify biometric authentication
   - [ ] Test all main navigation tabs

### Step 8: Required Legal Documents

1. **Privacy Policy** (Sample):
   ```
   WEPO Wallet Privacy Policy
   
   Data Collection: We do not collect any personal data.
   Local Storage: All wallet data is stored locally on your device.
   Third Parties: We do not share data with third parties.
   Analytics: We do not use analytics or tracking.
   Contact: support@wepo.network for privacy questions.
   ```

2. **Terms of Service** (Sample):
   ```
   WEPO Wallet Terms of Service
   
   Self-Custodial: You are responsible for your wallet security.
   Recovery: Lost recovery phrases cannot be recovered.
   Risks: Cryptocurrency investments carry financial risk.
   No Warranty: Software provided "as is" without warranty.
   Support: Community support available at wepo.network.
   ```

### Step 9: Common Issues & Solutions

**Build Errors**:
- Ensure all dependencies are properly installed
- Check code signing configuration
- Verify bundle identifier uniqueness

**TestFlight Review Rejection**:
- Add required cryptocurrency disclaimers
- Include privacy policy URL
- Provide clear app description
- Add content rating explanation

**Testing Issues**:
- Test on multiple iOS versions (16.0+)
- Verify network connectivity requirements
- Test biometric authentication on real devices

### Step 10: Launch Timeline

**Recommended Schedule**:
- **Week 1**: Apple Developer account + App Store Connect setup
- **Week 2**: Build upload + internal testing
- **Week 3**: External beta testing + feedback collection
- **Week 4**: Final fixes + App Store submission preparation

**Target Release Planning**:
- TestFlight Beta: November 2024
- App Store Review: December 2024  
- Public Launch: TBD pending release approval

## 🎯 Success Metrics

**TestFlight Goals**:
- [ ] 100+ beta testers
- [ ] 4.0+ average rating
- [ ] <5% crash rate
- [ ] All major features tested
- [ ] Zero security issues reported

**Ready for App Store**:
- [ ] TestFlight feedback addressed
- [ ] Performance optimized
- [ ] All legal requirements met
- [ ] Full feature completeness
- [ ] Public launch criteria reviewed and approved

---

## 📞 Support

**Technical Issues**: Refer to main project documentation
**App Store Issues**: Apple Developer Support
**WEPO Network**: Community support channels

**The WEPO iOS Wallet is prepared for continued TestFlight work.**
