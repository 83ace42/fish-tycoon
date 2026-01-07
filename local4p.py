#fish_storage //market value of fish shouldnt change before the freezing and selling process??
import math
import random
import os
import time

# --- RICH UI IMPORTS ---
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.text import Text
    from rich.prompt import IntPrompt, Confirm
    from rich.align import Align
    from rich import box
except ImportError:
    print("ERROR: Please install the 'rich' library first.")
    print("Run: pip install rich")
    exit()

# Initialize Rich Console
console = Console()

# --- 1. STABILIZED CONFIGURATION ---
MAX_FISH_CAPACITY = 2000
BASE_FISH_PRICE = 5.0
STARTING_CASH = 1000
SHIP_COST = 300
SHIP_SCRAP = 150
STORAGE_COST = 1.0  # Cost per unit to freeze fish

# BALANCING
BASELINE_DEMAND = 260 
CONTRACT_QTY_RANGE = (25, 60) 
CONTRACT_PRICE_MULT = 1.20   
CONTRACT_PENALTY_MULT = 2

def wait_for_enter():
    console.input("\n[italic]Press Enter to continue...[/italic]")

def get_valid_int(prompt_text, min_val=0, max_val=99999):
    while True:
        val = IntPrompt.ask(prompt_text, default=0)
        if min_val <= val <= max_val:
            return val
        console.print(f"[red] -> Please enter a number between {min_val} and {max_val}.[/red]")

def transition_to_player(player_name, phase_name="TURN START"):
    console.clear()
    console.print("\n" * 5)
    console.print(Panel(Align.center(f"[bold cyan]{phase_name}: {player_name}[/bold cyan]"), box=box.HEAVY))
    console.print(Align.center("\n Please come to the keyboard."))
    console.print(Align.center("Everyone else, look away!"))
    console.print("\n" * 2)
    console.input("[italic]Press Enter when ready...[/italic]")
    console.clear()

# --- EVENTS ---
class Event:
    def __init__(self, name, description, shore_mod=1.0, deep_mod=1.0, growth_mod=0.0):
        self.name = name
        self.description = description
        self.shore_mod = shore_mod
        self.deep_mod = deep_mod
        self.growth_mod = growth_mod

EVENTS = [
    Event("Calm Seas", "Perfect weather. Business as usual.", 1.0, 1.0, 0.0),
    Event("Coastal Storm", "High waves! Shore efficiency -50%.", 0.5, 1.0, 0.0),
    Event("Deep Freeze", "Icebergs! Deep efficiency -50%.", 1.0, 0.5, 0.0),
    Event("Algae Bloom", "Toxic algae. Reproduction -10%.", 1.0, 1.0, -0.10),
    Event("Upwelling", "Nutrient surge! Reproduction +15%.", 1.0, 1.0, 0.15),
    Event("Whale Migration", "Whales in deep water. Deep Eff -30%, Growth +5%.", 1.0, 0.7, 0.05),
]

class Ocean:
    def __init__(self):
        self.max_fish = MAX_FISH_CAPACITY
        self.fish_shore = (self.max_fish * 0.4) * 0.4 
        self.fish_deep = (self.max_fish * 0.6) * 0.4
        self.current_total_fish = self.fish_shore + self.fish_deep
        self.current_event = EVENTS[0]

    def trigger_event(self):
        weights = [40] + [12] * (len(EVENTS) - 1)
        self.current_event = random.choices(EVENTS, weights=weights, k=1)[0]

    def get_ship_market_price(self):
        density = self.current_total_fish / self.max_fish
        price = SHIP_SCRAP + (1000 - SHIP_SCRAP) * (density ** 2)
        return round(price, 2)

    def calculate_catch(self, players):
        total_shore_ships = sum(p.allocation['shore'] for p in players)
        total_deep_ships = sum(p.allocation['deep'] for p in players)

        # Base efficiency
        eff_shore = 0.035 * self.current_event.shore_mod
        eff_deep  = 0.055 * self.current_event.deep_mod
        
        # Crowding penalties
        shore_penalty = 1.0 / (1 + max(0, total_shore_ships - 10) * 0.05)
        deep_penalty = 1.0 / (1 + max(0, total_deep_ships - 10) * 0.05)

        potential_shore = min(self.fish_shore, self.fish_shore * eff_shore * total_shore_ships * shore_penalty)
        potential_deep = min(self.fish_deep, self.fish_deep * eff_deep * total_deep_ships * deep_penalty)

        catch_results = {p: {'shore': 0.0, 'deep': 0.0} for p in players}
        total_mass = 0.0

        if total_shore_ships > 0:
            for p in players:
                share = p.allocation['shore'] / total_shore_ships
                shore_share = potential_shore * share
                catch_results[p]['shore'] += shore_share
                total_mass += shore_share

        if total_deep_ships > 0:
            for p in players:
                share = p.allocation['deep'] / total_deep_ships
                deep_share = potential_deep * share
                catch_results[p]['deep'] += deep_share
                total_mass += deep_share

        self.fish_shore = max(0, self.fish_shore - potential_shore)
        self.fish_deep = max(0, self.fish_deep - potential_deep)
        self.current_total_fish = self.fish_shore + self.fish_deep

        return catch_results, total_mass


    def reproduce_fish(self):
        r_shore = 0.28 + self.current_event.growth_mod
        r_deep = 0.35 + self.current_event.growth_mod
        cap_shore = self.max_fish * 0.4
        cap_deep = self.max_fish * 0.6

        growth_shore = r_shore * self.fish_shore * (1 - (self.fish_shore / cap_shore))
        growth_deep = r_deep * self.fish_deep * (1 - (self.fish_deep / cap_deep))

        self.fish_shore = max(0, self.fish_shore + growth_shore)
        self.fish_deep = max(0, self.fish_deep + growth_deep)
        self.current_total_fish = self.fish_shore + self.fish_deep

# --- PLAYER ---
class Player:
    def __init__(self, name):
        self.name = name
        self.cash = float(STARTING_CASH)
        self.ships = 3
        self.pending_ships = 0
        self.allocation = {"harbor": 3, "shore": 0, "deep": 0} 
        self.last_profit = 0
        self.last_catch = 0 
        self.accepted_contract = False
        self.freezer = 0  # NEW: Cold Storage Inventory

    def print_private_status(self):
        # RICH UI: Player Dashboard
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", ratio=1)
        
        # Financials
        cash_color = "green" if self.cash >= 0 else "red"
        profit_color = "green" if self.last_profit >= 0 else "red"
        
        grid.add_row(
            f"[bold]Cash:[/bold] [{cash_color}]${int(self.cash)}[/{cash_color}]",
            f"[bold]Fleet:[/bold] [blue]{self.ships}[/blue] ships"
        )
        grid.add_row(
            f"[bold]Last Profit:[/bold] [{profit_color}]${int(self.last_profit)}[/{profit_color}]",
            f"[bold]Last Catch:[/bold] [cyan]{int(self.last_catch)}[/cyan] units"
        )
        grid.add_row(
            f"[bold]In Freezer:[/bold] [cyan]{int(self.freezer)}[/cyan] units",
            ""
        )
        if self.pending_ships > 0:
            grid.add_row(f"[dim]Pending Order: +{self.pending_ships} ships[/dim]", "")

        console.print(Panel(grid, title=f"[bold gold1]{self.name}'s Dashboard[/bold gold1]", border_style="gold1"))


    def order_ships(self):
        console.print("\n[bold]🚢 SHIPYARD[/bold]")
        if self.cash < SHIP_COST:
            console.print(f" [dim](Not enough cash to buy ships. Cost ${SHIP_COST})[/dim]")
            return
        
        max_afford = int(self.cash // SHIP_COST)
        console.print(f" Price: [yellow]${SHIP_COST}[/yellow]. You can afford [bold]{max_afford}[/bold].")
        qty = get_valid_int(f" Order quantity (0 to skip): ", 0, max_afford)
        
        if qty > 0:
            cost = qty * SHIP_COST
            self.cash -= cost
            self.pending_ships += qty
            console.print(f" [green]Ordered {qty} ships.[/green]")

    def allocate_ships(self):
        console.print("\n[bold]⚓ FLEET COMMAND[/bold]")
        console.print(f" Ships Available: [blue]{self.ships}[/blue]")
        console.print(" Costs: Harbor([green]$5[/green]), Shore([yellow]$45[/yellow]), Deep([red]$60[/red])")
        
        s = get_valid_int(f" Ships to [yellow]SHORE[/yellow]: ", 0, self.ships)
        remaining = self.ships - s
        if remaining > 0:
            d = get_valid_int(f" Ships to [red]DEEP[/red] (max {remaining}): ", 0, remaining)
        else:
            d = 0
        h = self.ships - s - d
        
        self.allocation = {"harbor": h, "shore": s, "deep": d}
        console.print(f" -> Allocation set: [green]{h} Harbor[/green], [yellow]{s} Shore[/yellow], [red]{d} Deep[/red].")
        time.sleep(1)

# --- GAME SYSTEMS ---

def print_public_report(year, ocean, last_price, contract_qty, contract_price):
    console.clear()
    
    # Header
    console.print(Panel(f"[bold white]PUBLIC REPORT: YEAR {year}[/bold white]", style="bold white on blue", expand=True))

    # Event Panel
    event_color = "red" if ocean.current_event.name != "Calm Seas" else "green"
    console.print(Panel(
        f"[bold]{ocean.current_event.name}[/bold]\n{ocean.current_event.description}",
        title="📢 WEATHER REPORT", border_style=event_color
    ))

    # Market & Ecology Table
    table = Table(title="Market & Ecology", box=box.SIMPLE)
    table.add_column("Indicator", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Fish Price", f"${round(last_price, 2)} / unit")
    table.add_row("Ship Resale Value", f"${ocean.get_ship_market_price()} / ship")
    table.add_row("Shore Population", f"{int(ocean.fish_shore)}")
    table.add_row("Deep Population", f"{int(ocean.fish_deep)}")
    
    console.print(table)
    
    # Contract Panel
    console.print(Panel(
        f"Deliver [bold green]{contract_qty}[/bold green] units @ [bold green]${contract_price}[/bold green]/unit\n"
        "[dim](Significant penalty applies if you accept and fail)[/dim]",
        title="📜 YEARLY CONTRACT OFFER", border_style="gold1"
    ))
    
    console.print("\n[italic]Discuss strategy now. When ready, we begin the turns.[/italic]")
    wait_for_enter()

def run_sealed_auction(players, market_price):
    # 1. Listing
    listings = []
    
    for p in players:
        if p.ships == 0: continue
        transition_to_player(p.name, "AUCTION")
        console.print(f"[bold]🏷️  AUCTION HOUSE[/bold] (Market Val: [green]${market_price}[/green])")
        p.print_private_status()
        
        sell = get_valid_int("Ships to list for sale (0 to skip): ", 0, p.ships)
        if sell > 0:
            min_p = get_valid_int(f"Minimum TOTAL price for lot of {sell} ships: ", 0, 999999)
            listings.append({'seller': p, 'qty': sell, 'min': min_p})
            console.print("[green]Listing recorded.[/green]")
        else:
            console.print("[dim]No listing.[/dim]")
        time.sleep(0.5)

    if not listings:
        console.clear()
        console.print(Panel("No ships were listed for sale this year.", title="Auction Results", border_style="dim"))
        wait_for_enter()
        return

    # 2. Bidding
    all_bids = {i: {} for i in range(len(listings))}

    for p in players:
        transition_to_player(p.name, "BIDDING")
        console.print(Panel(f"[bold]BIDDING PHASE: {p.name}[/bold]", style="on black"))
        console.print(f"Cash Available: [green]${int(p.cash)}[/green]")
        
        for i, lot in enumerate(listings):
            seller = lot['seller']
            if p == seller:
                console.print(f"\n[dim]Lot #{i+1}: Your listing of {lot['qty']} ships.[/dim]")
                continue
                
            console.print(f"\n[bold]Lot #{i+1}:[/bold] [cyan]{lot['qty']} ships[/cyan] from {seller.name}")
            
            # Logic Guard: Player cannot bid if cash is negative
            max_bid = max(0, int(p.cash))
            bid = get_valid_int(f"Your Sealed Bid (0 to pass, max {max_bid}): ", 0, max_bid)
            all_bids[i][p] = bid

    # 3. Resolution
    console.clear()
    console.print(Panel("[bold]🔨 AUCTION RESULTS[/bold]", expand=True))
    
    results_table = Table(box=box.MINIMAL_DOUBLE_HEAD)
    results_table.add_column("Lot")
    results_table.add_column("Seller")
    results_table.add_column("Qty")
    results_table.add_column("Result")
    
    for i, lot in enumerate(listings):
        seller = lot['seller']
        qty = lot['qty']
        min_price = lot['min']
        lot_bids = all_bids[i]
        
        winner = None
        highest_bid = 0
        
        for bidder, bid_val in lot_bids.items():
            if bid_val >= min_price and bid_val > highest_bid:
                highest_bid = bid_val
                winner = bidder
        
        if winner:
            result_str = f"[bold green]SOLD[/bold green] to {winner.name} (${highest_bid})"
            seller.ships -= qty
            seller.cash += highest_bid
            winner.ships += qty
            winner.cash -= highest_bid
        else:
            result_str = f"[red]UNSOLD[/red] (Reserve ${min_price})"
        
        results_table.add_row(f"#{i+1}", seller.name, str(qty), result_str)

    console.print(results_table)
    wait_for_enter()

def plot_fish_history(history):
    try:
        import matplotlib.pyplot as plt
        years = [h["year"] for h in history]
        shore = [h["shore"] for h in history]
        deep = [h["deep"] for h in history]
        total = [h["total"] for h in history]

        plt.figure()
        plt.plot(years, shore, label="Shore")
        plt.plot(years, deep, label="Deep")
        plt.plot(years, total, label="Total")
        plt.xlabel("Year")
        plt.ylabel("Fish Stock")
        plt.title("Fish Population Over Time")
        plt.legend()
        plt.show()
    except:
        console.print("[red]Matplotlib not found. Skipping graph.[/red]")

def main():
    console.clear()
    console.print(Panel("[bold cyan]ADVANCED FISHING SIM (RICH EDITION)[/bold cyan]", box=box.HEAVY))
    
    num_players = get_valid_int("How many players? ", 1, 10)
    players = []
    for i in range(num_players):
        name = console.input(f"Enter name for Player {i+1}: ")
        players.append(Player(name))
    
    ocean = Ocean()
    current_fish_price = BASE_FISH_PRICE
    years = get_valid_int("How many years to play for? ", 1, 20)
    fish_history = []
    yearly_records = []

    for year in range(1, years + 1):
        # 1. Update Environment
        ocean.trigger_event()
        
        # 1.5 Dynamic Contracts
        avg_ships = sum(p.ships for p in players) / len(players)
        base_qty = avg_ships * 18 
        contract_qty = int(random.uniform(base_qty * 0.7, base_qty * 1.1))
        contract_qty = max(30, contract_qty)
        contract_price = round(current_fish_price * CONTRACT_PRICE_MULT, 2)

        # 2. Public Report
        print_public_report(year, ocean, current_fish_price, contract_qty, contract_price)
        
        # 3. Auction
        ship_val = ocean.get_ship_market_price()
        run_sealed_auction(players, ship_val)
        
        # 4. Action Phase
        for p in players:
            transition_to_player(p.name, "ACTION PHASE")
            p.print_private_status()
            
            console.print(Panel(f"Deliver [bold]{contract_qty}[/bold] fish @ [green]${contract_price}[/green]", title="CONTRACT OFFER"))
            accept = Confirm.ask("Accept contract?")
            p.accepted_contract = accept

            p.order_ships()
            p.allocate_ships()
            console.print("\nTurn complete. Press Enter to hide screen...")
            input()

        # 5. Simulation
        console.clear()
        with console.status("[bold green]Simulating the year...[/bold green]", spinner="dots"):
            time.sleep(1.5) # Fake delay for suspense
            catches, total_mass = ocean.calculate_catch(players)
        
        # Calculate Market Price
        def compute_price(BASE_FISH_PRICE, BASELINE_DEMAND, total_mass):
            k = 0.005 
            m = max(1, total_mass)
            diff = BASELINE_DEMAND - m
            multiplier = math.exp(k * diff)
            price = BASE_FISH_PRICE * multiplier
            return max(1.0, min(15.0, round(price, 2))) 
        
        current_fish_price = compute_price(BASE_FISH_PRICE, BASELINE_DEMAND, total_mass)

        # 6. SALES & STORAGE PHASE (The New Mechanic)
        player_sales_data = {} # Store results for accounting

        for p in players:
            transition_to_player(p.name, "SALES & STORAGE")
            
            # Data prep
            caught_now = catches[p]['shore'] + catches[p]['deep']
            p.last_catch = caught_now # Update metric for dashboard
            
            old_freezer = p.freezer
            total_available = int(caught_now + old_freezer)
            
            # Display Status
            p.print_private_status()
            
            console.print(Panel(
                f"Catch this year: [cyan]{int(caught_now)}[/cyan]\n"
                f"From Freezer:    [cyan]{int(old_freezer)}[/cyan]\n"
                f"TOTAL AVAILABLE: [bold white]{total_available}[/bold white]",
                title="INVENTORY CHECK"
            ))
            
            console.print(Panel(
                f"Current Market Price: [green]${current_fish_price}[/green] / unit\n"
                f"Freezer Cost:         [red]${STORAGE_COST}[/red] / unit",
                title="MARKET & STORAGE COSTS", style="white on blue"
            ))

            if p.accepted_contract:
                console.print(f"⚠️  [bold yellow]CONTRACT ACTIVE:[/bold yellow] You promised to deliver {contract_qty} units.")
                console.print("   (Contract is filled from fish you DO NOT freeze)")

            # Input
            to_freeze = get_valid_int("How many units do you want to FREEZE for next year? ", 0, total_available)
            
            # Math
            to_sell = total_available - to_freeze
            storage_bill = to_freeze * STORAGE_COST
            
            # Store decisions for the accounting step
            player_sales_data[p] = {
                'to_freeze': to_freeze,
                'to_sell': to_sell,
                'storage_bill': storage_bill
            }
            
            console.print(f"\n[green]Confirmed.[/green] Selling {to_sell} units. Storing {to_freeze} units (Cost: ${int(storage_bill)}).")
            time.sleep(1.0)
            
            # We do NOT show leaderboard here. We continue to next player.

        # --- TRANSITION SCREEN TO CALL EVERYONE BACK ---
        console.clear()
        console.print("\n" * 5)
        console.print(Panel(Align.center("[bold white]ALL TURNS COMPLETE[/bold white]"), style="bold white on blue", box=box.HEAVY))
        console.print(Align.center("\nPlease call all players to the screen for the Year End Report."))
        console.print("\n" * 2)
        console.input("[italic]Press Enter to reveal results...[/italic]")
        # -----------------------------------------------

        # 7. Accounting
        for p in players:
            data = player_sales_data[p]
            
            to_sell = data['to_sell']
            to_freeze = data['to_freeze']
            storage_bill = data['storage_bill']
            
            # Execute Storage Logic
            p.freezer = to_freeze
            p.cash -= storage_bill

            revenue = 0
            contract_status = p.accepted_contract

            # Contract Logic
            if p.accepted_contract:
                delivered = min(contract_qty, to_sell)
                revenue += delivered * contract_price
                to_sell -= delivered # Remove delivered fish from market pile

                if delivered < contract_qty:
                    missing = contract_qty - delivered
                    penalty = missing * contract_price * CONTRACT_PENALTY_MULT
                    p.cash -= penalty
                    # Note: We print this later in the year-end summary usually, 
                    # but here we just calculate it.

            # Sell remaining fish at market price
            revenue += to_sell * current_fish_price

            # Operating Costs
            op_costs = (p.allocation['harbor']*5) + (p.allocation['shore']*45) + (p.allocation['deep']*60)
            
            # Profit Calculation
            # Revenue - (Operating Costs + Storage Bill)
            profit = revenue - (op_costs + storage_bill)
            
            p.cash += revenue - op_costs # Note: storage bill was already deducted above, but for profit calc we need net flow
            p.last_profit = profit

            # Ships Delivery
            if p.pending_ships > 0:
                p.ships += p.pending_ships
                p.pending_ships = 0
            
            # Record Data
            yearly_records.append({
                "Year": year,
                "Player": p.name,
                "Ships": p.ships,
                "Caught_Total": round(p.last_catch, 2),
                "Frozen": to_freeze,
                "Accepted_Contract": contract_status,
                "Profit": round(p.last_profit, 2),
                "Cash": round(p.cash, 2)
            })

            p.accepted_contract = False

        # Leaderboard
        console.clear()
        ranked = sorted(players, key=lambda p: p.last_profit, reverse=True)
        
        table_lb = Table(title=f"🏆 YEAR {year} RESULTS (By Profit)", box=box.SIMPLE)
        table_lb.add_column("Rank", justify="center")
        table_lb.add_column("Player")
        table_lb.add_column("Catch (New)", justify="right")
        table_lb.add_column("Stored", justify="right")
        table_lb.add_column("Profit", justify="right", style="bold green")
        table_lb.add_column("Total Cash", justify="right", style="bold cyan")
        
        for i, p in enumerate(ranked):
            t = catches[p]['shore'] + catches[p]['deep']
            table_lb.add_row(
                str(i+1), 
                p.name, 
                str(int(t)), 
                str(int(p.freezer)), 
                f"${int(p.last_profit)}", 
                f"${int(p.cash)}"
            )
        
        console.print(table_lb)

        # 8. Growth
        ocean.reproduce_fish()
        
        fish_history.append({
            "year": year,
            "shore": ocean.fish_shore,
            "deep": ocean.fish_deep,
            "total": ocean.current_total_fish
        })

        console.print(Panel(
            f"Total Catch: [bold]{int(total_mass)}[/bold]  |  Market Demand: {BASELINE_DEMAND}\n"
            f"Final Market Price: [green]${round(current_fish_price, 2)}[/green]",
            title="MARKET SUMMARY", border_style="dim"
        ))
        
        wait_for_enter()

    # Game Over
    console.clear()
    console.print(Panel("[bold gold1]=== GAME OVER ===[/bold gold1]", box=box.DOUBLE))
    final_ship_price = ocean.get_ship_market_price()
    
    # Calculate Wealth including Fish in Freezer (valued at 0 or current price? Let's say current price)
    # Actually standard accounting: Liquid Cash + Ship Assets. Fish spoil if game ends.
    players.sort(key=lambda p: p.cash + (p.ships * final_ship_price), reverse=True)
    
    final_table = Table(title="Final Standings")
    final_table.add_column("Rank", style="cyan")
    final_table.add_column("Player", style="white")
    final_table.add_column("Total Wealth", style="green")
    
    for i, p in enumerate(players):
        wealth = p.cash + (p.ships * final_ship_price)
        final_table.add_row(str(i+1), p.name, f"${int(wealth)}")
        
    console.print(final_table)

    # Excel Export
    try:
        import pandas as pd
        df = pd.DataFrame(yearly_records)
        with pd.ExcelWriter("fishing_game_report.xlsx", engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Data", index=False)
        console.print(f"\n[green]📊 Data saved to fishing_game_report.xlsx[/green]")
    except:
        console.print("[red]Could not save Excel file.[/red]")

    if Confirm.ask("Show graph?"):
        plot_fish_history(fish_history)

if __name__ == "__main__":
    main()
