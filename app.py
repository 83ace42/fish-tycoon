import streamlit as st
import random
import math
import pandas as pd
import uuid
import time

# --- CONFIGURATION ---
MAX_FISH_CAPACITY = 2000
BASE_FISH_PRICE = 5.0
STARTING_CASH = 1000
SHIP_COST = 300
SHIP_SCRAP = 150
STORAGE_COST = 1.0
BASELINE_DEMAND = 260
CONTRACT_PRICE_MULT = 1.20
CONTRACT_PENALTY_MULT = 2

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Fish Tycoon Multiplayer",
    page_icon="🐟",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom CSS for cleaner look
st.markdown("""
    <style>
    .stButton>button {width: 100%; border-radius: 8px; height: 3em; font-weight: bold;}
    .metric-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; border: 1px solid #ccc;}
    </style>
    """, unsafe_allow_html=True)

# --- GAME LOGIC CLASSES ---
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
        self.current_event = EVENTS[0]

    def trigger_event(self):
        weights = [40] + [12] * (len(EVENTS) - 1)
        self.current_event = random.choices(EVENTS, weights=weights, k=1)[0]

    def get_ship_market_price(self):
        total = self.fish_shore + self.fish_deep
        density = total / self.max_fish
        return round(SHIP_SCRAP + (1000 - SHIP_SCRAP) * (density ** 2), 2)

    def reproduce(self):
        r_shore = 0.28 + self.current_event.growth_mod
        r_deep = 0.35 + self.current_event.growth_mod
        
        g_shore = r_shore * self.fish_shore * (1 - (self.fish_shore / (self.max_fish * 0.4)))
        g_deep = r_deep * self.fish_deep * (1 - (self.fish_deep / (self.max_fish * 0.6)))
        
        self.fish_shore = max(0, self.fish_shore + g_shore)
        self.fish_deep = max(0, self.fish_deep + g_deep)

# --- SERVER STATE (The "Database") ---
@st.cache_resource
def get_server_state():
    return {
        'ocean': Ocean(),
        'players': {},     # {uuid: {data}}
        'year': 1,
        'max_years': 5,    # Default, changed in Lobby
        'phase': 'LOBBY',  # LOBBY, BRIEFING, SHIPYARD, FISHING, PROCESSING, SALES, RESULTS, GAMEOVER
        'market_price': BASE_FISH_PRICE,
        'contract': {},
        'buffer': {},      # Stores temporary moves from players
        'logs': []
    }

game = get_server_state()

# --- CLIENT STATE (The User) ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]

# --- HELPER FUNCTIONS ---
def format_currency(val):
    return f"${val:,.0f}"

def reset_year_logic():
    game['buffer'] = {}
    game['year'] += 1
    game['phase'] = 'BRIEFING'
    game['ocean'].trigger_event()
    
    # Generate Contract
    avg_ships = sum(p['ships'] for p in game['players'].values()) / len(game['players'])
    base_qty = avg_ships * 18
    qty = max(25, int(random.uniform(base_qty * 0.7, base_qty * 1.1)))
    price = round(game['market_price'] * CONTRACT_PRICE_MULT, 2)
    game['contract'] = {'qty': qty, 'price': price}

def process_fishing():
    # This runs between Fishing and Sales phases
    total_shore_ships = sum(m['shore'] for m in game['buffer'].values())
    total_deep_ships = sum(m['deep'] for m in game['buffer'].values())
    
    ocean = game['ocean']
    evt = ocean.current_event
    
    # Efficiency
    eff_shore = 0.035 * evt.shore_mod
    eff_deep = 0.055 * evt.deep_mod
    
    # Crowding
    shore_pen = 1.0 / (1 + max(0, total_shore_ships - 10) * 0.05)
    deep_pen = 1.0 / (1 + max(0, total_deep_ships - 10) * 0.05)
    
    pot_shore = min(ocean.fish_shore, ocean.fish_shore * eff_shore * total_shore_ships * shore_pen)
    pot_deep = min(ocean.fish_deep, ocean.fish_deep * eff_deep * total_deep_ships * deep_pen)
    
    total_catch_mass = 0
    
    # assign catch to players temp data
    for pid, move in game['buffer'].items():
        p = game['players'][pid]
        
        s_share = (move['shore']/total_shore_ships)*pot_shore if total_shore_ships > 0 else 0
        d_share = (move['deep']/total_deep_ships)*pot_deep if total_deep_ships > 0 else 0
        
        caught = s_share + d_share
        total_catch_mass += caught
        
        # Deduct Operation Costs immediately
        op_costs = (move['shore']*45) + (move['deep']*60) + (move['harbor']*5)
        p['cash'] -= op_costs
        
        # Store catch in player object for the Sales Phase
        p['current_catch'] = caught
        p['accepted_contract'] = move['contract']
    
    # Update Ecology
    ocean.fish_shore = max(0, ocean.fish_shore - pot_shore)
    ocean.fish_deep = max(0, ocean.fish_deep - pot_deep)
    
    # Update Market Price Dynamic
    k = 0.005
    diff = BASELINE_DEMAND - total_catch_mass
    mult = math.exp(k * diff)
    new_price = max(1.0, min(15.0, BASE_FISH_PRICE * mult))
    game['market_price'] = new_price # Price updates BEFORE sales
    
    # Reset buffer for Sales Phase
    game['buffer'] = {} 
    game['phase'] = 'SALES'

def process_sales():
    for pid, move in game['buffer'].items():
        p = game['players'][pid]
        
        to_freeze = move['freeze']
        to_sell = move['sell']
        
        # Storage Cost
        storage_bill = to_freeze * STORAGE_COST
        p['cash'] -= storage_bill
        p['freezer'] = to_freeze # Set new inventory
        
        revenue = 0
        penalty = 0
        
        # Contract Logic
        if p['accepted_contract']:
            req = game['contract']['qty']
            delivered = min(req, to_sell)
            revenue += delivered * game['contract']['price']
            to_sell -= delivered
            
            if delivered < req:
                penalty = (req - delivered) * game['contract']['price'] * CONTRACT_PENALTY_MULT
                p['cash'] -= penalty
                
        # Market Sales
        revenue += to_sell * game['market_price']
        p['cash'] += revenue
        
        # Stats
        p['last_profit'] = revenue - (storage_bill + penalty) # simplified profit view
        p['last_penalty'] = penalty
        
    ocean = game['ocean']
    ocean.reproduce()
    
    game['buffer'] = {}
    game['phase'] = 'RESULTS'

# ================= UI LOGIC =================

st.title("🐟 Fish Tycoon: Multiplayer")

# --- 1. LOBBY ---
if game['phase'] == 'LOBBY':
    st.subheader("Lobby")
    
    if not st.session_state.get('joined'):
        with st.form("join_form"):
            name = st.text_input("Enter Captain Name")
            submitted = st.form_submit_button("Join Game")
            if submitted and name:
                game['players'][st.session_state.user_id] = {
                    'name': name, 'cash': STARTING_CASH, 'ships': 3, 
                    'freezer': 0, 'last_profit': 0, 'current_catch': 0, 'accepted_contract': False
                }
                st.session_state.joined = True
                st.rerun()
    else:
        st.success(f"Joined as {game['players'][st.session_state.user_id]['name']}")
        
        # Admin Settings
        if len(game['players']) > 0:
            st.write("---")
            st.write("### Game Settings")
            # Only let the first player change settings to avoid chaos
            first_player_id = list(game['players'].keys())[0]
            if st.session_state.user_id == first_player_id:
                yrs = st.number_input("Game Duration (Years)", 1, 20, 5)
                if st.button("👑 START GAME"):
                    game['max_years'] = yrs
                    game['ocean'].trigger_event()
                    # Init contract
                    avg_ships = 3
                    qty = int(avg_ships * 18)
                    price = round(game['market_price'] * CONTRACT_PRICE_MULT, 2)
                    game['contract'] = {'qty': qty, 'price': price}
                    game['phase'] = 'BRIEFING'
                    st.rerun()
            else:
                st.info(f"Waiting for host to start ({game['max_years']} years)...")
        
        st.write("### Captains List")
        for pid, p in game['players'].items():
            st.write(f"⚓ {p['name']}")
            
        if st.button("Refresh Lobby"):
            st.rerun()

# --- 2. BRIEFING (Year Start) ---
elif game['phase'] == 'BRIEFING':
    st.header(f"📅 Year {game['year']} of {game['max_years']}")
    
    # Event & Ecology Data (Req #4)
    c1, c2 = st.columns(2)
    with c1:
        st.info(f"**Event:** {game['ocean'].current_event.name}\n\n{game['ocean'].current_event.description}")
    with c2:
        st.metric("Shore Population", int(game['ocean'].fish_shore))
        st.metric("Deep Population", int(game['ocean'].fish_deep))
    
    st.write("---")
    st.write("### Market Outlook")
    m1, m2 = st.columns(2)
    m1.metric("Current Fish Price", format_currency(game['market_price']))
    m2.metric("Ship Market Value", format_currency(game['ocean'].get_ship_market_price()))
    
    if st.button("Go to Shipyard"):
        game['phase'] = 'SHIPYARD'
        st.rerun()

# --- 3. SHIPYARD (Auction/Buy Phase - Req #3) ---
elif game['phase'] == 'SHIPYARD':
    my_id = st.session_state.user_id
    if my_id in game['buffer']:
        st.info("✅ Ship orders submitted. Waiting for others...")
        if len(game['buffer']) == len(game['players']):
            # Apply ship orders instantly
            for pid, qty in game['buffer'].items():
                cost = qty * SHIP_COST
                game['players'][pid]['cash'] -= cost
                game['players'][pid]['ships'] += qty
            
            game['buffer'] = {}
            game['phase'] = 'FISHING'
            st.rerun()
        else:
            if st.button("Refresh"): st.rerun()
            
    else:
        st.header("🏗️ The Shipyard")
        p = game['players'][my_id]
        st.metric("Your Cash", format_currency(p['cash']))
        
        st.write(f"New ships cost **{format_currency(SHIP_COST)}**.")
        max_buy = int(p['cash'] // SHIP_COST)
        
        with st.form("ship_form"):
            qty = st.number_input(f"How many ships to buy? (Max {max_buy})", 0, max_buy, 0)
            if st.form_submit_button("Confirm Orders"):
                game['buffer'][my_id] = qty
                st.rerun()

# --- 4. FISHING STRATEGY ---
elif game['phase'] == 'FISHING':
    my_id = st.session_state.user_id
    if my_id in game['buffer']:
        st.info("✅ Fleet deployed. Waiting for other captains...")
        if len(game['buffer']) == len(game['players']):
            # All deployed, calculate results
            if st.button("Start Simulation"):
                process_fishing() # This moves to SALES phase
                st.rerun()
        else:
            if st.button("Refresh"): st.rerun()
    else:
        st.header("⚓ Fleet Command")
        p = game['players'][my_id]
        
        # Contract Display
        contract = game['contract']
        st.warning(f"📜 **CONTRACT:** Deliver {contract['qty']} fish @ {format_currency(contract['price'])}")
        
        with st.form("fish_form"):
            st.write(f"You have **{p['ships']} ships** available.")
            
            c1, c2 = st.columns(2)
            with c1:
                shore = st.number_input("Ships to Shore ($45)", 0, p['ships'], 0)
            with c2:
                rem = p['ships'] - shore
                deep = st.number_input("Ships to Deep ($60)", 0, rem, 0)
            
            harbor = p['ships'] - shore - deep
            st.caption(f"Ships in Harbor ($5): {harbor}")
            
            accept = st.checkbox("Accept Contract? (Penalty applies if failed)")
            
            est_cost = (shore*45) + (deep*60) + (harbor*5)
            st.write(f"**Operational Cost:** {format_currency(est_cost)}")
            
            if st.form_submit_button("Deploy Fleet"):
                if est_cost > p['cash']:
                    st.error("Insufficient funds for fuel/crew!")
                else:
                    game['buffer'][my_id] = {
                        'shore': shore, 'deep': deep, 'harbor': harbor, 'contract': accept
                    }
                    st.rerun()

# --- 5. SALES & STORAGE (Req #2) ---
elif game['phase'] == 'SALES':
    my_id = st.session_state.user_id
    
    if my_id in game['buffer']:
        st.info("✅ Sales finalized. Waiting for market close...")
        if len(game['buffer']) == len(game['players']):
            if st.button("View Results"):
                process_sales()
                st.rerun()
        else:
            if st.button("Refresh"): st.rerun()
    else:
        st.header("❄️ Cold Storage & Sales")
        p = game['players'][my_id]
        
        # Calculate totals
        fresh_catch = p['current_catch']
        old_stock = p['freezer']
        total_avail = fresh_catch + old_stock
        
        st.success(f"**Market Price Update:** Fish is now trading at **{format_currency(game['market_price'])}**")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Fresh Catch", int(fresh_catch))
        c2.metric("Freezer Stock", int(old_stock))
        c3.metric("Total Available", int(total_avail))
        
        with st.form("sales_form"):
            st.write(f"Storage Cost: **{format_currency(STORAGE_COST)} / unit**")
            
            keep = st.number_input("How many units to FREEZE? (Rest will be sold)", 0, int(total_avail), 0)
            
            sell_amt = total_avail - keep
            est_rev = sell_amt * game['market_price']
            est_store_cost = keep * STORAGE_COST
            
            st.write(f"You will sell **{int(sell_amt)}** units.")
            st.caption(f"Est. Revenue: {format_currency(est_rev)} | Storage Bill: {format_currency(est_store_cost)}")
            
            if st.form_submit_button("Confirm Sales"):
                if est_store_cost > p['cash']:
                    st.error("Not enough cash to pay storage fees!")
                else:
                    game['buffer'][my_id] = {
                        'freeze': keep, 'sell': sell_amt
                    }
                    st.rerun()

# --- 6. RESULTS ---
elif game['phase'] == 'RESULTS':
    st.header(f"🏆 Year {game['year']} Results")
    
    data = []
    for pid, p in game['players'].items():
        data.append({
            'Player': p['name'],
            'Cash': format_currency(p['cash']),
            'Freezer': int(p['freezer']),
            'Ships': p['ships']
        })
    
    df = pd.DataFrame(data).sort_values(by="Cash", ascending=False)
    st.table(df)
    
    if game['year'] >= game['max_years']:
        if st.button("END GAME"):
            game['phase'] = 'GAMEOVER'
            st.rerun()
    else:
        if st.button("START NEXT YEAR"):
            reset_year_logic()
            st.rerun()

# --- 7. GAMEOVER ---
elif game['phase'] == 'GAMEOVER':
    st.balloons()
    st.title("GAME OVER")
    
    ship_val = game['ocean'].get_ship_market_price()
    st.write(f"Ship Liquidation Value: {format_currency(ship_val)}")
    
    final = []
    for pid, p in game['players'].items():
        wealth = p['cash'] + (p['ships'] * ship_val)
        final.append({
            'Player': p['name'],
            'Final Wealth': format_currency(wealth),
            'Cash': format_currency(p['cash']),
            'Fleet': p['ships']
        })
    
    st.table(pd.DataFrame(final).sort_values(by="Final Wealth", ascending=False))
    
    if st.button("Reset Server"):
        st.cache_resource.clear()
        st.rerun()
