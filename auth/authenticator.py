"""Auth module for external site authentication.

This module handles authentication with the external document site,
including token management and automatic re-authentication.
"""

from typing import Optional, Dict
import requests
from datetime import datetime, timedelta

from config import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class SiteAuthenticator:
    """Handles authentication with the external document site.
    
    Features:
    - Token-based authentication (Bearer token)
    - Automatic token refresh when expired
    - Support for manual token input or automatic login
    - Session management for efficient requests
    
    Attributes:
        base_url: Base URL of the external site
        token: Current Bearer token
        token_expires_at: Token expiration timestamp
        session: Requests session with pre-configured headers
    """
    
    def __init__(self, token: Optional[str] = None):
        """Initialize authenticator.
        
        Args:
            token: Optional pre-existing token. If not provided,
                  will attempt to obtain one via login.
        """
        self.base_url = settings.site.BASE_URL.rstrip('/')
        self.token = token or settings.site.TOKEN
        self.token_expires_at: Optional[datetime] = None
        self.session = self._create_session()
        
        # Login credentials
        self.login = settings.site.LOGIN
        self.password = settings.site.PASSWORD
        self.login_endpoint = settings.site.LOGIN_ENDPOINT
        
        logger.debug("SiteAuthenticator initialized")
    
    def _create_session(self) -> requests.Session:
        """Create configured requests session.
        
        Returns:
            Configured session object
        """
        session = requests.Session()
        session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "ru,en;q=0.9",
            "Referer": f"{self.base_url}/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        # Configure SSL verification
        session.verify = settings.site.VERIFY_SSL
        
        if self.token:
            self._set_token_in_session(self.token)
        
        return session
    
    def _set_token_in_session(self, token: str) -> None:
        """Set authorization header in session.
        
        Args:
            token: Bearer token to set
        """
        header_name = settings.site.TOKEN_HEADER
        prefix = settings.site.TOKEN_PREFIX
        self.session.headers[header_name] = f"{prefix} {token}"
    
    def authenticate(self) -> bool:
        """Authenticate with the site and obtain token.
        
        Returns:
            True if authentication successful, False otherwise
        """
        # If token already exists and is valid, use it
        if self.token and not self._is_token_expired():
            logger.info("Using existing valid token")
            return True
        
        # Try to login and get new token
        try:
            return self._login()
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def _login(self) -> bool:
        """Perform login to obtain token.
        
        Returns:
            True if login successful, False otherwise
        """
        login_url = f"{self.base_url}{self.login_endpoint}"
        
        logger.info(f"Attempting login to {login_url}")
        
        payload = {
            "username": self.login,
            "password": self.password
        }
        
        try:
            response = self.session.post(
                login_url,
                json=payload,
                timeout=settings.site.TIMEOUT
            )
            
            if response.status_code == 200:
                data = response.json()
                # Extract token from response (adjust based on actual API)
                self.token = data.get('token') or data.get('access_token')
                
                if self.token:
                    self._set_token_in_session(self.token)
                    # Set expiration (default 1 hour if not specified)
                    expires_in = data.get('expires_in', 3600)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                    logger.info("Login successful, token obtained")
                    return True
                else:
                    logger.error("No token in login response")
                    return False
            else:
                logger.error(f"Login failed with status {response.status_code}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Login request failed: {e}")
            return False
    
    def _is_token_expired(self) -> bool:
        """Check if current token is expired.
        
        Returns:
            True if token is expired or about to expire, False otherwise
        """
        if not self.token_expires_at:
            # If no expiration set, assume token is valid for 1 hour from now
            return False
        
        # Consider token expired 5 minutes before actual expiration
        buffer = timedelta(minutes=5)
        return datetime.now() >= (self.token_expires_at - buffer)
    
    def ensure_authenticated(self) -> bool:
        """Ensure we have a valid token, refreshing if necessary.
        
        Returns:
            True if authenticated successfully, False otherwise
        """
        if not self.token or self._is_token_expired():
            return self.authenticate()
        return True
    
    def get_headers(self) -> Dict[str, str]:
        """Get current authorization headers.
        
        Returns:
            Dictionary with authorization header
        """
        if not self.token:
            return {}
        
        header_name = settings.site.TOKEN_HEADER
        prefix = settings.site.TOKEN_PREFIX
        return {header_name: f"{prefix} {self.token}"}
    
    def make_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make authenticated HTTP request with automatic re-authentication.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments for requests
            
        Returns:
            Response object or None if request failed
        """
        # Ensure we have valid token
        if not self.ensure_authenticated():
            logger.error("Cannot make request: not authenticated")
            return None
        
        try:
            response = self.session.request(
                method,
                url,
                timeout=settings.site.TIMEOUT,
                **kwargs
            )
            
            # If we get 401/403, token might be invalid - try to re-authenticate
            if response.status_code in (401, 403):
                logger.warning(f"Got {response.status_code}, attempting re-authentication")
                if self._login():
                    # Retry request with new token
                    response = self.session.request(
                        method,
                        url,
                        timeout=settings.site.TIMEOUT,
                        **kwargs
                    )
            
            return response
            
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None
    
    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make authenticated GET request.
        
        Args:
            url: Request URL
            **kwargs: Additional arguments for requests
            
        Returns:
            Response object or None if request failed
        """
        return self.make_request("GET", url, **kwargs)
    
    def post(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make authenticated POST request.
        
        Args:
            url: Request URL
            **kwargs: Additional arguments for requests
            
        Returns:
            Response object or None if request failed
        """
        return self.make_request("POST", url, **kwargs)
