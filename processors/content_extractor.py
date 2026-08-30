"""Content extractor module.

Extracts text content from various file types including:
- Documents (DOC, DOCX)
- PDFs (text and scanned via OCR)
- Images (via OCR)
- Archives (ZIP, RAR, 7z, TAR)
"""

import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import zipfile
import tarfile

try:
    import rarfile
except ImportError:
    rarfile = None

try:
    import py7zr
except ImportError:
    py7zr = None

from config import settings
from utils.hash_utils import detect_encoding, normalize_filename
from utils.logger import setup_logger
from db.repository import get_repository


logger = setup_logger(__name__)


class ContentExtractor:
    """Extracts text content from files.
    
    Supports multiple file formats with automatic format detection
    and fallback mechanisms for corrupted files.
    """
    
    def __init__(self):
        """Initialize extractor."""
        self.repo = get_repository()
        self.archive_extensions = set(settings.processing.ARCHIVE_EXTS)
    
    def extract_content(self, file_path: Path, file_id: str, ext: str) -> Dict[str, Any]:
        """Extract content from a single file.
        
        Args:
            file_path: Path to the file
            file_id: Unique file identifier
            ext: File extension (lowercase, without dot)
        
        Returns:
            Dictionary with extraction results
        """
        ext = ext.lower().lstrip('.')
        
        try:
            if ext in self.archive_extensions:
                return self._process_archive(file_path, file_id, ext)
            elif ext in ('doc', 'docx'):
                return self._process_document(file_path, file_id, ext)
            elif ext == 'pdf':
                return self._process_pdf(file_path, file_id)
            elif ext in ('jpg', 'jpeg', 'png', 'bmp', 'tiff', 'gif'):
                return self._process_image(file_path, file_id)
            else:
                return self._error_result(file_id, ext, 'Unsupported format')
        
        except Exception as e:
            logger.error(f"Error extracting {file_path}: {e}")
            return self._error_result(file_id, ext, str(e))
    
    def _process_archive(
        self, 
        archive_path: Path, 
        file_id: str, 
        ext: str
    ) -> Dict[str, Any]:
        """Process archive file and extract contents.
        
        Args:
            archive_path: Path to archive
            file_id: Archive file ID
            ext: Archive extension
        
        Returns:
            Result dictionary (for archives, indicates successful extraction)
        """
        tmpdir = None
        try:
            tmpdir = tempfile.mkdtemp(prefix="archive_")
            inner_files = self._extract_archive(archive_path, ext, tmpdir)
            
            if not inner_files:
                return {
                    'id': file_id,
                    'status': 'done',
                    'type_read': f'archive/{ext}',
                    'page_count': 0,
                    'char_count': 0,
                    'image_quality': None,
                    'full_text': ''
                }
            
            # Process each file in archive
            all_text = []
            total_chars = 0
            page_count = 0
            
            for inner_path, rel_path, inner_ext in inner_files:
                # Normalize filename encoding
                detected_enc, confidence = detect_encoding(rel_path.encode('utf-8'))
                normalized_name = normalize_filename(rel_path, detected_enc)
                
                if detected_enc != 'utf-8':
                    logger.warning(
                        f"Filename encoding detected: {detected_enc} "
                        f"(confidence: {confidence:.2f}) - {rel_path} -> {normalized_name}"
                    )
                
                # Generate ID for inner file
                inner_id = f"{file_id}/{rel_path}"
                
                # Process inner file (recursively for nested archives)
                if inner_ext in self.archive_extensions:
                    result = self._process_archive(inner_path, inner_id, inner_ext)
                else:
                    result = self.extract_content(inner_path, inner_id, inner_ext)
                
                if result.get('full_text'):
                    all_text.append(f"\n=== {normalized_name} ===\n{result['full_text']}")
                    total_chars += result.get('char_count', 0)
                    page_count += result.get('page_count', 0)
            
            return {
                'id': file_id,
                'status': 'done',
                'type_read': f'archive/{ext}',
                'page_count': page_count,
                'char_count': total_chars,
                'image_quality': None,
                'full_text': '\n'.join(all_text)
            }
        
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
    
    def _extract_archive(
        self, 
        archive_path: Path, 
        ext: str, 
        extract_dir: str
    ) -> List[Tuple[Path, str, str]]:
        """Extract archive to directory.
        
        Args:
            archive_path: Path to archive
            ext: Archive extension
            extract_dir: Directory to extract to
        
        Returns:
            List of (file_path, relative_path, extension) tuples
        """
        archive_path = Path(archive_path)
        extract_path = Path(extract_dir)
        
        if ext == 'zip':
            with zipfile.ZipFile(archive_path, 'r') as z:
                z.extractall(extract_path)
        elif ext in ('tar', 'tar.gz', 'tgz', 'tar.bz2', 'tar.xz'):
            with tarfile.open(archive_path, 'r:*') as t:
                t.extractall(extract_path)
        elif ext == 'rar' and rarfile:
            with rarfile.RarFile(archive_path) as r:
                r.extractall(extract_path)
        elif ext == '7z' and py7zr:
            with py7zr.SevenZipFile(archive_path, 'r') as sz:
                sz.extractall(extract_path)
        else:
            raise ValueError(f"Unsupported archive format: {ext}")
        
        files = []
        for root, _, filenames in extract_path.rglob('*'):
            if root.is_file():
                continue
            for fn in filenames:
                fp = Path(root) / fn
                rel = str(fp.relative_to(extract_path))
                inner_ext = fp.suffix.lstrip('.').lower()
                files.append((fp, rel, inner_ext))
        
        return files
    
    def _process_document(
        self, 
        file_path: Path, 
        file_id: str, 
        ext: str
    ) -> Dict[str, Any]:
        """Process Word document (DOC/DOCX).
        
        Args:
            file_path: Path to document
            file_id: File ID
            ext: Extension (doc or docx)
        
        Returns:
            Result dictionary with extracted text
        """
        # Import here to avoid circular imports
        from processors.document_reader import read_docx, read_doc_antiword, read_docx_zip
        
        try:
            if ext == 'docx':
                try:
                    return read_docx(file_path, file_id)
                except Exception as e:
                    logger.warning(f"DOCX python-docx failed: {e}, trying ZIP fallback")
                    return read_docx_zip(file_path, file_id)
            elif ext == 'doc':
                try:
                    return read_doc_antiword(file_path, file_id)
                except Exception as e:
                    logger.warning(f"DOC antiword failed: {e}, trying ZIP fallback")
                    try:
                        return read_docx_zip(file_path, file_id)
                    except Exception as e2:
                        return self._error_result(file_id, ext, f"antiword: {e}, zip: {e2}")
            else:
                return self._error_result(file_id, ext, 'Unknown document format')
        
        except Exception as e:
            return self._error_result(file_id, ext, str(e))
    
    def _process_pdf(self, file_path: Path, file_id: str) -> Dict[str, Any]:
        """Process PDF file.
        
        Determines if PDF has text layer or requires OCR.
        
        Args:
            file_path: Path to PDF
            file_id: File ID
        
        Returns:
            Result dictionary with extracted text
        """
        # Import here to avoid circular imports
        from processors.pdf_reader import process_readable_pdf, process_pdf_osr, type_pdf
        
        try:
            pdf_type = type_pdf(file_path)
            if pdf_type == 'read':
                return process_readable_pdf(file_path, file_id)
            else:
                return process_pdf_osr(file_path, file_id)
        except Exception as e:
            return self._error_result(file_id, 'pdf', str(e))
    
    def _process_image(self, file_path: Path, file_id: str) -> Dict[str, Any]:
        """Process image file with OCR.
        
        Args:
            file_path: Path to image
            file_id: File ID
        
        Returns:
            Result dictionary with OCR text
        """
        # Import here to avoid circular imports
        from processors.image_ocr import process_image_osr
        
        try:
            return process_image_osr(file_path, file_id)
        except Exception as e:
            return self._error_result(file_id, 'image', str(e))
    
    def _error_result(
        self, 
        file_id: str, 
        type_read: str, 
        error_msg: str
    ) -> Dict[str, Any]:
        """Create error result dictionary.
        
        Args:
            file_id: File ID
            type_read: File type
            error_msg: Error message
        
        Returns:
            Error result dictionary
        """
        return {
            'id': file_id,
            'status': f'error: {error_msg}',
            'type_read': type_read,
            'page_count': 0,
            'char_count': 0,
            'image_quality': f'error: {error_msg}',
            'full_text': f'[Ошибка: {error_msg}]'
        }
    
    def save_content(self, content_data: Dict[str, Any]) -> bool:
        """Save extracted content to database.
        
        Args:
            content_data: Content dictionary from extraction
        
        Returns:
            True if saved successfully
        """
        try:
            self.repo.upsert_file_content(content_data)
            return True
        except Exception as e:
            logger.error(f"Failed to save content for {content_data.get('file_id')}: {e}")
            return False
