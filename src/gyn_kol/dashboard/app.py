import httpx
import networkx as nx
import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from gyn_kol.graph.export import export_pyvis_html_for_dashboard

API_BASE = "http://127.0.0.1:8002"

st.set_page_config(page_title="GYN KOL Dashboard", layout="wide")
st.title("GYN KOL Identification Dashboard")

# Sidebar filters
st.sidebar.header("Filters")
tier_filter = st.sidebar.selectbox("Tier", [None, 1, 2, 3, 4], format_func=lambda x: "All" if x is None else f"Tier {x}")
state_filter = st.sidebar.selectbox("State", [None, "NSW", "VIC", "QLD", "WA", "SA", "TAS", "NT", "ACT"], format_func=lambda x: "All" if x is None else x)
page_size = st.sidebar.slider("Results per page", 10, 500, 50)

# Build query params
params: dict = {"page": 1, "page_size": page_size}
if tier_filter:
    params["tier"] = tier_filter
if state_filter:
    params["state"] = state_filter

# Tabs
tab_table, tab_detail, tab_graph, tab_summary, tab_override = st.tabs(
    ["Clinician Table", "Detail View", "Network Graph", "Tier Summary", "Manual Override"]
)

try:
    resp = httpx.get(f"{API_BASE}/clinicians", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    clinicians = data.get("items", [])
    total = data.get("total", 0)
except httpx.ConnectError:
    st.error("Could not connect to API. Is the server running? (`make run`)")
    clinicians = []
    total = 0
except httpx.HTTPStatusError as e:
    st.error(f"API error {e.response.status_code}: {e.response.text}")
    clinicians = []
    total = 0
except Exception as e:
    st.error(f"Unexpected error: {e}")
    clinicians = []
    total = 0

# Tab 1: Clinician Table
with tab_table:
    st.subheader(f"Clinicians ({total} total)")
    if clinicians:
        df = pd.DataFrame(clinicians)
        display_cols = [c for c in ["name_display", "tier", "influence_score", "early_adopter_score", "state", "specialty", "source_flags"] if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True)
    else:
        st.info("No clinicians found. Run the ingestion pipeline first.")

# Tab 2: Detail View
with tab_detail:
    st.subheader("Clinician Detail")
    if clinicians:
        names = {c["name_display"]: c["clinician_id"] for c in clinicians if c.get("name_display")}
        selected = st.selectbox("Select clinician", list(names.keys()))
        if selected:
            cid = names[selected]
            try:
                detail_resp = httpx.get(f"{API_BASE}/clinicians/{cid}", timeout=10)
                detail = detail_resp.json()

                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Influence Score", detail.get("influence_score", "N/A"))
                    st.metric("Early Adopter", detail.get("early_adopter_score", "N/A"))
                    st.metric("Tier", detail.get("tier", "N/A"))
                with col2:
                    st.write(f"**Institution:** {detail.get('primary_institution', 'N/A')}")
                    st.write(f"**State:** {detail.get('state', 'N/A')}")
                    st.write(f"**Subspecialty:** {detail.get('specialty', 'N/A')}")
                    st.write(f"**Publications:** {detail.get('pub_count', 0)}")
                    st.write(f"**Trials:** {detail.get('trial_count', 0)}")
                    st.write(f"**Grants:** {detail.get('grant_count', 0)}")

                if detail.get("profile_summary"):
                    st.subheader("Profile Summary")
                    st.write(detail["profile_summary"])
                if detail.get("engagement_approach"):
                    st.subheader("Engagement Approach")
                    st.write(detail["engagement_approach"])

                # Publications
                with st.expander("Publications", expanded=True):
                    try:
                        pub_resp = httpx.get(
                            f"{API_BASE}/clinicians/{cid}/publications", timeout=10,
                        )
                        pub_resp.raise_for_status()
                        pubs = pub_resp.json()
                        if pubs:
                            for p in pubs:
                                title = p.get("title") or "Untitled"
                                journal = p.get("journal") or ""
                                pub_date = p.get("pub_date") or ""
                                doi = p.get("doi")
                                pmid = p.get("pmid")

                                if doi:
                                    link = f"https://doi.org/{doi}"
                                elif pmid:
                                    link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                                else:
                                    link = None

                                if link:
                                    st.markdown(f"**[{title}]({link})**")
                                else:
                                    st.markdown(f"**{title}**")

                                meta_parts = [x for x in [journal, pub_date] if x]
                                if meta_parts:
                                    st.caption(" · ".join(meta_parts))
                        else:
                            st.info("No publications found.")
                    except Exception as exc:
                        st.error(f"Error loading publications: {exc}")

                # Ego network
                with st.expander("Co-author Network", expanded=False):
                    max_neighbors = st.slider(
                        "Max co-authors shown", 5, 50, 20, key="ego_max_neighbors",
                    )
                    try:
                        ego_resp = httpx.get(
                            f"{API_BASE}/graph/clinician-graph/{cid}/ego",
                            params={"radius": 1, "max_neighbors": max_neighbors},
                            timeout=30,
                        )
                        ego_resp.raise_for_status()
                        ego_data = ego_resp.json()

                        if ego_data["nodes"]:
                            displayed = len(ego_data["nodes"]) - 1  # exclude ego node
                            st.caption(f"Showing top {displayed} co-authors by shared papers")
                            G_ego = nx.Graph()
                            for n in ego_data["nodes"]:
                                G_ego.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
                            for e in ego_data["edges"]:
                                G_ego.add_edge(e["source"], e["target"], weight=e.get("weight", 1))
                            html = export_pyvis_html_for_dashboard(
                                G_ego, title=f"Network: {selected}",
                                height="450px", highlight_node=cid,
                            )
                            components.html(html, height=500, scrolling=True)
                        else:
                            st.info("No co-authorship connections found.")
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 404:
                            st.info("No co-authorship connections found for this clinician.")
                        else:
                            st.error(f"Error loading ego network: {exc}")
                    except Exception as exc:
                        st.error(f"Error loading ego network: {exc}")

            except Exception as e:
                st.error(f"Error loading detail: {e}")

# Tab 3: Network Graph
with tab_graph:
    st.subheader("Co-authorship Network")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        graph_tier = st.selectbox(
            "Filter by Tier", [None, 1, 2, 3, 4],
            format_func=lambda x: "All" if x is None else f"Tier {x}",
            key="graph_tier",
        )
    with col_f2:
        graph_state = st.selectbox(
            "Filter by State",
            [None, "NSW", "VIC", "QLD", "WA", "SA", "TAS", "NT", "ACT"],
            format_func=lambda x: "All" if x is None else x,
            key="graph_state",
        )
    with col_f3:
        min_papers = st.slider("Min shared papers", 1, 10, 2, key="min_papers")

    max_nodes = st.slider("Max nodes displayed", 20, 300, 100, key="max_nodes")

    graph_params: dict = {"min_weight": min_papers, "max_nodes": max_nodes}
    if graph_tier:
        graph_params["tier"] = graph_tier
    if graph_state:
        graph_params["state"] = graph_state

    try:
        graph_resp = httpx.get(
            f"{API_BASE}/graph/clinician-graph", params=graph_params, timeout=30,
        )
        graph_resp.raise_for_status()
        graph_data = graph_resp.json()

        if graph_data["nodes"]:
            st.caption(
                f"{len(graph_data['nodes'])} clinicians, "
                f"{len(graph_data['edges'])} connections"
            )
            G = nx.Graph()
            for n in graph_data["nodes"]:
                G.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
            for e in graph_data["edges"]:
                G.add_edge(e["source"], e["target"], weight=e.get("weight", 1))

            html = export_pyvis_html_for_dashboard(G, title="KOL Co-authorship Network")
            components.html(html, height=650, scrolling=True)
        else:
            st.info("No connections found with current filters. Try reducing the minimum shared papers.")
    except httpx.ConnectError:
        st.error("Could not connect to API for graph data.")
    except Exception as e:
        st.error(f"Error loading graph: {e}")

# Tab 4: Tier Summary
with tab_summary:
    st.subheader("Tier Distribution")
    if clinicians:
        df = pd.DataFrame(clinicians)
        if "tier" in df.columns:
            tier_counts = df["tier"].value_counts().sort_index()
            tier_df = pd.DataFrame({"Tier": tier_counts.index.astype(str), "Count": tier_counts.values})
            fig_bar = px.bar(tier_df, x="Tier", y="Count", title="Clinicians by Tier")
            st.plotly_chart(fig_bar, use_container_width=True)

        if "state" in df.columns:
            state_counts = df["state"].value_counts()
            fig_pie = px.pie(values=state_counts.values, names=state_counts.index, title="Clinicians by State")
            st.plotly_chart(fig_pie, use_container_width=True)

# Tab 5: Manual Override
with tab_override:
    st.subheader("Score Override")
    if clinicians:
        names = {c["name_display"]: c["clinician_id"] for c in clinicians if c.get("name_display")}
        override_target = st.selectbox("Select clinician to override", list(names.keys()), key="override_select")
        if override_target:
            cid = names[override_target]
            col1, col2, col3 = st.columns(3)
            with col1:
                new_influence = st.number_input("Influence Score", 0.0, 100.0, step=1.0, key="inf_override")
            with col2:
                new_ea = st.number_input("Early Adopter Score", 0.0, 10.0, step=0.5, key="ea_override")
            with col3:
                new_tier = st.selectbox("Tier", [1, 2, 3, 4], key="tier_override")

            changed_by = st.text_input("Changed by", value="manual", key="changed_by")

            if st.button("Apply Override"):
                try:
                    override_resp = httpx.patch(
                        f"{API_BASE}/clinicians/{cid}/score",
                        json={
                            "influence_score": new_influence,
                            "early_adopter_score": new_ea,
                            "tier": new_tier,
                            "changed_by": changed_by,
                        },
                        timeout=10,
                    )
                    if override_resp.status_code == 200:
                        st.success(f"Override applied: {override_resp.json()}")
                    else:
                        st.error(f"Override failed: {override_resp.text}")
                except Exception as e:
                    st.error(f"Error: {e}")
