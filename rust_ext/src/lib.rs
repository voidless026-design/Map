//! Optional Rust-accelerated binary signature scanner for OpenAtlas.
//!
//! Exposes a single `scan(path) -> dict` function via PyO3. It mirrors the pure-Python
//! fallback in `openatlas/tools/image_analysis.py` but runs the byte search in Rust.
//! To integrate the real `binwalk` crate, add it to Cargo.toml and extend `scan`.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::fs;

const SIGNATURES: &[(&[u8], &str)] = &[
    (b"\x1f\x8b\x08", "gzip compressed data"),
    (b"BZh", "bzip2 compressed data"),
    (b"PK\x03\x04", "zip archive"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"\x7fELF", "ELF executable"),
    (b"hsqs", "squashfs filesystem"),
    (b"UBI#", "UBI image"),
    (b"%PDF", "PDF document"),
];

fn find_all(haystack: &[u8], needle: &[u8]) -> Vec<usize> {
    let mut offsets = Vec::new();
    if needle.is_empty() || haystack.len() < needle.len() {
        return offsets;
    }
    let mut i = 0usize;
    while i + needle.len() <= haystack.len() {
        if &haystack[i..i + needle.len()] == needle {
            offsets.push(i);
        }
        i += 1;
    }
    offsets
}

#[pyfunction]
fn scan(py: Python<'_>, path: String) -> PyResult<PyObject> {
    let data = fs::read(&path)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
    let result = PyDict::new_bound(py);
    result.set_item("file", &path)?;
    result.set_item("size", data.len())?;
    let hits = PyList::empty_bound(py);
    for (sig, desc) in SIGNATURES {
        for off in find_all(&data, sig) {
            let hit = PyDict::new_bound(py);
            hit.set_item("offset", off)?;
            hit.set_item("signature", *desc)?;
            hits.append(hit)?;
        }
    }
    result.set_item("signatures", hits)?;
    result.set_item("backend", "rust-binwalk_bindings")?;
    Ok(result.into())
}

#[pymodule]
fn binwalk_bindings(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(scan, m)?)?;
    Ok(())
}
