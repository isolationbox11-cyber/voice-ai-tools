#!/bin/bash

# Build script for Rust PyO3 audio processor

echo "🔨 Building Rust PyO3 audio processor..."

# Install maturin if not already installed
if ! command -v maturin &> /dev/null; then
    echo "📦 Installing maturin..."
    pip install maturin
fi

# Build the PyO3 extension
cd rust_audio_processor_py
maturin develop --release

echo "✅ PyO3 extension build complete!"
echo "📦 The audio_processor_py module is now available in Python"
