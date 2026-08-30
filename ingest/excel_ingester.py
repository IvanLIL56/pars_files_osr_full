"""Ingest module for processing Excel files with URLs.

This module orchestrates the complete workflow:
1. Read URLs from Excel file
2. Authenticate with external site
3. Download files in parallel
4. Process downloaded files using existing processors
"""

import os
import signal
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

from config import settings
from utils.logger import default_logger
from auth.authenticator import SiteAuthenticator
from downloader.file_downloader import FileDownloader
from db.repository import get_repository, DatabaseRepository
from processors.file_scanner import FileScanner
from utils.keyword_search import KeywordSearcher


class ExcelIngester:
    """Orchestrates ingestion from Excel file to processed database records.
    
    Features:
    - Read URLs from Excel file
    - Parallel file downloading
    - Integration with existing file processors
    - Comprehensive statistics and reporting
    - Graceful shutdown on interrupt
    
    Attributes:
        excel_file_path: Path to Excel file with URLs
        url_column: Name of column containing URLs
        authenticator: SiteAuthenticator instance
        downloader: FileDownloader instance
        repo: Database repository
        max_parallel: Maximum parallel downloads
    """
    
    def __init__(
        self,
        excel_file_path: str = None,
        url_column: str = None
    ):
        """Initialize ingester.
        
        Args:
            excel_file_path: Path to Excel file (default from config)
            url_column: Column name with URLs (default from config)
        """
        self.excel_file_path = Path(
            excel_file_path or settings.excel.FILE_PATH
        )
        self.url_column = url_column or settings.excel.URL_COLUMN
        self.max_parallel = settings.download.MAX_PARALLEL_DOWNLOADS
        
        # Initialize components
        self.authenticator = SiteAuthenticator()
        self.downloader = FileDownloader(self.authenticator)
        self.repo = get_repository()
        
        # Statistics
        self.stats = {
            'total_urls': 0,
            'unique_urls': 0,
            'contracts_processed': 0,
            'files_downloaded': 0,
            'files_skipped': 0,
            'files_failed': 0,
            'files_processed_db': 0,
            'errors': 0,
            'start_time': None,
            'end_time': None
        }
        
        # Shutdown handling
        self._shutdown_requested = False
        self._setup_signal_handlers()
        
        default_logger.info(
            f"ExcelIngester initialized: excel={self.excel_file_path}, "
            f"column={self.url_column}"
        )
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def handler(signum, frame):
            default_logger.warning("Shutdown requested, finishing current tasks...")
            self._shutdown_requested = True
        
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
    
    def read_urls_from_excel(self) -> List[str]:
        """Read unique URLs from Excel file.
        
        Returns:
            List of unique URLs
        """
        if not self.excel_file_path.exists():
            raise FileNotFoundError(f"Excel file not found: {self.excel_file_path}")
        
        default_logger.info(f"Reading URLs from {self.excel_file_path}")
        
        try:
            # Read Excel file
            df = pd.read_excel(self.excel_file_path)
            
            # Check if column exists
            if self.url_column not in df.columns:
                available_columns = list(df.columns)
                raise ValueError(
                    f"Column '{self.url_column}' not found. "
                    f"Available columns: {available_columns}"
                )
            
            # Extract unique URLs, drop NaN values
            urls = df[self.url_column].dropna().unique().tolist()
            urls = [str(url).strip() for url in urls if str(url).strip()]
            
            self.stats['total_urls'] = len(df[self.url_column].dropna())
            self.stats['unique_urls'] = len(urls)
            
            default_logger.info(
                f"Found {self.stats['total_urls']} total URLs, "
                f"{self.stats['unique_urls']} unique"
            )
            
            return urls
            
        except Exception as e:
            default_logger.error(f"Error reading Excel file: {e}")
            raise
    
    def _download_with_progress(
        self,
        url: str
    ) -> Dict[str, Any]:
        """Download all files for a contract with progress tracking.
        
        The URL from Excel is used to extract the contract number.
        Then files are downloaded from all three sections (docs, projectdocs, printformdocs).
        
        Args:
            url: URL from Excel (used to extract contract number)
            
        Returns:
            Dictionary with download result summary including all file metadata
        """
        if self._shutdown_requested:
            return {
                'url': url,
                'success': False,
                'error': 'Shutdown requested',
                'contract_number': None,
                'files_downloaded': 0,
                'results': []
            }
        
        try:
            # Extract contract number from URL
            contract_number = FileDownloader.extract_contract_number(url)
            
            default_logger.info(f"Processing contract {contract_number}")
            
            # Download all files for this contract from all three sections
            # Results contain standardized metadata records matching example_pars.py format
            results = self.downloader.download_files_for_contract(contract_number)
            
            # Count successes and failures based on status field
            successful = sum(1 for r in results if r.get('status') in ('downloaded', 'skipped', 'already_exists'))
            failed = sum(1 for r in results if r.get('status') not in ('downloaded', 'skipped', 'already_exists', 'no_files'))
            
            # Process each downloaded file - only after ALL downloads for this contract are complete
            # This ensures files are fully written before processing starts
            files_processed = 0
            for result in results:
                # Only process successfully downloaded files (not skipped)
                if result.get('status') == 'downloaded' and result.get('url'):
                    if self._process_downloaded_file(result['url']):
                        files_processed += 1
            
            return {
                'url': url,
                'success': True,
                'contract_number': contract_number,
                'files_found': len(results),
                'files_downloaded': successful,
                'files_failed': failed,
                'files_processed_db': files_processed,
                'results': results  # Include all metadata for Excel report
            }
            
        except Exception as e:
            default_logger.error(f"Error processing contract from URL {url}: {e}")
            return {
                'url': url,
                'success': False,
                'error': str(e),
                'contract_number': None,
                'files_downloaded': 0,
                'results': []
            }
    
    def _process_downloaded_file(self, file_path: str) -> bool:
        """Process a downloaded file using existing processors.
        
        This method is called AFTER the file has been completely downloaded
        and saved to disk. The metadata has already been saved to DB by
        FileDownloader._save_metadata_to_db().
        
        Args:
            file_path: Path to downloaded file
            
        Returns:
            True if processing successful
        """
        try:
            # Use FileScanner to register and process the file
            scanner = FileScanner()
            
            # Extract contract number from path
            path_obj = Path(file_path)
            contract_number = path_obj.parent.name if path_obj.parent else None
            
            # Generate file ID
            file_id = scanner._generate_file_id(path_obj)
            
            # Check if already processed (idempotency check)
            if self.repo.check_file_processed(file_id):
                default_logger.debug(f"File already processed: {file_path}")
                return True
            
            # Update status to PROCESSING
            from models.db_models import FileStatus
            self.repo.update_file_status(file_id, FileStatus.PROCESSING)
            
            # TODO: Here you would call the existing content extraction pipeline
            # For now, we just update the status
            # The actual processing can be done by calling existing processors:
            # - processors/content_extractor.py
            # - processors/document_reader.py
            # etc.
            
            # Mark as DONE after successful processing
            self.repo.update_file_status(file_id, FileStatus.DONE)
            
            default_logger.info(f"Processed file: {file_path}")
            return True
            
        except Exception as e:
            default_logger.error(f"Error processing file {file_path}: {e}")
            # Mark as ERROR
            try:
                from models.db_models import FileStatus
                # Try to find the file record and mark as error
                existing = self.repo.get_file_by_path(file_path)
                if existing:
                    self.repo.update_file_status(existing.id, FileStatus.ERROR, str(e))
            except:
                pass
            return False
    
    def download_all(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Download all files from URLs in parallel.
        
        Args:
            urls: List of URLs to download
            
        Returns:
            List of download results with all metadata
        """
        results = []
        contracts_seen: Set[str] = set()
        all_file_metadata = []  # Collect all file metadata for Excel report
        
        default_logger.info(
            f"Starting parallel download (max {self.max_parallel} parallel)"
        )
        
        with ThreadPoolExecutor(max_workers=self.max_parallel) as executor:
            # Submit all download tasks
            future_to_url = {
                executor.submit(self._download_with_progress, url): url
                for url in urls
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_url):
                if self._shutdown_requested:
                    default_logger.info("Shutdown requested, stopping downloads")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                
                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result['success']:
                        contract = result['contract_number']
                        if contract:
                            contracts_seen.add(contract)
                        
                        # Collect file metadata for Excel report
                        if result.get('results'):
                            all_file_metadata.extend(result['results'])
                        
                        # Process downloaded files
                        for file_result in result.get('results', []):
                            if file_result.get('status') == 'downloaded' and file_result.get('url'):
                                if self._process_downloaded_file(file_result['url']):
                                    self.stats['files_processed_db'] += 1
                    
                except Exception as e:
                    default_logger.error(f"Error in download task for {url}: {e}")
                    results.append({
                        'url': url,
                        'success': False,
                        'error': str(e),
                        'results': []
                    })
        
        self.stats['contracts_processed'] = len(contracts_seen)
        
        # Save metadata to Excel report
        if all_file_metadata:
            self._save_metadata_report(all_file_metadata)
        
        return results
    
    def _save_metadata_report(self, all_metadata: List[Dict[str, Any]]) -> None:
        """Save file metadata to Excel report.
        
        Args:
            all_metadata: List of file metadata dictionaries
        """
        try:
            current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            report_path = settings.paths.DOWNLOAD_DIR / f"{current_time}_contr.xlsx"
            
            df = pd.DataFrame(all_metadata)
            df.to_excel(report_path, index=False)
            
            default_logger.info(f"Metadata report saved to: {report_path}")
        except Exception as e:
            default_logger.error(f"Failed to save metadata report: {e}")
    
    def run(self) -> Dict[str, Any]:
        """Run the complete ingestion workflow.
        
        Returns:
            Dictionary with final statistics
        """
        self.stats['start_time'] = datetime.now()
        default_logger.info("=" * 70)
        default_logger.info("Starting Excel ingestion workflow")
        default_logger.info("=" * 70)
        
        try:
            # Step 1: Authenticate
            default_logger.info("Step 1: Authenticating with site...")
            if not self.authenticator.authenticate():
                raise Exception("Failed to authenticate with site")
            default_logger.info("Authentication successful")
            
            # Step 2: Read URLs from Excel
            default_logger.info("Step 2: Reading URLs from Excel...")
            urls = self.read_urls_from_excel()
            
            if not urls:
                default_logger.warning("No URLs found in Excel file")
                return self.get_statistics()
            
            # Step 3: Download files
            default_logger.info("Step 3: Downloading files...")
            download_results = self.download_all(urls)
            
            # Update statistics from downloader
            dl_stats = self.downloader.get_statistics()
            self.stats['files_downloaded'] = dl_stats['downloaded']
            self.stats['files_skipped'] = dl_stats['skipped']
            self.stats['files_failed'] = dl_stats['failed']
            
            # Count errors
            self.stats['errors'] = sum(
                1 for r in download_results if not r['success']
            )
            
            # Step 4: Summary
            self.stats['end_time'] = datetime.now()
            elapsed = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
            
            default_logger.info("=" * 70)
            default_logger.info("INGESTION COMPLETE")
            default_logger.info("=" * 70)
            default_logger.info(f"Total URLs processed: {self.stats['unique_urls']}")
            default_logger.info(f"Contracts processed: {self.stats['contracts_processed']}")
            default_logger.info(f"Files downloaded: {self.stats['files_downloaded']}")
            default_logger.info(f"Files skipped (existed): {self.stats['files_skipped']}")
            default_logger.info(f"Files failed: {self.stats['files_failed']}")
            default_logger.info(f"Files registered in DB: {self.stats['files_processed_db']}")
            default_logger.info(f"Errors: {self.stats['errors']}")
            default_logger.info(f"Time elapsed: {elapsed:.1f} seconds")
            default_logger.info("=" * 70)
            
        except KeyboardInterrupt:
            default_logger.warning("Process interrupted by user")
            self.stats['end_time'] = datetime.now()
        except Exception as e:
            default_logger.error(f"Ingestion failed: {e}", exc_info=True)
            self.stats['end_time'] = datetime.now()
            raise
        
        return self.get_statistics()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get ingestion statistics.
        
        Returns:
            Dictionary with statistics
        """
        stats = self.stats.copy()
        
        # Add downloader stats
        stats['downloader_stats'] = self.downloader.get_statistics()
        
        # Calculate derived metrics
        if stats['start_time'] and stats['end_time']:
            stats['duration_seconds'] = (
                stats['end_time'] - stats['start_time']
            ).total_seconds()
        else:
            stats['duration_seconds'] = None
        
        # Convert datetime objects to strings for JSON serialization
        if stats['start_time']:
            stats['start_time'] = stats['start_time'].isoformat()
        if stats['end_time']:
            stats['end_time'] = stats['end_time'].isoformat()
        
        return stats


def ingest_from_excel(
    excel_file_path: str = None,
    url_column: str = None
) -> Dict[str, Any]:
    """Convenience function to run Excel ingestion.
    
    Args:
        excel_file_path: Path to Excel file (optional, uses config default)
        url_column: Column name with URLs (optional, uses config default)
    
    Returns:
        Dictionary with ingestion statistics
    """
    ingester = ExcelIngester(excel_file_path, url_column)
    return ingester.run()
