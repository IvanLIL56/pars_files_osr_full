"""Ingest module initialization."""

from .excel_ingester import ExcelIngester, ingest_from_excel

__all__ = ['ExcelIngester', 'ingest_from_excel']
