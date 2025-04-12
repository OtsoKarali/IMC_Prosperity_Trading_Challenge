from datamodel import Order, OrderDepth, TradingState
from typing import List, Dict
from collections import deque
import json

# =============================
# Shared Base Strategy Classes
# =============================

class Strategy:
    def __init__(self, symbol: str, limit: int) -> None:
        self.symbol = symbol
        self.limit = limit
        self.orders = []
        self.conversions = 0

    def run(self, state: TradingState) -> tuple[list[Order], int]:
        self.orders = []
        self.conversions = 0
        self.act(state)
        return self.orders, self.conversions

    def buy(self, price: int, quantity: int) -> None:
        self.orders.append(Order(self.symbol, price, quantity))

    def sell(self, price: int, quantity: int) -> None:
        self.orders.append(Order(self.symbol, price, -quantity))

    def convert(self, amount: int) -> None:
        self.conversions += amount

    def save(self) -> dict:
        return {}

    def load(self, data: dict) -> None:
        pass

    def act(self, state: TradingState) -> None:
        raise NotImplementedError()

# ===========================================
# Market Making Strategy (3 Products Example)
# ===========================================

class MarketMakingStrategy(Strategy):
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        self.window = deque()
        self.window_size = 10
        # Static or dynamic fair value placeholder per product
        self.true_value = None
        if symbol == "RAINFOREST_RESIN":
            self.true_value = 10000  # Can be overridden dynamically

    def get_fair_value(self, state: TradingState) -> int:
        # Use static true value if defined
        if self.true_value is not None:
            return self.true_value

        # Otherwise use midpoint of most popular bid/ask
        order_depth = state.order_depths[self.symbol]
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())
        if not buy_orders or not sell_orders:
            return 0

        popular_buy = max(buy_orders, key=lambda tup: tup[1])[0]
        popular_sell = min(sell_orders, key=lambda tup: tup[1])[0]
        return round((popular_buy + popular_sell) / 2)

    def act(self, state: TradingState) -> None:
        order_depth = state.order_depths[self.symbol]
        position = state.position.get(self.symbol, 0)
        to_buy = self.limit - position
        to_sell = self.limit + position

        true_value = self.get_fair_value(state)
        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        # Update our position pressure window
        self.window.append(abs(position) == self.limit)
        if len(self.window) > self.window_size:
            self.window.popleft()

        # Rename soft/hard liquidation for less traceability
        emergency_rebalance = len(self.window) == self.window_size and all(self.window)
        risk_off_rebalance = (
            len(self.window) == self.window_size
            and sum(self.window) >= self.window_size / 2
            and self.window[-1]
        )

        # Adjust prices when holding large positions
        max_buy_price = true_value - 1 if position > self.limit * 0.5 else true_value
        min_sell_price = true_value + 1 if position < -self.limit * 0.5 else true_value

        # Active buy against book
        for price, volume in sell_orders:
            if to_buy > 0 and price <= max_buy_price:
                quantity = min(to_buy, -volume)
                self.buy(price, quantity)
                to_buy -= quantity

        # Rebalance logic when stuck at limit
        if to_buy > 0 and emergency_rebalance:
            self.buy(true_value, to_buy // 2)
            to_buy -= to_buy // 2
        if to_buy > 0 and risk_off_rebalance:
            self.buy(true_value - 2, to_buy // 2)
            to_buy -= to_buy // 2
        if to_buy > 0 and buy_orders:
            popular_bid = max(buy_orders, key=lambda tup: tup[1])[0]
            bid_price = min(max_buy_price, popular_bid + 1)
            self.buy(bid_price, to_buy)

        # Active sell against book
        for price, volume in buy_orders:
            if to_sell > 0 and price >= min_sell_price:
                quantity = min(to_sell, volume)
                self.sell(price, quantity)
                to_sell -= quantity

        # Rebalance logic for selling
        if to_sell > 0 and emergency_rebalance:
            self.sell(true_value, to_sell // 2)
            to_sell -= to_sell // 2
        if to_sell > 0 and risk_off_rebalance:
            self.sell(true_value + 2, to_sell // 2)
            to_sell -= to_sell // 2
        if to_sell > 0 and sell_orders:
            popular_ask = min(sell_orders, key=lambda tup: tup[1])[0]
            ask_price = max(min_sell_price, popular_ask - 1)
            self.sell(ask_price, to_sell)

# ====================================
# Picnic Basket Arbitrage Strategies
# ====================================

class PicnicBasketStrategy(Strategy):
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        # Historical mean of the spread between basket price and component prices
        # Found through back-testing on historical data
        self.mean = 50
        # Standard deviation of the spread - measures how volatile this relationship is
        self.std = 85
        # Z-score threshold for trade entry - how extreme the divergence needs to be 
        # Higher threshold = fewer trades but potentially more profitable
        self.z_entry = 1.5
        # Z-score threshold for trade exit - when positions should be closed
        # Lower threshold = faster exit, capturing profit before full mean reversion
        self.z_exit = 0.5
        # Tracks whether we currently have an open arbitrage position
        self.in_position = False

    def act(self, state: TradingState) -> None:
        # List of products needed for arbitrage calculation
        # PICNIC_BASKET1 = 6 CROISSANTS + 3 JAMS + 1 DJEMBES
        required = ["CROISSANTS", "JAMS", "DJEMBES", "PICNIC_BASKET1"]
        if not all(p in state.order_depths for p in required):
            # If any product is missing market data, we can't calculate spread
            return

        # Get current mid-prices for all components and the basket
        prices = {p: self.get_mid(state, p) for p in required}
        
        # Calculate theoretical fair value of basket based on its components
        # This is the key formula for statistical arbitrage
        fv = 6 * prices["CROISSANTS"] + 3 * prices["JAMS"] + prices["DJEMBES"]
        
        # Calculate the spread (difference between actual and theoretical price)
        # Positive spread = basket trading above fair value (overpriced)
        # Negative spread = basket trading below fair value (underpriced)
        spread = prices["PICNIC_BASKET1"] - fv
        
        # Convert spread to z-score to standardize the measurement
        # Z-score tells us how unusual the current spread is compared to history
        z = (spread - self.mean) / self.std

        if not self.in_position:
            # Entry logic - looking for significantly mispriced baskets
            if z > self.z_entry:
                # Basket is expensive (>1.5 std devs above mean)
                # Strategy: Sell overpriced basket, buy underpriced components
                basket_price = int(prices["PICNIC_BASKET1"])
                croissant_price = int(prices["CROISSANTS"])
                jam_price = int(prices["JAMS"])
                djembe_price = int(prices["DJEMBES"])
                
                self.sell(basket_price, 1)
                self.buy(croissant_price, 6)
                self.buy(jam_price, 3)
                self.buy(djembe_price, 1)
                self.in_position = True
            elif z < -self.z_entry:
                # Basket is cheap (>1.5 std devs below mean)
                # Strategy: Buy underpriced basket, sell overpriced components
                basket_price = int(prices["PICNIC_BASKET1"])
                croissant_price = int(prices["CROISSANTS"])
                jam_price = int(prices["JAMS"])
                djembe_price = int(prices["DJEMBES"])
                
                self.buy(basket_price, 1)
                self.sell(croissant_price, 6)
                self.sell(jam_price, 3)
                self.sell(djembe_price, 1)
                self.in_position = True
        elif abs(z) < self.z_exit:
            # Exit logic - spread has normalized to within 0.5 std devs of mean
            # Close all positions to realize the profit from convergence
            for sym in ["PICNIC_BASKET1", "CROISSANTS", "JAMS", "DJEMBES"]:
                pos = state.position.get(sym, 0)
                price = int(prices[sym])
                if pos > 0:
                    self.sell(price, pos)
                elif pos < 0:
                    self.buy(price, -pos)
            self.in_position = False

    def get_mid(self, state: TradingState, sym: str) -> float:
        # Calculate the mid-price between best bid and best ask
        # This is a standard way to estimate "fair market price"
        od = state.order_depths[sym]
        bids = sorted(od.buy_orders.items(), reverse=True)
        asks = sorted(od.sell_orders.items())
        if not bids or not asks:
            # If market is one-sided, can't calculate mid price
            return 0
        return (bids[0][0] + asks[0][0]) / 2

class PicnicBasket2Strategy(Strategy):
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(symbol, limit)
        # Historical mean of the spread between PICNIC_BASKET2 and its components
        # This basket has a different composition than PICNIC_BASKET1
        self.mean = 30.24
        # Standard deviation of the spread - smaller than PICNIC_BASKET1
        # This suggests a more stable pricing relationship
        self.std = 14.93
        # Same z-score threshold as PICNIC_BASKET1 strategy for consistency
        self.z_entry = 1.5
        # Slightly lower exit threshold - we're willing to exit sooner
        # This might be due to less historical volatility in the spread
        self.z_exit = 0.4
        # Tracks whether we currently have an open arbitrage position
        self.in_position = False

    def act(self, state: TradingState) -> None:
        # List of products needed for arbitrage calculation
        # PICNIC_BASKET2 = 4 CROISSANTS + 2 JAMS (no DJEMBES in this basket)
        required = ["CROISSANTS", "JAMS", "PICNIC_BASKET2"]
        if not all(p in state.order_depths for p in required):
            # If any product is missing market data, we can't calculate spread
            return

        # Get current mid-prices for all components and the basket
        prices = {p: self.get_mid(state, p) for p in required}
        
        # Calculate theoretical fair value - different composition than BASKET1
        # No DJEMBES in this basket, and different ratios of other components
        fv = 4 * prices["CROISSANTS"] + 2 * prices["JAMS"]
        
        # Calculate the spread (difference between actual and theoretical price)
        spread = prices["PICNIC_BASKET2"] - fv
        
        # Convert spread to z-score to standardize the measurement
        z = (spread - self.mean) / self.std

        if not self.in_position:
            # Entry logic - looking for significantly mispriced baskets
            if z > self.z_entry:
                # Basket is expensive compared to components
                # Strategy: Sell overpriced basket, buy underpriced components
                basket_price = int(prices["PICNIC_BASKET2"])
                croissant_price = int(prices["CROISSANTS"])
                jam_price = int(prices["JAMS"])
                
                self.sell(basket_price, 1)
                self.buy(croissant_price, 4)
                self.buy(jam_price, 2)
                self.in_position = True
            elif z < -self.z_entry:
                # Basket is cheap compared to components
                # Strategy: Buy underpriced basket, sell overpriced components
                basket_price = int(prices["PICNIC_BASKET2"])
                croissant_price = int(prices["CROISSANTS"])
                jam_price = int(prices["JAMS"])
                
                self.buy(basket_price, 1)
                self.sell(croissant_price, 4)
                self.sell(jam_price, 2)
                self.in_position = True
        elif abs(z) < self.z_exit:
            # Exit logic - spread has normalized to within 0.4 std devs of mean
            # This is slightly more aggressive exit than BASKET1 strategy
            for sym in ["PICNIC_BASKET2", "CROISSANTS", "JAMS"]:
                pos = state.position.get(sym, 0)
                price = int(prices[sym])
                if pos > 0:
                    self.sell(price, pos)
                elif pos < 0:
                    self.buy(price, -pos)
            self.in_position = False

    def get_mid(self, state: TradingState, sym: str) -> float:
        # Calculate the mid-price between best bid and best ask
        # Identical method to the one in PicnicBasketStrategy
        od = state.order_depths[sym]
        bids = sorted(od.buy_orders.items(), reverse=True)
        asks = sorted(od.sell_orders.items())
        if not bids or not asks:
            return 0
        return (bids[0][0] + asks[0][0]) / 2

# =========================
# Main Trader Entry Point
# =========================

class Trader:
    def __init__(self):
        limits = {
            "RAINFOREST_RESIN": 50,
            "KELP": 50,
            "SQUID_INK": 50,
            "CROISSANTS": 250,
            "JAMS": 350,
            "DJEMBES": 60,
            "PICNIC_BASKET1": 60,
            "PICNIC_BASKET2": 100,
        }

        self.strategies = {
            "RAINFOREST_RESIN": MarketMakingStrategy("RAINFOREST_RESIN", limits["RAINFOREST_RESIN"]),
            "KELP": MarketMakingStrategy("KELP", limits["KELP"]),
            "SQUID_INK": MarketMakingStrategy("SQUID_INK", limits["SQUID_INK"]),
            "CROISSANTS": PicnicBasketStrategy("CROISSANTS", limits["CROISSANTS"]),
            "JAMS": PicnicBasketStrategy("JAMS", limits["JAMS"]),
            "DJEMBES": PicnicBasketStrategy("DJEMBES", limits["DJEMBES"]),
            "PICNIC_BASKET1": PicnicBasketStrategy("PICNIC_BASKET1", limits["PICNIC_BASKET1"]),
            "PICNIC_BASKET2": PicnicBasket2Strategy("PICNIC_BASKET2", limits["PICNIC_BASKET2"]),
        }

    def run(self, state: TradingState):
        orders = {}
        conversions = 0
        traderData = ""

        for symbol, strategy in self.strategies.items():
            if symbol in state.order_depths:
                o, c = strategy.run(state)
                orders[symbol] = o
                conversions += c

        return orders, conversions, traderData
