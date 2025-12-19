# --- 1. ROAD NETWORK CACHING ---
@st.cache_resource
def get_road_network():
    # Mumbai center coordinates
    return ox.graph_from_point((19.0760, 72.8777), dist=8000, network_type='drive')

# --- Route Optimization Page ---
elif page == "Route Optimization":
    st.title("🚛 AI Multi-Fleet Dispatcher & Navigation")
    
    # Define Garages
    GARAGES = {
        "Truck 1 (Worli)": (19.0178, 72.8478),
        "Truck 2 (Bandra)": (19.0596, 72.8295),
        "Truck 3 (Andheri)": (19.1136, 72.8697),
        "Truck 4 (Kurla)": (19.0726, 72.8844),
        "Truck 5 (Borivali)": (19.2307, 72.8567)
    }
    DEONAR_DUMPING = (19.0550, 72.9250)

    # Sidebar Controls
    st.sidebar.header("Fleet Control Panel")
    selected_truck = st.sidebar.selectbox("Active Truck", list(GARAGES.keys()))
    threshold = st.sidebar.slider("Urgency Threshold (Fill %)", 0, 100, 75)

    # --- THE MENTOR'S SECRET: TIME TRAVEL ---
    # This allows you to pick a point in your data where bins ARE full
    st.sidebar.subheader("📅 Simulation Time")
    unique_times = sorted(df['timestamp'].unique())
    # Set default to a time where bins are likely full (e.g., 80% through the data)
    default_index = int(len(unique_times) * 0.8) 
    sim_time = st.sidebar.select_slider("Select Time to View City Status", options=unique_times, value=unique_times[default_index])
    
    # Filter data for THAT specific time
    df_snapshot = df[df['timestamp'] == sim_time].copy()

    # Logic: Assign bins to the nearest truck (Assignment Problem)
    def assign_nearest(row):
        bin_loc = (row['bin_location_lat'], row['bin_location_lon'])
        # FIXED MATH: Using **2 for squaring and **0.5 for square root
        distances = {name: ((bin_loc[0]-g[0])**2 + (bin_loc[1]-g[1])**2)**0.5 for name, g in GARAGES.items()}
        return min(distances, key=distances.get)

    df_snapshot['assigned_truck'] = df_snapshot.apply(assign_nearest, axis=1)
    
    # Filter bins for the selected truck that are over the threshold
    my_bins = df_snapshot[(df_snapshot['assigned_truck'] == selected_truck) & (df_snapshot['bin_fill_percent'] >= threshold)]
    
    # Stats
    c1, c2, c3 = st.columns(3)
    c1.metric("Selected Vehicle", selected_truck)
    c2.metric("Assigned Pickups", len(my_bins))
    c3.metric("Snapshot Time", sim_time.strftime('%H:%M %d-%m'))

    # --- MAP RENDERING ---
    try:
        G = get_road_network() 
        m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

        # 1. Plot Bins
        for _, row in df_snapshot.iterrows():
            is_mine = (row['assigned_truck'] == selected_truck)
            is_full = (row['bin_fill_percent'] >= threshold)
            
            # Logic: Red = My pickup, Orange = Other truck's pickup, Green = Safe
            if is_full and is_mine: color = 'red'
            elif is_full and not is_mine: color = 'orange'
            else: color = 'green'
            
            folium.Marker(
                [row['bin_location_lat'], row['bin_location_lon']],
                popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                icon=folium.Icon(color=color, icon='trash', prefix='fa')
            ).add_to(m)

        # 2. Draw Optimized Route (Only if there are bins to pick up)
        if not my_bins.empty:
            garage_loc = GARAGES[selected_truck]
            # Limit to top 8 bins to keep QR code and Path stable
            top_bins = my_bins.sort_values('bin_fill_percent', ascending=False).head(8)
            mission_points = [garage_loc] + list(zip(top_bins['bin_location_lat'], top_bins['bin_location_lon'])) + [DEONAR_DUMPING]
            
            path_coords = []
            for i in range(len(mission_points)-1):
                try:
                    n1 = ox.nearest_nodes(G, mission_points[i][1], mission_points[i][0])
                    n2 = ox.nearest_nodes(G, mission_points[i+1][1], mission_points[i+1][0])
                    route = nx.shortest_path(G, n1, n2, weight='length')
                    path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in route])
                except:
                    path_coords.append([mission_points[i][0], mission_points[i][1]])
                    path_coords.append([mission_points[i+1][0], mission_points[i+1][1]])
            
            if path_coords:
                folium.PolyLine(path_coords, color="#e74c3c", weight=6, opacity=0.8).add_to(m)

        # 3. Add Garage Markers
        for name, coords in GARAGES.items():
            folium.Marker(coords, popup=name, icon=folium.Icon(color='blue' if name == selected_truck else 'gray', icon='truck', prefix='fa')).add_to(m)

        st_folium(m, width=1100, height=600, key="optimized_map")

        # --- 4. QR CODE GENERATION ---
        if not my_bins.empty:
            st.subheader(f"📲 Driver Navigation: {selected_truck}")
            origin = f"{garage_loc[0]},{garage_loc[1]}"
            dest = f"{DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
            waypoints = "|".join([f"{lat},{lon}" for lat, lon in zip(top_bins['bin_location_lat'], top_bins['bin_location_lon'])])
            
            # Official Google Maps Directions Link
            google_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={dest}&waypoints={waypoints}&travelmode=driving"
            
            qr = qrcode.make(google_url)
            buf = BytesIO()
            qr.save(buf)
            st.image(buf, width=200, caption="Scan to start Mission")

    except Exception as e:
        st.error(f"Mapping Engine Error: {e}")
