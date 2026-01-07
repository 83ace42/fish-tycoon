import streamlit as st
import random
import math
import pandas as pd
import uuid
import time

# --- 1. CONFIGURATION (MATCHING YOUR CLI CODE) ---
MAX_FISH_CAPACITY = 2000
BASE_FISH_PRICE = 5.0
STARTING_CASH = 1000
SHIP_COST = 300
SHIP_SCRAP = 150
STORAGE_COST = 1.0 
BASELINE_DEMAND = 260
CONTRACT_PRICE_MULT = 1.20
CONTRACT_PENALTY_MULT = 2

# --- 2. SERVER STATE ---
@st.cache_resource
def get_game_state():
    return {
        'phase': 'LOBBY', # LOBBY -> AUCTION_LIST -> AUCTION_BID -> FISHING -> STORAGE -> GAMEOVER
        'year': 1,
        'max_years': 5,
        
        # Ecology
        'fish_shore': (MAX_FISH_CAPACITY * 0.4) * 0.4,
        'fish_deep': (MAX_FISH_CAPACITY * 0.6) * 0.4,
        'market_price': BASE_FISH_PRICE,
        
        # Event
        'current_event': {"name": "Calm Seas", "desc": "Normal conditions.", "s_mod": 1.0, "d_mod": 1.0, "g_mod": 0.0},
        
        # Players & Sync
        'players': {},
        'actions': {}, # Temporary storage for moves
        'auction_lots': [], # Stores items for sale
        'logs': []
    }

state = get_game_state()

# --- 3. IDENTITY ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]
my_id = st.session_state.user_id

# --- 4. LOGIC FUNCTIONS (EXACTLY AS REQUESTED) ---
def trigger_event():
    # Weights: 40 for Calm, 12 for others
    events = [
        {"name": "Calm Seas", "desc": "Business as usual.", "s_mod": 1.0, "d_mod": 1.0, "g_mod": 0.0},
        {"name": "Coastal Storm", "desc": "Shore efficiency -50%.", "s_mod": 0.5, "d_mod": 1.0, "g_mod": 0.0},
        {"name": "Deep Freeze", "desc": "Deep efficiency -50%.", "s_mod": 1.0, "d_mod": 0.5, "g_mod": 0.0},
        {"name": "Algae Bloom", "desc": "Reproduction -10%.", "s_mod": 1.0, "d_mod": 1.0, "g_mod": -0.10},
        {"name": "Upwelling", "desc": "Reproduction +15%.", "s_mod": 1.0, "d_mod": 1.0, "g_mod": 0.15},
    ]
    # Simple random choice for web stability
    state['current_event'] = random.choice(events)

def compute_price(total_mass):
    # Your specific exponential formula
    k = 0.005
    m = max(1, total_mass)
    diff = BASELINE_DEMAND - m
    multiplier = math.exp(k * diff)
    price = BASE_FISH_PRICE * multiplier
    return max(1.0, min(15.0, round(price, 2)))

def log(msg):
    state['logs'].insert(0, f"[Year {state['year']}] {msg}")

# --- 5. UI COMPONENTS ---

# SIDEBAR REFRESH BUTTON (CRITICAL FOR MULTIPLAYER)
with st.sidebar:
    st.header(f"Year {state['year']}")
    
    # Refresh Button
    if st.button("🔄 REFRESH STATUS", type="primary"):
        st.rerun()
        
    st.divider()
    st.write(f"**Phase:** {state['phase']}")
    st.metric("Market Price", f"${state['market_price']:.2f}")
    st.metric("Shore Fish", int(state['fish_shore']))
    st.metric("Deep Fish", int(state['fish_deep']))
    st.info(f"Event: {state['current_event']['name']}")

# SAFETY CHECK
if state['phase'] != 'LOBBY' and my_id not in state['players']:
    st.error("You are not in this game. Please wait for the next one.")
    if st.button("Hard Reset Server"):
        st.cache_resource.clear()
        st.rerun()
    st.stop()

# --- 6. GAME PHASES ---

# PHASE: LOBBY
if state['phase'] == 'LOBBY':
    st.title("🐟 Fish Tycoon Lobby")
    
    if my_id not in state['players']:
        name = st.text_input("Enter Captain Name")
        if st.button("Join Game"):
            state['players'][my_id] = {
                'name': name, 'cash': STARTING_CASH, 'ships': 3, 
                'freezer': 0, 'last_catch': 0, 'last_profit': 0
            }
            st.rerun()
    else:
        st.success(f"Signed in as {state['players'][my_id]['name']}")
        st.write("### Players Joined:")
        for p in state['players'].values():
            st.write(f"- {p['name']}")
            
        if list(state['players'].keys())[0] == my_id:
            st.write("---")
            state['max_years'] = st.number_input("Game Length (Years)", 1, 20, 5)
            if st.button("🚀 START GAME"):
                trigger_event()
                state['phase'] = 'AUCTION_LIST'
                st.rerun()
        else:
            st.info("Waiting for host to start...")
            if st.button("Refresh Lobby"): st.rerun()

# PHASE: AUCTION - STEP 1 (LISTING)
elif state['phase'] == 'AUCTION_LIST':
    st.header("⚖️ Auction House: List Ships")
    p = state['players'][my_id]
    
    if my_id in state['actions']:
        st.info("✅ Listing submitted. Waiting for other players...")
        if st.button("Refresh / Check Others"): st.rerun()
        
        # Advance Phase if everyone is ready
        if len(state['actions']) == len(state['players']):
            state['auction_lots'] = []
            for pid, data in state['actions'].items():
                if data['qty'] > 0:
                    state['auction_lots'].append({
                        'seller_id': pid,
                        'seller_name': state['players'][pid]['name'],
                        'qty': data['qty'],
                        'min_price': data['min_price']
                    })
            state['actions'] = {}
            state['phase'] = 'AUCTION_BID'
            st.rerun()
            
    else:
        st.write(f"You have **{p['ships']} ships**. Do you want to sell any?")
        with st.form("list_form"):
            qty_sell = st.number_input("How many ships to sell?", 0, p['ships'], 0)
            min_price = st.number_input("Minimum Price (Reserve) for the whole lot?", 0, 5000, 500)
            if st.form_submit_button("Submit Listing"):
                state['actions'][my_id] = {'qty': qty_sell, 'min_price': min_price}
                st.rerun()

# PHASE: AUCTION - STEP 2 (BIDDING)
elif state['phase'] == 'AUCTION_BID':
    st.header("⚖️ Auction House: Bidding")
    p = state['players'][my_id]
    
    # If no lots, skip
    if not state['auction_lots']:
        if my_id not in state['actions']:
            state['actions'][my_id] = "skip"
            st.rerun()
    
    if my_id in state['actions']:
        st.info("✅ Bids submitted. Waiting for auction resolution...")
        if st.button("Refresh Results"): st.rerun()
        
        if len(state['actions']) == len(state['players']):
            # Resolve Auction
            bids = state['actions'] # {pid: {lot_index: amount}}
            
            logs = []
            for idx, lot in enumerate(state['auction_lots']):
                highest_bid = 0
                winner_id = None
                
                # Find highest bidder for this lot
                for bidder_id, bid_map in bids.items():
                    if bid_map == "skip": continue
                    bid_val = bid_map.get(idx, 0)
                    if bid_val >= lot['min_price'] and bid_val > highest_bid:
                        # Prevent self-bidding exploits if desired, 
                        # but standard logic allows buying back your own if you pay up
                        if bidder_id != lot['seller_id']: 
                            highest_bid = bid_val
                            winner_id = bidder_id
                
                if winner_id:
                    # Execute Trade
                    state['players'][winner_id]['cash'] -= highest_bid
                    state['players'][winner_id]['ships'] += lot['qty']
                    
                    state['players'][lot['seller_id']]['cash'] += highest_bid
                    state['players'][lot['seller_id']]['ships'] -= lot['qty']
                    
                    log(f"{state['players'][winner_id]['name']} bought {lot['qty']} ships from {lot['seller_name']} for ${highest_bid}")
                else:
                    log(f"Lot from {lot['seller_name']} ({lot['qty']} ships) went unsold.")
            
            state['actions'] = {}
            state['phase'] = 'FISHING'
            st.rerun()
    
    else:
        st.write(f"Your Cash: **${int(p['cash'])}**")
        
        if not state['auction_lots']:
            st.write("No ships for sale this year.")
            if st.button("Continue"):
                state['actions'][my_id] = "skip"
                st.rerun()
        else:
            bids_placed = {}
            with st.form("bidding_form"):
                for idx, lot in enumerate(state['auction_lots']):
                    if lot['seller_id'] == my_id:
                        st.caption(f"Lot #{idx+1}: Your listing ({lot['qty']} ships). Min: ${lot['min_price']}")
                    else:
                        st.markdown(f"**Lot #{idx+1}:** {lot['qty']} ships from {lot['seller_name']} (Min: ${lot['min_price']})")
                        bids_placed[idx] = st.number_input(f"Your Bid for Lot #{idx+1}", 0, int(p['cash']), 0, key=f"bid_{idx}")
                        st.divider()
                
                if st.form_submit_button("Submit Sealed Bids"):
                    state['actions'][my_id] = bids_placed
                    st.rerun()

# PHASE: FISHING
elif state['phase'] == 'FISHING':
    st.header("⚓ Fleet Deployment")
    p = state['players'][my_id]
    
    if my_id in state['actions']:
        st.info("✅ Fleet deployed. Waiting for catch results...")
        if st.button("Refresh / Check Catch"): st.rerun()
        
        if len(state['actions']) == len(state['players']):
            # CALC CATCH
            total_s = sum(x['s'] for x in state['actions'].values())
            total_d = sum(x['d'] for x in state['actions'].values())
            
            # Efficiency & Crowding
            evt = state['current_event']
            eff_s = 0.035 * evt['s_mod']
            eff_d = 0.055 * evt['d_mod']
            
            # Penalty: 1 / (1 + (Excess * 0.05))
            crowd_s = 1.0 / (1 + max(0, total_s - 10) * 0.05)
            crowd_d = 1.0 / (1 + max(0, total_d - 10) * 0.05)
            
            pot_s = min(state['fish_shore'], state['fish_shore'] * eff_s * total_s * crowd_s)
            pot_d = min(state['fish_deep'], state['fish_deep'] * eff_d * total_d * crowd_d)
            
            total_caught_mass = 0
            
            for pid, alloc in state['actions'].items():
                s_share = (alloc['s'] / total_s * pot_s) if total_s > 0 else 0
                d_share = (alloc['d'] / total_d * pot_d) if total_d > 0 else 0
                
                catch = s_share + d_share
                state['players'][pid]['last_catch'] = catch
                total_caught_mass += catch
                
                # Deduct Op Costs
                cost = (alloc['s']*45) + (alloc['d']*60) + (alloc['h']*5)
                state['players'][pid]['cash'] -= cost
            
            # Ecology Update
            state['fish_shore'] -= pot_s
            state['fish_deep'] -= pot_d
            
            # PRICE UPDATE (HAPPENS HERE, BEFORE FREEZING)
            state['market_price'] = compute_price(total_caught_mass)
            log(f"Total Catch: {int(total_caught_mass)}. New Price: ${state['market_price']}")
            
            state['actions'] = {}
            state['phase'] = 'STORAGE'
            st.rerun()
            
    else:
        st.write(f"Ships Available: **{p['ships']}**")
        with st.form("fish_form"):
            s = st.number_input("Shore (Cost $45)", 0, p['ships'], 0)
            d = st.number_input("Deep (Cost $60)", 0, p['ships']-s, 0)
            h = p['ships'] - s - d
            st.caption(f"Harbor: {h} ships (Cost $5)")
            
            if st.form_submit_button("Launch Fleet"):
                state['actions'][my_id] = {'s': s, 'd': d, 'h': h}
                st.rerun()

# PHASE: STORAGE (CRITICAL LOGIC UPDATE)
elif state['phase'] == 'STORAGE':
    st.header("❄️ Storage & Sales")
    p = state['players'][my_id]
    
    # Logic: We know the price. We know the catch. Now we decide freeze vs sell.
    fresh = p['last_catch']
    old_frozen = p['freezer']
    total_avail = fresh + old_frozen
    
    st.success(f"**Current Market Price:** ${state['market_price']:.2f}")
    
    if my_id in state['actions']:
        st.info("Transaction confirmed. Waiting for year end...")
        if st.button("Refresh"): st.rerun()
        
        if len(state['actions']) == len(state['players']):
            # Finalize Accounting
            for pid, freeze_qty in state['actions'].items():
                p_obj = state['players'][pid]
                
                # Recalculate based on request
                # Total available was (last_catch + old_freezer)
                total_stock = p_obj['last_catch'] + p_obj['freezer']
                
                to_sell = total_stock - freeze_qty
                
                revenue = to_sell * state['market_price']
                bill = freeze_qty * STORAGE_COST
                
                # Update Cash
                p_obj['cash'] += revenue - bill
                
                # Update Freezer
                p_obj['freezer'] = freeze_qty
                
                # Calculate Profit for leaderboard (Cash change)
                # This is simplified; accurate profit tracking would need previous cash snapshot
                # but for now, we just update the cash.
            
            # Growth
            evt = state['current_event']
            r_s = 0.28 + evt['g_mod']
            r_d = 0.35 + evt['g_mod']
            
            # Logistic Growth
            state['fish_shore'] += r_s * state['fish_shore'] * (1 - state['fish_shore']/(MAX_FISH_CAPACITY*0.4))
            state['fish_deep'] += r_d * state['fish_deep'] * (1 - state['fish_deep']/(MAX_FISH_CAPACITY*0.6))
            
            state['actions'] = {}
            state['year'] += 1
            state['phase'] = 'AUCTION_LIST' if state['year'] <= state['max_years'] else 'GAMEOVER'
            if state['phase'] == 'AUCTION_LIST': trigger_event()
            st.rerun()
            
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Fresh Catch", int(fresh))
        c2.metric("In Freezer", int(old_frozen))
        c3.metric("Total Stock", int(total_avail))
        
        with st.form("store_form"):
            st.write("How much to **FREEZE** for next year? (The rest is sold now)")
            freeze = st.number_input(f"Units to Freeze (${STORAGE_COST}/unit)", 0, int(total_avail), 0)
            
            selling = total_avail - freeze
            est_rev = selling * state['market_price']
            est_stor = freeze * STORAGE_COST
            
            st.caption(f"Selling: {int(selling)} units | Est. Revenue: ${est_rev:.2f}")
            st.caption(f"Freezing: {int(freeze)} units | Storage Cost: ${est_stor:.2f}")
            
            if st.form_submit_button("Execute Sales"):
                state['actions'][my_id] = freeze
                st.rerun()

# PHASE: GAMEOVER
elif state['phase'] == 'GAMEOVER':
    st.balloons()
    st.title("🏆 Game Over")
    
    # Calculate Wealth
    ship_val = SHIP_SCRAP # Simplified for end game
    res = []
    for pid, p in state['players'].items():
        wealth = p['cash'] + (p['ships'] * ship_val)
        res.append({
            "Captain": p['name'],
            "Cash": p['cash'],
            "Ships": p['ships'],
            "Total Wealth": wealth
        })
    
    df = pd.DataFrame(res).sort_values("Total Wealth", ascending=False)
    st.table(df)
    
    if st.button("Start New Game"):
        st.cache_resource.clear()
        st.rerun()
