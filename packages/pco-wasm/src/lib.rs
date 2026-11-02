//! Decode-only WebAssembly bindings for pcodec's standalone format.
//!
//! `numcodecs.pcodec` (zarr codec name "numcodecs.pcodec") stores each chunk as a pco
//! *standalone* file (`pcodec.standalone.simple_compress`), so decoding a chunk is a single
//! `pco::standalone::simple_decompress::<T>` call with T taken from the array's data type.

use pco::standalone::simple_decompress;
use wasm_bindgen::prelude::*;

fn decode<T: pco::data_types::Number>(bytes: &[u8]) -> Result<Vec<T>, JsError> {
    simple_decompress::<T>(bytes).map_err(|e| JsError::new(&format!("pcodec decode failed: {e}")))
}

#[wasm_bindgen]
pub fn decode_f32(bytes: &[u8]) -> Result<Vec<f32>, JsError> {
    decode::<f32>(bytes)
}

#[wasm_bindgen]
pub fn decode_f64(bytes: &[u8]) -> Result<Vec<f64>, JsError> {
    decode::<f64>(bytes)
}

#[wasm_bindgen]
pub fn decode_u16(bytes: &[u8]) -> Result<Vec<u16>, JsError> {
    decode::<u16>(bytes)
}

#[wasm_bindgen]
pub fn decode_i16(bytes: &[u8]) -> Result<Vec<i16>, JsError> {
    decode::<i16>(bytes)
}

#[wasm_bindgen]
pub fn decode_u32(bytes: &[u8]) -> Result<Vec<u32>, JsError> {
    decode::<u32>(bytes)
}

#[wasm_bindgen]
pub fn decode_i32(bytes: &[u8]) -> Result<Vec<i32>, JsError> {
    decode::<i32>(bytes)
}

#[wasm_bindgen]
pub fn decode_u64(bytes: &[u8]) -> Result<Vec<u64>, JsError> {
    decode::<u64>(bytes)
}

#[wasm_bindgen]
pub fn decode_i64(bytes: &[u8]) -> Result<Vec<i64>, JsError> {
    decode::<i64>(bytes)
}
