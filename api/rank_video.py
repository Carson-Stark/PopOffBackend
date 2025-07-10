import numpy as np
from django.conf import settings
from .models import UserData
import math
from datetime import datetime, timezone

def compare_embeddings(embedding1, embedding2):
    embedding1 = np.array(embedding1)
    embedding2 = np.array(embedding2)
    return np.dot(embedding1, embedding2)
    
LEARNING_RATE = 0.1
MATCH_THRESHOLD = 0.55

def update_user_data(video, user_data, engagement):
    video_embedding = video.embedding
    user_current_embeddings = user_data.user_preference_embeddings

    # Find most similar embedding in user_current_embeddings or make new one
    max_interest_score = 0
    best_interest_index = -1
    overlapping_interests = []
    
    for index, interest_group in enumerate(user_current_embeddings):
        interest_embedding = interest_group["embedding"]
        interest_score = compare_embeddings(video_embedding, interest_embedding)
        #print(f"Interest score for index {index}: {interest_score}")
        if interest_score > max_interest_score:
            max_interest_score = interest_score
            best_interest_index = index
        if interest_score > MATCH_THRESHOLD:  # Identify overlapping interests
            #print(f"Overlapping interest found at index {index} with score {interest_score}")
            overlapping_interests.append((index, interest_score))

    # If no strong match, create a new interest group
    if best_interest_index == -1 or max_interest_score < MATCH_THRESHOLD:
        #print("Creating new interest group")
        new_user_embedding = video_embedding
        weight = engagement
        user_current_embeddings.append({"embedding": new_user_embedding, "weight": weight})
        user_data.user_preference_embeddings = user_current_embeddings
        user_data.save()
        #np.save(f'user_snapshots/{user_data.user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.npy', user_current_embeddings)
        return

    #print("Best interest index: ", best_interest_index)
    #print("Interest score: ", max_interest_score)    

    # Update the best matching embedding with weighted adjustment
    matching_interest = user_current_embeddings[best_interest_index]
    matching_interest_embedding = np.array(matching_interest["embedding"])
    matching_interest_weight = np.array(matching_interest["weight"])
    new_user_embedding = matching_interest_embedding + (video_embedding - matching_interest_embedding) * engagement * LEARNING_RATE
    new_user_embedding = new_user_embedding / np.linalg.norm(new_user_embedding) #normalize

    def calculate_delta(w, e, alpha=0.1, scale=10):
        sigmoid_factor = w * (1 - w)
        delta = alpha * (e - 0.25)
        return scale * sigmoid_factor * delta
    
    delta_weight = 0.5 * calculate_delta(matching_interest_weight, engagement)
    new_user_weight = min(max(matching_interest_weight + delta_weight, 0), 1)  # Clamp to [0, 1]
    
    # merge interests if they are similar with the new one
    for index, interest_group in enumerate(user_current_embeddings):
        if index == best_interest_index or len(interest_group["embedding"]) == 0:
            continue
        if compare_embeddings(interest_group["embedding"], new_user_embedding) > MATCH_THRESHOLD:
            #print(f"Merging interest group at index {index} with score {interest_score}")
            new_user_weight = (new_user_weight + interest_group["weight"]) / 2
            new_user_embedding = (new_user_embedding + interest_group["embedding"]) / 2
            new_user_embedding = new_user_embedding / np.linalg.norm(new_user_embedding) #normalize
            user_current_embeddings.pop(index)
            break

    user_current_embeddings[best_interest_index] = {"embedding": new_user_embedding.tolist(), "weight": new_user_weight}
    
    user_data.user_preference_embeddings = user_current_embeddings
    user_data.save()

    # save weights and embeddings to npy file with datetime
    #np.save(f'user_snapshots/{user_data.user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.npy', user_current_embeddings)

def get_days_since_upload(video):
    return (video.date_uploaded - datetime.now(timezone.utc)).days

def score_interest(user_interests, other, threshold=0.25):
    
    interest_score = 0
    best_score = 0
    similar_interests = []

    for interest_group in user_interests:
        if len(interest_group["embedding"]) == 0:
            continue

        similarity = compare_embeddings(interest_group["embedding"], other)
        if similarity > threshold:
            similar_interests.append(interest_group)
            interest_score += similarity * interest_group["weight"]
        
        if similarity * interest_group["weight"] > best_score:
            best_score = similarity * interest_group["weight"]

    #print (f"Found {len(similar_interests)} similar interests")

    if len(similar_interests) > 1:
        #reward for having multiple similar interests
        interest_score = min(interest_score / (len(similar_interests) / 2.0), 1)  # Cap interest score at 1
        
    if len(similar_interests) == 0:
        # No similar interests, return 0
        interest_score = best_score

    return interest_score

def calculate_video_rank(user_data, video):
    user_interests = user_data.user_preference_embeddings

    if len(video.embedding) == 0:
        return (0, 1)

    interest_score = score_interest(user_interests, video.embedding, MATCH_THRESHOLD)

    recentness_score = max(10 - get_days_since_upload(video), 0) / 10 # percentage out of 10 days since upload
    engagement_rate = 0 if video.views <= 0 else (video.likes + video.comments) / video.views # percentage of views that engaged with video

    interest_weight = 0.6
    recentness_weight = 0.2
    engagement_weight = 0.2

    return (interest_score, interest_score * interest_weight + recentness_score * recentness_weight + engagement_rate * engagement_weight)

def calculate_engagement_score(video_duration, watch_time, liked, commented, viewed_comments):
    if video_duration <= 0:
        return 0

    # Parameters
    MAX_WATCH_TIME = 120  # Cap benefit at 2 minutes
    max_interaction_score = 6.0  # Full engagement from all actions

    # Normalize watch time (non-linear reward)
    watch_percentage = min(watch_time / (video_duration / 1000), 1.0)
    time_factor = math.sqrt(min(watch_time, MAX_WATCH_TIME)) / math.sqrt(MAX_WATCH_TIME)

    # Interaction component
    interaction_score = 0.0
    if liked:
        interaction_score += 2.0
    if commented:
        interaction_score += 3.0
    if viewed_comments:
        interaction_score += 1.0

    interaction_score /= max_interaction_score  # Normalize to [0, 1]

    # Blend components (tune weights if needed)
    #print(watch_percentage)
    engagement = (0.3 * watch_percentage) + 0.3 * time_factor + (0.4 * interaction_score)

    # Clamp to [0, 1] for safety
    engagement = min(1.0, max(0.0, engagement))

    #print(f"Engagement Score: {engagement:.4f}")
    return engagement

def output_user_preferences(user_data):

    categories = np.load("api/data/catagory_embeddings.npy", allow_pickle=True).item()
    cat_embeddings = categories["embeddings"]
    cat_text = categories["categories"]

    user_interests = user_data.user_preference_embeddings

    scores = [0] * len(cat_embeddings)

    for i, cat_embedding in enumerate(cat_embeddings):
        scores[i] = score_interest(user_interests, cat_embedding)

    #print (f"Scores: {scores}")

    def softmax(x, temperature=1.0):
        e_x = np.exp((x - np.max(x)) / temperature)
        return e_x / e_x.sum()

    adjusted_scores = [s - min(scores) for s in scores]
    percentages = softmax(np.array(adjusted_scores), 0.1)

    return dict(zip(cat_text, percentages))
