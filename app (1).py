@st.cache_data
def load_custom_data():
    target_file = 'data.csv'
    
    # 1. Check if file exists
    if not os.path.exists(target_file):
        all_files = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_files: target_file = all_files[0]
        else:
            st.error("❌ No CSV files found.")
            return None

    try:
        # 2. Read the file
        df = pd.read_csv(target_file)
        
        # 3. CLEAN THE COLUMNS (The Fix!)
        # This removes any hidden spaces or weird characters from headers
        df.columns = df.columns.str.strip()
        
        # 4. Debug check (Only shows if there's a problem)
        if 'timestamp' not in df.columns:
            st.error(f"❌ Could not find 'timestamp' column. Available columns are: {list(df.columns)}")
            return None
        
        # 5. Process the data
        df['timestamp'] = pd.to_datetime(df['timestamp']) # Convert to real dates
        latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
        return latest
        
    except Exception as e:
        st.error(f"❌ Error: {e}")
        return None
