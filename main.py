import streamlit as st
import pandas as pd
import numpy as np
from difflib import SequenceMatcher
import re
from io import BytesIO
import unicodedata

# Set page config
st.set_page_config(page_title="Client Visit Reconciliation", page_icon="📊", layout="wide")

st.title("📊 Client Visit Reconciliation Tool")
st.markdown("Automated solution for reconciling client visit data from Wellpass and Glofox systems")

# Helper functions
def normalize_name(name):
    """Normalize names for better matching"""
    if pd.isna(name):
        return ""
    # Remove accents and special characters
    name = unicodedata.normalize('NFD', str(name))
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    # Convert to lowercase, remove extra spaces, and special characters
    name = re.sub(r'[^\w\s]', '', name.lower().strip())
    name = ' '.join(name.split())
    return name

def similarity(a, b):
    """Calculate similarity ratio between two strings"""
    return SequenceMatcher(None, a, b).ratio()

def find_potential_matches(name, name_list, threshold=0.7):
    """Find potential matches for a name in a list"""
    matches = []
    normalized_name = normalize_name(name)
    for other_name in name_list:
        normalized_other = normalize_name(other_name)
        if normalized_name != normalized_other:
            sim = similarity(normalized_name, normalized_other)
            if sim >= threshold:
                matches.append((other_name, sim))
    return sorted(matches, key=lambda x: x[1], reverse=True)

def to_excel_download(df, filename):
    """Convert dataframe to excel and create download button"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    processed_data = output.getvalue()
    return processed_data

def create_multi_sheet_excel(dataframes_dict):
    """Create Excel file with multiple sheets"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dataframes_dict.items():
            df.to_excel(writer, index=False, sheet_name=sheet_name)
    processed_data = output.getvalue()
    return processed_data

# Data Upload Section
st.header("📁 Data Upload")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Wellpass Data Upload")
    wellpass_file = st.file_uploader("Upload Wellpass Excel file", type=['xlsx'], key="wellpass")

with col2:
    st.subheader("Glofox Data Upload")
    glofox_file = st.file_uploader("Upload Glofox Excel file", type=['xlsx'], key="glofox")

# Process data if both files are uploaded
if wellpass_file is not None and glofox_file is not None:
    try:
        # Load data
        wellpass_df = pd.read_excel(wellpass_file)
        glofox_df = pd.read_excel(glofox_file)
        
        st.success("✅ Both files loaded successfully!")
        
        # Display data preview
        st.subheader("📋 Data Preview")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Wellpass Data Preview:**")
            st.dataframe(wellpass_df.head())
            
        with col2:
            st.write("**Glofox Data Preview:**")
            st.dataframe(glofox_df.head())
        
        # Process Wellpass data (assuming columns: 'Vor- & Nachname', 'Datum', 'Zeit')
        wellpass_processed = wellpass_df.copy()
        wellpass_processed['Full_Name'] = wellpass_processed.iloc[:, 0]  # First column (name)
        wellpass_processed['Date'] = pd.to_datetime(wellpass_processed.iloc[:, 1])  # Second column (date)
        
        # Process Glofox data (assuming columns: 'Visit Date', 'Client Name')
        glofox_processed = glofox_df.copy()
        glofox_processed['Full_Name'] = glofox_processed.iloc[:, 1]  # Second column (client name)
        glofox_processed['Date'] = pd.to_datetime(glofox_processed.iloc[:, 0])  # First column (visit date)
        
        st.divider()
        
        # Step 1: Aggregate Totals
        st.header("📊 Aggregate Totals")
        
        # Count visits per client in each system
        wellpass_counts = wellpass_processed['Full_Name'].value_counts().reset_index()
        wellpass_counts.columns = ['Full_Name', 'Total_Visits']
        wellpass_counts['System'] = 'Wellpass'
        
        glofox_counts = glofox_processed['Full_Name'].value_counts().reset_index()
        glofox_counts.columns = ['Full_Name', 'Total_Visits']
        glofox_counts['System'] = 'Glofox'
        
        # Combine and sort
        step1_df = pd.concat([wellpass_counts, glofox_counts], ignore_index=True)
        step1_df = step1_df.sort_values('Full_Name').reset_index(drop=True)
        
        st.dataframe(step1_df)
        
        # Download button for Step 1
        step1_excel = to_excel_download(step1_df, "Aggregate_Totals.xlsx")
        st.download_button(
            label="📥 Download Aggregate Totals",
            data=step1_excel,
            file_name="Aggregate_Totals.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.divider()
        
        # Step 2: Differences in Visit Counts
        st.header("⚠️ Differences")
        
        # Pivot to compare counts
        step2_df = step1_df.pivot(index='Full_Name', columns='System', values='Total_Visits').fillna(0)
        step2_df = step2_df.reset_index()
        
        # Ensure both columns exist
        if 'Glofox' not in step2_df.columns:
            step2_df['Glofox'] = 0
        if 'Wellpass' not in step2_df.columns:
            step2_df['Wellpass'] = 0
        
        step2_df['Glofox'] = step2_df['Glofox'].astype(int)
        step2_df['Wellpass'] = step2_df['Wellpass'].astype(int)
        step2_df['Difference'] = abs(step2_df['Glofox'] - step2_df['Wellpass'])
        
        # Filter only rows with differences
        differences_df = step2_df[step2_df['Difference'] > 0].copy()
        differences_df = differences_df.sort_values('Difference', ascending=False).reset_index(drop=True)
        
        st.dataframe(differences_df)
        
        # Download button for Step 2
        if not differences_df.empty:
            step2_excel = to_excel_download(differences_df, "Differences.xlsx")
            st.download_button(
                label="📥 Download Differences",
                data=step2_excel,
                file_name="Differences.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No differences found in visit counts!")
        
        st.divider()
        
        # Step 3: Potential Name Differences
        st.header("🔍 Potential Name Differences")
        
        all_wellpass_names = set(wellpass_counts['Full_Name'].tolist())
        all_glofox_names = set(glofox_counts['Full_Name'].tolist())
        
        potential_matches = []
        
        # Check Wellpass names against Glofox names
        for wp_name in all_wellpass_names:
            if wp_name not in all_glofox_names:
                matches = find_potential_matches(wp_name, all_glofox_names)
                for match_name, similarity_score in matches[:3]:  # Top 3 matches
                    potential_matches.append({
                        'Original_Name': wp_name,
                        'System': 'Wellpass',
                        'Potential_Match': match_name,
                        'Match_System': 'Glofox',
                        'Similarity_Score': round(similarity_score, 3),
                        'Issue_Type': 'Potential Misspelling/Format Difference'
                    })
        
        # Check Glofox names against Wellpass names
        for gf_name in all_glofox_names:
            if gf_name not in all_wellpass_names:
                matches = find_potential_matches(gf_name, all_wellpass_names)
                for match_name, similarity_score in matches[:3]:  # Top 3 matches
                    potential_matches.append({
                        'Original_Name': gf_name,
                        'System': 'Glofox',
                        'Potential_Match': match_name,
                        'Match_System': 'Wellpass',
                        'Similarity_Score': round(similarity_score, 3),
                        'Issue_Type': 'Potential Misspelling/Format Difference'
                    })
        
        step3_df = pd.DataFrame(potential_matches)
        if not step3_df.empty:
            step3_df = step3_df.sort_values(['Similarity_Score'], ascending=False).reset_index(drop=True)
            step3_df = step3_df.drop_duplicates(subset=['Original_Name', 'Potential_Match'])
        
        st.dataframe(step3_df)
        
        # Download button for Step 3
        if not step3_df.empty:
            step3_excel = to_excel_download(step3_df, "Potential_Name_Differences.xlsx")
            st.download_button(
                label="📥 Download Potential Name Differences",
                data=step3_excel,
                file_name="Potential_Name_Differences.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No potential name differences found!")
        
        st.divider()
        
        # Step 4: Clients in One List but Not the Other
        st.header("👥 Clients in One List Only")
        
        missing_clients = []
        
        # Clients in Wellpass but not in Glofox
        wellpass_only = all_wellpass_names - all_glofox_names
        for name in wellpass_only:
            missing_clients.append({
                'Name': name,
                'List_Appeared': 'Wellpass',
                'List_Missing': 'Glofox'
            })
        
        # Clients in Glofox but not in Wellpass
        glofox_only = all_glofox_names - all_wellpass_names
        for name in glofox_only:
            missing_clients.append({
                'Name': name,
                'List_Appeared': 'Glofox',
                'List_Missing': 'Wellpass'
            })
        
        step4_df = pd.DataFrame(missing_clients)
        if not step4_df.empty:
            step4_df = step4_df.sort_values(['List_Appeared', 'Name']).reset_index(drop=True)
        
        st.dataframe(step4_df)
        
        # Download button for Step 4
        if not step4_df.empty:
            step4_excel = to_excel_download(step4_df, "Clients_One_List_Only.xlsx")
            st.download_button(
                label="📥 Download Clients in One List Only",
                data=step4_excel,
                file_name="Clients_One_List_Only.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("All clients appear in both lists!")
        
        # Summary section
        st.divider()
        st.header("📈 Summary")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Wellpass Clients", len(all_wellpass_names))
        
        with col2:
            st.metric("Total Glofox Clients", len(all_glofox_names))
        
        with col3:
            st.metric("Clients with Differences", len(differences_df))
        
        with col4:
            st.metric("Potential Name Issues", len(step3_df))
        
        # Download All Data Button
        st.divider()
        st.header("Complete Report")
        
        # Prepare all dataframes for multi-sheet Excel
        all_data_sheets = {
            "1_Aggregate_Totals": step1_df,
            "2_Differences": differences_df if not differences_df.empty else pd.DataFrame([{"Note": "No differences found"}]),
            "3_Potential_Name_Differences": step3_df if not step3_df.empty else pd.DataFrame([{"Note": "No potential name differences found"}]),
            "4_Clients_One_List_Only": step4_df if not step4_df.empty else pd.DataFrame([{"Note": "All clients appear in both lists"}])
        }
        
        # Create summary sheet
        summary_data = {
            "Metric": [
                "Total Wellpass Clients",
                "Total Glofox Clients", 
                "Clients with Visit Count Differences",
                "Potential Name Issues",
                "Clients Only in Wellpass",
                "Clients Only in Glofox"
            ],
            "Value": [
                len(all_wellpass_names),
                len(all_glofox_names),
                len(differences_df),
                len(step3_df),
                len(wellpass_only),
                len(glofox_only)
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        all_data_sheets["0_Summary"] = summary_df
        
        # Create the multi-sheet Excel file
        all_data_excel = create_multi_sheet_excel(all_data_sheets)
        
        st.download_button(
            label="Download Complete Reconciliation Report",
            data=all_data_excel,
            file_name="Complete_Client_Visit_Reconciliation_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Downloads all reconciliation data in a single Excel file with separate sheets for each step"
        )
        
        st.success("✅ Complete reconciliation analysis finished! Use the button above to download all results in one comprehensive Excel file.")
            
    except Exception as e:
        st.error(f"Error processing files: {str(e)}")
        st.info("Please ensure your Excel files have the correct format and column names.")

else:
    st.info("👆 Please upload both Wellpass and Glofox Excel files to begin the reconciliation process.")
