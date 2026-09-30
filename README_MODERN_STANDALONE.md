# Cloud-Based Online Examination & Evaluation System

A Flask-based online examination system with a modern HTML/CSS/JavaScript frontend, PostgreSQL support for cloud deployment, automatic MCQ evaluation, manual descriptive-answer evaluation, results, and performance analytics.

## Technology Stack

- **Frontend:** HTML, CSS, JavaScript, Bootstrap
- **Backend:** Flask (Python)
- **Database:** PostgreSQL for cloud deployment; SQLite fallback for local development
- **Cloud:** Render deployment with Gunicorn and PostgreSQL

## Features

- Student, teacher, and admin login
- Teacher exam creation and publishing
- MCQ and descriptive questions
- Automatic MCQ scoring
- Manual evaluation of descriptive answers by teachers
- Results and rankings
- Student performance analytics
- PostgreSQL/cloud database support
- Render deployment configuration

## Local Setup

1. Create a virtual environment: `python -m venv venv`
2. Activate it on Windows: `venv\Scripts\activate`
3. Install packages: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`.
5. Leave `DATABASE_URL` empty for local SQLite, or provide a PostgreSQL connection string.
6. Run: `python app.py`
7. Open `http://127.0.0.1:5000` in your browser.

## Demo Accounts

- Admin: `admin@example.com` / `admin123`
- Teacher: `teacher@example.com` / `teacher123`
- Student: `student@example.com` / `student123`

## Cloud Deployment

The project includes `Procfile` and `render.yaml`. On Render, the Flask app runs with Gunicorn and uses the provisioned PostgreSQL database through `DATABASE_URL`.

No AI service or AI API is required for this version.
