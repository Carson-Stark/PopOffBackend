"""
Utility script to visualize video embeddings and text category embeddings using dimensionality reduction and clustering.

This script loads video embeddings from a CSV file and text category embeddings from a numpy file,
scales and reduces their dimensionality using UMAP, clusters the embeddings with KMeans,
and visualizes the results with Plotly including video thumbnails with colored borders and text labels.

It also loads time snapshot data for animation of user interests over time.

Usage:
    python visualize_embeddings.py
"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sklearn.manifold import TSNE  # or use umap
import umap
import plotly.express as px
import plotly.graph_objects as go
import requests
from PIL import Image, ImageOps
from io import BytesIO
import base64
import plotly.io as pio
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib import cm

# Load data
df = pd.read_csv('video_embeddings.csv')
text_data = np.load("api/data/category_embeddings_trends.npy", allow_pickle=True).item()
text_df = pd.DataFrame({'text': text_data['categories']})
text_embeddings = np.array(text_data['embeddings'])

# Scale embeddings
video_embs = np.vstack(df['embedding'].apply(lambda x: np.fromstring(x.strip('[]'), sep=',')))
scalar = StandardScaler().fit(video_embs)
video_embs_scaled = scalar.transform(video_embs)
text_embs_scaled = StandardScaler().fit_transform(text_embeddings)

# Combine all embeddings
all_embeddings = np.vstack([video_embs_scaled, text_embs_scaled])

# Dimensionality reduction
reducer = umap.UMAP(n_components=2, random_state=42)
embedding_2d = reducer.fit_transform(all_embeddings)

embedding_2d[:, 0] *= 1.8  # Stretch X-axis

# Split reduced embeddings
video_2d = embedding_2d[:len(df)]
text_2d = embedding_2d[len(df):]
df['x'] = video_2d[:, 0]
df['y'] = video_2d[:, 1]
text_df['x'] = text_2d[:, 0]
text_df['y'] = text_2d[:, 1]

# Cluster the video embeddings in 2D space
num_clusters = 30
kmeans = KMeans(n_clusters=num_clusters, random_state=42)
text_df['cluster'] = kmeans.fit_predict(text_2d)
df['cluster'] = kmeans.predict(video_2d)

# Assign a bright distinct color to each cluster
from itertools import cycle
unique_clusters = text_df['cluster'].unique()
color_palette = px.colors.qualitative.Alphabet  # larger set of distinct colors
color_cycle = cycle(color_palette)
cluster_color_map = {cluster: next(color_cycle) for cluster in unique_clusters}
df['hex_color'] = df['cluster'].map(cluster_color_map)

# Assign same color to text categories based on nearest video cluster
text_df['hex_color'] = text_df['cluster'].map(cluster_color_map)

# Download and encode images with colored border
def encode_image_with_border(url, border_color):
    try:
        response = requests.get(url)
        img = Image.open(BytesIO(response.content)).convert('RGB').resize((64, 64))
        bordered_img = ImageOps.expand(img, border=4, fill=border_color)
        buffer = BytesIO()
        bordered_img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except:
        return None


df['img_base64'] = df.apply(lambda row: encode_image_with_border(row['thumbnail_link'], row['hex_color']), axis=1)
x_range = df['x'].max() - df['x'].min()
y_range = df['y'].max() - df['y'].min()
image_size = 0.025 * max(x_range, y_range)

# Plot setup
fig = go.Figure()

# Plot video thumbnails with cluster-based colored border
for _, row in df.iterrows():
    if row['img_base64']:
        fig.add_layout_image(
            dict(
                source=row['img_base64'],
                x=row['x'],
                y=row['y'],
                xref="x",
                yref="y",
                sizex=image_size,
                sizey=image_size,
                xanchor="center",
                yanchor="middle",
                layer="above",
                opacity=0.8
            )
        )

# Plot text category labels with cluster-based color
for _, row in text_df.iterrows():
    fig.add_trace(go.Scatter(
        x=[row['x']],
        y=[row['y']],
        text=[row['text']],
        mode='text',
        textposition='middle center',
        textfont=dict(size=10, color=row['hex_color']),
        opacity=0.6,
        hoverinfo='text'
    ))

# Final layout
fig.update_layout(
    title="Video Embeddings Visualization (Cluster Colored - Bright)",
    dragmode='pan',
    plot_bgcolor='black',
    paper_bgcolor='black',
    xaxis=dict(
        visible=False,
        showgrid=False,
        gridcolor='gray',
        zeroline=False,
        showticklabels=False,
        scaleanchor='y',
        scaleratio=1
    ),
    yaxis=dict(
        visible=False,
        showgrid=False,
        gridcolor='gray',
        zeroline=False,
        showticklabels=False
    ),
    autosize=True,
    height=None,
    width=None,
    margin=dict(l=0, r=0, t=50, b=0)
)

import os
from glob import glob

# Load all time snapshot .npy files (ensure they are ordered)
snapshot_folder = "user_snapshots_0.55"
snapshot_files = sorted(glob(os.path.join(snapshot_folder, "*.npy")))

# Initialize frames list for animation
animation_frames = []
user_colors = px.colors.qualitative.Light24

min_marker_size = 5
max_marker_size = 20

for i, snapshot_path in enumerate(snapshot_files):
    snapshot_data = np.load(snapshot_path, allow_pickle=True)
    
    # Extract embeddings and weights
    embeddings = np.array([item['embedding'] for item in snapshot_data])
    weights = np.array([item['weight'] for item in snapshot_data])
    
    # Normalize weights for marker sizing
    norm_weights = (weights - weights.min()) / (weights.max() - weights.min() + 1e-6)
    marker_sizes = min_marker_size + norm_weights * (max_marker_size - min_marker_size)

    # Scale and reduce
    embeddings_scaled = scalar.transform(embeddings)
    embeddings_2d_interests = reducer.transform(embeddings_scaled)

    # Frame for this snapshot
    frame = go.Frame(
        data=[
            go.Scatter(
                x=embeddings_2d_interests[:, 0],
                y=embeddings_2d_interests[:, 1],
                mode="markers",
                marker=dict(
                    size=marker_sizes,
                    color='yellow',
                    opacity=1,
                    line=dict(width=1, color='white')
                ),
                name=f"Snapshot {i}",
                hovertext=[f"Interest {j}<br>Weight: {weights[j]:.3f}" for j in range(len(embeddings_2d_interests))],
                showlegend=False
            )
        ],
        name=f"frame{i}"
    )
    animation_frames.append(frame)

# Add frames and animation controls
fig.frames = animation_frames

fig.update_layout(
    updatemenus=[dict(
        type="buttons",
        showactive=False,
        y=1.05,
        x=1.15,
        xanchor="left",
        yanchor="top",
        buttons=[dict(
            label="Play",
            method="animate",
            args=[None, {
                "frame": {"duration": 500, "redraw": True},
                "fromcurrent": True,
                "transition": {"duration": 200, "easing": "linear"}
            }]
        )]
    )],
    sliders=[dict(
        steps=[dict(method="animate", args=[[f.name], {"frame": {"duration": 300, "redraw": True},
                                                       "mode": "immediate"}],
                    label=f"Snapshot {i}")
               for i, f in enumerate(animation_frames)],
        active=0,
        x=0.1,
        y=0,
        xanchor="left",
        yanchor="bottom",
        len=0.9
    )]
)

pio.show(fig, config={"responsive": True, "scrollZoom": True})
