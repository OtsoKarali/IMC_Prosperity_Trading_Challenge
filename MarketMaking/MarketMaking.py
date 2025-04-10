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

    def update_cost_basis_and_pnl(self, product: str, price: float, qty: int, pos: int):
        if qty == 0:
            return

        if product not in self.cost_basis:
            self.cost_basis[product] = 0.0
            self.realized_pnl[product] = 0.0

        old_pos = pos - qty
        if old_pos == 0:
            self.cost_basis[product] = price
        elif (old_pos > 0 and qty > 0) or (old_pos < 0 and qty < 0):
            total_cost = self.cost_basis[product] * abs(old_pos) + price * abs(qty)
            self.cost_basis[product] = total_cost / abs(pos)
        else:
            realized = qty * (price - self.cost_basis[product])
            self.realized_pnl[product] += realized
            if pos == 0:
                self.cost_basis[product] = 0.0

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        traderData = ""

        position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50
        }

        order_size = 30
        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []

            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                spread = best_ask - best_bid
                mid_price = (best_bid + best_ask) / 2

                self.update_price_history(product, mid_price)
                fair_value = self.get_fair_value(product, mid_price)

                pos = state.position.get(product, 0)
                limit = position_limits[product]
                pos_bias = pos / limit
                price_distance = (fair_value - mid_price) / fair_value
                volatility = self.volatility.get(product, 1.0)

                buy_price = int(fair_value - 2)
                sell_price = int(fair_value + 2)

                bid_volume = abs(order_depth.buy_orders.get(best_bid, 0))
                ask_volume = abs(order_depth.sell_orders.get(best_ask, 0))
                market_volume = (bid_volume + ask_volume) / 2

                size_adjust = min(order_size, max(4, int(market_volume * 0.6)))
                conf_factor = min(1.5, abs(price_distance) * 300)
                position_factor = max(0.25, 1.0 - abs(pos_bias) * 0.75)
                adjusted_size = int(size_adjust * conf_factor * position_factor)
                adjusted_size = max(2, adjusted_size)

                max_buy = min(adjusted_size, limit - pos)
                max_sell = min(adjusted_size, limit + pos)

                if pos < limit:
                    orders.append(Order(product, buy_price, max_buy))
                if pos > -limit:
                    orders.append(Order(product, sell_price, -max_sell))

            result[product] = orders

        return result, conversions, traderData
