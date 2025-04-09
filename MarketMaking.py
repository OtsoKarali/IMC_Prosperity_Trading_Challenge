from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List

class Trader:
    def run(self, state: TradingState):
        result = {}
        conversions = 0
        traderData = ""

        # Position limits per product based on Round 1
        position_limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50
        }

        order_size = 5       # Base order size
        tick_offset = 2      # Distance from fair value

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []

            # Fair price estimation using mid-price if both sides exist
            if order_depth.buy_orders and order_depth.sell_orders:
                best_bid = max(order_depth.buy_orders.keys())
                best_ask = min(order_depth.sell_orders.keys())
                fair_price = (best_bid + best_ask) / 2
            elif order_depth.buy_orders:
                fair_price = max(order_depth.buy_orders.keys())
            elif order_depth.sell_orders:
                fair_price = min(order_depth.sell_orders.keys())
            else:
                continue  # No market data

            pos = state.position.get(product, 0)
            limit = position_limits.get(product, 20)  # Default fallback limit

            # Inventory adjustment: shift price by 0.1 ticks per unit of inventory
            inventory_bias = -0.1 * pos

            buy_price = round(fair_price - tick_offset + inventory_bias)
            sell_price = round(fair_price + tick_offset + inventory_bias)

            # Ensure we don't breach limits
            max_buy = min(order_size, limit - pos)
            max_sell = min(order_size, limit + pos)

            if max_buy > 0:
                orders.append(Order(product, buy_price, max_buy))
            if max_sell > 0:
                orders.append(Order(product, sell_price, -max_sell))

            result[product] = orders

        return result, conversions, traderData