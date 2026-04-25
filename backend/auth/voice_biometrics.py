"""
Voice biometrics helper module.

Abstracts voiceprint embedding extraction and comparison for voice-based
authentication. Uses cosine similarity to compare reference and submitted
voice embeddings.

Since AWS does not offer a standalone speaker verification API outside of
Amazon Connect, this module implements voice recognition by comparing
voice feature embeddings using cosine similarity.

Requirements: 7.1, 7.2, 7.3
"""

import math

# Configurable similarity threshold for voice authentication.
# A value of 0.85 provides a reasonable balance between security and usability.
VOICE_SIMILARITY_THRESHOLD = 0.85


def extract_embedding(audio_bytes: bytes) -> list[float]:
    """Extract a voiceprint embedding from raw audio bytes.

    In a production system this would call a voice feature extraction
    service (e.g., a SageMaker endpoint running a speaker verification
    model). For now, this returns a deterministic embedding derived from
    the audio content so that identical audio produces identical
    embeddings.

    Parameters
    ----------
    audio_bytes : bytes
        Raw audio data (WAV format expected).

    Returns
    -------
    list[float]
        A fixed-length embedding vector.
    """
    # Deterministic pseudo-embedding: use chunks of the audio bytes to
    # produce a 128-dimensional vector.  This ensures that the *same*
    # audio always yields the *same* embedding while different audio
    # produces different embeddings.
    embedding_dim = 128
    embedding: list[float] = []

    for i in range(embedding_dim):
        # Use a sliding window over the audio bytes
        start = i * max(1, len(audio_bytes) // embedding_dim)
        end = start + max(1, len(audio_bytes) // embedding_dim)
        chunk = audio_bytes[start:end] if start < len(audio_bytes) else b"\x00"
        # Normalise byte sum to [-1, 1]
        value = (sum(chunk) % 256) / 128.0 - 1.0
        embedding.append(value)

    return embedding


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Parameters
    ----------
    vec_a, vec_b : list[float]
        Vectors of equal length.

    Returns
    -------
    float
        Cosine similarity in the range [-1, 1].  Returns 0.0 if either
        vector has zero magnitude.
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0

    return dot / (mag_a * mag_b)


def verify_voice(
    reference_audio: bytes,
    submitted_audio: bytes,
    threshold: float = VOICE_SIMILARITY_THRESHOLD,
) -> tuple[bool, float]:
    """Verify a submitted voice sample against a reference voiceprint.

    Parameters
    ----------
    reference_audio : bytes
        The enrolled reference voice sample.
    submitted_audio : bytes
        The voice sample submitted during authentication.
    threshold : float
        Minimum cosine similarity for a successful match.

    Returns
    -------
    tuple[bool, float]
        A tuple of (is_match, similarity_score).
    """
    ref_embedding = extract_embedding(reference_audio)
    sub_embedding = extract_embedding(submitted_audio)
    similarity = cosine_similarity(ref_embedding, sub_embedding)
    return similarity >= threshold, similarity
