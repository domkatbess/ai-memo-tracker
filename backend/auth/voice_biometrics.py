"""Voice biometric utilities for voiceprint embedding extraction.

Extracts voiceprint embeddings from raw audio bytes for use in
speaker verification during authentication.

Since AWS does not offer a standalone speaker verification API outside
of Amazon Connect, voice recognition is implemented by storing voice
feature embeddings extracted from enrollment samples and comparing them
against authentication samples using cosine similarity.
"""

import hashlib
import struct


def extract_embedding(audio_bytes: bytes) -> list[float]:
    """Extract a voiceprint embedding vector from raw audio bytes.

    This is a simplified embedding extractor that produces a deterministic
    fixed-length feature vector from audio data. In production, this would
    use a neural network model (e.g., a speaker verification model) to
    extract a d-vector or x-vector embedding.

    Args:
        audio_bytes: Raw audio bytes (e.g., WAV file content).

    Returns:
        A list of 128 float values representing the voiceprint embedding.
    """
    if not audio_bytes:
        raise ValueError("Audio bytes must not be empty.")

    # Generate a deterministic 128-dimensional embedding from audio content.
    # In production, replace with a real speaker embedding model.
    embedding = []
    for i in range(128):
        chunk = audio_bytes + struct.pack(">I", i)
        digest = hashlib.sha256(chunk).digest()
        # Convert first 8 bytes of hash to a float in [-1, 1]
        value = struct.unpack(">d", digest[:8])[0]
        # Normalize to [-1, 1] range
        normalized = (value % 2.0) - 1.0
        embedding.append(round(normalized, 8))

    return embedding
