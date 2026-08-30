"""Utility functions for file processor.

This module provides utility functions for:
- Hash computation for duplicate detection
- Filename encoding detection and normalization
- File type detection
"""

import hashlib
from pathlib import Path
from typing import Optional, Tuple, List
import chardet

from config import settings


def compute_partial_hash(
    file_path: Path,
    prefix_bytes: int = None,
    middle_slice_size: int = None
) -> str:
    """Compute partial hash of a file for duplicate detection.
    
    The hash is computed from:
    - First N bytes (prefix)
    - Two slices from the middle (at 1/3 and 2/3 of file size)
    - Last N bytes (suffix)
    - File size in bytes
    - File extension (normalized, lowercase)
    
    This approach allows efficient duplicate detection without reading
    the entire file, while still being robust against files with same
    names but different content.
    
    Args:
        file_path: Path to the file
        prefix_bytes: Number of bytes to read from start/end (default from config)
        middle_slice_size: Size of middle slices (default from config)
    
    Returns:
        SHA-256 hex digest of the combined data
    """
    if prefix_bytes is None:
        prefix_bytes = settings.processing.HASH_PREFIX_BYTES
    if middle_slice_size is None:
        middle_slice_size = settings.processing.HASH_MIDDLE_SLICES
    
    try:
        file_size = file_path.stat().st_size
        extension = file_path.suffix.lower()
        
        # Prepare data for hashing
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
        # Return hash of error to handle consistently
        error_hash = hashlib.sha256(f"error:{str(e)}".encode()).hexdigest()
        return error_hash


def compute_full_hash(file_path: Path, algorithm: str = "sha256") -> Optional[str]:
    """Compute full file hash.
    
    Args:
        file_path: Path to the file
        algorithm: Hash algorithm to use (default: sha256)
    
    Returns:
        Hex digest or None if error
    """
    try:
        hasher = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(settings.processing.CHUNK_SIZE), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (IOError, OSError):
        return None


def detect_encoding(data: bytes) -> Tuple[str, float]:
    """Detect character encoding of byte data.
    
    Uses chardet library for encoding detection with fallback.
    
    Args:
        data: Byte data to analyze
    
    Returns:
        Tuple of (encoding_name, confidence)
    """
    if not data:
        return ('utf-8', 1.0)
    
    result = chardet.detect(data)
    
    if result and result.get('confidence', 0) > 0.7:
        return (result['encoding'] or 'utf-8', result['confidence'])
    
    # Fallback encodings based on common cases
    fallback_encodings = ['cp866', 'cp1251', 'latin_1', 'utf-8']
    
    for encoding in fallback_encodings:
        try:
            data.decode(encoding)
            return (encoding, 0.5)  # Lower confidence for fallback
        except UnicodeDecodeError:
            continue
    
    return ('utf-8', 0.3)  # Ultimate fallback


def normalize_filename(filename: str, detected_encoding: str = None) -> str:
    """Normalize filename to UTF-8.
    
    Handles filenames extracted from archives that may be in different encodings.
    
    Args:
        filename: Original filename (possibly in wrong encoding)
        detected_encoding: Detected or specified encoding
    
    Returns:
        Normalized UTF-8 filename
    """
    if not filename:
        return ""
    
    # If already valid UTF-8, return as-is
    try:
        filename.encode('utf-8').decode('utf-8')
        return filename
    except UnicodeEncodeError:
        pass
    
    # Try to decode using detected encoding
    if detected_encoding:
        try:
            # Encode as latin-1 (preserves bytes), then decode with detected encoding
            bytes_data = filename.encode('latin-1')
            decoded = bytes_data.decode(detected_encoding)
            return decoded
        except (UnicodeDecodeError, LookupError):
            pass
    
    # Try common encodings
    for encoding in ['cp866', 'cp1251', 'cp437', 'iso-8859-1']:
        try:
            bytes_data = filename.encode('latin-1')
            decoded = bytes_data.decode(encoding)
            return decoded
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Last resort: replace invalid characters
    try:
        bytes_data = filename.encode('latin-1')
        return bytes_data.decode('utf-8', errors='replace')
    except:
        return filename


def get_mime_type(file_path: Path) -> str:
    """Get MIME type of a file based on extension.
    
    Args:
        file_path: Path to the file
    
    Returns:
        MIME type string
    """
    ext = file_path.suffix.lower()
    
    mime_types = {
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.txt': 'text/plain',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff',
        '.zip': 'application/zip',
        '.rar': 'application/vnd.rar',
        '.7z': 'application/x-7z-compressed',
        '.tar': 'application/x-tar',
        '.gz': 'application/gzip',
        '.bz2': 'application/x-bzip2',
        '.xz': 'application/x-xz',
    }
    
    return mime_types.get(ext, 'application/octet-stream')


def safe_filename(filename: str) -> str:
    """Make filename safe for filesystem operations.
    
    Removes or replaces problematic characters.
    
    Args:
        filename: Original filename
    
    Returns:
        Safe filename
    """
    # Characters to remove or replace
    unsafe_chars = '<>:"/\\|?*'
    
    for char in unsafe_chars:
        filename = filename.replace(char, '_')
    
    # Remove null bytes
    filename = filename.replace('\x00', '')
    
    # Strip leading/trailing spaces and dots
    filename = filename.strip(' .')
    
    # Limit length (most filesystems support 255 chars)
    if len(filename) > 200:
        name, ext = Path(filename).stem, Path(filename).suffix
        filename = f"{name[:200-len(ext)]}{ext}"
    
    return filename if filename else "unnamed_file"
