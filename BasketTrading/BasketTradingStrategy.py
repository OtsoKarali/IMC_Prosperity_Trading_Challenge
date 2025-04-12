from datamodel import Order, OrderDepth, TradingState
from BasketTrading.Strategy import Strategy
from typing import Dict, List

class PicnicBasketArbStrategy(Strategy):
    def __init__(self):
        self.z_entry = 0.35
        self.z_exit = 0.2
        self.mean = 50  # set based on what we find in Exploratory Data Analysis
        self.std = 85   # set based on what we find in Exploratory Data Analysis
        self.last_z = 0
        self.in_position = False

    def act(self, state: TradingState) -> Dict[str, List[Order]]:
        # Reset orders
        self.orders = {}
        self.position = state.position
        
        required = ["CROISSANTS", "JAMS", "DJEMBES", "PICNIC_BASKET1"]
        if not all(p in state.order_depths for p in required):
            return self.orders

        croissant = self.get_mid_price(state, "CROISSANTS")
        jam = self.get_mid_price(state, "JAMS")
        djembe = self.get_mid_price(state, "DJEMBES")
        basket = self.get_mid_price(state, "PICNIC_BASKET1")

        fair_value = 6 * croissant + 3 * jam + 1 * djembe
        spread = basket - fair_value
        z = (spread - self.mean) / self.std
        self.last_z = z

        # Entry/Exit logic
        if not self.in_position:
            if z > self.z_entry:
                self.short_basket_long_components(state)
                self.in_position = True
            elif z < -self.z_entry:
                self.long_basket_short_components(state)
                self.in_position = True
        else:
            if abs(z) < self.z_exit:
                self.exit_all(state)
                self.in_position = False

    def get_mid_price(self, state: TradingState, symbol: str) -> float:
        depth = state.order_depths[symbol]
        if not depth.buy_orders or not depth.sell_orders:
            return 0
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        return (best_bid + best_ask) / 2

    def short_basket_long_components(self, state: TradingState):
        self.sell("PICNIC_BASKET1", 1)
        self.buy("CROISSANTS", 6)
        self.buy("JAMS", 3)
        self.buy("DJEMBES", 1)

    def long_basket_short_components(self, state: TradingState):
        self.buy("PICNIC_BASKET1", 1)
        self.sell("CROISSANTS", 6)
        self.sell("JAMS", 3)
        self.sell("DJEMBES", 1)

    def exit_all(self, state: TradingState):
        self.exit_position("PICNIC_BASKET1")
        self.exit_position("CROISSANTS")
        self.exit_position("JAMS")
        self.exit_position("DJEMBES")

    def exit_position(self, symbol: str):
        # Neutralize your current inventory
        pos = self.position.get(symbol, 0)
        if pos > 0:
            self.sell(symbol, pos)
        elif pos < 0:
            self.buy(symbol, -pos)
