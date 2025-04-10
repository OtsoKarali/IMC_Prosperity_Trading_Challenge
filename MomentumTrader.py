from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List
import numpy as np

class Trader:
    def __init__(self):
        self.mid_price_history = {}
        self.buffer_size = 5  # For momentum and volatility calc
        self.position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50
        }
        self.momentum_threshold = 1.0
        self.volatility_filter = False
        self.volatility_min = 0.2
        self.volatility_max = 3.0

    def update_price_buffer(self, product: str, mid_price: float):
        if product not in self.mid_price_history:
            self.mid_price_history[product] = []
        self.mid_price_history[product].append(mid_price)
        if len(self.mid_price_history[product]) > self.buffer_size:
            self.mid_price_history[product].pop(0)

    def calculate_momentum(self, prices: List[float]) -> float:
        if len(prices) < self.buffer_size:
            return 0.0
        return prices[-1] - prices[0]

    def calculate_volatility(self, prices: List[float]) -> float:
        if len(prices) < 2:
            return 0.0
        return np.std(prices)

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        traderData = ""

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []

            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                mid_price = (best_bid + best_ask) / 2
                self.update_price_buffer(product, mid_price)

                price_buffer = self.mid_price_history[product]
                momentum = self.calculate_momentum(price_buffer)
                volatility = self.calculate_volatility(price_buffer)

                bid_volume = sum(order_depth.buy_orders.values())
                ask_volume = -sum(order_depth.sell_orders.values())
                volume_ratio = ask_volume / (bid_volume + 1e-6)

                position = state.position.get(product, 0)
                limit = self.position_limits.get(product, 50)

                # Check volatility filter
                if self.volatility_filter:
                    if volatility < self.volatility_min or volatility > self.volatility_max:
                        result[product] = orders
                        continue

                # Aggressive Buy
                if momentum > self.momentum_threshold and volume_ratio > 1.1 and position < limit:
                    buy_qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
                    if buy_qty > 0:
                        orders.append(Order(product, best_ask, buy_qty))

                # Aggressive Sell
                elif momentum < -self.momentum_threshold and volume_ratio < 0.9 and position > -limit:
                    sell_qty = min(position + limit, order_depth.buy_orders[best_bid])
                    if sell_qty > 0:
                        orders.append(Order(product, best_bid, -sell_qty))

            result[product] = orders

        return result, conversions, traderData