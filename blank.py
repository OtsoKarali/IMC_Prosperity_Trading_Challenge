from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List
import statistics

class Trader:
    def __init__(self):
        self.fair_values = {}
        self.price_history = {}
        self.history_size = 12
        self.last_prices = {}
        self.volatility = {}
        self.cost_basis = {}
        self.realized_pnl = {}
        self.metrics = {}
        self.order_size_default = 15

    def update_price_history(self, product: str, mid_price: float):
        if product not in self.price_history:
            self.price_history[product] = []
            self.last_prices[product] = mid_price
            self.volatility[product] = 0
            self.cost_basis[product] = 0.0
            self.realized_pnl[product] = 0.0

        price_change = abs(mid_price - self.last_prices[product])
        self.volatility[product] = 0.8 * self.volatility[product] + 0.2 * price_change
        self.last_prices[product] = mid_price

        self.price_history[product].append(mid_price)
        if len(self.price_history[product]) > self.history_size:
            self.price_history[product].pop(0)

    def get_fair_value(self, product: str, current_mid: float) -> float:
        if product not in self.price_history:
            return current_mid
        return statistics.median(self.price_history[product])

    def configure_from_metrics(self, external_metrics: Dict[str, Dict]):
        self.metrics = external_metrics

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        traderData = ""

        position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50
        }

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            metrics = self.metrics.get(product, {
                "mode": "adaptive",
                "spread_threshold": 0.5
            })

            pos = state.position.get(product, 0)
            limit = position_limits[product]
            mode = metrics.get("mode", "adaptive")
            spread_threshold = metrics.get("spread_threshold", 0.5)

            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders)
                best_ask = min(order_depth.sell_orders)
                spread = best_ask - best_bid
                mid_price = (best_bid + best_ask) / 2

                self.update_price_history(product, mid_price)
                fair_value = self.get_fair_value(product, mid_price)
                price_diff = fair_value - mid_price

                bid_volume = abs(order_depth.buy_orders.get(best_bid, 0))
                ask_volume = abs(order_depth.sell_orders.get(best_ask, 0))
                market_volume = max((bid_volume + ask_volume) // 2, 1)

                size = min(self.order_size_default * 2, int(market_volume * 0.6))
                size = max(1, size)

                max_buy = min(size, limit - pos)
                max_sell = min(size, limit + pos)

                if abs(price_diff) > spread_threshold:
                    if price_diff > 0 and pos < limit:
                        orders.append(Order(product, best_ask, max_buy))
                    elif price_diff < 0 and pos > -limit:
                        orders.append(Order(product, best_bid, -max_sell))
                else:
                    if pos < limit:
                        orders.append(Order(product, best_bid, max_buy))
                    if pos > -limit:
                        orders.append(Order(product, best_ask, -max_sell))

            result[product] = orders

        return result, conversions, traderData
