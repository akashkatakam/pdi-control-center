# PDI Control Center

Vehicle tracking and PDI (Pre-Delivery Inspection) operations management system built with FastAPI.

## Features

- **Role-based access control** (Owner, PDI, Mechanic)
- **Vehicle inventory management**
- **PDI task tracking**
- **Real-time updates** with HTMX
- **Mobile-responsive UI** with Tailwind CSS

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy
- **Frontend:** Jinja2 templates, Tailwind CSS, HTMX
- **Database:** AWS Aurora (MySQL)

## Project Structure

```
pdi-control-center/
├── main.py                 # FastAPI application entry point
├── database.py             # Database configuration
├── models.py              # SQLAlchemy models
├── constants.py           # Application constants
│
├── routers/               # API routes
│   ├── auth.py           # Authentication routes
│   ├── pdi.py            # PDI dashboard routes
│   └── mechanic.py       # Mechanic task routes
│
├── services/              # Business logic layer
│   ├── stock_service.py
│   ├── sales_service.py
│   └── ...
│
├── utils/                 # Utility functions
│   └── auth_utils.py
│
├── templates/             # Jinja2 HTML templates
│   ├── base.html
│   ├── login.html
│   ├── pdi_dashboard.html
│   └── mechanic_tasks.html
│
└── static/                # Static files (CSS, JS, images)
    ├── css/
    └── js/
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/akashkatakam/pdi-control-center.git
cd pdi-control-center
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your Aurora database credentials
```

### 5. Run the application

```bash
uvicorn main:app --reload
```

Access the application at `http://localhost:8000`

## Migration from Streamlit

This project replaces the Streamlit-based vehicle tracking system with a FastAPI implementation to:

- ✅ Eliminate unnecessary page reloads
- ✅ Reduce database calls
- ✅ Improve performance
- ✅ Maintain existing service layer and business logic

## Deployment

Recommended platforms:
- **AWS App Runner** (same VPC as Aurora)
- **Railway** (easiest setup)
- **Render** (free tier available)
- **Fly.io** (global edge deployment)

## License

MIT
