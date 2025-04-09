from typing import Dict, List, Optional

class Order:
    def __init__(self, symbol: str, price: int, quantity: int):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __repr__(self):
        return f"Order({self.symbol}, {self.price}, {self.quantity})"

class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}

class TradingState:
    def __init__(self,
                 traderData: str,
                 timestamp: int,
                 listings: Dict,
                 order_depths: Dict[str, OrderDepth],
                 own_trades: Dict,
                 market_trades: Dict,
                 position: Dict[str, int],
                 observations: Optional[dict]):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations
