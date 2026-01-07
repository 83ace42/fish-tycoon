import streamlit as st
import random
import math
import pandas as pd
import uuid
import time

# --- 1. CONFIGURATION & CONSTANTS ---
# (All game balance variables are defined here)
MAX_FISH_CAPACITY = 2000
STARTING_CASH = 1000
SHIP_COST = 300
SHIP_SCRAP = 150        # Value of a ship when the game ends
STORAGE_COST = 2.0      # Cost per unit to freeze fish per year
BASE_FISH_PRICE = 5.0
BASELINE_DEMAND = 300

# --- 2. SERVER STATE MANAGEMENT ---
# This function guarantees a single "Game State" exists for all players.
@st.cache_resource
def get_game_state():
    return {
        # Game Settings
        'phase': 'LOBBY',       # Phases: LOBBY -> AUCTION -> FISHING -> STORAGE -> RESULTS -> GAMEOVER
        'year': 1,
        'max_years': 5,         # Default, will be updated by Host
        
        # Ecology
        'fish_shore': 800.0,    # Starting population
        'fish_deep': 1200.0,    # Starting population
        'market_price': BASE_FISH_PRICE,
        'current_event': {"name": "Calm Seas", "desc": "Business as usual.", "shore_mod": 1.0, "deep_mod": 1.0},
        
        # Player Data
        'players': {},          # {uuid: {name, cash, ships, freezer, last_catch, ready}}
        
        # Synchronization
        'actions': {},          # Stores player moves for the current phase to enable simultaneous turns
        'logs': []              # Public event log
    }

state = get_game_state()

# --- 3. USER IDENTITY ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]
    
my_id = st.session_state.user_id

# --- 4. HELPER FUNCTIONS ---
def log(msg):
    # Add a message to the shared log
    state['logs'].insert(0, f"[Year {state['year']}] {msg}")

def trigger_event():
    # Randomly select an event for the new year
    events = [
        {"name": "Calm Seas", "desc": "Normal conditions.", "shore_mod": 1.0, "deep_mod": 1.0},
        {"name": "Stormy Coast", "desc": "Shore fishing is dangerous (-50% efficiency).", "shore_mod": 0.5, "deep_mod": 1.0},
        {"name": "Deep Freeze", "desc": "Deep waters are frozen (-50% efficiency).", "shore_mod": 1.0, "deep_mod": 0.5},
        {"name": "Algae Bloom", "desc": "Fish die-off in shallow waters.", "shore_mod": 0.8, "deep_mod": 1.0},
        {"name": "Whale Migration", "desc": "Whales protect the deep (-30% efficiency).", "shore_mod": 1.0, "deep_mod": 0.7},
    ]
    state['current_event'] = random.choice(events)

# --- 5. UI HEADER & SIDEBAR ---
st.set_page_config(page_title="Fish Tycoon Pro", page_icon="⚓")

# Custom CSS for better visibility
st.markdown("""
<style>
    .metric-box { border: 1px solid #ddd; padding: 10px; border-radius: 5px; background-color: #f9f9f9; text-align: center; }
    .phase-badge { background-color: #2e86c1; color: white; padding: 5px 10px; border-radius: 15px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# Sidebar: Intelligence Report (Requirement #4: Yearly Data Display)
with st.sidebar:
    st.header(f"📅 Year {state['year']} / {state['max_years']}")
    st.markdown(f"<span class='phase-badge'>{state['phase']}</span>", unsafe_allow_html=True)
    
    st.divider()
    
    st.subheader("🌍 Ecology Report")
    c1, c2 = st.columns(2)
    c1.metric("Shore Fish", f"{int(state['fish_shore'])}")
    c2.metric("Deep Fish", f"{int(state['fish_deep'])}")
    
    st.info(f"**Event:** {state['current_event']['name']}\n\n_{state['current_event']['desc']}_")
    
    st.subheader("💰 Market")
    st.metric("Fish Price", f"${state['market_price']:.2f}")

    # A refresh button is essential for multiplayer in Streamlit
    if st.button("🔄 Refresh Game State"):
        st.rerun()

# --- 6. MAIN GAME LOGIC ---

# 0. SAFETY CHECK
# If game is running but you aren't in the player list, show error
if state['phase'] != 'LOBBY' and my_id not in state['players']:
    st.error("⚠️ You are not in this game session.")
    if st.button("Emergency Reset (Restart Everything)"):
        st.cache_resource.clear()
        st.rerun()
    st.stop()


# PHASE 1: LOBBY
if state['phase'] == 'LOBBY':
    st.title("⚓ Fish Tycoon Lobby")
    
    # Registration
    if my_id not in state['players']:
        with st.form("join_form"):
            name = st.text_input("Captain Name")
            if st.form_submit_button("Join Fleet"):
                if name:
                    state['players'][my_id] = {
                        'name': name, 'cash': STARTING_CASH, 'ships': 3, 
                        'freezer': 0, 'last_catch': 0
                    }
                    st.rerun()
    else:
        st.success(f"Welcome aboard, Captain {state['players'][my_id]['name']}!")
        
        # Host Controls (Requirement #1: Ask number of years at the beginning)
        # We assume the first player to join is the "Host"
        players_list = list(state['players'].values())
        if list(state['players'].keys())[0] == my_id:
            st.divider()
            st.write("### 👑 Host Controls")
            years_setting = st.number_input("Game Duration (Years)", min_value=1, max_value=20, value=5)
            
            if st.button("Start Game"):
                state['max_years'] = years_setting
                state['phase'] = 'AUCTION'
                trigger_event()
                log("The game has begun!")
                st.rerun()
        else:
            st.info("Waiting for Host to configure and start the game...")

    st.write("### Registered Captains")
    for p in state['players'].values():
        st.write(f"👤 {p['name']}")


# PHASE 2: AUCTION (Requirement #3: Done at beginning of each year)
elif state['phase'] == 'AUCTION':
    st.title("🏗️ Shipyard & Auction")
    st.write("Purchase new vessels to expand your fleet before the fishing season begins.")
    
    p = state['players'][my_id]
    
    # Synchronization Wait Screen
    if my_id in state['actions']:
        st.info("✅ Order submitted. Waiting for other captains...")
        if len(state['actions']) == len(state['players']):
            # Process Orders
            for pid, qty in state['actions'].items():
                cost = qty * SHIP_COST
                state['players'][pid]['cash'] -= cost
                state['players'][pid]['ships'] += qty
                if qty > 0: log(f"{state['players'][pid]['name']} bought {qty} ships.")
            
            state['actions'] = {}
            state['phase'] = 'FISHING'
            st.rerun()
        else:
            if st.button("Check for others"): st.rerun()
            
    # Input Screen
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Your Cash", f"${int(p['cash'])}")
        c2.metric("Your Fleet", f"{p['ships']} Ships")
        c3.metric("Ship Price", f"${SHIP_COST}")
        
        max_buy = int(p['cash'] // SHIP_COST)
        
        with st.form("auction_form"):
            buy_qty = st.number_input(f"Ships to buy (Max {max_buy})", 0, max_buy, 0)
            if st.form_submit_button("Place Order"):
                state['actions'][my_id] = buy_qty
                st.rerun()


# PHASE 3: FISHING STRATEGY
elif state['phase'] == 'FISHING':
    st.title("🌊 Fishing Strategy")
    st.write("Allocate your fleet. Note the ecological data in the sidebar.")
    
    p = state['players'][my_id]
    
    # Synchronization
    if my_id in state['actions']:
        st.info("✅ Fleet deployed. Waiting for other captains...")
        if len(state['actions']) == len(state['players']):
            # --- CALCULATE CATCH (Core Logic) ---
            total_shore_ships = sum(m['shore'] for m in state['actions'].values())
            total_deep_ships = sum(m['deep'] for m in state['actions'].values())
            
            # Event Modifiers
            evt = state['current_event']
            
            # Catch Formulas
            # Base catch per ship adjusted by modifiers
            shore_factor = 0.04 * evt['shore_mod']
            deep_factor = 0.06 * evt['deep_mod']
            
            # Crowding: If > 5 ships total, efficiency drops
            shore_eff = 1.0 / (1 + max(0, total_shore_ships - 5) * 0.1)
            deep_eff = 1.0 / (1 + max(0, total_deep_ships - 5) * 0.1)
            
            total_shore_catch = min(state['fish_shore'], state['fish_shore'] * shore_factor * total_shore_ships * shore_eff)
            total_deep_catch = min(state['fish_deep'], state['fish_deep'] * deep_factor * total_deep_ships * deep_eff)
            
            # Distribute Catch
            total_mass_caught = 0
            for pid, alloc in state['actions'].items():
                p_obj = state['players'][pid]
                
                s_share = (alloc['shore'] / total_shore_ships * total_shore_catch) if total_shore_ships > 0 else 0
                d_share = (alloc['deep'] / total_deep_ships * total_deep_catch) if total_deep_ships > 0 else 0
                
                catch = s_share + d_share
                p_obj['last_catch'] = catch
                total_mass_caught += catch
                
                # Pay Op Costs (Fuel etc)
                cost = (alloc['shore']*40) + (alloc['deep']*60)
                p_obj['cash'] -= cost
            
            # Update Ecology
            state['fish_shore'] -= total_shore_catch
            state['fish_deep'] -= total_deep_catch
            
            # Update Market Price based on supply vs demand
            ratio = total_mass_caught / BASELINE_DEMAND
            # If catch is high, price drops. If low, price rises.
            new_price = max(1.0, BASE_FISH_PRICE * (1.5 / (0.5 + ratio)))
            state['market_price'] = round(new_price, 2)
            
            log(f"Fleet returned. Total catch: {int(total_mass_caught)}. New Price: ${state['market_price']}")
            
            state['actions'] = {}
            state['phase'] = 'STORAGE'
            st.rerun()
        else:
            if st.button("Check for others"): st.rerun()
            
    # Input Screen
    else:
        st.write(f"**Ships available:** {p['ships']}")
        with st.form("fishing_form"):
            c1, c2 = st.columns(2)
            with c1:
                shore = st.number_input("Shore Deployment ($40/ship)", 0, p['ships'], 0)
            with c2:
                remaining = p['ships'] - shore
                deep = st.number_input("Deep Deployment ($60/ship)", 0, remaining, 0)
            
            if st.form_submit_button("Launch Fleet"):
                state['actions'][my_id] = {'shore': shore, 'deep': deep}
                st.rerun()


# PHASE 4: STORAGE & SALES (Requirement #2: End of year, after catch)
elif state['phase'] == 'STORAGE':
    st.title("❄️ Processing & Sales")
    p = state['players'][my_id]
    
    # Calculate available inventory
    fresh = p['last_catch']
    frozen = p['freezer']
    total_inventory = fresh + frozen
    
    st.success(f"**Market Price Update:** ${state['market_price']:.2f}/unit")
    
    # Synchronization
    if my_id in state['actions']:
        st.info("✅ Sales confirmed. Wrapping up the year...")
        if len(state['actions']) == len(state['players']):
            # Process Sales for Everyone
            for pid, freeze_amt in state['actions'].items():
                p_obj = state['players'][pid]
                
                # Logic: We have Total. We keep 'freeze_amt'. We sell the rest.
                # We need to recalculate total_inventory here to be safe
                p_total = p_obj['last_catch'] + p_obj['freezer']
                sell_amt = p_total - freeze_amt
                
                revenue = sell_amt * state['market_price']
                storage_bill = freeze_amt * STORAGE_COST
                
                p_obj['cash'] += (revenue - storage_bill)
                p_obj['freezer'] = freeze_amt
            
            # End of Year Ecology Growth (Logistic Growth)
            # Cap growth so it doesn't explode infinitely
            state['fish_shore'] = min(MAX_FISH_CAPACITY * 0.5, state['fish_shore'] * 1.25)
            state['fish_deep'] = min(MAX_FISH_CAPACITY * 0.5, state['fish_deep'] * 1.30)
            
            state['actions'] = {}
            state['year'] += 1
            
            # Check Game Over condition
            if state['year'] > state['max_years']:
                state['phase'] = 'GAMEOVER'
            else:
                trigger_event()
                state['phase'] = 'AUCTION'
            
            st.rerun()
        else:
            if st.button("Check for others"): st.rerun()

    # Input Screen
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Fresh Catch", f"{int(fresh)}")
        c2.metric("In Freezer", f"{int(frozen)}")
        c3.metric("Total Stock", f"{int(total_inventory)}")
        
        st.write("---")
        with st.form("storage_form"):
            st.write("Decide how much to keep for next year. The rest is sold automatically.")
            to_freeze = st.number_input(f"Units to Freeze (${STORAGE_COST}/unit)", 0, int(total_inventory), 0)
            
            to_sell = total_inventory - to_freeze
            est_rev = to_sell * state['market_price']
            est_cost = to_freeze * STORAGE_COST
            
            st.caption(f"Selling: {int(to_sell)} | Est. Profit: ${est_rev - est_cost:.2f}")
            
            if st.form_submit_button("Confirm Transactions"):
                state['actions'][my_id] = to_freeze
                st.rerun()


# PHASE 5: GAMEOVER
elif state['phase'] == 'GAMEOVER':
    st.title("🏆 Game Over")
    
    # Calculate Scores (Cash + Assets)
    results = []
    for pid, p in state['players'].items():
        # Fish in freezer are valued at current market price
        asset_val = (p['ships'] * SHIP_SCRAP) + (p['freezer'] * state['market_price'])
        total_wealth = p['cash'] + asset_val
        results.append({
            "Captain": p['name'],
            "Cash": f"${p['cash']:.2f}",
            "Assets": f"${asset_val:.2f}",
            "Total Wealth": total_wealth
        })
    
    # Sort by total wealth
    df = pd.DataFrame(results).sort_values("Total Wealth", ascending=False)
    
    # Display Winner
    winner = df.iloc[0]
    st.balloons()
    st.success(f"🎉 Winner: {winner['Captain']} with ${winner['Total Wealth']:.2f}")
    
    st.table(df)
    
    if st.button("Start New Game"):
        st.cache_resource.clear()
        st.rerun()
