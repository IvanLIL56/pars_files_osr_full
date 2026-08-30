"""Downloader module for fetching files from external site.

This module handles downloading files from the external document site,
including retry logic, progress tracking, and file management.

The download process follows these steps:
1. Get lists of files from three sections: docs, projectdocs, printformdocs
2. For each file in the lists, download using the attachment download API
3. Save files organized by contract number
"""

import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import urlparse, unquote
import requests

from config import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)
from auth.authenticator import SiteAuthenticator
from db.repository import get_repository
from models.db_models import FilesMetadata, FileStatus
from utils.hash_utils import compute_partial_hash
import uuid
from datetime import datetime


# URL templates for getting file lists from three sections
URL_DOCS = lambda number_contr: f'{settings.site.BASE_URL}/api/v1/document/attachData/{number_contr}/docs/?filter=[%22parentId%22,%22=%22,%227%22]&fields=fields.AttachmentDocType||fields.AttachmentTitle||fields.AttachmentAutoCreate||fields.AttachmentPublication||fields.AttachmentSigning||fields.AttachmentVersion||fields.AttachmentLastModificator||fields.AttachmentLastModify||fields.AttachmentFileSize||actionColumn||emptyColumn'

URL_PROJECT_DOCS = lambda number_contr: f'{settings.site.BASE_URL}/api/v1/document/attachData/{number_contr}/projectdocs/?filter=[%22parentId%22,%22=%22,%227%22]&fields=fields.AttachmentDocType||fields.AttachmentTitle||fields.AttachmentAutoCreate||fields.AttachmentPublication||fields.AttachmentSigning||fields.AttachmentVersion||fields.AttachmentLastModificator||fields.AttachmentLastModify||fields.AttachmentFileSize||actionColumn||emptyColumn'

URL_PRINT_FORM_DOCS = lambda number_contr: f'{settings.site.BASE_URL}/api/v1/document/attachData/{number_contr}/printformdocs/?filter=[%22parentId%22,%22=%22,%227%22]&fields=fields.AttachmentDocType||fields.AttachmentTitle||fields.AttachmentAutoCreate||fields.AttachmentPublication||fields.AttachmentSigning||fields.AttachmentVersion||fields.AttachmentLastModificator||fields.AttachmentLastModify||fields.AttachmentFileSize||actionColumn||emptyColumn'


class FileDownloader:
    """Downloads files from the external document site.
    
    Features:
    - Parallel download support (via ThreadPoolExecutor externally)
    - Automatic retry on failures
    - Skip existing files with same size
    - Organized folder structure by contract number
    - Filename length limits to avoid OS issues
    - Support for three document sections: docs, projectdocs, printformdocs
    
    Attributes:
        download_dir: Base directory for downloaded files
        authenticator: SiteAuthenticator instance for authenticated requests
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        skip_if_exists: Skip download if file exists with same size
        overwrite_existing: Overwrite files even if they exist
    """
    
    def __init__(self, authenticator: SiteAuthenticator = None):
        """Initialize downloader.
        
        Args:
            authenticator: Optional SiteAuthenticator instance.
                          If not provided, creates new one.
        """
        self.download_dir = Path(settings.paths.DOWNLOAD_DIR)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        self.authenticator = authenticator or SiteAuthenticator()
        
        self.max_retries = settings.download.RETRY_COUNT
        self.retry_delay = settings.download.RETRY_DELAY
        self.skip_if_exists = settings.download.SKIP_IF_EXISTS
        self.overwrite_existing = settings.download.OVERWRITE_EXISTING
        self.max_filename_length = settings.download.MAX_FILENAME_LENGTH
        
        # Statistics
        self.stats = {
            'downloaded': 0,
            'skipped': 0,
            'failed': 0,
            'total_bytes': 0
        }
        
        logger.debug(f"FileDownloader initialized, download_dir={self.download_dir}")
    
    @staticmethod
    def extract_contract_number(url: str) -> str:
        """Extract contract number from URL.
        
        The contract number is extracted based on URL pattern.
        Examples:
        - https://test.xxx.xxx/contract/12345 -> 12345
        - https://test.xxx.xxx/api/v1/document/attachData/67890/docs/... -> 67890
        
        Args:
            url: Full URL
            
        Returns:
            Contract number (extracted from path)
        """
        from urllib.parse import urlparse, unquote
        import re
        
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        path_parts = path.split('/')
        
        # Try to find contract number in common patterns
        # Pattern 1: /attachData/{contract_number}/...
        for i, part in enumerate(path_parts):
            if part == 'attachData' and i + 1 < len(path_parts):
                return unquote(path_parts[i + 1])
        
        # Pattern 2: /contract/{contract_number}
        for i, part in enumerate(path_parts):
            if part == 'contract' and i + 1 < len(path_parts):
                return unquote(path_parts[i + 1])
        
        # Fallback: use the last non-empty segment that looks like an ID
        # (numeric or alphanumeric, but not common words like 'docs', 'api', etc.)
        skip_words = {'api', 'v1', 'document', 'attachData', 'docs', 'projectdocs', 
                      'printformdocs', 'contract', 'www'}
        
        for part in reversed(path_parts):
            if part and part.lower() not in skip_words:
                return unquote(part)
        
        # Ultimate fallback: return the very last segment
        return unquote(path_parts[-1]) if path_parts else ''
    
    @staticmethod
    def safe_filename(filename: str, max_len: int = 155) -> str:
        """Create safe filename with length limit.
        
        Args:
            filename: Original filename
            max_len: Maximum filename length
            
        Returns:
            Safe filename with extension preserved
        """
        if len(filename) <= max_len:
            return filename
        
        name, ext = os.path.splitext(filename)
        # Reserve space for extension and tilde
        cutoff = max_len - len(ext) - 1
        return name[:cutoff] + '~' + ext
    
    def _get_filename_from_response(self, response: requests.Response, url: str, attachment_title: str = None) -> str:
        """Extract filename from response, URL, or attachment title.
        
        Args:
            response: HTTP response object
            url: Original request URL
            attachment_title: Optional attachment title from metadata
            
        Returns:
            Filename string
        """
        # Prefer attachment title if provided
        if attachment_title:
            return self.safe_filename(attachment_title, self.max_filename_length)
        
        # Try Content-Disposition header first
        content_disposition = response.headers.get('Content-Disposition', '')
        if 'filename=' in content_disposition:
            # Parse filename from header
            for part in content_disposition.split(';'):
                if 'filename=' in part:
                    filename = part.split('=')[1].strip().strip('"\'')
                    return self.safe_filename(filename, self.max_filename_length)
        
        # Try to get from URL
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if filename:
            return self.safe_filename(filename, self.max_filename_length)
        
        # Generate fallback filename
        return f"document_{int(time.time())}.bin"
    
    def _should_skip_download(self, file_path: Path, remote_size: int) -> bool:
        """Check if download should be skipped.
        
        Args:
            file_path: Local file path
            remote_size: Remote file size
            
        Returns:
            True if download should be skipped
        """
        if not file_path.exists():
            return False
        
        if self.overwrite_existing:
            return False
        
        local_size = file_path.stat().st_size
        if self.skip_if_exists and local_size == remote_size:
            return True
        
        return False
    
    def get_file_lists(
        self,
        contract_number: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Get file lists from all three sections for a contract.
        
        Args:
            contract_number: Contract number
            
        Returns:
            Tuple of (docs_list, projectdocs_list, printformdocs_list)
            Each list contains dictionaries with file metadata
        """
        urls = [
            ('docs', URL_DOCS(contract_number)),
            ('projectdocs', URL_PROJECT_DOCS(contract_number)),
            ('printformdocs', URL_PRINT_FORM_DOCS(contract_number))
        ]
        
        results = {'docs': [], 'projectdocs': [], 'printformdocs': []}
        
        for section_name, url in urls:
            try:
                if not self.authenticator.ensure_authenticated():
                    logger.error(f"Authentication failed for {section_name}")
                    continue
                
                response = self.authenticator.get(url)
                
                if response is None:
                    logger.error(f"Got None response for {section_name}")
                    continue
                
                if response.status_code != 200:
                    logger.error(f"Failed to get {section_name}: HTTP {response.status_code}")
                    continue
                
                data = response.json()
                items = data.get('data', [])
                
                logger.debug(
                    f"Contract {contract_number}, section {section_name}: "
                    f"found {len(items)} files"
                )
                
                for item in items:
                    file_info = {
                        'key': item.get('key'),
                        'documentKey': item.get('documentKey'),
                        'AttachmentDocType': item.get('fields', {}).get('AttachmentDocType'),
                        'AttachmentTitle': item.get('fields', {}).get('AttachmentTitle'),
                        'AttachmentLastModificator': item.get('fields', {}).get('AttachmentLastModificator'),
                        'AttachmentLastModify': item.get('fields', {}).get('AttachmentLastModify'),
                        'AttachmentFileSize': item.get('fields', {}).get('AttachmentFileSize'),
                        'place': section_name,
                        'contract_number': contract_number
                    }
                    results[section_name].append(file_info)
                    
            except Exception as e:
                logger.error(f"Error getting {section_name} for contract {contract_number}: {e}")
        
        return results['docs'], results['projectdocs'], results['printformdocs']
    
    def download_single_file(
        self,
        contract_number: str,
        document_key: str,
        file_key: str,
        attachment_title: str = None,
        place: str = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Download a single file using the attachment download API.
        
        Args:
            contract_number: Contract number
            document_key: Document key from file list
            file_key: File key from file list
            attachment_title: Optional attachment title for filename
            place: Section name (docs, projectdocs, printformdocs)
            
        Returns:
            Tuple of (success, file_path, metadata)
        """
        metadata = {
            'contract_number': contract_number,
            'document_key': document_key,
            'file_key': file_key,
            'attachment_title': attachment_title,
            'place': place,
            'status': 'pending',
            'error': None,
            'bytes_downloaded': 0,
            'attempts': 0
        }
        
        # Create contract-specific folder
        contract_folder = self.download_dir / contract_number
        contract_folder.mkdir(parents=True, exist_ok=True)
        
        # Build download URL
        token = self.authenticator.token
        download_url = f"{settings.site.BASE_URL}/api/v1/attachment/download/{document_key}/{file_key}"
        
        # Attempt download with retries
        for attempt in range(1, self.max_retries + 1):
            metadata['attempts'] = attempt
            
            try:
                # Ensure we have valid authentication
                if not self.authenticator.ensure_authenticated():
                    metadata['status'] = 'auth_failed'
                    metadata['error'] = 'Authentication failed'
                    self.stats['failed'] += 1
                    return False, None, metadata
                
                # Make request with token in URL (as per example_pars.py)
                response = requests.get(
                    download_url,
                    headers=self.authenticator.session.headers,
                    verify=settings.site.VERIFY_SSL,
                    timeout=settings.site.TIMEOUT
                )
                
                if response.status_code != 200:
                    metadata['error'] = f'HTTP {response.status_code}'
                    if response.status_code in (401, 403):
                        metadata['status'] = 'auth_failed'
                        break
                    continue
                
                # Get file info
                remote_size = int(response.headers.get('Content-Length', 0))
                filename = self._get_filename_from_response(
                    response, download_url, attachment_title
                )
                file_path = contract_folder / filename
                
                # Check if we should skip
                if self._should_skip_download(file_path, remote_size):
                    logger.info(f"Skipping existing file: {file_path}")
                    metadata['status'] = 'skipped'
                    metadata['file_path'] = str(file_path)
                    self.stats['skipped'] += 1
                    return True, str(file_path), metadata
                
                # Download file
                total_downloaded = 0
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            total_downloaded += len(chunk)
                
                metadata['status'] = 'downloaded'
                metadata['file_path'] = str(file_path)
                metadata['bytes_downloaded'] = total_downloaded
                metadata['remote_size'] = remote_size
                
                self.stats['downloaded'] += 1
                self.stats['total_bytes'] += total_downloaded
                
                logger.info(
                    f"Downloaded: {filename} ({total_downloaded} bytes) "
                    f"to {contract_folder}"
                )
                
                return True, str(file_path), metadata
                
            except requests.RequestException as e:
                metadata['error'] = str(e)
                logger.warning(
                    f"Download attempt {attempt}/{self.max_retries} failed: {e}"
                )
                
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                else:
                    metadata['status'] = 'failed'
                    self.stats['failed'] += 1
                    logger.error(
                        f"Download failed after {self.max_retries} attempts: {download_url}"
                    )
                    return False, None, metadata
        
        # All retries exhausted
        metadata['status'] = 'failed'
        self.stats['failed'] += 1
        return False, None, metadata
    
    def download_files_for_contract(
        self,
        contract_number: str
    ) -> List[Dict[str, Any]]:
        """Download all files for a single contract from all three sections.
        
        Args:
            contract_number: Contract number
            
        Returns:
            List of download results for all files with metadata
        """
        results = []
        
        logger.info(f"Processing contract {contract_number}")
        
        # Get file lists from all sections
        docs, projectdocs, printformdocs = self.get_file_lists(contract_number)
        
        all_files = docs + projectdocs + printformdocs
        
        if not all_files:
            logger.info(f"No files found for contract {contract_number}")
            # Record empty result with standardized structure
            results.append({
                'number_iproc': contract_number,
                'key': None,
                'documentKey': None,
                'AttachmentDocType': None,
                'AttachmentTitle': None,
                'AttachmentLastModificator': None,
                'AttachmentLastModify': None,
                'AttachmentFileSize': None,
                'url': None,
                'status': 'no_files',
                'place': 'all_sections'
            })
            return results
        
        logger.info(
            f"Contract {contract_number}: found {len(all_files)} files "
            f"(docs={len(docs)}, projectdocs={len(projectdocs)}, "
            f"printformdocs={len(printformdocs)})"
        )
        
        # Download each file
        for file_info in all_files:
            if not file_info.get('documentKey') or not file_info.get('key'):
                logger.warning(
                    f"Skipping file with missing keys: {file_info}"
                )
                results.append({
                    'number_iproc': contract_number,
                    'key': file_info.get('key'),
                    'documentKey': file_info.get('documentKey'),
                    'AttachmentDocType': file_info.get('AttachmentDocType'),
                    'AttachmentTitle': file_info.get('AttachmentTitle'),
                    'AttachmentLastModificator': file_info.get('AttachmentLastModificator'),
                    'AttachmentLastModify': file_info.get('AttachmentLastModify'),
                    'AttachmentFileSize': file_info.get('AttachmentFileSize'),
                    'url': None,
                    'status': 'missing_key_info',
                    'place': file_info.get('place')
                })
                continue
            
            success, file_path, metadata = self.download_single_file(
                contract_number=contract_number,
                document_key=file_info['documentKey'],
                file_key=file_info['key'],
                attachment_title=file_info.get('AttachmentTitle'),
                place=file_info.get('place')
            )
            
            # Save metadata to database immediately after download attempt
            if file_path:
                try:
                    self._save_metadata_to_db(file_path, file_info, metadata)
                except Exception as e:
                    logger.error(f"Failed to save metadata for {file_path}: {e}")
            
            # Create standardized result record matching example_pars.py format
            result = {
                'number_iproc': contract_number,
                'key': file_info.get('key'),
                'documentKey': file_info.get('documentKey'),
                'AttachmentDocType': file_info.get('AttachmentDocType'),
                'AttachmentTitle': file_info.get('AttachmentTitle'),
                'AttachmentLastModificator': file_info.get('AttachmentLastModificator'),
                'AttachmentLastModify': file_info.get('AttachmentLastModify'),
                'AttachmentFileSize': file_info.get('AttachmentFileSize'),
                'url': file_path,
                'status': metadata.get('status', 'unknown'),
                'place': file_info.get('place')
            }
            results.append(result)
        
        return results
    
    def _save_metadata_to_db(self, file_path: str, file_info: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        """Save file metadata to database after successful download.
        
        Args:
            file_path: Path to downloaded file
            file_info: File information from API
            metadata: Download metadata
        """
        import os
        from pathlib import Path
        
        repo = get_repository()
        
        # Parse last modified date from API if available
        last_modified_dt = None
        if file_info.get('AttachmentLastModify'):
            try:
                # Try to parse ISO format or other common formats
                last_modified_dt = datetime.fromisoformat(file_info['AttachmentLastModify'].replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass
        
        # Calculate partial hash for duplicate detection
        try:
            partial_hash = compute_partial_hash(file_path)
        except Exception as e:
            logger.warning(f"Could not compute hash for {file_path}: {e}")
            partial_hash = None
        
        # Prepare metadata record
        file_data = {
            'id': str(uuid.uuid4()),
            'filename': os.path.basename(file_path),
            'full_path': file_path,
            'directory': str(Path(file_path).parent),
            'extension': Path(file_path).suffix.lstrip('.') or 'bin',
            'mime_type': None,  # Will be detected during processing
            'size_bytes': metadata.get('remote_size', 0) or os.path.getsize(file_path),
            'contract_number': file_info.get('contract_number') or metadata.get('contract_number'),
            'document_key': file_info.get('documentKey'),
            'attachment_type': file_info.get('AttachmentDocType'),
            'attachment_title': file_info.get('AttachmentTitle'),
            'source_place': file_info.get('place'),
            'api_last_modified': last_modified_dt,
            'content_hash': None,  # Will be computed during full processing
            'partial_hash': partial_hash,
            'status': FileStatus.PENDING,
            'error_message': None,
            'is_encrypted': 0,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            'processed_at': None,
            'duplicate_of_id': None,
            'parent_id': None,
            'archive_name': None,
            'original_encoding': None,
        }
        
        # Upsert (insert or update if exists)
        repo.upsert_file_metadata(file_data)
        logger.debug(f"Saved metadata for {file_path} to DB")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get download statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            **self.stats,
            'total_processed': self.stats['downloaded'] + self.stats['skipped'] + self.stats['failed']
        }
    
    def reset_statistics(self) -> None:
        """Reset download statistics."""
        self.stats = {
            'downloaded': 0,
            'skipped': 0,
            'failed': 0,
            'total_bytes': 0
        }
