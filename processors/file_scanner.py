"""File scanner module.

Scans directories for files, computes hashes, and manages file metadata
in the database with support for idempotent processing.
"""

import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator, Tuple
from datetime import datetime

from config import settings
from utils.hash_utils import compute_partial_hash, get_mime_type
from utils.logger import setup_logger
from db.repository import get_repository
from models.db_models import FileStatus


logger = setup_logger(__name__)


class FileScanner:
    """Scans directories and manages file metadata in database.
    
    Features:
    - Recursive directory scanning
    - Partial hash computation for duplicate detection
    - Idempotent processing (skips already processed files)
    - Archive filename encoding detection
    """
    
    def __init__(self, input_dir: str = None):
        """Initialize scanner.
        
        Args:
            input_dir: Root directory to scan (default from config)
        """
        self.input_dir = Path(input_dir) if input_dir else Path(settings.paths.INPUT_DIR)
        self.repo = get_repository()
        self.supported_extensions = set(settings.processing.SUPPORTED_EXTS)
        self.archive_extensions = set(settings.processing.ARCHIVE_EXTS)
    
    def scan_directory(self) -> Generator[Dict[str, Any], None, None]:
        """Scan directory and yield file information.
        
        Yields:
            Dictionary with file metadata
        """
        self.input_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path in self._find_files():
            try:
                file_info = self._extract_file_info(file_path)
                if file_info:
                    yield file_info
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
    
    def _find_files(self) -> Generator[Path, None, None]:
        """Find all files in input directory recursively."""
        for file_path in self.input_dir.rglob('*'):
            if file_path.is_file():
                yield file_path
    
    def _extract_file_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Extract metadata from a single file.
        
        Args:
            file_path: Path to the file
        
        Returns:
            Dictionary with file metadata or None if should be skipped
        """
        # Get extension
        ext = file_path.suffix.lower().lstrip('.')
        
        # Check if it's an archive - we still process archives themselves
        is_archive = ext in self.archive_extensions
        
        # For non-archive files, check if extension is supported
        if not is_archive and ext not in self.supported_extensions:
            logger.debug(f"Skipping unsupported extension: {ext} - {file_path}")
            return None
        
        # Compute partial hash for duplicate detection
        partial_hash = compute_partial_hash(file_path)
        
        # Check if this is a duplicate
        existing_id = self.repo.find_duplicate_by_hash(partial_hash)
        
        # Generate stable file ID from path
        file_id = self._generate_file_id(file_path)
        
        # If already fully processed, skip
        if self.repo.check_file_processed(file_id):
            logger.debug(f"File already processed: {file_path}")
            return None
        
        # Build metadata record
        metadata = {
            'id': file_id,
            'filename': file_path.name,
            'full_path': str(file_path.resolve()),
            'directory': str(file_path.parent),
            'extension': ext,
            'mime_type': get_mime_type(file_path),
            'size_bytes': file_path.stat().st_size,
            'partial_hash': partial_hash,
            'status': FileStatus.PENDING.value,
            'duplicate_of_id': existing_id,
            'parent_id': None,
            'archive_name': None,
            'original_encoding': None,
        }
        
        # If it's a duplicate, mark as done without content
        if existing_id:
            metadata['status'] = FileStatus.DONE.value
            logger.info(f"Duplicate detected: {file_path} -> {existing_id}")
        
        return metadata
    
    def _generate_file_id(self, file_path: Path) -> str:
        """Generate stable unique ID from file path.
        
        Args:
            file_path: Path to the file
        
        Returns:
            Hex-encoded MD5 hash of normalized path
        """
        normalized = str(file_path.resolve()).lower()
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()
    
    def register_files(self, batch_size: int = 100) -> Tuple[int, int, int]:
        """Scan directory and register files in database.
        
        Args:
            batch_size: Number of records to insert at once
        
        Returns:
            Tuple of (total_found, new_files, duplicates)
        """
        total_found = 0
        new_files = 0
        duplicates = 0
        batch = []
        
        for file_info in self.scan_directory():
            total_found += 1
            
            if file_info['duplicate_of_id']:
                duplicates += 1
                # Insert duplicate record with reference
                batch.append(file_info)
            else:
                new_files += 1
                batch.append(file_info)
            
            # Flush batch when full
            if len(batch) >= batch_size:
                self.repo.bulk_insert_metadata(batch)
                batch = []
        
        # Flush remaining
        if batch:
            self.repo.bulk_insert_metadata(batch)
        
        logger.info(
            f"Scan complete: {total_found} files found, "
            f"{new_files} new, {duplicates} duplicates"
        )
        
        return total_found, new_files, duplicates
    
    def get_pending_files(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get files that need processing.
        
        Args:
            limit: Maximum number of files to return
        
        Returns:
            List of file metadata dictionaries
        """
        files = self.repo.get_files_to_process(limit=limit)
        return [f.to_dict() for f in files]
    
    def mark_file_error(self, file_id: str, error_message: str) -> bool:
        """Mark file as having an error.
        
        Args:
            file_id: File ID
            error_message: Error description
        
        Returns:
            True if updated successfully
        """
        return self.repo.update_file_status(file_id, FileStatus.ERROR, error_message)
    
    def mark_file_done(self, file_id: str) -> bool:
        """Mark file as successfully processed.
        
        Args:
            file_id: File ID
        
        Returns:
            True if updated successfully
        """
        return self.repo.update_file_status(file_id, FileStatus.DONE)
