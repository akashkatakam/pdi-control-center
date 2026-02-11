# PDI Control Center

🚀 A comprehensive FastAPI-based web application for managing vehicle Pre-Delivery Inspection (PDI) operations, inventory tracking, and logistics across multiple branches.

## Features

### 🏠 Overview Dashboard
- Real-time statistics for PDI status, transit, and stock
- Universal search (chassis, customer name, DC number)
- Quick action links to common tasks
- Multi-branch support with hierarchy

### 📋 Task Manager
- Assign PDI tasks to mechanics
- Real-time monitoring of in-progress work
- Track assignments by branch
- Status updates and workflow management

### 🚗 Inventory Management
- **Stock Levels**: View aggregated stock by model/variant/color
- **Vehicle Locator**: Search by chassis number or vehicle attributes
- Multi-branch visibility
- Expandable model groups with detailed breakdown

### 📦 Logistics
- **Receive Inward**: Process incoming shipments
- **Email Integration**: Automatically fetch S08 files from HMSI emails
- **Transfer/Outward**: Manage stock transfers between branches
- Load reference tracking

### 📈 Reports & Analytics
- Summary reports (Outward/Inward)
- Detailed sales and transfers
- PDI performance metrics
- Inventory snapshots
- Date range filtering

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Tailwind CSS, HTMX
- **Database**: SQLAlchemy ORM (MySQL/PostgreSQL)
- **Session Management**: Starlette SessionMiddleware
- **Data Processing**: Pandas

## Installation

### Prerequisites

- Python 3.8+
- MySQL or PostgreSQL database
- Git

### Setup

1. **Clone the repository**
```bash
git clone https://github.com/akashkatakam/pdi-control-center.git
cd pdi-control-center
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure database**

Create a `.env` file:
```env
DATABASE_URL=mysql+pymysql://user:password@localhost/pdi_db
SECRET_KEY=your-secret-key-here
```

5. **Run database migrations** (if applicable)
```bash
# Your migration commands here
```

6. **Run the application**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

7. **Access the application**

Open your browser and navigate to: `http://localhost:8000`

## Project Structure

```
pdi-control-center/
├── main.py                 # FastAPI application entry point
├── database.py             # Database configuration
├── models.py               # SQLAlchemy models
├── routers/                # API route handlers
│   ├── __init__.py
│   ├── auth.py
│   ├── overview.py
│   ├── task_manager.py
│   ├── inventory.py
│   ├── logistics.py
│   └── reports.py
├── services/               # Business logic
│   ├── branch_service.py
│   ├── stock_service.py
│   ├── report_service.py
│   └── email_import_service.py
├── templates/              # Jinja2 HTML templates
│   ├── base.html
│   ├── overview.html
│   ├── task_manager.html
│   ├── inventory_*.html
│   ├── logistics_*.html
│   └── reports.html
├── static/                 # Static assets
│   ├── css/
│   └── js/
├── requirements.txt        # Python dependencies
└── README.md
```

## Key Features Implementation

### Multi-Branch Support

The application supports branch hierarchy:
- **Head Branches**: Can view and manage sub-branches
- **Sub-Branches**: Managed by head branches
- Uses `branch_service.get_managed_branches()` to get all branches in hierarchy

### PDI Workflow

1. Vehicle arrives at branch (recorded in `VehicleMaster`)
2. Sale is created (recorded in `SalesRecord`)
3. Manager assigns PDI task to mechanic via Task Manager
4. Mechanic completes PDI
5. Status updated to "PDI Complete"
6. Vehicle ready for delivery

### Role-Based Access

- **Owner**: Full access to all features
- **PDI Manager**: Task assignment and monitoring
- **Mechanic**: View assigned tasks
- **Branch Staff**: Branch-specific access

## API Endpoints

### Authentication
- `GET /login` - Login page
- `POST /login` - Login submission
- `GET /logout` - Logout

### Overview
- `GET /overview` - Dashboard
- `GET /overview/search?query=` - Universal search

### Task Manager
- `GET /task-manager` - Task management page
- `POST /task-manager/assign` - Assign task to mechanic

### Inventory
- `GET /inventory/stock-levels` - Stock overview
- `GET /inventory/locator` - Vehicle search
- `POST /inventory/locator/search` - Search vehicles

### Logistics
- `GET /logistics/receive` - Receive inward page
- `POST /logistics/receive-load` - Receive a load
- `POST /logistics/email-scan` - Scan emails for S08
- `GET /logistics/transfer` - Transfer page

### Reports
- `GET /reports` - Reports page
- `POST /reports/generate` - Generate report

## Database Models

Key tables:
- `Branch` - Branch information
- `BranchHierarchy` - Parent-child relationships
- `VehicleMaster` - Vehicle inventory
- `SalesRecord` - Sales and PDI tracking
- `User` - User accounts and roles

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is proprietary and confidential.

## Support

For support, contact: [akashkatakam@gmail.com](mailto:akashkatakam@gmail.com)

## Acknowledgments

- Built for Katakam Motors dealership network
- Integrates with HMSI (Honda Motorcycle & Scooter India) systems
- Replaces legacy Streamlit application with modern FastAPI architecture
