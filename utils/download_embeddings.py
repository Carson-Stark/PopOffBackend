"""
Utility script to download video embeddings and related thumbnail links from the PostgreSQL database.

This script connects to the database using environment variables for credentials,
fetches the video_id, embedding, and thumbnail_link from the api_postrecord table,
and saves the data as a CSV file named 'video_embeddings.csv'.

Usage:
    python download_embeddings.py
"""

import psycopg2
from decouple import config
import pandas as pd
from sqlalchemy import create_engine

DB_HOST = config('DB_HOST', default='database-1.c9k6y8qk8zdq.us-east-2.rds.amazonaws.com')
DB_PORT = int(config('DB_PORT', default='5432'))
DB_NAME = config('DB_NAME', default='popoffdb')
USER = config('DB_USER', default='postgres')
DB_PASSWORD = config('DB_PASSWORD', default='replace-this-with-your-db-password')

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=USER,
        password=DB_PASSWORD
    )
    print("✅ Connection successful!")
    conn.close()
except Exception as e:
    print("❌ Connection failed:", e)

EMBEDDING_TABLE = 'api_postrecord'
# RDS connection string — already works on your server
RDS_URI = f'postgresql://{USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

engine = create_engine(RDS_URI)
df = pd.read_sql(f'SELECT video_id, embedding, thumbnail_link FROM {EMBEDDING_TABLE}', engine)

df.to_csv('video_embeddings.csv', index=False)
print("✅ CSV saved.")
