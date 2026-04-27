# WEPO iOS Wallet

A native iOS wallet application for the WEPO cryptocurrency network, built with SwiftUI and designed for TestFlight distribution.

## 🎯 Project Overview

WEPO iOS Wallet is a self-custodial cryptocurrency wallet that provides:
- **Secure Wallet Management**: BIP-39 compliant seed phrase generation and storage
- **Bitcoin Integration**: Self-custodial Bitcoin wallet with BIP-44 standard
- **Privacy Features**: Quantum Vault integration for enhanced anonymity
- **Network Participation**: Mobile mining and staking capabilities
- **Modern iOS Design**: Built with SwiftUI for iOS 16+

## ✨ Features

### Core Wallet Features
- ✅ Create and import WEPO wallets
- ✅ Secure seed phrase storage in iOS Keychain
- ✅ Send and receive WEPO tokens
- ✅ Transaction history and balance tracking
- ✅ Biometric authentication (Face ID/Touch ID)

### Bitcoin Integration
- ✅ Self-custodial Bitcoin wallet
- ✅ BIP-44 standard compliance
- ✅ Bitcoin balance viewing
- ✅ Address generation and QR codes
- ✅ Recovery information for portability

### Advanced Features
- ✅ Mobile mining interface
- ✅ Staking rewards system
- ✅ Quantum Vault privacy protection
- ✅ Private transaction modes
- ✅ QR code scanning and generation

### Security & Privacy
- ✅ Keychain integration with biometric protection
- ✅ Input validation and sanitization
- ✅ Address validation for WEPO and Bitcoin
- ✅ Secure storage for sensitive data
- ✅ No data tracking or analytics

## 🏗️ Architecture

### Technology Stack
- **Framework**: SwiftUI + Combine
- **Target iOS**: 16.0+
- **Architecture**: MVVM pattern
- **Security**: iOS Keychain + Secure Enclave
- **Networking**: Alamofire for API calls
- **Cryptography**: CryptoSwift + Apple CryptoKit

### Project Structure
```
WepoWallet/
├── WepoWalletApp.swift          # App entry point
├── ContentView.swift            # Main content view
├── Views/                       # UI components
│   ├── WalletSetupView.swift    # Wallet creation/import
│   ├── DashboardView.swift      # Main dashboard
│   ├── SendTokenView.swift      # Send transactions
│   ├── ReceiveTokenView.swift   # Receive tokens
│   ├── BitcoinView.swift        # Bitcoin integration
│   ├── MiningView.swift         # Mining interface
│   ├── QuantumVaultView.swift   # Privacy vaults
│   └── SettingsView.swift       # App settings
├── Services/                    # Business logic
│   ├── WalletManager.swift      # Wallet state management
│   └── APIManager.swift         # Backend API integration
└── Security/                    # Security utilities
    └── SecurityManager.swift    # Keychain & crypto operations
```

## 🚀 Getting Started

### Prerequisites
- Xcode 15+
- iOS 16+ target device or simulator
- Apple Developer Account (for TestFlight)
- macOS Ventura+ development machine

### Installation

1. **Clone the project**:
   ```bash
   cd /app/wepo-ios-wallet
   ```

2. **Open in Xcode**:
   ```bash
   open WepoWallet.xcodeproj
   ```

3. **Install Dependencies**:
   - The project uses Swift Package Manager
   - Dependencies will be resolved automatically by Xcode
   - Required packages: Alamofire, CryptoSwift, Base58Swift, BigInt, Swift-Crypto

4. **Configure Signing**:
   - Select your development team in Xcode
   - Update bundle identifier if needed
   - Ensure proper code signing certificates

5. **Build and Run**:
   - Select target device or simulator
   - Press Cmd+R to build and run

### Backend Configuration

The app connects to the WEPO backend API. Update the base URL in `APIManager.swift`:

```swift
// For production
self.baseURL = "https://api.wepo.network"

// For development
self.baseURL = "http://localhost:8001"
```

## 📱 App Store / TestFlight Setup

### TestFlight Preparation

1. **App Store Connect Setup**:
   - Create app record in App Store Connect
   - Configure app metadata and descriptions
   - Upload required screenshots and app icon

2. **Required Metadata**:
   - **App Name**: WEPO Wallet
   - **Category**: Finance
   - **Age Rating**: 17+ (Unrestricted Web Access)
   - **Privacy Policy**: Required for financial apps

3. **Build Upload**:
   ```bash
   # Archive the app
   xcodebuild archive -project WepoWallet.xcodeproj -scheme WepoWallet -archivePath WepoWallet.xcarchive

   # Export for App Store
   xcodebuild -exportArchive -archivePath WepoWallet.xcarchive -exportPath . -exportOptionsPlist ExportOptions.plist
   ```

4. **TestFlight Distribution**:
   - Upload build via Xcode or Transporter
   - Add internal testers (up to 25)
   - Configure external testing (up to 10,000)
   - Provide test information and instructions

### Required Disclaimers

The app must include these disclaimers for App Store approval:

- Cryptocurrency investment risks
- Self-custodial wallet warnings  
- Network fees and transaction costs
- Beta software limitations
- No warranty or guarantee statements

## 🔐 Security Implementation

### Keychain Integration
```swift
// Secure wallet storage with biometric protection
let accessControl = SecAccessControlCreateWithFlags(
    kCFAllocatorDefault,
    kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
    [.biometryAny],
    &error
)
```

### Biometric Authentication
```swift
// Face ID / Touch ID authentication
func authenticateWithBiometrics(reason: String) async throws -> Bool {
    let context = LAContext()
    return try await context.evaluatePolicy(
        .deviceOwnerAuthenticationWithBiometrics,
        localizedReason: reason
    )
}
```

### Input Validation
```swift
// Address validation
func validateWepoAddress(_ address: String) -> Bool {
    return address.hasPrefix("wepo") && address.count == 40
}

// Amount validation with precision limits
func validateTransactionAmount(_ amount: String) -> Double? {
    guard let doubleValue = Double(amount),
          doubleValue > 0,
          doubleValue <= 1_000_000 else { return nil }
    
    let multiplier = pow(10.0, 8.0)
    return round(doubleValue * multiplier) / multiplier
}
```

## 🧪 Testing

### Unit Testing
Run unit tests for core functionality:
```bash
xcodebuild test -project WepoWallet.xcodeproj -scheme WepoWallet -destination 'platform=iOS Simulator,name=iPhone 15'
```

### UI Testing
Test complete user flows:
- Wallet creation and import
- Send/receive transactions
- Bitcoin integration
- Settings and security features

### TestFlight Beta Testing
- **Internal Testing**: 25 team members
- **External Testing**: Up to 10,000 beta users
- **Feedback Collection**: Built-in TestFlight feedback system

## 🔗 API Integration

### Backend Endpoints
The app integrates with these WEPO backend endpoints:

```swift
// Wallet Management
POST /api/wallet/create
POST /api/wallet/import
GET  /api/wallet/{address}

// Transactions
POST /api/transactions/send
GET  /api/transactions/{address}
GET  /api/balance/{address}

// Bitcoin Integration
POST /api/bitcoin/wallet/init
GET  /api/bitcoin/balance/{address}
POST /api/bitcoin/wallet/sync

// Network Features
POST /api/mining/start
GET  /api/mining/status
POST /api/staking/stake
POST /api/vault/create
```

### Error Handling
```swift
enum APIError: LocalizedError {
    case networkError(String)
    case serverError(String)
    case decodingError
    case invalidURL
    
    var errorDescription: String? {
        // Localized error messages
    }
}
```

## 📋 Development Roadmap

### Phase 1: MVP (Complete) ✅
- [x] Wallet creation and import
- [x] Basic WEPO send/receive
- [x] Bitcoin integration (view-only)
- [x] Security implementation
- [x] TestFlight ready

### Phase 2: Enhanced Features
- [ ] QR code camera integration
- [ ] Push notifications
- [ ] Advanced mining controls
- [ ] Transaction history filtering
- [ ] Multi-language support

### Phase 3: Advanced Features
- [ ] Hardware wallet integration
- [ ] DeFi protocol integration
- [ ] Advanced privacy features
- [ ] Performance optimizations
- [ ] App Store submission

## Launch Planning

The app is being developed toward a future public launch, with release timing still to be determined:

- **Backend Integration**: 100% compatible with existing WEPO API
- **Self-Custodial**: Full user control over funds and keys
- **Security Audited**: Comprehensive security implementation
- **TestFlight Ready**: Beta testing capabilities enabled

## 🆘 Support

### Technical Issues
- Check existing backend API documentation
- Review iOS development guidelines
- Test with WEPO network endpoints

### App Store Review
- Follow Apple's App Review Guidelines
- Include required cryptocurrency disclaimers
- Provide comprehensive app descriptions
- Ensure privacy policy compliance

### Community Resources
- WEPO Developer Documentation
- iOS Cryptocurrency App Guidelines
- TestFlight Beta Testing Best Practices

## 📄 License

This project is part of the WEPO cryptocurrency ecosystem. Please refer to the main project license for terms and conditions.

---

**Ready for TestFlight Distribution! 🚀**

The WEPO iOS Wallet is under active development and should be treated as a TestFlight evaluation candidate, not a production-approved release.
