//! Versioned Ghost protocol surfaces that are safe to exercise independently.

#[doc(hidden)]
#[allow(dead_code)]
#[path = "../bin/step2_bundle.rs"]
pub mod complete_bundle;
pub use complete_bundle::wallet;

pub mod protocol;
pub mod verifier;
pub mod wallet_protocol;

#[cfg(target_arch = "wasm32")]
pub mod wasm;
