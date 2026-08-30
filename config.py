"""Configuration management for file processor.

This module provides centralized configuration management using pydantic settings,
supporting both environment variables and .env files.
"""

import os
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class PathsSettings(BaseSettings):
    """Path configuration settings."""
    
    INPUT_DIR: str = Field(default="./input", description="Input directory for files")
    LOG_DIR: str = Field(default="./logs", description="Directory for log files")
    DOWNLOAD_DIR: str = Field(default="./downloaded_files", description="Directory for downloaded files")
    
    model_config = SettingsConfigDict(env_prefix="PATH_")


class ProcessingSettings(BaseSettings):
    """Processing configuration settings."""
    
    MAX_WORKERS: int = Field(default=4, description="Maximum worker processes")
    MAX_OCR_WORKERS: int = Field(default=2, description="Maximum parallel OCR processes")
    BATCH_SIZE: int = Field(default=50, description="Batch size for database writes")
    
    SUPPORTED_EXTS: List[str] = Field(
        default=["pdf", "docx", "doc", "txt", "rtf", "odt", "xlsx", "xls"],
        description="Supported file extensions"
    )
    ARCHIVE_EXTS: List[str] = Field(
        default=["zip", "rar", "7z", "tar", "gz"],
        description="Archive extensions"
    )
    
    KEYWORDS_FILE: str = Field(default="./keywords.txt", description="Path to keywords file")
    ENABLE_KEYWORD_SEARCH: bool = Field(default=True, description="Enable keyword search")
    
    CHECK_ENCRYPTION: bool = Field(default=True, description="Check files for encryption")
    
    model_config = SettingsConfigDict(env_prefix="PROC_")


class DatabaseSettings(BaseSettings):
    """Database configuration settings.
    
    Supports multiple database types: postgresql, mysql, sqlite.
    """
    
    DB_TYPE: str = Field(default="sqlite", description="Database type: postgresql, mysql, sqlite")
    
    # PostgreSQL settings
    PG_HOST: str = Field(default="localhost", description="PostgreSQL host")
    PG_PORT: int = Field(default=5432, description="PostgreSQL port")
    PG_USER: str = Field(default="postgres", description="PostgreSQL user")
    PG_PASSWORD: str = Field(default="postgres", description="PostgreSQL password")
    PG_DB: str = Field(default="file_processor", description="PostgreSQL database name")
    
    # MySQL settings
    MYSQL_HOST: str = Field(default="localhost", description="MySQL host")
    MYSQL_PORT: int = Field(default=3306, description="MySQL port")
    MYSQL_USER: str = Field(default="root", description="MySQL user")
    MYSQL_PASSWORD: str = Field(default="root", description="MySQL password")
    MYSQL_DB: str = Field(default="file_processor", description="MySQL database name")
    
    # SQLite settings
    SQLITE_PATH: str = Field(default="./data/file_processor.db", description="SQLite database path")
    
    # Connection pool settings (for PostgreSQL/MySQL)
    POOL_SIZE: int = Field(default=5, description="Database connection pool size")
    MAX_OVERFLOW: int = Field(default=10, description="Maximum overflow connections")
    POOL_PRE_PING: bool = Field(default=True, description="Enable connection pre-ping")
    
    model_config = SettingsConfigDict(env_prefix="DB_")


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""
    
    LOG_LEVEL_CONSOLE: str = Field(default="INFO", description="Console logging level")
    LOG_LEVEL_FILE: str = Field(default="DEBUG", description="File logging level")
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format"
    )
    LOG_DATE_FORMAT: str = Field(default="%Y-%m-%d %H:%M:%S", description="Log date format")
    LOG_ROTATION_SIZE: int = Field(default=10485760, description="Log file rotation size (bytes)")
    LOG_BACKUP_COUNT: int = Field(default=5, description="Number of backup log files")
    LOG_USE_SINGLE_FILE: bool = Field(default=True, description="Use single log file instead of timestamped")
    
    model_config = SettingsConfigDict(env_prefix="LOG_")


class SiteSettings(BaseSettings):
    """External site authentication settings."""
    
    BASE_URL: str = Field(default="https://test.xxx.xxx", description="Base URL of the site")
    LOGIN_ENDPOINT: str = Field(default="/api/auth/login", description="Login API endpoint")
    TOKEN_URL: str = Field(default="", description="URL for obtaining token")
    
    LOGIN: str = Field(default="", description="Site login")
    PASSWORD: str = Field(default="", description="Site password")
    API_KEY: str = Field(default="", description="API key for authentication")
    TOKEN: str = Field(default="", description="Bearer token for authentication")
    
    TOKEN_HEADER: str = Field(default="Authorization", description="Header name for token")
    TOKEN_PREFIX: str = Field(default="Bearer", description="Token prefix in header")
    
    TIMEOUT: int = Field(default=30, description="Request timeout in seconds")
    VERIFY_SSL: bool = Field(default=False, description="Verify SSL certificates")
    
    model_config = SettingsConfigDict(env_prefix="SITE_")


class ExcelSettings(BaseSettings):
    """Excel file processing settings."""
    
    FILE_PATH: str = Field(default="./contracts.xlsx", description="Path to Excel file with URLs")
    URL_COLUMN: str = Field(default="Url документа", description="Column name containing URLs")
    
    model_config = SettingsConfigDict(env_prefix="EXCEL_")


class DownloadSettings(BaseSettings):
    """File download settings."""
    
    MAX_PARALLEL_DOWNLOADS: int = Field(default=5, description="Maximum parallel downloads")
    RETRY_COUNT: int = Field(default=3, description="Number of retry attempts")
    RETRY_DELAY: int = Field(default=5, description="Delay between retries in seconds")
    OVERWRITE_EXISTING: bool = Field(default=False, description="Overwrite existing files")
    SKIP_IF_EXISTS: bool = Field(default=True, description="Skip if file exists with same size")
    MAX_FILENAME_LENGTH: int = Field(default=155, description="Maximum filename length")
    
    model_config = SettingsConfigDict(env_prefix="DOWNLOAD_")


class Settings(BaseSettings):
    """Main application settings."""
    
    PROJECT_NAME: str = Field(default="FileProcessor", description="Project name")
    
    # Direct access to sub-settings for convenience
    INPUT_DIR: str = Field(default="./input", description="Input directory for files")
    LOG_DIR: str = Field(default="./logs", description="Directory for log files")
    DOWNLOAD_DIR: str = Field(default="./downloaded_files", description="Directory for downloaded files")
    
    MAX_WORKERS: int = Field(default=4, description="Maximum worker processes")
    MAX_OCR_WORKERS: int = Field(default=2, description="Maximum parallel OCR processes")
    BATCH_SIZE: int = Field(default=50, description="Batch size for database writes")
    
    SUPPORTED_EXTS: List[str] = Field(
        default=["pdf", "docx", "doc", "txt", "rtf", "odt", "xlsx", "xls"],
        description="Supported file extensions"
    )
    
    KEYWORDS_FILE: str = Field(default="./keywords.txt", description="Path to keywords file")
    ENABLE_KEYWORD_SEARCH: bool = Field(default=True, description="Enable keyword search")
    
    DB_TYPE: str = Field(default="sqlite", description="Database type: postgresql, mysql, sqlite")
    
    PG_HOST: str = Field(default="localhost", description="PostgreSQL host")
    PG_PORT: int = Field(default=5432, description="PostgreSQL port")
    PG_USER: str = Field(default="postgres", description="PostgreSQL user")
    PG_PASSWORD: str = Field(default="postgres", description="PostgreSQL password")
    PG_DB: str = Field(default="file_processor", description="PostgreSQL database name")
    
    MYSQL_HOST: str = Field(default="localhost", description="MySQL host")
    MYSQL_PORT: int = Field(default=3306, description="MySQL port")
    MYSQL_USER: str = Field(default="root", description="MySQL user")
    MYSQL_PASSWORD: str = Field(default="root", description="MySQL password")
    MYSQL_DB: str = Field(default="file_processor", description="MySQL database name")
    
    SQLITE_PATH: str = Field(default="./data/file_processor.db", description="SQLite database path")
    
    POOL_SIZE: int = Field(default=5, description="Database connection pool size")
    MAX_OVERFLOW: int = Field(default=10, description="Maximum overflow connections")
    POOL_PRE_PING: bool = Field(default=True, description="Enable connection pre-ping")
    
    LOG_LEVEL_CONSOLE: str = Field(default="INFO", description="Console logging level")
    LOG_LEVEL_FILE: str = Field(default="DEBUG", description="File logging level")
    LOG_USE_SINGLE_FILE: bool = Field(default=True, description="Use single log file")
    
    SITE_BASE_URL: str = Field(default="https://test.xxx.xxx", description="Base URL of the site")
    SITE_LOGIN_ENDPOINT: str = Field(default="/api/auth/login", description="Login API endpoint")
    SITE_LOGIN: str = Field(default="", description="Site login")
    SITE_PASSWORD: str = Field(default="", description="Site password")
    SITE_TOKEN: str = Field(default="", description="Bearer token for authentication")
    SITE_VERIFY_SSL: bool = Field(default=False, description="Verify SSL certificates")
    
    EXCEL_FILE_PATH: str = Field(default="./contracts.xlsx", description="Path to Excel file with URLs")
    EXCEL_URL_COLUMN: str = Field(default="Url документа", description="Column name containing URLs")
    
    MAX_PARALLEL_DOWNLOADS: int = Field(default=5, description="Maximum parallel downloads")
    DOWNLOAD_RETRY_COUNT: int = Field(default=3, description="Number of retry attempts")
    DOWNLOAD_RETRY_DELAY: int = Field(default=5, description="Delay between retries in seconds")
    OVERWRITE_EXISTING: bool = Field(default=False, description="Overwrite existing files")
    SKIP_IF_EXISTS: bool = Field(default=True, description="Skip if file exists with same size")
    MAX_FILENAME_LENGTH: int = Field(default=155, description="Maximum filename length")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Create global settings instance
settings = Settings()
