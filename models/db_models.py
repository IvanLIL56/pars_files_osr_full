"""Database models for file processor.

This module defines SQLAlchemy ORM models for the database schema.
Two main tables:
- files_metadata: Information about files (name, path, size, hash, status, etc.)
- files_content: Text content of files with foreign key to metadata
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, 
    Index, UniqueConstraint, Enum as SQLEnum
)
from sqlalchemy.orm import relationship, declarative_base
import enum


Base = declarative_base()


class FileStatus(str, enum.Enum):
    """Status of file processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class FilesMetadata(Base):
    """Model for files_metadata table.
    
    Stores information about processed files including:
    - File identification (id, filename, path, size)
    - Hash values for duplicate detection
    - Processing status and error information
    - MIME type and extension
    - Duplicate reference if file is a duplicate
    - Contract number extracted from directory path
    """
    __tablename__ = "files_metadata"
    
    id = Column(String(64), primary_key=True)
    filename = Column(String(512), nullable=False, index=True)
    full_path = Column(String(2048), nullable=False)
    directory = Column(String(1024))
    extension = Column(String(32), nullable=False)
    mime_type = Column(String(128))
    size_bytes = Column(Integer, nullable=False)
    
    # Contract/Agreement number extracted from directory path
    contract_number = Column(String(64), index=True)
    
    # Metadata from external API (for downloaded files)
    document_key = Column(String(100), index=True)      # Уникальный ключ документа из API
    attachment_type = Column(String(100))               # Тип вложения (AttachmentDocType)
    attachment_title = Column(String(500))              # Оригинальное имя файла
    source_place = Column(String(50))                   # Откуда скачан (docs/projectdocs/printformdocs)
    api_last_modified = Column(DateTime)                # Дата последнего изменения из API
    
    # Hash values for duplicate detection
    content_hash = Column(String(64), unique=True, index=True)  # Full file hash (optional)
    partial_hash = Column(String(64), unique=False, index=True)  # Partial hash for quick duplicate check
    
    # Processing status
    status = Column(SQLEnum(FileStatus), default=FileStatus.PENDING, nullable=False, index=True)
    error_message = Column(Text)
    
    # Encryption flag
    is_encrypted = Column(Integer, default=0)  # 1 if encrypted, 0 otherwise
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime)
    
    # Duplicate detection - references another file's id
    duplicate_of_id = Column(String(64), ForeignKey("files_metadata.id"), index=True)
    
    # Parent archive id (for files inside archives)
    parent_id = Column(String(64), ForeignKey("files_metadata.id"), index=True)
    
    # Additional metadata
    archive_name = Column(String(512))  # If file was inside an archive
    original_encoding = Column(String(64))  # Detected encoding for archive filenames
    
    # Relationships
    content = relationship("FilesContent", back_populates="metadata", uselist=False, cascade="all, delete-orphan")
    keyword_results = relationship("KeywordSearchResults", back_populates="metadata", cascade="all, delete-orphan")
    duplicates = relationship("FilesMetadata", remote_side=[duplicate_of_id])
    children = relationship("FilesMetadata", remote_side=[parent_id])
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_status_extension', 'status', 'extension'),
        Index('idx_partial_hash_status', 'partial_hash', 'status'),
        Index('idx_created_at', 'created_at'),
        Index('idx_processed_at', 'processed_at'),
        Index('idx_contract_number', 'contract_number'),
    )
    
    def __repr__(self) -> str:
        return f"<FilesMetadata(id={self.id}, filename={self.filename}, status={self.status})>"
    
    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "filename": self.filename,
            "full_path": self.full_path,
            "directory": self.directory,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "contract_number": self.contract_number,
            "document_key": self.document_key,
            "attachment_type": self.attachment_type,
            "attachment_title": self.attachment_title,
            "source_place": self.source_place,
            "api_last_modified": self.api_last_modified.isoformat() if self.api_last_modified else None,
            "content_hash": self.content_hash,
            "partial_hash": self.partial_hash,
            "status": self.status.value if self.status else None,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "duplicate_of_id": self.duplicate_of_id,
            "parent_id": self.parent_id,
            "archive_name": self.archive_name,
            "original_encoding": self.original_encoding,
        }


class FilesContent(Base):
    """Model for files_content table.
    
    Stores the extracted text content of files.
    Each record corresponds to one file from files_metadata.
    """
    __tablename__ = "files_content"
    
    id = Column(String(64), primary_key=True)
    file_id = Column(String(64), ForeignKey("files_metadata.id", ondelete="CASCADE"), 
                     nullable=False, unique=True)
    
    # Content fields
    full_text = Column(Text)
    page_count = Column(Integer, default=0)
    char_count = Column(Integer, default=0)
    
    # Processing method
    type_read = Column(String(64))  # e.g., 'pdf', 'docx', 'osr'
    image_quality = Column(Text)  # Quality metrics for OCR results
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship back to metadata (renamed from 'metadata' to avoid conflict with reserved word)
    parent_metadata = relationship("FilesMetadata", back_populates="content")
    
    # Indexes - using unique names to avoid conflicts
    __table_args__ = (
        Index('idx_fc_file_id', 'file_id'),
        Index('idx_fc_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<FilesContent(id={self.id}, file_id={self.file_id}, char_count={self.char_count})>"
    
    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "file_id": self.file_id,
            "full_text": self.full_text,
            "page_count": self.page_count,
            "char_count": self.char_count,
            "type_read": self.type_read,
            "image_quality": self.image_quality,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KeywordSearchResults(Base):
    """Model for keyword_search_results table.
    
    Stores results of keyword search in file content.
    Each record contains found keywords, their counts, and text examples.
    """
    __tablename__ = "keyword_search_results"
    
    id = Column(String(64), primary_key=True)
    file_id = Column(String(64), ForeignKey("files_metadata.id", ondelete="CASCADE"), 
                     nullable=False, index=True)
    
    # Search results
    keywords_found = Column(Text)  # JSON array of found keywords
    total_keywords_count = Column(Integer, default=0)  # Total count of all keyword occurrences
    keyword_details = Column(Text)  # JSON with detailed info per keyword (count, examples)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship back to metadata (renamed from 'metadata' to avoid conflict)
    parent_file = relationship("FilesMetadata", back_populates="keyword_results")
    
    # Indexes - using unique names to avoid conflicts
    __table_args__ = (
        Index('idx_kw_file_id', 'file_id'),
        Index('idx_kw_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<KeywordSearchResults(id={self.id}, file_id={self.file_id}, total_count={self.total_keywords_count})>"
    
    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "file_id": self.file_id,
            "keywords_found": self.keywords_found,
            "total_keywords_count": self.total_keywords_count,
            "keyword_details": self.keyword_details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
