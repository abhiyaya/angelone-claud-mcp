# server.py
from SmartApi import SmartConnect
import os
import pyotp
from logzero import logger
from dotenv import load_dotenv
from typing import Any, Dict
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("AngelOne")
load_dotenv()
api_key = os.environ.get('api_key')
username = os.environ.get('username')
pwd = os.environ.get('pwd')
token = os.environ.get('token')
correlation_id = os.environ.get('correlation_id')

def get_smart_api_session():
    """
    Establishes and returns an authenticated session with Angel One SmartAPI.
    This function handles the authentication process and creates a new SmartAPI session. 
    
    Returns:
        SmartConnect: An authenticated SmartAPI session instance
        
    Raises:
        Exception: If authentication fails or if there's an error in the process
    """
    smartApi = SmartConnect(api_key)
    try:
        totp = pyotp.TOTP(token).now()
        data = smartApi.generateSession(username, pwd, totp)
        if data['status'] == False:
            logger.error(data)
            raise Exception("Failed to authenticate with SmartAPI")
        return smartApi
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise e
    

@mcp.tool()
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
        smartApi = get_smart_api_session()
        allholding = smartApi.holding()
        return allholding
    except Exception as e:
        logger.exception(f"Failed to get portfolio: {e}")
        raise e

@mcp.tool()
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
        smartApi = get_smart_api_session()
        queryParams={
        "exchange": "NSE",
        "symboltoken": symboltoken,
        "interval": interval,
        "fromdate": start_time, 
        "todate": end_time
        }
        response = smartApi.getCandleData(queryParams)
        return response
    except Exception as e:
        logger.exception(f"Historic Api failed: {e}")
        return None

@mcp.tool()
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
            
    Returns None if the order placement fails.
    """
    try:
        orderParams = {
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
        smartApi = get_smart_api_session()
        response = smartApi.placeOrderFullResponse(orderParams)
        return response
    except Exception as e:
        logger.exception(f"Order placement failed: {e}")
        return None

@mcp.tool()
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
            
    Returns None if the cancellation fails.
    """
    try:
        smartApi = get_smart_api_session()
        response = smartApi.cancelOrder(order_id,variety)
        return response
    except Exception as e:
        logger.exception(f"Failed to cancel the order: {e}")
        return None

@mcp.tool()
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
            
    Returns None if the API call fails.
    """
    try:
        smartApi = get_smart_api_session()
        orderbook = smartApi.orderBook()
        return orderbook
    except Exception as e:
        logger.exception(f"Fetching order book failed: {e}")
        return None

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """
    Generates a personalized greeting message.
    
    Args:
        name (str): Name of the person to greet
        
    Returns:
        str: A personalized greeting message
    """
    return f"Namastae, {name}!"
