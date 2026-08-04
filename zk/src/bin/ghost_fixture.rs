//! Generate a deterministic, honestly-proved Ghost verifier request.
//!
//! Usage:
//!     ghost_fixture <output-file>
//!
//! The resulting file is the exact binary request accepted on stdin by
//! `ghost_verifier`. It contains only public statement data and a ZK proof.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::process;

use wepo_zk::ghost::{complete_bundle, protocol as ghost_protocol};

fn decode_sighash(value: &std::ffi::OsStr) -> Result<[u8; 32], &'static str> {
    let text = value.to_str().ok_or("sighash must be UTF-8 hex")?;
    if text.len() != 64 {
        return Err("sighash must be exactly 64 hex characters");
    }
    let mut result = [0u8; 32];
    for (index, byte) in result.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], 16)
            .map_err(|_| "sighash contains non-hex characters")?;
    }
    Ok(result)
}
fn run() -> Result<(), &'static str> {
    let mut args = env::args_os();
    let _program = args.next();
    let output = PathBuf::from(args.next().ok_or("missing output path")?);
    let requested_sighash = match args.next() {
        Some(value) => Some(decode_sighash(&value)?),
        None => None,
    };
    if args.next().is_some() {
        return Err("expected output path and optional 32-byte sighash hex");
    }

    let fixture = match requested_sighash {
        Some(sighash) => complete_bundle::fixture::build_with_sighash(sighash),
        None => complete_bundle::fixture::build(),
    };
    if !complete_bundle::production::verify_complete_bundle(
        &fixture.anchor,
        &fixture.nullifiers,
        &fixture.commitments,
        fixture.value_balance,
        &fixture.sighash,
        &fixture.raw_proof,
    ) {
        return Err("generated proof did not pass the production verifier");
    }
    let statement = ghost_protocol::PublicStatement {
        anchor: fixture.anchor,
        nullifiers: fixture.nullifiers,
        commitments: fixture.commitments,
        value_balance: fixture.value_balance,
        sighash: fixture.sighash,
    };
    let digest = ghost_protocol::statement_digest(&statement);
    let envelope = ghost_protocol::encode_envelope(&statement, &fixture.raw_proof)
        .ok_or("could not encode proof envelope")?;
    let request = ghost_protocol::encode_request(&digest, &envelope)
        .ok_or("could not encode verifier request")?;
    fs::write(output, request).map_err(|_| "could not write output file")
}

fn main() {
    if run().is_err() {
        process::exit(1);
    }
}
