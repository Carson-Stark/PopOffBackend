import numpy as np
import random
import openai
import os

client = openai.Client(api_key=os.getenv("OPENAI_API_KEY"))

def generate_video_embedding(video_description):
    return generate_embedding(video_description)

def generate_embedding(text):
    embedding = client.embeddings.create(input=[text], model="text-embedding-3-small").data[0].embedding
    print("Got embedding")
    return np.array(embedding)

# Load the .npy file
data = np.load('api/data/category_embeddings.npy', allow_pickle=True).item()

categories = data['categories']
embeddings = data['embeddings']

def compare_embeddings(embedding1, embedding2):
    return np.dot(embedding1, embedding2)

# Get most similar categories
def get_most_similar_categories(embedding, categories, embeddings, top_n=5):
    # Calculate similarity
    similarities = [compare_embeddings(embedding, emb) for emb in embeddings]
    
    # Get indices of top n most similar categories
    top_indices = np.argsort(similarities)[::-1][:top_n]
    
    # Get top n most similar categories
    top_categories = [categories[i] for i in top_indices]
    top_similarities = [float(similarities[i]) for i in top_indices]
    
    return top_categories, top_similarities

def get_average_embedding(embedding1, embedding2):
    print ("Similarity between embeddings: ", compare_embeddings(embedding1, embedding2))
    return (embedding1 + embedding2) / 2

def print_similar_categories(embedding, categories, embeddings, top_n=5):
    top_categories, top_similarities = get_most_similar_categories(embedding, categories, embeddings, top_n)
    
    for i, category in enumerate(top_categories):
        print(f"{i+1}. {category} : {top_similarities[i]}")

# Test the function
rnd_idx1 = random.randint(0, len(categories) - 1)
rnd_idx2 = random.randint(0, len(categories) - 1)
test_embedding1 = embeddings[rnd_idx1]
test_category1 = categories[rnd_idx1]

print ("Test category 1: ", test_category1)
print_similar_categories(test_embedding1, categories, embeddings, top_n=5)

mod = input("Modification:")
test_embedding2 = generate_embedding(mod)
average_embedding = get_average_embedding(test_embedding1, test_embedding2)

#get the new category
print_similar_categories(average_embedding, categories, embeddings, top_n=5)
