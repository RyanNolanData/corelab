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

def find_exact_or_high_similarity_match(name, name_list, name_counts_dict, threshold=0.85):
    """Find exact match or high similarity match (>0.85) for a name"""
    normalized_name = normalize_name(name)
    
    # First check for exact match
    for other_name in name_list:
        if normalize_name(other_name) == normalized_name:
            return other_name, name_counts_dict.get(other_name, 0), 1.0
    
    # Then check for high similarity matches
    for other_name in name_list:
        normalized_other = normalize_name(other_name)
        if normalized_name != normalized_other:
            sim = similarity(normalized_name, normalized_other)
            if sim >= threshold:
                return other_name, name_counts_dict.get(other_name, 0), sim
    
    return None, 0, 0.0

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
        
        # Create dictionaries for easy lookup
        wellpass_counts_dict = dict(zip(wellpass_counts['Full_Name'], wellpass_counts['Total_Visits']))
        glofox_counts_dict = dict(zip(glofox_counts['Full_Name'], glofox_counts['Total_Visits']))
        
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
        
        # Step 2: Updated Differences Section
        st.header("⚠️ Differences")
        
        all_wellpass_names = set(wellpass_counts['Full_Name'].tolist())
        all_glofox_names = set(glofox_counts['Full_Name'].tolist())
        
        differences_data = []
        matched_pairs = set()  # Track matched pairs to avoid duplicates
        
        # Process each Wellpass name
        for wp_name in sorted(all_wellpass_names):
            wp_count = wellpass_counts_dict[wp_name]
            
            # Find exact or high similarity match in Glofox
            matched_name, gf_count, sim_score = find_exact_or_high_similarity_match(
                wp_name, all_glofox_names, glofox_counts_dict, threshold=0.85
            )
            
            if matched_name:
                # Found a match with similarity >= 0.85
                pair_key = (wp_name, matched_name)
                if pair_key not in matched_pairs:
                    matched_pairs.add(pair_key)
                    difference = abs(gf_count - wp_count)
                    differences_data.append({
                        'Wellpass System Name': wp_name,
                        'Glofox System Name': matched_name,
                        'Glofox': gf_count,
                        'Wellpass': wp_count,
                        'Difference': difference
                    })
            else:
                # No match found
                differences_data.append({
                    'Wellpass System Name': wp_name,
                    'Glofox System Name': '',
                    'Glofox': 0,
                    'Wellpass': wp_count,
                    'Difference': wp_count
                })
        
        # Process remaining Glofox names that weren't matched
        matched_glofox_names = set()
        for pair in matched_pairs:
            matched_glofox_names.add(pair[1])  # pair[1] is the Glofox name
        
        remaining_glofox_names = all_glofox_names - matched_glofox_names
        for gf_name in sorted(remaining_glofox_names):
            gf_count = glofox_counts_dict[gf_name]
            differences_data.append({
                'Wellpass System Name': '',
                'Glofox System Name': gf_name,
                'Glofox': gf_count,
                'Wellpass': 0,
                'Difference': gf_count
            })
        
        # Create DataFrame and sort by Wellpass System Name
        step2_df = pd.DataFrame(differences_data)
        # Filter out rows where difference is 0
        step2_df = step2_df[step2_df['Difference'] > 0]
        step2_df = step2_df.sort_values('Wellpass System Name', na_position='last').reset_index(drop=True)
        
        st.dataframe(step2_df)
        
        # Download button for Step 2
        if not step2_df.empty:
            step2_excel = to_excel_download(step2_df, "Differences.xlsx")
            st.download_button(
                label="📥 Download Differences",
                data=step2_excel,
                file_name="Differences.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No differences found in visit counts!")
        
        st.divider()
        
        # Step 3: Updated Potential Name Differences Section
        st.header("🔍 Potential Name Differences")
        
        potential_matches = []
        
        # Check Wellpass names against Glofox names for potential matches (0.7 and above similarity)
        for wp_name in all_wellpass_names:
            wp_count = wellpass_counts_dict[wp_name]
            
            # Find matches with similarity 0.7 and above
            matches = find_potential_matches(wp_name, all_glofox_names, threshold=0.7)
            for match_name, similarity_score in matches:
                gf_count = glofox_counts_dict[match_name]
                potential_matches.append({
                    'Wellpass System Name': wp_name,
                    'Times in System Wellpass': wp_count,
                    'Glofox System Name': match_name,
                    'Times in System Glofox': gf_count,
                    'Similarity_Score': round(similarity_score, 3),
                    'Issue_Type': 'Potential Misspelling/Format Difference'
                })
        
        # Check Glofox names against Wellpass names for potential matches (0.7 and above similarity)
        for gf_name in all_glofox_names:
            gf_count = glofox_counts_dict[gf_name]
            
            # Find matches with similarity 0.7 and above
            matches = find_potential_matches(gf_name, all_wellpass_names, threshold=0.7)
            for match_name, similarity_score in matches:
                wp_count = wellpass_counts_dict[match_name]
                
                # Check if this combination already exists (to avoid duplicates)
                duplicate_exists = False
                for existing in potential_matches:
                    if (existing['Wellpass System Name'] == match_name and 
                        existing['Glofox System Name'] == gf_name):
                        duplicate_exists = True
                        break
                
                if not duplicate_exists:
                    potential_matches.append({
                        'Wellpass System Name': match_name,
                        'Times in System Wellpass': wp_count,
                        'Glofox System Name': gf_name,
                        'Times in System Glofox': gf_count,
                        'Similarity_Score': round(similarity_score, 3),
                        'Issue_Type': 'Potential Misspelling/Format Difference'
                    })
        
        step3_df = pd.DataFrame(potential_matches)
        if not step3_df.empty:
            step3_df = step3_df.sort_values(['Similarity_Score'], ascending=False).reset_index(drop=True)
            step3_df = step3_df.drop_duplicates(subset=['Wellpass System Name', 'Glofox System Name'])
        
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
        
        # Find names that don't have exact or high similarity matches
        wellpass_unmatched = set()
        glofox_unmatched = set()
        
        for wp_name in all_wellpass_names:
            matched_name, _, _ = find_exact_or_high_similarity_match(
                wp_name, all_glofox_names, glofox_counts_dict, threshold=0.85
            )
            if not matched_name:
                wellpass_unmatched.add(wp_name)
        
        for gf_name in all_glofox_names:
            matched_name, _, _ = find_exact_or_high_similarity_match(
                gf_name, all_wellpass_names, wellpass_counts_dict, threshold=0.85
            )
            if not matched_name:
                glofox_unmatched.add(gf_name)
        
        # Clients in Wellpass but not matched in Glofox
        for name in wellpass_unmatched:
            missing_clients.append({
                'Name': name,
                'List_Appeared': 'Wellpass',
                'List_Missing': 'Glofox'
            })
        
        # Clients in Glofox but not matched in Wellpass
        for name in glofox_unmatched:
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
            st.metric("Clients with Differences", len(step2_df))
        
        with col4:
            st.metric("Potential Name Issues", len(step3_df))
        
        # Download All Data Button
        st.divider()
        st.header("Complete Report")
        
        # Prepare all dataframes for multi-sheet Excel
        all_data_sheets = {
            "1_Aggregate_Totals": step1_df,
            "2_Differences": step2_df if not step2_df.empty else pd.DataFrame([{"Note": "No differences found"}]),
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
                len(step2_df),
                len(step3_df),
                len(wellpass_unmatched),
                len(glofox_unmatched)
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
