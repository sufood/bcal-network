import logging
from pathlib import Path

import networkx as nx
from pyvis.network import Network

logger = logging.getLogger(__name__)


def export_graphml(G: nx.Graph, path: str | Path) -> None:
    nx.write_graphml(G, str(path))
    logger.info("Exported GraphML to %s", path)


def export_json(G: nx.Graph) -> dict:
    nodes = [{"id": n, **G.nodes[n]} for n in G.nodes]
    edges = [{"source": u, "target": v, **d} for u, v, d in G.edges(data=True)]
    return {"nodes": nodes, "edges": edges}


def export_pyvis_html(G: nx.Graph, path: str | Path, title: str = "KOL Network") -> None:
    net = Network(height="750px", width="100%", bgcolor="#222222", font_color="white")
    net.from_nx(G)
    net.toggle_physics(True)
    net.save_graph(str(path))
    logger.info("Exported pyvis HTML to %s", path)


TIER_COLORS = {1: "#ff4b4b", 2: "#ffa421", 3: "#21c354", 4: "#00d4ff"}
DEFAULT_COLOR = "#888888"


def export_pyvis_html_for_dashboard(
    G: nx.Graph,
    title: str = "KOL Network",
    height: str = "600px",
    highlight_node: str | None = None,
) -> str:
    """Generate pyvis HTML string for embedding in Streamlit via st.components.v1.html()."""
    net = Network(height=height, width="100%", bgcolor="#0e1117", font_color="white")

    for node_id, data in G.nodes(data=True):
        color = TIER_COLORS.get(data.get("tier"), DEFAULT_COLOR)
        size = 10 + (data.get("influence_score") or 0) * 0.3
        label = data.get("label", str(node_id)[:8])
        hover = (
            f"{label}\n"
            f"Tier: {data.get('tier') or 'N/A'}\n"
            f"Score: {data.get('influence_score') or 'N/A'}\n"
            f"{data.get('institution', '')}"
        )
        border = 3 if node_id == highlight_node else 1
        net.add_node(
            node_id, label=label, title=hover, color=color,
            size=size, borderWidth=border,
        )

    for u, v, data in G.edges(data=True):
        weight = data.get("weight", 1)
        net.add_edge(u, v, value=weight, title=f"Shared papers: {weight}")

    net.set_options("""{
        "physics": {
            "barnesHut": {"gravitationalConstant": -3000, "springLength": 150},
            "stabilization": {"iterations": 200, "fit": true}
        },
        "interaction": {"hover": true, "tooltipDelay": 100}
    }""")

    html = net.generate_html()

    # Disable physics after stabilization so the graph stops moving
    stabilize_script = (
        '<script type="text/javascript">'
        'network.once("stabilizationIterationsDone", function() {'
        '  network.setOptions({physics: false});'
        '});'
        '</script>'
    )
    html = html.replace("</body>", stabilize_script + "</body>")

    return html
