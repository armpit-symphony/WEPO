//! Minimal raw-WASM ABI for the exact Ghost wallet request handler.
//!
//! This deliberately exposes byte buffers only. The browser wrapper must use
//! the same bounded protocol and response framing as the native sidecar.

use std::slice;

use super::wallet_protocol;

static mut LAST_RESPONSE: Vec<u8> = Vec::new();

#[no_mangle]
pub extern "C" fn wepo_ghost_alloc(length: usize) -> *mut u8 {
    let mut buffer = Vec::with_capacity(length);
    let pointer = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    pointer
}

#[no_mangle]
pub unsafe extern "C" fn wepo_ghost_dealloc(pointer: *mut u8, length: usize) {
    if !pointer.is_null() {
        drop(Vec::from_raw_parts(pointer, 0, length));
    }
}

#[no_mangle]
pub unsafe extern "C" fn wepo_ghost_handle_request(pointer: *const u8, length: usize) -> u32 {
    if pointer.is_null() || length > wallet_protocol::MAX_REQUEST_BYTES {
        LAST_RESPONSE = Vec::new();
        return 0;
    }
    let request = slice::from_raw_parts(pointer, length);
    LAST_RESPONSE = wallet_protocol::handle_request(request);
    LAST_RESPONSE.as_ptr() as u32
}

#[no_mangle]
pub unsafe extern "C" fn wepo_ghost_response_ptr() -> u32 {
    LAST_RESPONSE.as_ptr() as u32
}

#[no_mangle]
pub unsafe extern "C" fn wepo_ghost_response_len() -> u32 {
    LAST_RESPONSE.len() as u32
}
