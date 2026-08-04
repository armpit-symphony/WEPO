//! Local-only Ghost wallet bridge. Reads one bounded binary request from stdin
//! and writes one bounded response to stdout. It never accepts secrets in argv,
//! opens a socket, writes a witness to disk, or emits witness-bearing logs.

use std::io::{self, Read, Write};
use wepo_zk::ghost::wallet_protocol::{handle_request, MAX_REQUEST_BYTES};

fn main() -> io::Result<()> {
    let mut request = Vec::new();
    io::stdin()
        .take((MAX_REQUEST_BYTES + 1) as u64)
        .read_to_end(&mut request)?;
    let response = handle_request(&request);
    io::stdout().write_all(&response)?;
    io::stdout().flush()
}
