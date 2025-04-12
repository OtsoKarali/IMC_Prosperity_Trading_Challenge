from datamodel import Order, TradingState
from typing import Dict, List

class Strategy:
    def __init__(self):
        self.position = {}
        self.orders = {}
        
    def act(self, state: TradingState) -> Dict[str, List[Order]]:
        """Implement this method in subclasses"""
        return self.orders
        
    def buy(self, symbol: str, quantity: int):
        if symbol not in self.orders:
            self.orders[symbol] = []
        self.orders[symbol].append(Order(symbol, 0, quantity))
        
    def sell(self, symbol: str, quantity: int):
        if symbol not in self.orders:
            self.orders[symbol] = []
        self.orders[symbol].append(Order(symbol, 0, -quantity)) 