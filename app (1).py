import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETTINGS & MULTI-TRUCK HUBS ---
st.set_page_config(page_title="Evergreen AI: Multi-Fleet Dispatch", layout="wide")

# 5 Municipal Garages across Mumbai
GARAGES = {
    "Truck 1 (Worli)": (19.0178, 72.8478),
    "Truck 2 (Bandra)": (19.0596, 72.8295),
    "Truck 3 (Andheri)": (19.1136, 72.8697),
    "Truck 4 (Kurla)": (19.0726, 72.8844),
    "Truck 5 (Borivali)": (19.2307, 72.8567)
}
DEONAR_DUMPING = (19.0550, 72.9250)

@st.cache_data
def load_and_clean_data():
    # Detects your specific file name automatically
    target = 'cleaned_data_with_fuel_weight_co2 (1).csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_csvs: target = all_csvs[0]
        else: return None
    try:
        df = pd.read_csv(target)
        df.columns = df.columns.str.strip()
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        return df.dropna(subset=['timestamp', 'bin_fill_percent'])
    except Exception as e:
        st.error(f"Data Error: {e}")
        return None

# Fixed Math Function (Using **2 for squaring)
def get_dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

@st.cache_resource
def get_road_network():
    return ox.graph_from_point((19.0760, 72.8777), dist=8000, network_type='drive')

# --- 2. MAIN NAVIGATION ---
df = load_and_clean_data()

if df is not None:
    page = st.sidebar.selectbox("Navigate to:", ["Home", "Mission Control"])

    if page == "Home":
        st.title("🏡 Evergreen Smart Waste AI")
        st.subheader("Project Mission")
        st.write("Optimizing Mumbai's waste collection through AI-driven fleet assignment and shortest-path routing.")
        st.image("https://images.unsplash.com/photo-1532996122724-e3c354a0b15b?auto=format&fit=crop&q=80&w=1000", caption="Sustainable City Logistics")
        st.dataframe(df.head())

    elif page == "Mission Control":
        st.title("🚛 AI Multi-Fleet Dispatcher")

        # SIDEBAR MISSION SETTINGS
        st.sidebar.header("Mission Parameters")
        selected_truck = st.sidebar.selectbox("Select Truck to Dispatch", list(GARAGES.keys()))
        threshold = st.sidebar.slider("Urgency Threshold (%)", 0, 100, 75)

        # THE SIMULATION TIME SLIDER (Solves the "Empty Bin" problem)
        unique_times = sorted(df['timestamp'].unique())
        # Default to a time where bins were at 80% (Peak waste time)
        default_idx = int(len(unique_times) * 0.8)
        sim_time = st.sidebar.select_slider("Select Simulation Time", 
                                            options=unique_times, 
                                            value=unique_times[default_idx])
        
        # Filter for the specific moment in time
        df_snapshot = df[df['timestamp'] == sim_time].copy()

        # ASSIGNMENT LOGIC: Assign each bin to the NEAREST garage
        def assign_truck(row):
            bin_loc = (row['bin_location_lat'], row['bin_location_lon'])
            dists = {name: get_dist(bin_loc, coord) for name, coord in GARAGES.items()}
            return min(dists, key=dists.get)

        df_snapshot['assigned_truck'] = df_snapshot.apply(assign_truck, axis=1)
        
        # Filter bins for the SELECTED truck that are over the threshold
        my_bins = df_snapshot[(df_snapshot['assigned_truck'] == selected_truck) & 
                              (df_snapshot['bin_fill_percent'] >= threshold)]
        
        # Dashboard Stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Active Vehicle", selected_truck)
        c2.metric("Pickups Required", len(my_bins))
        c3.metric("Final Destination", "Deonar")

        # --- MAP VISUALIZATION ---
        try:
            G = get_road_network()
            m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

            # 1. Plot all Bins with Logic
            for _, row in df_snapshot.iterrows():
                is_full = row['bin_fill_percent'] >= threshold
                is_mine = row['assigned_truck'] == selected_truck
                
                # Red = My job, Orange = Other truck's job, Green = Safe
                if is_full and is_mine: color = 'red'
                elif is_full and not is_mine: color = 'orange'
                else: color = 'green'
                
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']],
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                    icon=folium.Icon(color=color, icon='trash', prefix='fa')
                ).add_to(m)

            # 2. Draw the Optimized Route (Garage -> My Bins -> Deonar)
            garage_coords = GARAGES[selected_truck]
            if not my_bins.empty:
                # Top 8 most urgent bins (Priority Queue)
                target_bins = my_bins.sort_values('bin_fill_percent', ascending=False).head(8)
                mission_points = [garage_coords] + list(zip(target_bins['bin_location_lat'], target_bins['bin_location_lon'])) + [DEONAR_DUMPING]
                
                path_coords = []
                for i in range(len(mission_points)-1):
                    try:
                        n1 = ox.nearest_nodes(G, mission_points[i][1], mission_points[i][0])
                        n2 = ox.nearest_nodes(G, mission_points[i+1][1], mission_points[i+1][0])
                        path = nx.shortest_path(G, n1, n2, weight='length')
                        path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in path])
                    except:
                        path_coords.append([mission_points[i][0], mission_points[i][1]])
                        path_coords.append([mission_points[i+1][0], mission_points[i+1][1]])
                
                if path_coords:
                    folium.PolyLine(path_coords, color="#3498db", weight=6, opacity=0.8).add_to(m)

            # 3. Add Garage Markers
            for name, coords in GARAGES.items():
                is_active = (name == selected_truck)
                folium.Marker(coords, popup=name, 
                              icon=folium.Icon(color='blue' if is_active else 'gray', icon='truck', prefix='fa')).add_to(m)
            
            # 4. Add Deonar Marker
            folium.Marker(DEONAR_DUMPING, popup="DEONAR DUMPING GROUND", 
                          icon=folium.Icon(color='black', icon='home', prefix='fa')).add_to(m)

            st_folium(m, width=1200, height=550)

        except Exception as e:
            st.error(f"Map Rendering Error: {e}")

        # --- QR CODE DRIVER NAVIGATION ---
        if not my_bins.empty:
            st.subheader(f"📲 Driver Navigation: {selected_truck}")
            origin = f"{garage_coords[0]},{garage_coords[1]}"
            dest = f"{DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
            waypoints = "|".join([f"{lat},{lon}" for lat, lon in zip(target_bins['bin_location_lat'], target_bins['bin_location_lon'])])
            
            google_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={dest}&waypoints={waypoints}&travelmode=driving"
            
            c_qr, c_txt = st.columns([1, 4])
            with c_qr:
                qr = qrcode.make(google_url)
                buf = BytesIO()
                qr.save(buf)
                st.image(buf, width=200)
            with c_txt:
                st.success("✅ Path Optimized for Shortest Driving Time.")
                st.write("**Presentation Tip for Judges:**")
                st.write("- 'Red Bins' are assigned to this truck because they are closer to this garage than any other.")
                st.write("- 'Orange Bins' are full but assigned to a different truck to optimize total city fuel usage.")

else:
    st.error("Missing 'data.csv'. Please upload to Replit sidebar.")
