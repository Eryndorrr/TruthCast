"""
HTTP Client for CLI
Wraps httpx Client with unified error handling and retry logic.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Error Classes
# ============================================================================


class APIError(Exception):
    """Base exception for API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: str = ""):
        self.message = message
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(self.message)
    
    def user_friendly_message(self) -> str:
        """Returns a user-friendly error message."""
        return self.message


class NetworkError(APIError):
    """Network connectivity errors (connection refused, DNS failure, etc.)."""
    
    def user_friendly_message(self) -> str:
        return (
            f"[ERROR] Unable to connect to server\n\n"
            f"Error: {self.message}\n\n"
            f"Suggestions:\n"
            f"  1. 检查后端服务是否已启动 (uvicorn app.main:app ...)\n"
            f"  2. 检查 --api-base 参数是否正确\n"
            f"  3. 检查网络连接是否正常"
        )


class TimeoutError(APIError):
    """Request timeout errors."""
    
    def user_friendly_message(self) -> str:
        return (
            f"[TIMEOUT] Request timed out\n\n"
            f"Error: {self.message}\n\n"
            f"Suggestions:\n"
            f"  1. 检查网络连接\n"
            f"  2. 检查后端服务是否响应缓慢\n"
            f"  3. 尝试增加超时时间 (--timeout 参数)"
        )


class HTTPStatusError(APIError):
    """HTTP status code errors (4xx, 5xx)."""
    
    def user_friendly_message(self) -> str:
        status = self.status_code or "Unknown"
        return (
            f"[SERVER ERROR] (HTTP {status})\n\n"
            f"Error: {self.message}\n\n"
            f"Response: {self.response_text[:200]}"
        )


class JSONParseError(APIError):
    """JSON parsing errors in response."""
    
    def user_friendly_message(self) -> str:
        return (
            f"[JSON ERROR] Failed to parse JSON\n\n"
            f"Error: {self.message}\n\n"
            f"原始Response: {self.response_text[:200]}"
        )



# ============================================================================
# Stream Context Manager Wrapper
# ============================================================================


class _StreamContextWrapper:
    """
    Wrapper around httpx context manager for SSE streaming.
    Validates status code when entering the context.
    """
    
    def __init__(self, ctx_mgr):
        self.ctx_mgr = ctx_mgr
        self.response = None
    
    def __enter__(self):
        self.response = self.ctx_mgr.__enter__()
        # Check status code after entering context
        if self.response.status_code >= 400:
            response_text = self.response.text
            raise HTTPStatusError(
                f"HTTP {self.response.status_code}: {response_text[:100]}",
                status_code=self.response.status_code,
                response_text=response_text,
            )
        return self.response
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.ctx_mgr.__exit__(exc_type, exc_val, exc_tb)

# ============================================================================
# HTTP Client
# ============================================================================


class APIClient:
    """
    HTTP Client wrapper around httpx.Client with unified error handling.
    
    Features:
    - Configurable base_url, timeout, retry strategy
    - Unified error handling for network, timeout, HTTP status, JSON parse errors
    - Support for streaming responses (SSE)
    - Sensitive header masking in logs
    """
    
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
        retry_times: int = 1,
    ):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL for API server (e.g., http://127.0.0.1:8000)
            timeout: Request timeout in seconds
            retry_times: Number of retries on network errors (not on 4xx/5xx)
        """
        self.base_url = base_url
        self.timeout = timeout
        self.retry_times = retry_times
        
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
            trust_env=False,  # Prevent SOCKS proxy detection
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def close(self):
        """Close the underlying httpx client."""
        if self._client:
            self._client.close()
    
    def _log_request(self, method: str, url: str, **kwargs):
        """Log request details (without sensitive headers)."""
        headers = kwargs.get("headers", {})
        # Mask sensitive headers
        safe_headers = {k: "***" for k in headers if k.lower() in ["authorization", "x-api-key"]}
        safe_headers.update({k: v for k, v in headers.items() if k.lower() not in ["authorization", "x-api-key"]})
        logger.debug(f"{method} {url} | headers: {safe_headers}")
    
    def _handle_error(self, error: Exception, attempt: int) -> None:
        """Handle different error types and log them."""
        logger.error(f"Request failed (attempt {attempt}): {type(error).__name__}: {str(error)}")
    
    def get(self, path: str, **kwargs) -> Dict[str, Any]:
        """
        Make GET request.
        
        Raises:
            NetworkError: Connection failure
            TimeoutError: Request timeout
            HTTPStatusError: Non-2xx HTTP status
            JSONParseError: JSON parsing failure
        """
        url = urljoin(self.base_url, path)
        self._log_request("GET", url, **kwargs)
        
        for attempt in range(1, self.retry_times + 1):
            try:
                response = self._client.get(path, **kwargs)
                return self._process_response(response)
            except httpx.ConnectTimeout as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(
                        f"Connection timeout: server may be unreachable",
                    ) from e
            except httpx.TimeoutException as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise TimeoutError(
                        f"Request timeout after {self.retry_times} attempts",
                    ) from e
            except (httpx.ConnectError, httpx.NetworkError) as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(
                        str(e),
                    ) from e
            except httpx.HTTPError as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(
                        f"HTTP error: {str(e)}",
                    ) from e
    
    def post(self, path: str, json: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """
        Make POST request.
        
        Raises:
            NetworkError: Connection failure
            TimeoutError: Request timeout
            HTTPStatusError: Non-2xx HTTP status
            JSONParseError: JSON parsing failure
        """
        url = urljoin(self.base_url, path)
        self._log_request("POST", url, json=json, **kwargs)
        
        for attempt in range(1, self.retry_times + 1):
            try:
                response = self._client.post(path, json=json, **kwargs)
                return self._process_response(response)
            except httpx.ConnectTimeout as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(
                        f"Connection timeout: server may be unreachable",
                    ) from e
            except httpx.TimeoutException as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise TimeoutError(
                        f"Request timeout after {self.retry_times} attempts",
                    ) from e
            except (httpx.ConnectError, httpx.NetworkError) as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(
                        str(e),
                    ) from e
            except httpx.HTTPError as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(
                        f"HTTP error: {str(e)}",
                    ) from e
    
    def stream(self, method: str, path: str, json: Optional[Dict[str, Any]] = None, **kwargs):
        """
        Make streaming request and return context manager for SSE processing.
        
        Used for SSE (Server-Sent Events) responses.
        Returns a context manager that yields httpx.Response.
        
        Usage:
            with client.stream("POST", "/simulate/stream", json=payload) as response:
                for chunk in response.iter_lines():
                    ...
        
        Raises:
            NetworkError: Connection failure
            TimeoutError: Request timeout
            HTTPStatusError: Non-2xx HTTP status
        """
        url = urljoin(self.base_url, path)
        self._log_request(method, url, json=json, **kwargs)
        
        try:
            if method.upper() == "POST":
                # Return the context manager directly; httpx.stream() is a context manager
                ctx_mgr = self._client.stream(method, path, json=json, **kwargs)
            else:
                ctx_mgr = self._client.stream(method, path, **kwargs)
            
            # Wrap the context manager to check status code on entry
            return _StreamContextWrapper(ctx_mgr)
        except httpx.ConnectTimeout as e:
            raise NetworkError(
                f"Connection timeout: server may be unreachable",
            ) from e
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Stream request timeout",
            ) from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise NetworkError(str(e)) from e
        except HTTPStatusError:
            raise
        except httpx.HTTPError as e:
            raise NetworkError(f"HTTP error: {str(e)}") from e
    
    def _process_response(self, response: httpx.Response) -> Dict[str, Any]:
        """
        Process HTTP response.
        
        Handles:
        - Non-2xx status codes -> HTTPStatusError
        - JSON parse errors -> JSONParseError
        
        Returns:
            Parsed JSON response
        """
        # Check status code
        if response.status_code >= 400:
            response_text = response.text
            raise HTTPStatusError(
                f"HTTP {response.status_code}: {response_text[:100]}",
                status_code=response.status_code,
                response_text=response_text,
            )
        
        # Parse JSON
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as e:
            response_text = response.text
            raise JSONParseError(
                f"Failed to parse JSON response: {str(e)}",
                response_text=response_text,
            ) from e


# ============================================================================
# Async Version
# ============================================================================


class AsyncAPIClient:
    """
    Async HTTP Client wrapper around httpx.AsyncClient with unified error handling.
    
    Features:
    - Configurable base_url, timeout, retry strategy
    - Unified error handling for network, timeout, HTTP status, JSON parse errors
    - Support for streaming responses (SSE)
    - Sensitive header masking in logs
    """
    
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
        retry_times: int = 1,
    ):
        """
        Initialize async API client.
        
        Args:
            base_url: Base URL for API server
            timeout: Request timeout in seconds
            retry_times: Number of retries on network errors
        """
        self.base_url = base_url
        self.timeout = timeout
        self.retry_times = retry_times
        
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def close(self):
        """Close the underlying httpx client."""
        if self._client:
            await self._client.aclose()
    
    def _log_request(self, method: str, url: str, **kwargs):
        """Log request details (without sensitive headers)."""
        headers = kwargs.get("headers", {})
        safe_headers = {k: "***" for k in headers if k.lower() in ["authorization", "x-api-key"]}
        safe_headers.update({k: v for k, v in headers.items() if k.lower() not in ["authorization", "x-api-key"]})
        logger.debug(f"{method} {url} | headers: {safe_headers}")
    
    def _handle_error(self, error: Exception, attempt: int) -> None:
        """Handle different error types and log them."""
        logger.error(f"Request failed (attempt {attempt}): {type(error).__name__}: {str(error)}")
    
    async def get(self, path: str, **kwargs) -> Dict[str, Any]:
        """Make async GET request."""
        url = urljoin(self.base_url, path)
        self._log_request("GET", url, **kwargs)
        
        for attempt in range(1, self.retry_times + 1):
            try:
                response = await self._client.get(path, **kwargs)
                return self._process_response(response)
            except httpx.TimeoutException as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise TimeoutError(f"Request timeout after {self.retry_times} attempts") from e
            except (httpx.ConnectError, httpx.NetworkError) as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(str(e)) from e
            except httpx.HTTPError as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(f"HTTP error: {str(e)}") from e
    
    async def post(self, path: str, json: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Make async POST request."""
        url = urljoin(self.base_url, path)
        self._log_request("POST", url, json=json, **kwargs)
        
        for attempt in range(1, self.retry_times + 1):
            try:
                response = await self._client.post(path, json=json, **kwargs)
                return self._process_response(response)
            except httpx.TimeoutException as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise TimeoutError(f"Request timeout after {self.retry_times} attempts") from e
            except (httpx.ConnectError, httpx.NetworkError) as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(str(e)) from e
            except httpx.HTTPError as e:
                self._handle_error(e, attempt)
                if attempt >= self.retry_times:
                    raise NetworkError(f"HTTP error: {str(e)}") from e
    
    async def stream(
        self, method: str, path: str, json: Optional[Dict[str, Any]] = None, **kwargs
    ) -> httpx.Response:
        """Make async streaming request for SSE."""
        url = urljoin(self.base_url, path)
        self._log_request(method, url, json=json, **kwargs)
        
        try:
            if method.upper() == "POST":
                response = self._client.stream(method, path, json=json, **kwargs)
            else:
                response = self._client.stream(method, path, **kwargs)
            
            # Check status code
            if response.status_code >= 400:
                response_text = await response.aread().decode()
                raise HTTPStatusError(
                    f"HTTP {response.status_code}: {response_text[:100]}",
                    status_code=response.status_code,
                    response_text=response_text,
                )
            
            return response
        except httpx.TimeoutException as e:
            raise TimeoutError("Stream request timeout") from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise NetworkError(str(e)) from e
        except HTTPStatusError:
            raise
        except httpx.HTTPError as e:
            raise NetworkError(f"HTTP error: {str(e)}") from e
    
    def _process_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Process HTTP response."""
        if response.status_code >= 400:
            response_text = response.text
            raise HTTPStatusError(
                f"HTTP {response.status_code}: {response_text[:100]}",
                status_code=response.status_code,
                response_text=response_text,
            )
        
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as e:
            response_text = response.text
            raise JSONParseError(
                f"Failed to parse JSON response: {str(e)}",
                response_text=response_text,
            ) from e
