import pandas as pd
import numpy as np
import sys
import matplotlib.pyplot as plt
import os
from collections import defaultdict
from datamodel import OrderDepth, TradingState, Order
from BasketTrading.BasketTradingStrategy import PicnicBasketArbStrategy

def ensure_output_dirs():
    """Create output directories if they don't exist"""
    base_dir = "BasketTradingResults"
    subdirs = ["data", "plots", "logs"]
    
    for subdir in [base_dir] + [f"{base_dir}/{d}" for d in subdirs]:
        if not os.path.exists(subdir):
            os.makedirs(subdir)
    return base_dir

def build_order_depth(row):
    depth = OrderDepth()
    for i in range(1, 4):
        bid_price = row.get(f'bid_price_{i}')
        bid_volume = row.get(f'bid_volume_{i}')
        ask_price = row.get(f'ask_price_{i}')
        ask_volume = row.get(f'ask_volume_{i}')
        if pd.notna(bid_price) and pd.notna(bid_volume):
            depth.buy_orders[int(bid_price)] = int(bid_volume)
        if pd.notna(ask_price) and pd.notna(ask_volume):
            depth.sell_orders[int(ask_price)] = -int(ask_volume)
    return depth

def match_order(order: Order, order_depth: OrderDepth) -> tuple[int, int]:
    if order.quantity > 0:  # Buy order
        # For market orders (price=0), use the best ask price
        if order.price == 0 and order_depth.sell_orders:
            order_price = min(order_depth.sell_orders.keys())
        else:
            order_price = order.price
            
        available_prices = sorted([p for p in order_depth.sell_orders.keys() if p <= order_price])
        executed_qty = 0
        total_spent = 0
        remaining_qty = order.quantity

        for price in available_prices:
            available_at_price = -order_depth.sell_orders[price]
            executed_at_price = min(remaining_qty, available_at_price)
            if executed_at_price <= 0:
                continue
            executed_qty += executed_at_price
            total_spent += executed_at_price * price
            remaining_qty -= executed_at_price
            if remaining_qty <= 0:
                break

        return executed_qty, (total_spent / executed_qty if executed_qty > 0 else 0)

    else:  # Sell order
        # For market orders (price=0), use the best bid price
        if order.price == 0 and order_depth.buy_orders:
            order_price = max(order_depth.buy_orders.keys())
        else:
            order_price = order.price
            
        available_prices = sorted([p for p in order_depth.buy_orders.keys() if p >= order_price], reverse=True)
        executed_qty = 0
        total_received = 0
        remaining_qty = -order.quantity

        for price in available_prices:
            available_at_price = order_depth.buy_orders[price]
            executed_at_price = min(remaining_qty, available_at_price)
            if executed_at_price <= 0:
                continue
            executed_qty += executed_at_price
            total_received += executed_at_price * price
            remaining_qty -= executed_at_price
            if remaining_qty <= 0:
                break

        return -executed_qty, (total_received / executed_qty if executed_qty > 0 else 0)

def run_basket_simulation():
    # Setup
    base_dir = ensure_output_dirs()
    day = sys.argv[1] if len(sys.argv) > 1 else "0"
    price_file = f"PriceData/Round2/prices_round_2_day_{day}.csv"
    print(f"Simulating basket trading strategy with price data from: {price_file}")

    prices_df = pd.read_csv(price_file, sep=";")
    timestamps = sorted(prices_df["timestamp"].unique())

    position = defaultdict(int)
    last_prices = {}
    order_log = []
    equity_curve_log = []
    
    # PnL tracking
    realized_pnl = 0
    position_cost = defaultdict(float)  # Track average cost basis of positions
    
    # Initialize BasketTradingStrategy without modifying it
    strategy = PicnicBasketArbStrategy()

    log_file = f"{base_dir}/logs/basket_day_{day}.log"
    with open(log_file, 'w') as f:
        f.write(f"Starting basket trading simulation for day {day}\n")

        for t in timestamps:
            snapshot = prices_df[prices_df["timestamp"] == t]
            
            # Build order depths for all products
            order_depths = {}
            for _, row in snapshot.iterrows():
                product = row['product']
                order_depths[product] = build_order_depth(row)
                
                # Calculate mid prices for PnL evaluation
                if order_depths[product].buy_orders and order_depths[product].sell_orders:
                    best_bid = max(order_depths[product].buy_orders.keys())
                    best_ask = min(order_depths[product].sell_orders.keys())
                    last_prices[product] = (best_bid + best_ask) / 2
            
            # Create trading state for the strategy
            state = TradingState(
                traderData="",
                timestamp=t,
                listings={},
                order_depths=order_depths,
                own_trades={},
                market_trades={},
                position=dict(position),
                observations=None
            )
            
            # Execute strategy 
            strategy.position = dict(position)  # Make sure strategy has updated position info
            strategy.orders = {}  # Reset orders before each call
            strategy.act(state)
            orders = strategy.orders
            
            # Process orders and update positions
            for product, order_list in orders.items():
                for order in order_list:
                    executed_qty, executed_price = match_order(order, order_depths[product])
                    if executed_qty != 0:
                        # Calculate trade PnL for closing positions
                        old_position = position[product]
                        trade_pnl = 0
                        
                        # If reducing position or flipping direction
                        if (old_position > 0 and executed_qty < 0) or (old_position < 0 and executed_qty > 0):
                            closing_qty = min(abs(old_position), abs(executed_qty))
                            avg_cost = position_cost[product] / old_position if old_position != 0 else 0
                            
                            # Calculate PnL: (sell price - buy price) * qty for longs, reverse for shorts
                            if old_position > 0:  # Long position being reduced
                                trade_pnl = (executed_price - avg_cost) * closing_qty
                            else:  # Short position being reduced
                                trade_pnl = (avg_cost - executed_price) * closing_qty
                            
                            realized_pnl += trade_pnl
                        
                        # Update position and cost basis
                        if position[product] == 0:
                            # New position
                            position_cost[product] = executed_qty * executed_price
                        elif (position[product] > 0 and executed_qty > 0) or (position[product] < 0 and executed_qty < 0):
                            # Adding to existing position (same direction)
                            position_cost[product] += executed_qty * executed_price
                        else:
                            # Reducing or flipping position (handled in PnL calculation)
                            remaining_qty = position[product] + executed_qty
                            if remaining_qty * position[product] < 0:  # Direction flipped
                                # Reset cost basis for new position
                                remaining_abs_qty = abs(remaining_qty)
                                position_cost[product] = remaining_qty * executed_price
                            else:
                                # Adjust for partial position close
                                old_abs_qty = abs(position[product])
                                new_abs_qty = abs(remaining_qty)
                                position_cost[product] = position_cost[product] * (new_abs_qty / old_abs_qty)
                        
                        position[product] += executed_qty
                        order_log.append([t, product, executed_price, executed_qty, trade_pnl])

            # Mark-to-market unrealized PnL
            unrealized_pnl = 0
            for product, pos in position.items():
                if pos != 0 and product in last_prices:
                    avg_cost = position_cost[product] / pos
                    if pos > 0:  # Long position
                        unrealized_pnl += (last_prices[product] - avg_cost) * pos
                    else:  # Short position
                        unrealized_pnl += (avg_cost - last_prices[product]) * abs(pos)
            
            total_pnl = realized_pnl + unrealized_pnl
            
            equity_curve_log.append({
                "timestamp": t,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "total_pnl": total_pnl,
                "positions": dict(position)
            })

            if int(t) % 100 == 0:
                status = f"\nTime {t} | PnL: {total_pnl:.2f} (R: {realized_pnl:.2f}, U: {unrealized_pnl:.2f}) | Z-score: {strategy.last_z:.2f} | Position: {dict(position)}"
                print(status)
                f.write(status + "\n")

        # Save results
        trades_df = pd.DataFrame(order_log, columns=["timestamp", "product", "price", "quantity", "trade_pnl"])
        equity_df = pd.DataFrame(equity_curve_log)
        pos_df = pd.json_normalize(equity_df["positions"])
        equity_df = pd.concat([equity_df.drop(columns=["positions"]), pos_df], axis=1)

        trades_df.to_csv(f"{base_dir}/data/basket_trades_day_{day}.csv", index=False)
        equity_df.to_csv(f"{base_dir}/data/basket_equity_day_{day}.csv", index=False)

        # Plot
        plt.figure(figsize=(12, 8))
        
        # Plot PnL components
        plt.subplot(2, 1, 1)
        plt.plot(equity_df["timestamp"], equity_df["total_pnl"], label="Total PnL", color="blue")
        plt.plot(equity_df["timestamp"], equity_df["realized_pnl"], label="Realized PnL", color="green")
        plt.plot(equity_df["timestamp"], equity_df["unrealized_pnl"], label="Unrealized PnL", color="orange")
        plt.title(f"Basket Trading Strategy PnL (Day {day})")
        plt.xlabel("Timestamp")
        plt.ylabel("PnL")
        plt.grid(True)
        plt.legend()
        
        # Plot positions if they exist in columns
        plt.subplot(2, 1, 2)
        basket_products = ["PICNIC_BASKET1", "CROISSANTS", "JAMS", "DJEMBES"]
        for product in basket_products:
            if product in equity_df.columns:
                plt.plot(equity_df["timestamp"], equity_df[product], label=product)
        plt.title("Position Sizes")
        plt.xlabel("Timestamp")
        plt.ylabel("Quantity")
        plt.grid(True)
        plt.legend()
        
        plt.tight_layout()
        plt.savefig(f"{base_dir}/plots/basket_pnl_day_{day}.png")
        plt.close()

        print(f"\nFinal PnL: {equity_df['total_pnl'].iloc[-1]:.2f} (Realized: {realized_pnl:.2f}, Unrealized: {unrealized_pnl:.2f})")

if __name__ == "__main__":
    run_basket_simulation() 