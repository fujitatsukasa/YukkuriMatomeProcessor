#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

root = Path.cwd()
voice_build = root / "voice_build"
sys.path.insert(0, str(voice_build / "tools"))

import generate_irodori_v4_voice_from_scratch as fresh  # noqa: E402
from irodori_tts.watermark import SilentCipherWatermarker  # noqa: E402

checkpoint = Path(os.environ["IRODORI_LOCAL_CHECKPOINT"]).resolve()
codec = Path(os.environ["IRODORI_LOCAL_CODEC"]).resolve()
if not checkpoint.is_file():
    raise FileNotFoundError(f"Local Irodori checkpoint not found: {checkpoint}")
if not codec.is_file():
    raise FileNotFoundError(f"Local DACVAE codec not found: {codec}")

# The official runtime treats watermarking as optional. Disable its separate
# model lookup in this isolated generation job so all network access is limited
# to the explicitly staged Irodori and DACVAE model files.
SilentCipherWatermarker._load_backend = staticmethod(lambda *, device, model_type: None)

fresh.base.CHECKPOINT = str(checkpoint)
fresh.base.CODEC = str(codec)

if __name__ == "__main__":
    fresh.base.main()
