# server.py
from SmartApi import SmartConnect
import os
import pyotp
import time
import threading
from datetime import datetime, timedelta
from logzero import logger
from dotenv import load_dotenv
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP
from functools import wraps

# Create an MCP server
mcp = FastMCP("AngelOne")
load_dotenv()

class AuthManager:
    """
    Manages authentication and session lifecycle for Angel One SmartAPI
    """
    
    def __init__(self):
        self.api_key = os.environ.get('ANGEL_API_KEY')
        self.username = os.environ.get('ANGEL_USERNAME') 
        self.password = os.environ.get('ANGEL_PASSWORD')
        self.totp_secret = os.environ.get('ANGEL_TOTP_SECRET')
        self.correlation_id = os.environ.get('ANGEL_CORRELATION_ID')
        
        # Validate required credentials
        self._validate_credentials()
        
        # Session management
        self._smart_api: Optional[SmartConnect] = None
        self._session_token: Optional[str] = None
        self._session_expiry: Optional[datetime] = None
        self._auth_lock = threading.Lock()
        
        # Session refresh settings
        self.SESSION_REFRESH_BUFFER = 300  # Refresh 5 minutes before expiry
        self.MAX_RETRY_ATTEMPTS = 3
        self.RETRY_DELAY = 1  # seconds
    
    def _validate_credentials(self):
        """Validate that all required credentials are present"""
        required_vars = {
            'ANGEL_API_KEY': self.api_key,
            'ANGEL_USERNAME': self.username,
            'ANGEL_PASSWORD': self.password,
            'ANGEL_TOTP_SECRET': self.totp_secret
        }
        
        missing_vars = [var for var, value in required_vars.items() if not value]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    def _generate_totp(self) -> str:
        """Generate TOTP token"""
        try:
            return pyotp.TOTP(self.totp_secret).now()
        except Exception as e:
            logger.error(f"Failed to generate TOTP: {e}")
            raise
    
    def _create_new_session(self) -> SmartConnect:
        """Create a new authenticated session"""
        smart_api = SmartConnect(self.api_key)
        
        for attempt in range(self.MAX_RETRY_ATTEMPTS):
            try:
                totp = self._generate_totp()
                response = smart_api.generateSession(self.username, self.password, totp)
                
                if not response.get('status', False):
                    error_msg = response.get('message', 'Unknown authentication error')
                    logger.error(f"Authentication failed: {error_msg}")
                    
                    if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                        logger.info(f"Retrying authentication (attempt {attempt + 2}/{self.MAX_RETRY_ATTEMPTS})")
                        time.sleep(self.RETRY_DELAY)
                        continue
                    else:
                        raise Exception(f"Authentication failed after {self.MAX_RETRY_ATTEMPTS} attempts: {error_msg}")
                
                # Extract session info
                data = response.get('data', {})
                self._session_token = data.get('jwtToken')
                
                # Calculate session expiry
                self._session_expiry = datetime.now() + timedelta(hours=24)
                
                logger.info("Successfully authenticated with Angel One SmartAPI")
                return smart_api
                
            except Exception as e:
                if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                    logger.warning(f"Authentication attempt {attempt + 1} failed: {e}")
                    time.sleep(self.RETRY_DELAY)
                else:
                    logger.error(f"All authentication attempts failed: {e}")
                    raise
        
        raise Exception("Authentication failed after all retry attempts")
    
    def _is_session_valid(self) -> bool:
        """Check if current session is valid and not expired"""
        if not self._smart_api or not self._session_token or not self._session_expiry:
            return False
        
        # Check if session is close to expiry
        time_until_expiry = self._session_expiry - datetime.now()
        return time_until_expiry.total_seconds() > self.SESSION_REFRESH_BUFFER
    
    def get_authenticated_session(self) -> SmartConnect:
        """
        Get an authenticated SmartConnect session, creating or refreshing as needed
        Thread-safe implementation
        """
        with self._auth_lock:
            if self._is_session_valid():
                return self._smart_api
            
            logger.info("Creating new session or refreshing expired session")
            self._smart_api = self._create_new_session()
            return self._smart_api
    
    def invalidate_session(self):
        """Invalidate current session (useful for error recovery)"""
        with self._auth_lock:
            self._smart_api = None
            self._session_token = None
            self._session_expiry = None
            logger.info("Session invalidated")

# Global auth manager instance
auth_manager = AuthManager()

def handle_api_errors(func):
    """Decorator to handle common API errors and retry with fresh session if needed"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check for authentication-related errors
            if any(keyword in error_msg for keyword in ['token', 'unauthorized', 'expired', 'invalid session']):
                logger.warning(f"Authentication error detected: {e}")
                logger.info("Attempting to refresh session and retry")
                
                # Invalidate current session and retry once
                auth_manager.invalidate_session()
                try:
                    return func(*args, **kwargs)
                except Exception as retry_error:
                    logger.error(f"Retry after session refresh also failed: {retry_error}")
                    raise retry_error
            else:
                # Re-raise non-authentication errors
                raise e
    return wrapper

@mcp.tool()
@handle_api_errors
def get_proftfolio() -> Dict[str, Any]:
    """
    Retrieves the complete portfolio holdings for the authenticated user.
    
    Returns:
        Dict[str, Any]: A dictionary containing portfolio holdings data with the following structure:
            {
                'status': bool,
                'message': str,
                'data': List[Dict]  # List of holdings with details
            }
            
    Raises:
        Exception: If the API call fails or if there's an error in processing the response
    """
    try:
        smart_api = auth_manager.get_authenticated_session()
        allholding = smart_api.holding()
        
        if not allholding.get('status', False):
            raise Exception(f"API returned error: {allholding.get('message', 'Unknown error')}")
            
        return allholding
    except Exception as e:
        logger.exception(f"Failed to get portfolio: {e}")
        raise e

@mcp.tool()
@handle_api_errors
def get_candle_data(start_time: str, end_time: str, symboltoken: str = "3045", interval: str = "ONE_MINUTE"):
    """
    Retrieves historical candlestick data for a specified security.
    This function fetches OHLC (Open, High, Low, Close) data for a given time period
    and interval. The data can be used for technical analysis and charting.
    
    Args:
        start_time (str): Start date and time in "YYYY-MM-DD HH:MM" format
        end_time (str): End date and time in "YYYY-MM-DD HH:MM" format
        symboltoken (str, optional): The unique identifier for the security. Defaults to "3045"
        interval (str, optional): The time interval for the candlestick data. 
            Available options: "ONE_MINUTE", "FIVE_MINUTE", "FIFTEEN_MINUTE", 
            "THIRTY_MINUTE", "ONE_HOUR", "ONE_DAY". Defaults to "ONE_MINUTE"

    Returns:
        dict: A dictionary containing the candlestick data with the following structure:
            {
                'status': bool,
                'message': str,
                'data': List[Dict]  # List of candles with OHLC data
            }
            
    Returns None if the API call fails.
    """
    try:
        smart_api = auth_manager.get_authenticated_session()
        query_params = {
            "exchange": "NSE",
            "symboltoken": symboltoken,
            "interval": interval,
            "fromdate": start_time, 
            "todate": end_time
        }
        response = smart_api.getCandleData(query_params)
        
        if not response.get('status', False):
            raise Exception(f"API returned error: {response.get('message', 'Unknown error')}")
            
        return response
    except Exception as e:
        logger.exception(f"Historic API failed: {e}")
        raise e

@mcp.tool()
@handle_api_errors
def place_order(symbol: str, symboltoken: str, transactiontype: str, quantity: int, 
                ordertype: str = 'LIMIT', producttype: str = 'DELIVERY', price: float = 0):
    """
    Places a new order on the exchange through Angel One SmartAPI.
    
    Args:
        symbol (str): Trading symbol of the security (e.g., "RELIANCE", "INFY")
        symboltoken (str): Unique identifier for the security
        transactiontype (str): Type of transaction - "BUY" or "SELL"
        quantity (int): Number of shares/units to trade
        ordertype (str, optional): Type of order - "MARKET" or "LIMIT". Defaults to "LIMIT"
        producttype (str, optional): Product type - "INTRADAY", "DELIVERY", "MARGIN".
            Defaults to "DELIVERY"
        price (float, optional): Price at which to place the order. Required for LIMIT orders.
            Defaults to 0

    Returns:
        dict: Order placement response with the following structure:
            {
                'status': bool,
                'message': str,
                'data': Dict  # Order details including order ID
            }
            
    Raises:
        Exception: If the order placement fails.
    """
    try:
        # Validate required parameters
        if ordertype == 'LIMIT' and price <= 0:
            raise ValueError("Price must be specified for LIMIT orders")
        
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": symboltoken,
            "transactiontype": transactiontype,
            "exchange": "NSE",
            "ordertype": ordertype,
            "producttype": producttype,
            "duration": "DAY",
            "price": price,
            "squareoff": "0",
            "stoploss": "0",
            "quantity": quantity
        }
        
        smart_api = auth_manager.get_authenticated_session()
        response = smart_api.placeOrderFullResponse(order_params)
        
        if not response.get('status', False):
            raise Exception(f"Order placement failed: {response.get('message', 'Unknown error')}")
            
        return response
    except Exception as e:
        logger.exception(f"Order placement failed: {e}")
        raise e

@mcp.tool()
@handle_api_errors
def cancel_order(order_id: str, variety: str = "NORMAL"):
    """
    Cancels an existing order in the system.
    This function allows cancellation of pending orders using the order ID.
    
    Args:
        order_id (str): Unique identifier of the order to be cancelled
        variety (str, optional): Order variety - "NORMAL", "AMO", "STOPLOSS".
            Defaults to "NORMAL"

    Returns:
        dict: Cancellation response with the following structure:
            {
                'status': bool,
                'message': str,
                'data': Dict  # Cancellation details
            }
            
    Raises:
        Exception: If the cancellation fails.
    """
    try:
        smart_api = auth_manager.get_authenticated_session()
        response = smart_api.cancelOrder(order_id, variety)
        
        if not response.get('status', False):
            raise Exception(f"Order cancellation failed: {response.get('message', 'Unknown error')}")
            
        return response
    except Exception as e:
        logger.exception(f"Failed to cancel the order: {e}")
        raise e

@mcp.tool()
@handle_api_errors
def get_order_book():
    """
    Retrieves the complete order book for the authenticated user.
    
    This function fetches all orders (pending, executed, cancelled) for the user,
    providing a comprehensive view of their trading activity.
    
    Returns:
        dict: Order book data with the following structure:
            {
                'status': bool,
                'message': str,
                'data': List[Dict]  # List of orders with their details
            }
            
    Raises:
        Exception: If fetching the order book fails.
    """
    try:
        smart_api = auth_manager.get_authenticated_session()
        orderbook = smart_api.orderBook()
        
        if not orderbook.get('status', False):
            raise Exception(f"Failed to fetch order book: {orderbook.get('message', 'Unknown error')}")
            
        return orderbook
    except Exception as e:
        logger.exception(f"Fetching order book failed: {e}")
        raise e


# Health check endpoint
@mcp.tool()
def health_check() -> Dict[str, Any]:
    """
    Performs a health check of the authentication system
    
    Returns:
        dict: Health status information
    """
    try:
        is_valid = auth_manager._is_session_valid()
        return {
            "status": True,
            "message": "Service is healthy",
            "data": {
                "session_valid": is_valid,
                "session_expiry": auth_manager._session_expiry.isoformat() if auth_manager._session_expiry else None
            }
        }
    except Exception as e:
        return {
            "status": False,
            "message": f"Health check failed: {str(e)}",
            "data": {}
        }

if __name__ == "__main__":
    try:
        auth_manager.get_authenticated_session()
        logger.info("Server started successfully with valid authentication")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise e