import requests

HF_TOKEN = "your_token_here"

def transcribe_audio_with_whisper(audio_path):
    api_url = "https://api-inference.huggingface.co/models/openai/whisper-large"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}"
    }

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    response = requests.post(api_url, headers=headers, data=audio_bytes)
    
    if response.status_code == 200:
        return response.json()["text"]
    else:
        print("Error:", response.status_code, response.text)
        return None

def caption_image_with_blip(image_path):
    api_url = "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-base"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}"
    }

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = requests.post(api_url, headers=headers, data=image_bytes)

    if response.status_code == 200:
        return response.json()[0]["generated_text"]
    else:
        print("Error:", response.status_code, response.text)
        return None
