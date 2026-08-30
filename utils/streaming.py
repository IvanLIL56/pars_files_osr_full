"""Streaming utilities for large file processing.

This module provides functionality for:
- Reading large files in chunks without loading entire file into memory
- Streaming hash computation
- Memory-efficient text extraction
- Progress tracking for large operations
"""

import hashlib
from pathlib import Path
from typing import Generator, Optional, Tuple, BinaryIO
from config import settings


def stream_file_chunks(
    file_path: Path, 
    chunk_size: int = None
) -> Generator[bytes, None, None]:
    """Stream file content in chunks.
    
    Args:
        file_path: Path to file
        chunk_size: Size of each chunk in bytes (from config if None)
    
    Yields:
        Byte chunks of file content
    """
    if chunk_size is None:
        chunk_size = settings.processing.CHUNK_SIZE
    
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def compute_hash_streaming(
    file_path: Path,
    algorithm: str = 'sha256',
    chunk_size: int = None
) -> Optional[str]:
    """Compute hash of large file using streaming.
    
    Args:
        file_path: Path to file
        algorithm: Hash algorithm to use
        chunk_size: Size of chunks for reading
    
    Returns:
        Hex digest or None if error
    """
    if chunk_size is None:
        chunk_size = settings.processing.CHUNK_SIZE
    
    try:
        hasher = hashlib.new(algorithm)
        
        for chunk in stream_file_chunks(file_path, chunk_size):
            hasher.update(chunk)
        
        return hasher.hexdigest()
    except (IOError, OSError):
        return None


def compute_partial_hash_streaming(
    file_path: Path,
    prefix_bytes: int = None,
    middle_slice_size: int = None
) -> str:
    """Compute partial hash of large file using streaming and seek operations.
    
    This is memory-efficient version that only reads necessary parts of file.
    
    Args:
        file_path: Path to file
        prefix_bytes: Number of bytes to read from start/end
        middle_slice_size: Size of middle slices
    
    Returns:
        SHA-256 hex digest of combined data
    """
    if prefix_bytes is None:
        prefix_bytes = settings.processing.HASH_PREFIX_BYTES
    if middle_slice_size is None:
        middle_slice_size = settings.processing.HASH_MIDDLE_SLICES
    
    try:
        file_size = file_path.stat().st_size
        extension = file_path.suffix.lower()
        
        hasher = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            # Read prefix
            prefix = f.read(prefix_bytes)
            hasher.update(prefix)
            
            # Read middle slices if file is large enough
            if file_size > prefix_bytes * 3:
                # Position at 1/3 of file
                pos1 = file_size // 3
                f.seek(pos1)
                middle1 = f.read(middle_slice_size)
                hasher.update(middle1)
                
                # Position at 2/3 of file
                pos2 = (file_size * 2) // 3
                f.seek(pos2)
                middle2 = f.read(middle_slice_size)
                hasher.update(middle2)
            
            # Read suffix (last N bytes)
            if file_size > prefix_bytes:
                f.seek(-prefix_bytes, 2)  # Seek from end
                suffix = f.read(prefix_bytes)
                hasher.update(suffix)
        
        # Add file size and extension to hash
        hasher.update(str(file_size).encode('utf-8'))
        hasher.update(extension.encode('utf-8'))
        
        return hasher.hexdigest()
    
    except (IOError, OSError) as e:
        error_hash = hashlib.sha256(f"error:{str(e)}".encode()).hexdigest()
        return error_hash


def read_text_streaming(
    file_path: Path,
    encoding: str = 'utf-8',
    chunk_size: int = None,
    max_chars: int = None
) -> Generator[str, None, None]:
    """Read text file in chunks as strings.
    
    Args:
        file_path: Path to text file
        encoding: File encoding
        chunk_size: Size of byte chunks to read
        max_chars: Maximum characters to read (None for unlimited)
    
    Yields:
        Text chunks
    """
    if chunk_size is None:
        chunk_size = settings.processing.CHUNK_SIZE
    
    chars_read = 0
    
    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
        while True:
            if max_chars and chars_read >= max_chars:
                break
            
            remaining = max_chars - chars_read if max_chars else chunk_size
            chunk = f.read(min(chunk_size, remaining))
            
            if not chunk:
                break
            
            yield chunk
            chars_read += len(chunk)


def get_file_size_mb(file_path: Path) -> float:
    """Get file size in megabytes.
    
    Args:
        file_path: Path to file
    
    Returns:
        File size in MB
    """
    return file_path.stat().st_size / (1024 * 1024)


def is_large_file(file_path: Path, threshold_mb: int = None) -> bool:
    """Check if file exceeds size threshold.
    
    Args:
        file_path: Path to file
        threshold_mb: Threshold in MB (from config if None)
    
    Returns:
        True if file is larger than threshold
    """
    if threshold_mb is None:
        threshold_mb = settings.processing.LARGE_FILE_THRESHOLD_MB
    
    return get_file_size_mb(file_path) > threshold_mb


class StreamingProgressTracker:
    """Track progress of streaming operations."""
    
    def __init__(self, total_bytes: int, chunk_size: int = None):
        """Initialize progress tracker.
        
        Args:
            total_bytes: Total bytes to process
            chunk_size: Expected chunk size
        """
        self.total_bytes = total_bytes
        self.chunk_size = chunk_size or settings.processing.CHUNK_SIZE
        self.processed_bytes = 0
        self.processed_chunks = 0
    
    def update(self, chunk_size: int) -> float:
        """Update progress with processed chunk.
        
        Args:
            chunk_size: Size of processed chunk
        
        Returns:
            Progress percentage (0-100)
        """
        self.processed_bytes += chunk_size
        self.processed_chunks += 1
        
        if self.total_bytes > 0:
            return (self.processed_bytes / self.total_bytes) * 100
        return 0.0
    
    @property
    def progress_percent(self) -> float:
        """Get current progress percentage."""
        if self.total_bytes > 0:
            return (self.processed_bytes / self.total_bytes) * 100
        return 0.0
    
    @property
    def estimated_remaining_chunks(self) -> int:
        """Estimate remaining chunks."""
        if self.chunk_size > 0:
            total_chunks = self.total_bytes // self.chunk_size
            return max(0, total_chunks - self.processed_chunks)
        return 0


def detect_encryption_pdf(file_path: Path) -> bool:
    """Detect if PDF file is encrypted.
    
    Args:
        file_path: Path to PDF file
    
    Returns:
        True if file appears to be encrypted
    """
    try:
        # Check first few KB for encryption markers
        with open(file_path, 'rb') as f:
            header = f.read(2048)
            
            # PDF encryption indicators
            if b'/Encrypt' in header or b'/Encryption' in header:
                return True
            
            # Check for standard PDF header
            if not header.startswith(b'%PDF'):
                return False
            
            # Try to find encryption dictionary in first part of file
            sample = header + f.read(8192)
            if b'/P ' in sample and (b'/R ' in sample or b'/U ' in sample):
                return True
        
        return False
    except Exception:
        return False


def detect_encryption_docx(file_path: Path) -> bool:
    """Detect if DOCX file is encrypted (password protected).
    
    DOCX files are ZIP archives - check for encryption flags.
    
    Args:
        file_path: Path to DOCX file
    
    Returns:
        True if file appears to be encrypted
    """
    try:
        import zipfile
        
        with zipfile.ZipFile(file_path, 'r') as zf:
            # Check for encryption flag in any file info
            for info in zf.infolist():
                if info.flag_bits & 0x1:  # Encrypted flag
                    return True
        
        return False
    except (zipfile.BadZipFile, Exception):
        # If can't open as ZIP, might be encrypted or corrupted
        return True


def detect_encryption_general(file_path: Path) -> bool:
    """General encryption detection for various file types.
    
    Args:
        file_path: Path to file
    
    Returns:
        True if file appears to be encrypted
    """
    ext = file_path.suffix.lower()
    
    if ext == '.pdf':
        return detect_encryption_pdf(file_path)
    elif ext in ['.docx', '.xlsx', '.pptx']:
        return detect_encryption_docx(file_path)
    elif ext in ['.doc', '.xls', '.ppt']:
        # Old Office formats - harder to detect without full parsing
        # Check entropy as heuristic (encrypted files have high entropy)
        try:
            with open(file_path, 'rb') as f:
                sample = f.read(4096)
                if len(sample) < 4096:
                    return False
                
                # Simple entropy check
                byte_counts = [0] * 256
                for byte in sample:
                    byte_counts[byte] += 1
                
                entropy = 0.0
                for count in byte_counts:
                    if count > 0:
                        p = count / len(sample)
                        entropy -= p * (p and (p * 0.6931471805599453))  # log2 approximation
                
                # High entropy (> 7.5 bits per byte) suggests encryption
                if entropy > 7.5:
                    return True
        except Exception:
            pass
        
        return False
    
    return False
