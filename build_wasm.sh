#!/bin/bash

# Build script for Rust WebAssembly audio processor

echo "🔨 Building Rust WebAssembly audio processor..."

# Add WebAssembly target if not already added
rustup target add wasm32-unknown-unknown

# Install wasm-pack if not already installed
if ! command -v wasm-pack &> /dev/null; then
    echo "📦 Installing wasm-pack..."
    cargo install wasm-pack
fi

# Build the WebAssembly package
cd rust_audio_processor
wasm-pack build --target web --out-dir ../extension/pkg

echo "✅ WebAssembly build complete!"
echo "📦 Output: extension/pkg/"
