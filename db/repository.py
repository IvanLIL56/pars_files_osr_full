"""Database repository layer for file processor.

This module provides a repository pattern for database operations,
abstracting away the specific database backend (SQLite/PostgreSQL).
"""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator
from sqlalchemy import create_engine, text, and_
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from config import settings
from models.db_models import Base, FilesMetadata, FilesContent, FileStatus, KeywordSearchResults
from utils.hash_utils import compute_partial_hash


class DatabaseRepository:
    """Repository for database operations.
    
    Provides methods for:
    - Database initialization and connection management
    - File metadata CRUD operations
    - File content CRUD operations
    - Duplicate detection queries
    - Status updates for idempotent processing
    """
    
    def __init__(self):
        """Initialize database connection."""
        self.engine = self._create_engine()
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._initialize_tables()
    
    def _create_engine(self):
        """Create SQLAlchemy engine based on configuration."""
        if settings.db.DB_TYPE == "postgresql":
            url = (
                f"postgresql://{settings.db.PG_USER}:{settings.db.PG_PASSWORD}"
                f"@{settings.db.PG_HOST}:{settings.db.PG_PORT}/{settings.db.PG_DB}"
            )
            return create_engine(
                url,
                pool_size=settings.db.POOL_SIZE,
                max_overflow=settings.db.MAX_OVERFLOW,
                pool_pre_ping=settings.db.POOL_PRE_PING,
            )
        elif settings.db.DB_TYPE == "mysql":
            url = (
                f"mysql+pymysql://{settings.db.MYSQL_USER}:{settings.db.MYSQL_PASSWORD}"
                f"@{settings.db.MYSQL_HOST}:{settings.db.MYSQL_PORT}/{settings.db.MYSQL_DB}"
            )
            return create_engine(
                url,
                pool_size=settings.db.POOL_SIZE,
                max_overflow=settings.db.MAX_OVERFLOW,
                pool_pre_ping=settings.db.POOL_PRE_PING,
            )
        else:  # SQLite
            # Ensure directory exists
            db_path = Path(settings.db.SQLITE_PATH)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
    
    def _initialize_tables(self):
        """Create database tables if they don't exist."""
        Base.metadata.create_all(bind=self.engine)
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get database session context manager."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    # ========== File Metadata Operations ==========
    
    def get_file_by_id(self, file_id: str) -> Optional[FilesMetadata]:
        """Get file metadata by ID."""
        with self.get_session() as session:
            return session.query(FilesMetadata).filter(FilesMetadata.id == file_id).first()
    
    def get_file_by_path(self, full_path: str) -> Optional[FilesMetadata]:
        """Get file metadata by full path."""
        with self.get_session() as session:
            return session.query(FilesMetadata).filter(FilesMetadata.full_path == full_path).first()
    
    def get_file_by_partial_hash(self, partial_hash: str) -> Optional[FilesMetadata]:
        """Get file metadata by partial hash (for duplicate detection)."""
        with self.get_session() as session:
            return session.query(FilesMetadata).filter(
                FilesMetadata.partial_hash == partial_hash
            ).first()
    
    def create_file_metadata(self, file_data: Dict[str, Any]) -> FilesMetadata:
        """Create new file metadata record."""
        with self.get_session() as session:
            metadata = FilesMetadata(**file_data)
            session.add(metadata)
            session.flush()  # Get generated ID
            return metadata
    
    def upsert_file_metadata(self, file_data: Dict[str, Any]) -> FilesMetadata:
        """Insert or update file metadata record (idempotent operation).
        
        If file with same full_path exists, updates it. Otherwise creates new record.
        Used for downloaded files to store API metadata.
        """
        with self.get_session() as session:
            # Check if exists by full_path
            existing = session.query(FilesMetadata).filter(
                FilesMetadata.full_path == file_data.get('full_path')
            ).first()
            
            if existing:
                # Update existing record
                for key, value in file_data.items():
                    if hasattr(existing, key) and value is not None:
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
                session.flush()
                return existing
            else:
                # Insert new record
                metadata = FilesMetadata(**file_data)
                session.add(metadata)
                session.flush()
                return metadata
    
    def update_file_status(
        self, 
        file_id: str, 
        status: FileStatus, 
        error_message: Optional[str] = None
    ) -> bool:
        """Update file processing status."""
        with self.get_session() as session:
            record = session.query(FilesMetadata).filter(FilesMetadata.id == file_id).first()
            if not record:
                return False
            
            record.status = status
            record.error_message = error_message
            if status == FileStatus.DONE:
                record.processed_at = datetime.utcnow()
            
            session.flush()
            return True
    
    def mark_as_duplicate(self, file_id: str, original_id: str) -> bool:
        """Mark a file as duplicate of another file."""
        with self.get_session() as session:
            record = session.query(FilesMetadata).filter(FilesMetadata.id == file_id).first()
            if not record:
                return False
            
            record.duplicate_of_id = original_id
            record.status = FileStatus.DONE
            session.flush()
            return True
    
    def get_files_to_process(self, limit: int = 100) -> List[FilesMetadata]:
        """Get files that need processing (pending or error status)."""
        with self.get_session() as session:
            return session.query(FilesMetadata).filter(
                and_(
                    FilesMetadata.status.in_([FileStatus.PENDING, FileStatus.ERROR])
                )
            ).limit(limit).all()
    
    def check_file_exists(self, file_id: str) -> bool:
        """Check if file exists in database."""
        with self.get_session() as session:
            return session.query(FilesMetadata.id).filter(
                FilesMetadata.id == file_id
            ).first() is not None
    
    def check_file_processed(self, file_id: str) -> bool:
        """Check if file was successfully processed (status=done and has content)."""
        with self.get_session() as session:
            metadata = session.query(FilesMetadata).filter(
                FilesMetadata.id == file_id
            ).first()
            
            if not metadata or metadata.status != FileStatus.DONE:
                return False
            
            # Check if content exists
            content = session.query(FilesContent.id).filter(
                FilesContent.file_id == file_id
            ).first()
            
            return content is not None
    
    # ========== File Content Operations ==========
    
    def get_file_content(self, file_id: str) -> Optional[FilesContent]:
        """Get file content by file ID."""
        with self.get_session() as session:
            return session.query(FilesContent).filter(
                FilesContent.file_id == file_id
            ).first()
    
    def create_file_content(self, content_data: Dict[str, Any]) -> FilesContent:
        """Create new file content record."""
        with self.get_session() as session:
            content = FilesContent(**content_data)
            session.add(content)
            session.flush()
            return content
    
    def upsert_file_content(self, content_data: Dict[str, Any]) -> FilesContent:
        """Insert or update file content."""
        with self.get_session() as session:
            content = session.query(FilesContent).filter(
                FilesContent.file_id == content_data["file_id"]
            ).first()
            
            if content:
                # Update existing
                for key, value in content_data.items():
                    if hasattr(content, key):
                        setattr(content, key, value)
                content.updated_at = datetime.utcnow()
            else:
                # Insert new
                content = FilesContent(**content_data)
                session.add(content)
            
            session.flush()
            return content
    
    # ========== Duplicate Detection ==========
    
    def find_duplicate_by_hash(self, partial_hash: str) -> Optional[str]:
        """Find ID of duplicate file by partial hash.
        
        Returns the ID of the original file if a duplicate exists, None otherwise.
        """
        with self.get_session() as session:
            record = session.query(FilesMetadata).filter(
                and_(
                    FilesMetadata.partial_hash == partial_hash,
                    FilesMetadata.status == FileStatus.DONE,
                    FilesMetadata.duplicate_of_id.is_(None)  # Only check original files
                )
            ).first()
            
            return record.id if record else None
    
    # ========== Statistics ==========
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics."""
        with self.get_session() as session:
            total = session.query(FilesMetadata).count()
            done = session.query(FilesMetadata).filter(
                FilesMetadata.status == FileStatus.DONE
            ).count()
            error = session.query(FilesMetadata).filter(
                FilesMetadata.status == FileStatus.ERROR
            ).count()
            pending = session.query(FilesMetadata).filter(
                FilesMetadata.status == FileStatus.PENDING
            ).count()
            duplicates = session.query(FilesMetadata).filter(
                FilesMetadata.duplicate_of_id.isnot(None)
            ).count()
            encrypted = session.query(FilesMetadata).filter(
                FilesMetadata.is_encrypted == 1
            ).count()
            
            return {
                "total_files": total,
                "processed": done,
                "errors": error,
                "pending": pending,
                "duplicates": duplicates,
                "encrypted": encrypted,
            }
    
    # ========== Keyword Search Operations ==========
    
    def save_keyword_results(self, file_id: str, search_results: Dict[str, Any]) -> Optional[KeywordSearchResults]:
        """Save keyword search results for a file.
        
        Args:
            file_id: ID of the file
            search_results: Dictionary with keyword search results
        
        Returns:
            Created/updated KeywordSearchResults object
        """
        import json
        from datetime import datetime
        import uuid
        
        content_data = {
            'id': str(uuid.uuid4()),
            'file_id': file_id,
            'keywords_found': json.dumps(search_results.get('keywords_found', [])),
            'total_keywords_count': search_results.get('total_count', 0),
            'keyword_details': json.dumps(search_results.get('details', {})),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
        }
        
        with self.get_session() as session:
            # Check if already exists
            existing = session.query(KeywordSearchResults).filter(
                KeywordSearchResults.file_id == file_id
            ).first()
            
            if existing:
                # Update existing
                existing.keywords_found = content_data['keywords_found']
                existing.total_keywords_count = content_data['total_keywords_count']
                existing.keyword_details = content_data['keyword_details']
                existing.updated_at = content_data['updated_at']
                session.flush()
                return existing
            else:
                # Insert new
                result = KeywordSearchResults(**content_data)
                session.add(result)
                session.flush()
                return result
    
    def get_keyword_results(self, file_id: str) -> Optional[KeywordSearchResults]:
        """Get keyword search results for a file.
        
        Args:
            file_id: ID of the file
        
        Returns:
            KeywordSearchResults object or None
        """
        with self.get_session() as session:
            return session.query(KeywordSearchResults).filter(
                KeywordSearchResults.file_id == file_id
            ).first()
    
    def search_by_keyword(self, keyword: str, contract_number: str = None) -> List[Dict[str, Any]]:
        """Search for files containing a specific keyword.
        
        Args:
            keyword: Keyword to search for
            contract_number: Optional contract number to filter by
        
        Returns:
            List of dictionaries with file info and keyword match details
        """
        import json
        
        with self.get_session() as session:
            query = session.query(
                FilesMetadata,
                KeywordSearchResults
            ).join(
                KeywordSearchResults,
                FilesMetadata.id == KeywordSearchResults.file_id
            ).filter(
                KeywordSearchResults.keywords_found.contains(keyword)
            )
            
            if contract_number:
                query = query.filter(FilesMetadata.contract_number == contract_number)
            
            results = []
            for metadata, kw_result in query.all():
                try:
                    details = json.loads(kw_result.keyword_details) if kw_result.keyword_details else {}
                    keyword_info = details.get(keyword, {})
                    
                    results.append({
                        'file_id': metadata.id,
                        'filename': metadata.filename,
                        'contract_number': metadata.contract_number,
                        'full_path': metadata.full_path,
                        'keyword_count': keyword_info.get('count', 0),
                        'examples': keyword_info.get('examples', []),
                        'processed_at': metadata.processed_at.isoformat() if metadata.processed_at else None,
                    })
                except Exception:
                    continue
            
            return results
    
    # ========== Bulk Operations ==========
    
    def bulk_insert_metadata(self, records: List[Dict[str, Any]]) -> int:
        """Bulk insert file metadata records."""
        if not records:
            return 0
        
        with self.get_session() as session:
            session.bulk_insert_mappings(FilesMetadata, records)
            return len(records)
    
    def bulk_update_status(self, file_ids: List[str], status: FileStatus) -> int:
        """Bulk update status for multiple files."""
        if not file_ids:
            return 0
        
        with self.get_session() as session:
            updated = session.query(FilesMetadata).filter(
                FilesMetadata.id.in_(file_ids)
            ).update(
                {"status": status},
                synchronize_session=False
            )
            return updated


# Singleton instance
_repository: Optional[DatabaseRepository] = None


def get_repository() -> DatabaseRepository:
    """Get singleton repository instance."""
    global _repository
    if _repository is None:
        _repository = DatabaseRepository()
    return _repository


def init_database():
    """Initialize database connection."""
    return get_repository()
