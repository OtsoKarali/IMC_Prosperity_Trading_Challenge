from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List
from collections import deque

class Trader:
    def __init__(self):
        # Tracks how long we've been at max position for each product
        self.window = {}
        self.window_size = 10

        # Static or dynamic fair value placeholder per product
        self.true_value = {
            "RAINFOREST_RESIN": 10000,  # Can be overridden dynamically
            "KELP": None,
            "SQUID_INK": None,
        }

    def get_fair_value(self, product: str, order_depth: OrderDepth) -> int:
        # Use static true value if defined
        if self.true_value.get(product) is not None:
            return self.true_value[product]

        # Otherwise use midpoint of most popular bid/ask
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())
        if not buy_orders or not sell_orders:
            return 0

        popular_buy = max(buy_orders, key=lambda tup: tup[1])[0]
        popular_sell = min(sell_orders, key=lambda tup: tup[1])[0]
        return round((popular_buy + popular_sell) / 2)

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
            if product not in position_limits:
                continue

            if product not in self.window:
                self.window[product] = deque()

            orders = []
            position = state.position.get(product, 0)
            limit = position_limits[product]
            to_buy = limit - position
            to_sell = limit + position

            true_value = self.get_fair_value(product, order_depth)
            buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
            sell_orders = sorted(order_depth.sell_orders.items())

            # Update our position pressure window
            self.window[product].append(abs(position) == limit)
            if len(self.window[product]) > self.window_size:
                self.window[product].popleft()

            # Rename soft/hard liquidation for less traceability
            emergency_rebalance = len(self.window[product]) == self.window_size and all(self.window[product])
            risk_off_rebalance = (
                len(self.window[product]) == self.window_size
                and sum(self.window[product]) >= self.window_size / 2
                and self.window[product][-1]
            )

            # Adjust prices when holding large positions
            max_buy_price = true_value - 1 if position > limit * 0.5 else true_value
            min_sell_price = true_value + 1 if position < -limit * 0.5 else true_value

            # Active buy against book
            for price, volume in sell_orders:
                if to_buy > 0 and price <= max_buy_price:
                    quantity = min(to_buy, -volume)
                    orders.append(Order(product, price, quantity))
                    to_buy -= quantity

            # Rebalance logic when stuck at limit
            if to_buy > 0 and emergency_rebalance:
                orders.append(Order(product, true_value, to_buy // 2))
                to_buy -= to_buy // 2
            if to_buy > 0 and risk_off_rebalance:
                orders.append(Order(product, true_value - 2, to_buy // 2))
                to_buy -= to_buy // 2
            if to_buy > 0 and buy_orders:
                popular_bid = max(buy_orders, key=lambda tup: tup[1])[0]
                bid_price = min(max_buy_price, popular_bid + 1)
                orders.append(Order(product, bid_price, to_buy))

            # Active sell against book
            for price, volume in buy_orders:
                if to_sell > 0 and price >= min_sell_price:
                    quantity = min(to_sell, volume)
                    orders.append(Order(product, price, -quantity))
                    to_sell -= quantity

            # Rebalance logic for selling
            if to_sell > 0 and emergency_rebalance:
                orders.append(Order(product, true_value, -to_sell // 2))
                to_sell -= to_sell // 2
            if to_sell > 0 and risk_off_rebalance:
                orders.append(Order(product, true_value + 2, -to_sell // 2))
                to_sell -= to_sell // 2
            if to_sell > 0 and sell_orders:
                popular_ask = min(sell_orders, key=lambda tup: tup[1])[0]
                ask_price = max(min_sell_price, popular_ask - 1)
                orders.append(Order(product, ask_price, -to_sell))

            result[product] = orders

        return result, conversions, traderData
