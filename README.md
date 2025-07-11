# PopOff Backend

PopOff is a short form video social media mobile app designed to replicate the core features of TikTok. The app allows users to create accounts, upload and share videos, interact with other users through likes, comments, and follows, and discover content through an intelligent recommendation algorithm. Built with a full stack approach, PopOff leverages React Native Expo for the mobile frontend, Django REST Framework for the backend API, PostgreSQL for data storage, and AWS for cloud infrastructure. The project was created as a challenge to build and deploy a TikTok clone within 24 hours, with the goal of launching on both the App Store and Play Store.

> View the frontend repo and demo videos here: https://github.com/Carson-Stark/PopOffFrontend

## Features

- User account creation and authentication
- Video upload, storage, and streaming
- Like, comment, and follow functionality for user interaction
- Intelligent recommendation algorithm for personalized content discovery
- Backend API built with Django REST Framework
- Mobile frontend built with React Native Expo
- PostgreSQL database for data persistence
- AWS cloud infrastructure for storage and deployment

## Installation / Setup

### Backend (Django)

1. Clone this repository:

   ```bash
   git clone https://github.com/Carson-Stark/TiktokServer.git
   cd TiktokServer
   ```

2. Create and activate a Python virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root with the necessary environment variables, for example:

   ```
   SECRET_KEY=your_django_secret_key
   DB_NAME=your_database_name
   DB_USER=your_database_user
   DB_PASSWORD=your_database_password
   DB_HOST=your_database_host
   DB_PORT=your_database_port
   AWS_BUCKET=your_aws_bucket_name
   AWS_ACCESS_KEY_ID=your_aws_access_key_id
   AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
   AWS_REGION=your_aws_region
   OPENAI_API_KEY=your_openai_api_key
   ```

5. Run database migrations:

   ```bash
   python manage.py migrate
   ```

6. Run the development server:

   ```bash
   python manage.py runserver
   ```

### Usage

- The backend API will be available at `http://localhost:8000/`.
- Use the API endpoints to interact with the app data.
- Access the Django admin interface at `http://localhost:8000/admin/` to manage users, videos, and other data models.
- For production deployment, configure your web server and environment variables accordingly.

## Deployment on AWS

To deploy the backend on AWS, follow these steps:

1. Run the Django development server to listen on all interfaces:

   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

2. Start the Celery worker for asynchronous task processing:

   ```bash
   celery -A ByteverseProject worker --loglevel=info
   ```

3. Use systemctl to manage production services:

   ```bash
   sudo systemctl restart gunicorn
   sudo systemctl reload nginx
   sudo systemctl restart celery
   ```

These commands assume you have Gunicorn and Nginx configured for your Django app, and Celery set up for background tasks. Adjust configurations as needed for your AWS environment.

## Database Design

![tiktok4k mp4 00_00_29_05 Still001](https://github.com/user-attachments/assets/c5c3245c-5a17-4b00-871c-9a25076cdc24)

## API Endpoints

| **Category**               | **Method** | **Endpoint**                     |
|----------------------------|------------|-----------------------------------|
| **Authentication**        | POST       | /auth/login                      |
|                            | POST       | /auth/register                   |
|                            | POST       | /auth/logout                     |
|                            | GET        | /auth/check_token                |
| **Media / Video**          | POST       | /media/upload                    |
|                            | POST       | /media/upload_hls                |
|                            | POST       | /media/post                      |
|                            | GET        | /media/get_feed                  |
|                            | GET        | /media/get_user_posts            |
|                            | DELETE     | /media/delete_post               |
| **Post Interaction**       | POST       | /post/like                       |
|                            | POST       | /post/add_comment                |
|                            | GET        | /post/get_comments               |
|                            | POST       | /post/update_posts_engagement    |
|                            | POST       | /post/report_video               |
| **User Interaction**       | POST       | /user/add_follower               |
|                            | POST       | /user/block_user                 |
|                            | DELETE     | /user/delete_account             |
|                            | GET        | /user/search                     |
|                            | GET        | /user/get_followers              |
|                            | POST       | /user/reset_user_engagement      |
|                            | GET        | /user/get_preferences            |

## Project Structure

- `api/`: Contains the Django backend app with the following key components:
  - `__init__.py`: Marks the directory as a Python package.
  - `admin.py`: Registers models with the Django admin interface for management.
  - `apps.py`: Configuration for the Django app.
  - `models.py`: Defines the database schema with Django models.
  - `serializers.py`: Converts complex data types like querysets and model instances to native Python datatypes for rendering into JSON or other content types.
  - `views.py`: Contains the API views handling HTTP requests and responses.
  - `urls.py`: Defines URL routing for the API endpoints.
  - `tasks.py`: Contains asynchronous task definitions for Celery workers.
  - `rank_video.py`: Implements video ranking logic including user preference embedding updates, engagement scoring, and video ranking calculations based on interest similarity, recentness, and engagement metrics.
  - `download.py`, `local_video_ai.py`, `save_embeddings.py`, `test_embeddings.py`: Modules handling specific backend functionalities such as video processing, AI integration, embedding management, and testing.
  - `data/`: Directory containing static data files used by the API, such as lists of censored words and video categories.
- `utils/`: Contains utility scripts for data processing and maintenance:
  - `download_embeddings.py`: Downloads video embeddings and thumbnail links from the database and saves them as a CSV file.
  - `update_hls_paths.py`: Manages HLS video path updates in the database and S3 file migrations.
  - `video_convert.py`: Processes videos by converting them to HLS format, uploading to S3, and updating database records.
  - `visualize_embeddings.py`: Visualizes video and text category embeddings using dimensionality reduction and clustering.

## Extending Functionality

To add new features or extend the backend API:

1. **Add Models**: Define new data models in `api/models.py`.
2. **Create Serializers**: Add serializers for your models in `api/serializers.py` to control data representation.
3. **Add Views**: Implement API views or viewsets in `api/views.py` to handle requests.
4. **Configure URLs**: Register new endpoints in `api/urls.py`.
5. **Migrations**: Run `python manage.py makemigrations` and `python manage.py migrate` to apply database changes.
6. **Testing**: Add tests in `api/tests.py` to ensure your changes work correctly.

This modular structure allows easy expansion of the backend API to support new features and frontend requirements.
