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
