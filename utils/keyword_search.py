"""Keyword search utility for file processor.

This module provides functionality for:
- Loading keywords from configuration file
- Searching for keywords in text content
- Extracting context around keyword matches
- Generating search result statistics
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict

from config import settings


class KeywordSearcher:
    """Performs keyword search in text content with context extraction."""
    
    def __init__(self, keywords_file: str = None):
        """Initialize keyword searcher.
        
        Args:
            keywords_file: Path to file with keywords (one per line).
                          If None, uses config default.
        """
        self.keywords_file = keywords_file or settings.processing.KEYWORDS_FILE
        self.keywords: List[str] = []
        self.compiled_patterns: List[re.Pattern] = []
        self._load_keywords()
    
    def _load_keywords(self) -> None:
        """Load keywords from file."""
        keywords_path = Path(self.keywords_file)
        
        if not keywords_path.exists():
            # Create empty keywords file if it doesn't exist
            keywords_path.parent.mkdir(parents=True, exist_ok=True)
            keywords_path.touch()
            return
        
        try:
            with open(keywords_path, 'r', encoding='utf-8') as f:
                # Read non-empty lines, strip whitespace
                self.keywords = [
                    line.strip() 
                    for line in f 
                    if line.strip() and not line.strip().startswith('#')
                ]
            
            # Compile regex patterns for each keyword (case-insensitive)
            self.compiled_patterns = [
                re.compile(re.escape(keyword), re.IGNORECASE) 
                for keyword in self.keywords
            ]
        except Exception as e:
            # Log error but continue with empty keywords
            self.keywords = []
            self.compiled_patterns = []
    
    def search_keywords(
        self, 
        text: str, 
        max_examples: int = None,
        context_chars: int = None
    ) -> Dict[str, Any]:
        """Search for all keywords in text.
        
        Args:
            text: Text content to search in
            max_examples: Maximum number of examples per keyword (from config if None)
            context_chars: Number of characters to capture around match (from config if None)
        
        Returns:
            Dictionary with search results:
            - keywords_found: List of keywords that were found
            - total_count: Total number of keyword occurrences
            - details: Dict per keyword with count and examples
        """
        if max_examples is None:
            max_examples = settings.processing.MAX_KEYWORD_EXAMPLES
        if context_chars is None:
            context_chars = settings.processing.KEYWORD_CONTEXT_CHARS
        
        if not text or not self.keywords:
            return {
                'keywords_found': [],
                'total_count': 0,
                'details': {}
            }
        
        results = {
            'keywords_found': [],
            'total_count': 0,
            'details': {}
        }
        
        for keyword, pattern in zip(self.keywords, self.compiled_patterns):
            # Find all matches
            matches = list(pattern.finditer(text))
            
            if matches:
                results['keywords_found'].append(keyword)
                match_count = len(matches)
                results['total_count'] += match_count
                
                # Extract examples with context
                examples = []
                for i, match in enumerate(matches[:max_examples]):
                    start = max(0, match.start() - context_chars)
                    end = min(len(text), match.end() + context_chars)
                    
                    example = text[start:end]
                    # Add ellipsis if truncated
                    if start > 0:
                        example = '...' + example
                    if end < len(text):
                        example = example + '...'
                    
                    examples.append(example)
                
                results['details'][keyword] = {
                    'count': match_count,
                    'examples': examples
                }
        
        return results
    
    def search_keywords_batch(
        self, 
        texts: List[str],
        max_examples: int = None,
        context_chars: int = None
    ) -> List[Dict[str, Any]]:
        """Search for keywords in multiple texts.
        
        Args:
            texts: List of text contents to search
            max_examples: Maximum number of examples per keyword
            context_chars: Number of characters to capture around match
        
        Returns:
            List of search result dictionaries (one per text)
        """
        return [
            self.search_keywords(text, max_examples, context_chars)
            for text in texts
        ]


def load_keywords(keywords_file: str = None) -> List[str]:
    """Load keywords from file or environment variable (convenience function).
    
    Priority:
    1. KEYWORDS_ENV environment variable (comma or newline separated)
    2. Keywords file (one per line)
    
    Args:
        keywords_file: Path to keywords file (uses config default if None)
    
    Returns:
        List of keywords (filtered by min length, comments removed)
    """
    from config import settings
    
    keywords_file = keywords_file or settings.processing.KEYWORDS_FILE
    min_length = settings.processing.KEYWORD_MIN_LENGTH
    
    # Try loading from environment variable first (highest priority)
    env_keywords = settings.processing.KEYWORDS_ENV
    if env_keywords and env_keywords.strip():
        # Support comma-separated or newline-separated
        if "\n" in env_keywords:
            words = [line.strip() for line in env_keywords.splitlines()]
        else:
            words = [w.strip() for w in env_keywords.split(",")]
        
        # Filter empty and too short words
        filtered = [w for w in words if w and len(w) >= min_length and not w.startswith('#')]
        if filtered:
            return filtered
    
    # If ENV is empty, try loading from file
    keywords_path = Path(keywords_file)
    
    if not keywords_path.exists():
        return []
    
    try:
        with open(keywords_path, 'r', encoding='utf-8') as f:
            # Read non-empty lines, strip whitespace, filter comments and short words
            words = [
                line.strip() 
                for line in f 
                if line.strip() 
                and not line.strip().startswith('#')
                and len(line.strip()) >= min_length
            ]
        return words
    except Exception as e:
        # Log error but continue with empty keywords
        from logger_config import default_logger
        default_logger.warning(f"Failed to read keywords file {keywords_file}: {e}")
        return []


def search_in_text(
    text: str, 
    keywords: List[str],
    max_examples: int = 5,
    context_chars: int = 100
) -> Dict[str, Any]:
    """Search for keywords in text (standalone function).
    
    Args:
        text: Text content to search
        keywords: List of keywords to search for
        max_examples: Maximum examples per keyword
        context_chars: Context characters around matches
    
    Returns:
        Search results dictionary
    """
    if not text or not keywords:
        return {
            'keywords_found': [],
            'total_count': 0,
            'details': {}
        }
    
    results = {
        'keywords_found': [],
        'total_count': 0,
        'details': {}
    }
    
    for keyword in keywords:
        try:
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            matches = list(pattern.finditer(text))
            
            if matches:
                results['keywords_found'].append(keyword)
                match_count = len(matches)
                results['total_count'] += match_count
                
                examples = []
                for match in matches[:max_examples]:
                    start = max(0, match.start() - context_chars)
                    end = min(len(text), match.end() + context_chars)
                    
                    example = text[start:end]
                    if start > 0:
                        example = '...' + example
                    if end < len(text):
                        example = example + '...'
                    
                    examples.append(example)
                
                results['details'][keyword] = {
                    'count': match_count,
                    'examples': examples
                }
        except Exception:
            # Skip problematic keywords
            continue
    
    return results


def extract_contract_number_from_path(file_path: str) -> Optional[str]:
    """Extract contract number from file path.
    
    Expected path pattern: down/parsfile/{contract_number}/...
    
    Args:
        file_path: Full path to file
    
    Returns:
        Contract number if found, None otherwise
    """
    try:
        pattern = settings.processing.CONTRACT_DIR_PATTERN
        match = re.search(pattern, file_path)
        if match:
            return match.group(1)
        return None
    except Exception:
        return None


def serialize_keyword_results(results: Dict[str, Any]) -> Dict[str, str]:
    """Serialize keyword search results for database storage.
    
    Args:
        results: Search results dictionary
    
    Returns:
        Dictionary with JSON-serialized fields
    """
    return {
        'keywords_found': json.dumps(results.get('keywords_found', [])),
        'total_keywords_count': str(results.get('total_count', 0)),
        'keyword_details': json.dumps(results.get('details', {}))
    }
