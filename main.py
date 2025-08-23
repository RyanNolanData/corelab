import streamlit as st
import pandas as pd
import numpy as np
from difflib import SequenceMatcher
import re
from io import BytesIO
import unicodedata

# ===============================
# Page setup
# ===============================
st.set_page_config(page_title="Client Visit Reconciliation", page_icon="📊", layout="wide")
st.title("📊 Client Visit Reconciliation Tool")
st.markdown("Automated solution for reconciling client visit data from Wellpass and Glofox systems")

# ===============================
# Helpers
# ===============================
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
    """Convert dataframe to excel and return bytes"""
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

# ---- session helpers ----
def _lower_yes(x):
    try:
        return str(x).strip().lower() == "yes"
    except Exception:
        return False

if "review_df" not in st.session_state:
    st.session_state.review_df = None
if "approved_mapping" not in st.session_state:
    st.session_state.approved_mapping = {}  # {Glofox_Name -> Wellpass_Name}
if "submitted_review" not in st.session_state:
    st.session_state.submitted_review = False

# ===============================
# Upload
# ===============================
st.header("📁 Data Upload")
col1, col2 = st.columns(2)

with col1:
    st.subheader("Wellpass Data Upload")
    wellpass_file = st.file_uploader("Upload Wellpass Excel file", type=['xlsx'], key="wellpass")

with col2:
    st.subheader("Glofox Data Upload")
    glofox_file = st.file_uploader("Upload Glofox Excel file", type=['xlsx'], key="glofox")

# ===============================
# Main
# ===============================
if wellpass_file is not None and glofox_file is not None:
    try:
        # Load data
        wellpass_df = pd.read_excel(wellpass_file)
        glofox_df = pd.read_excel(glofox_file)

        st.success("✅ Both files loaded successfully!")

        # Preview
        st.subheader("📋 Data Preview")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Wellpass Data Preview:**")
            st.dataframe(wellpass_df.head())
        with c2:
            st.write("**Glofox Data Preview:**")
            st.dataframe(glofox_df.head())

        # Normalize/prepare working frames (assumes col 0=name, col 1=date per your examples)
        wellpass_processed = wellpass_df.copy()
        wellpass_processed['Full_Name'] = wellpass_processed.iloc[:, 0]
        wellpass_processed['Date'] = pd.to_datetime(wellpass_processed.iloc[:, 1], errors='coerce')

        glofox_processed = glofox_df.copy()
        glofox_processed['Full_Name'] = glofox_processed.iloc[:, 1]
        glofox_processed['Date'] = pd.to_datetime(glofox_processed.iloc[:, 0], errors='coerce')

        # ---------------------------------------------------------
        # STEP A — Potential Name Differences (REVIEW FIRST)
        # ---------------------------------------------------------
        st.divider()
        st.header("🔍 Potential Name Differences (Review First)")

        # Build counts for suggestion scoring
        wellpass_counts = wellpass_processed['Full_Name'].value_counts().reset_index()
        wellpass_counts.columns = ['Full_Name', 'Total_Visits']
        glofox_counts = glofox_processed['Full_Name'].value_counts().reset_index()
        glofox_counts.columns = ['Full_Name', 'Total_Visits']

        # Dicts & name sets
        wellpass_counts_dict = dict(zip(wellpass_counts['Full_Name'], wellpass_counts['Total_Visits']))
        glofox_counts_dict  = dict(zip(glofox_counts['Full_Name'],  glofox_counts['Total_Visits']))

        all_wellpass_names = set(wellpass_counts['Full_Name'].tolist())
        all_glofox_names   = set(glofox_counts['Full_Name'].tolist())

        # Build suggestions (bi-directional, deduped)
        potential_matches = []

        # WP -> GF
        for wp_name in all_wellpass_names:
            wp_count = wellpass_counts_dict[wp_name]
            matches = find_potential_matches(wp_name, all_glofox_names, threshold=0.7)
            for match_name, similarity_score in matches:
                gf_count = glofox_counts_dict[match_name]
                potential_matches.append({
                    'Wellpass System Name': wp_name,
                    'Times in System Wellpass': wp_count,
                    'Glofox System Name': match_name,
                    'Times in System Glofox': gf_count,
                    'Similarity_Score': round(similarity_score, 3)
                })

        # GF -> WP (avoid duplicates)
        for gf_name in all_glofox_names:
            gf_count = glofox_counts_dict[gf_name]
            matches = find_potential_matches(gf_name, all_wellpass_names, threshold=0.7)
            for match_name, similarity_score in matches:
                wp_count = wellpass_counts_dict[match_name]
                duplicate_exists = any(
                    (existing['Wellpass System Name'] == match_name and existing['Glofox System Name'] == gf_name)
                    for existing in potential_matches
                )
                if not duplicate_exists:
                    potential_matches.append({
                        'Wellpass System Name': match_name,
                        'Times in System Wellpass': wp_count,
                        'Glofox System Name': gf_name,
                        'Times in System Glofox': gf_count,
                        'Similarity_Score': round(similarity_score, 3)
                    })

        step3_df = pd.DataFrame(potential_matches)
        if not step3_df.empty:
            step3_df = step3_df.sort_values(['Similarity_Score'], ascending=False).reset_index(drop=True)
            step3_df = step3_df.drop_duplicates(subset=['Wellpass System Name', 'Glofox System Name'])

        st.subheader("Review & Confirm, then click **Submit & Apply**")
        base_cols   = ['Wellpass System Name', 'Glofox System Name', 'Similarity_Score']
        review_base = (step3_df[base_cols].copy() if not step3_df.empty else pd.DataFrame(columns=base_cols))

        # 1) Auto-populate Yes/No by your 0.85 threshold
        if not review_base.empty:
            review_base['Confirm_Match'] = np.where(review_base['Similarity_Score'] >= 0.85, "Yes", "No")
        else:
            review_base['Confirm_Match'] = pd.Series(dtype=str)

        # Keep any prior user edits
        if st.session_state.review_df is not None and not st.session_state.review_df.empty:
            prev = st.session_state.review_df[base_cols + ['Confirm_Match']].copy()
            review_merged = review_base.merge(prev, on=base_cols, how='left', suffixes=('', '_prev'))
            review_merged['Confirm_Match'] = review_merged['Confirm_Match_prev'].fillna(review_merged['Confirm_Match'])
            review_merged = review_merged.drop(columns=['Confirm_Match_prev'])
        else:
            review_merged = review_base

        # 2) Use a form so it doesn't rerun while editing—only on submit
        with st.form("review_form", clear_on_submit=False):
            edited = st.data_editor(
                review_merged,
                use_container_width=True,
                num_rows="dynamic",
                hide_index=True,
                key="review_editor"
            )
            blanks = edited['Confirm_Match'].astype(str).str.strip().eq("").any() if not edited.empty else False
            submit_clicked = st.form_submit_button(
                "✅ Submit & Apply",
                disabled=blanks and not edited.empty,
                help="Applies your Yes/No and runs all calculations below"
            )

        # Persist what’s in the editor
        st.session_state.review_df = edited

        # Build mapping & unlock the rest only when submitted
        if submit_clicked:
            yes_rows = edited[edited['Confirm_Match'].astype(str).str.strip().str.lower().eq("yes")] if not edited.empty else pd.DataFrame(columns=edited.columns)
            approved_mapping = dict(zip(yes_rows['Glofox System Name'], yes_rows['Wellpass System Name']))
            st.session_state.approved_mapping = approved_mapping
            st.session_state.submitted_review = True
            st.success(f"Applied {len(approved_mapping)} approved matches. Calculating results below…")
        else:
            if not st.session_state.get("submitted_review", False):
                st.info("⬆️ Review the table above, then click **Submit & Apply** to proceed.")
                st.stop()

        # ---------------------------------------------------------
        # From here on: run all calculations using approved mapping
        # ---------------------------------------------------------
        glofox_canon = glofox_processed.copy()
        if st.session_state.approved_mapping:
            glofox_canon['Full_Name'] = glofox_canon['Full_Name'].replace(st.session_state.approved_mapping)

        st.divider()

        # ===============================
        # Step 1: Aggregate Totals (post-approval)
        # ===============================
        st.header("📊 Aggregate Totals")

        wp_counts = wellpass_processed['Full_Name'].value_counts().reset_index()
        wp_counts.columns = ['Full_Name', 'Total_Visits']
        wp_counts['System'] = 'Wellpass'

        gf_counts = glofox_canon['Full_Name'].value_counts().reset_index()
        gf_counts.columns = ['Full_Name', 'Total_Visits']
        gf_counts['System'] = 'Glofox'

        wp_counts_dict = dict(zip(wp_counts['Full_Name'], wp_counts['Total_Visits']))
        gf_counts_dict = dict(zip(gf_counts['Full_Name'], gf_counts['Total_Visits']))

        step1_df = pd.concat([wp_counts, gf_counts], ignore_index=True).sort_values('Full_Name').reset_index(drop=True)
        st.dataframe(step1_df)

        step1_excel = to_excel_download(step1_df, "Aggregate_Totals.xlsx")
        st.download_button(
            label="📥 Download Aggregate Totals",
            data=step1_excel,
            file_name="Aggregate_Totals.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.divider()

        # ===============================
        # Step 2: Differences (+ Missing Dates)
        # ===============================
        st.header("⚠️ Differences")

        all_wellpass_names = set(wp_counts['Full_Name'].tolist())
        all_glofox_names   = set(gf_counts['Full_Name'].tolist())

        differences_data = []
        matched_pairs = set()

        # Try exact match first; then fallback to similarity match for remaining
        for wp_name in sorted(all_wellpass_names):
            wp_count = wp_counts_dict[wp_name]
            if wp_name in all_glofox_names:
                gf_count = gf_counts_dict[wp_name]
                matched_pairs.add((wp_name, wp_name))
                difference = abs(gf_count - wp_count)
                differences_data.append({
                    'Wellpass System Name': wp_name,
                    'Glofox System Name': wp_name,
                    'Glofox': gf_count,
                    'Wellpass': wp_count,
                    'Difference': difference
                })
            else:
                matched_name, gf_count, _ = find_exact_or_high_similarity_match(
                    wp_name, all_glofox_names, gf_counts_dict, threshold=0.85
                )
                if matched_name:
                    matched_pairs.add((wp_name, matched_name))
                    difference = abs(gf_count - wp_count)
                    differences_data.append({
                        'Wellpass System Name': wp_name,
                        'Glofox System Name': matched_name,
                        'Glofox': gf_count,
                        'Wellpass': wp_count,
                        'Difference': difference
                    })
                else:
                    differences_data.append({
                        'Wellpass System Name': wp_name,
                        'Glofox System Name': '',
                        'Glofox': 0,
                        'Wellpass': wp_count,
                        'Difference': wp_count
                    })

        # Add remaining Glofox-only names
        matched_glofox_names = {pair[1] for pair in matched_pairs}
        remaining_gf = all_glofox_names - matched_glofox_names
        for gf_name in sorted(remaining_gf):
            gf_count = gf_counts_dict[gf_name]
            differences_data.append({
                'Wellpass System Name': '',
                'Glofox System Name': gf_name,
                'Glofox': gf_count,
                'Wellpass': 0,
                'Difference': gf_count
            })

        step2_df = pd.DataFrame(differences_data)
        step2_df = step2_df[step2_df['Difference'] > 0]
        step2_df = step2_df.sort_values('Wellpass System Name', na_position='last').reset_index(drop=True)

        # ---- Missing_Date_1..10 columns ----
        def to_date_set(df):
            # collapse to unique date objects
            dates = (df[['Full_Name', 'Date']]
                     .dropna(subset=['Full_Name', 'Date'])
                     .copy())
            dates['Date'] = pd.to_datetime(dates['Date'], errors='coerce').dt.date
            return dates.groupby('Full_Name')['Date'].apply(lambda s: set(s.tolist())).to_dict()

        wellpass_date_map = to_date_set(wellpass_processed)
        glofox_date_map   = to_date_set(glofox_canon)

        def compute_missing_dates(wp_name, gf_name):
            wp_dates = wellpass_date_map.get(wp_name, set()) if isinstance(wp_name, str) and wp_name else set()
            gf_dates = glofox_date_map.get(gf_name, set())   if isinstance(gf_name, str) and gf_name else set()

            if wp_dates and gf_dates:
                missing = sorted(wp_dates.symmetric_difference(gf_dates))
            elif wp_dates:
                missing = sorted(wp_dates)
            elif gf_dates:
                missing = sorted(gf_dates)
            else:
                missing = []
            return [d.isoformat() for d in missing[:10]]

        missing_cols = [f"Missing_Date_{i}" for i in range(1, 11)]
        for col in missing_cols:
            step2_df[col] = ""

        for idx, row in step2_df.iterrows():
            dates_list = compute_missing_dates(row.get('Wellpass System Name', ''), row.get('Glofox System Name', ''))
            for i, d in enumerate(dates_list):
                step2_df.at[idx, missing_cols[i]] = d

        st.dataframe(step2_df)

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

        # ===============================
        # Step 3: Reviewed Potential Name Differences (for reference/download)
        # ===============================
        st.header("📝 Reviewed Potential Name Differences (Your decisions)")
        st.dataframe(st.session_state.review_df if st.session_state.review_df is not None else pd.DataFrame())
        if st.session_state.review_df is not None and not st.session_state.review_df.empty:
            reviewed_excel = to_excel_download(st.session_state.review_df, "Reviewed_Potential_Matches.xlsx")
            st.download_button(
                "📥 Download Reviewed Potential Matches",
                data=reviewed_excel,
                file_name="Reviewed_Potential_Matches.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        st.divider()

        # ===============================
        # Step 4: Clients in One List Only
        # ===============================
        st.header("👥 Clients in One List Only")

        missing_clients = []
        wellpass_unmatched = set()
        glofox_unmatched = set()

        for wp_name in all_wellpass_names:
            matched_name, _, _ = find_exact_or_high_similarity_match(
                wp_name, all_glofox_names, gf_counts_dict, threshold=0.85
            )
            if not matched_name and wp_name not in all_glofox_names:
                wellpass_unmatched.add(wp_name)

        for gf_name in all_glofox_names:
            matched_name, _, _ = find_exact_or_high_similarity_match(
                gf_name, all_wellpass_names, wp_counts_dict, threshold=0.85
            )
            if not matched_name and gf_name not in all_wellpass_names:
                glofox_unmatched.add(gf_name)

        for name in wellpass_unmatched:
            missing_clients.append({'Name': name, 'List_Appeared': 'Wellpass', 'List_Missing': 'Glofox'})
        for name in glofox_unmatched:
            missing_clients.append({'Name': name, 'List_Appeared': 'Glofox', 'List_Missing': 'Wellpass'})

        step4_df = pd.DataFrame(missing_clients)
        if not step4_df.empty:
            step4_df = step4_df.sort_values(['List_Appeared', 'Name']).reset_index(drop=True)

        st.dataframe(step4_df)

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

        # ===============================
        # Summary + Complete Report
        # ===============================
        st.divider()
        st.header("📈 Summary")

        colA, colB, colC, colD = st.columns(4)
        with colA:
            st.metric("Total Wellpass Clients", len(all_wellpass_names))
        with colB:
            st.metric("Total Glofox Clients", len(all_glofox_names))
        with colC:
            st.metric("Clients with Differences", len(step2_df))
        with colD:
            st.metric("Potential Name Issues (suggestions shown)", len(step3_df))

        st.divider()
        st.header("Complete Report")

        all_data_sheets = {
            "1_Aggregate_Totals": step1_df,
            "2_Differences": step2_df if not step2_df.empty else pd.DataFrame([{"Note": "No differences found"}]),
            "3_Potential_Name_Differences_Reviewed": st.session_state.review_df if st.session_state.review_df is not None else pd.DataFrame([{"Note": "No review performed"}]),
            "4_Clients_One_List_Only": step4_df if not step4_df.empty else pd.DataFrame([{"Note": "All clients appear in both lists"}])
        }

        summary_data = {
            "Metric": [
                "Total Wellpass Clients",
                "Total Glofox Clients",
                "Clients with Visit Count Differences",
                "Potential Name Issues (suggestions shown)",
                "Clients Only in Wellpass",
                "Clients Only in Glofox"
            ],
            "Value": [
                len(all_wellpass_names),
                len(all_glofox_names),
                len(step2_df),
                len(step3_df),
                len({n for n in all_wellpass_names if n not in all_glofox_names}),
                len({n for n in all_glofox_names if n not in all_wellpass_names})
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        all_data_sheets["0_Summary"] = summary_df

        all_data_excel = create_multi_sheet_excel(all_data_sheets)
        st.download_button(
            label="Download Complete Reconciliation Report",
            data=all_data_excel,
            file_name="Complete_Client_Visit_Reconciliation_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="Downloads all reconciliation data in a single Excel file with separate sheets for each step"
        )

        st.success("✅ Reconciliation complete based on your approved matches.")

    except Exception as e:
        st.error(f"Error processing files: {str(e)}")
        st.info("Please ensure your Excel files have the correct format and column names.")
else:
    st.info("👆 Please upload both Wellpass and Glofox Excel files to begin the reconciliation process.")
