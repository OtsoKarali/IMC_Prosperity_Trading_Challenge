from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List
import numpy as np

class Trader:
    def __init__(self):
        self.price_history = {}
        self.rsi_window = 10
        self.sma_window = 20  # Reduced window for faster responsiveness
        self.position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50
        }
        self.zscore_threshold = 1.5
        self.exit_threshold = 0.3
        self.min_spread = 2

    def update_price_history(self, product: str, mid_price: float):
        if product not in self.price_history:
            self.price_history[product] = []
        self.price_history[product].append(mid_price)
        if len(self.price_history[product]) > self.sma_window:
            self.price_history[product].pop(0)

    def calculate_sma(self, prices: List[float]) -> float:
        if len(prices) < self.sma_window:
            return 0.0
        return np.mean(prices[-self.sma_window:])

    def calculate_rsi(self, prices: List[float]) -> float:
        if len(prices) < self.rsi_window + 1:
            return 50.0
        deltas = np.diff(prices[-(self.rsi_window+1):])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_zscore(self, prices: List[float], current_price: float) -> float:
        if len(prices) < self.sma_window:
            return 0.0
        mean = np.mean(prices)
        std = np.std(prices)
        return 0.0 if std == 0 else (current_price - mean) / std

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        traderData = ""

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []

            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                spread = best_ask - best_bid
                if spread < self.min_spread:
                    result[product] = orders
                    continue

                mid_price = (best_bid + best_ask) / 2

                self.update_price_history(product, mid_price)
                prices = self.price_history[product]
                zscore = self.calculate_zscore(prices, mid_price)

                position = state.position.get(product, 0)
                limit = self.position_limits.get(product, 50)
                remaining_buy = limit - position
                remaining_sell = limit + position

                # Buy if z-score indicates oversold
                if zscore <= -self.zscore_threshold and remaining_buy > 0:
                    quote_price = best_ask - 1 if (best_ask - 1) > best_bid else best_ask
                    orders.append(Order(product, quote_price, min(10, remaining_buy)))

                # Sell if z-score indicates overbought
                elif zscore >= self.zscore_threshold and remaining_sell > 0:
                    quote_price = best_bid + 1 if (best_bid + 1) < best_ask else best_bid
                    orders.append(Order(product, quote_price, -min(10, remaining_sell)))

                # Gradual exit when close to mean
                elif position > 0 and zscore > -self.exit_threshold:
                    quote_price = best_bid
                    orders.append(Order(product, quote_price, -min(10, position)))
                elif position < 0 and zscore < self.exit_threshold:
                    quote_price = best_ask
                    orders.append(Order(product, quote_price, -max(-10, position)))

            result[product] = orders

        return result, conversions, traderData
