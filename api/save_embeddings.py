import numpy as np
import openai
import os

client = openai.Client(api_key=os.getenv("OPENAI_API_KEY"))

def generate_video_embedding(video_description):
    return generate_embedding(video_description)

def generate_embedding(text):
    embedding = client.embeddings.create(input=[text], model="text-embedding-3-small").data[0].embedding
    print("Got embedding")
    return np.array(embedding)

def compare_embeddings(embedding1, embedding2):
    return np.dot(embedding1, embedding2)

# File paths
input_file = 'data/video_catagories.txt'
output_file = 'data/catagory_embeddings.npy'

# Open the file with video categories
with open(input_file, 'r') as f:
    video_categories = [line.strip() for line in f.readlines()]  # Read and clean each line

# Prepare storage for categories and embeddings
categories = []
embeddings = []

# Process each category
for category in video_categories:
    # Generate embedding for the category
    embedding = generate_embedding(category)
    
    # Store the category and its embedding
    categories.append(category)
    embeddings.append(embedding)

# Save categories and embeddings in a .npy file
np.save(output_file, {'categories': categories, 'embeddings': np.array(embeddings)})

print(f"Embeddings for video categories have been stored in '{output_file}'")
