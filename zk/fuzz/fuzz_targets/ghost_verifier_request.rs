#![no_main]

use libfuzzer_sys::fuzz_target;
use std::panic;
use wepo_zk::ghost::verifier::verify_request;

fuzz_target!(|data: &[u8]| {
    // This is the same entry point called by the production subprocess. A
    // deterministic honest request is generated into the runtime corpus before
    // each retained run so libFuzzer mutates real Winterfell proof metadata,
    // public inputs, statement binding, and both framing layers together.
    //
    // The production verifier contains Winterfell parser panics as a false
    // result. libFuzzer installs a panic hook that treats those contained
    // panics as fatal before unwind reaches the production catch boundary, so
    // the harness resets the hook to preserve the subprocess failure model.
    panic::set_hook(Box::new(|_| {}));
    let _ = verify_request(data);
});
