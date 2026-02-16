# services/sales_service.py
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import models
from models import IST_TIMEZONE


def get_sales_records_by_status(db: Session, status: str, branch_id: str = None) -> List[Dict[str, Any]]:
    """Get sales records by status"""
    query = db.query(models.SalesRecord).filter(models.SalesRecord.fulfillment_status == status)
    if branch_id:
        query = query.filter(models.SalesRecord.Branch_ID == branch_id)

    records = query.all()
    return [record_to_dict(record) for record in records]


def get_sales_records_for_mechanic(db: Session, mechanic_username: str, branch_id: str = None) -> List[Dict[str, Any]]:
    """Get sales records assigned to a mechanic"""
    query = db.query(models.SalesRecord).filter(
        models.SalesRecord.pdi_assigned_to == mechanic_username,
        models.SalesRecord.fulfillment_status == 'PDI In Progress'
    )
    if branch_id:
        query = query.filter(models.SalesRecord.Branch_ID == branch_id)

    records = query.all()
    return [record_to_dict(record) for record in records]


def get_completed_sales_last_48h(db: Session, branch_id: str = None) -> List[Dict[str, Any]]:
    """Get completed sales in last 48 hours"""
    time_48h_ago = datetime.now(IST_TIMEZONE) - timedelta(days=2)
    query = db.query(models.SalesRecord).filter(
        models.SalesRecord.fulfillment_status.in_(['PDI Complete', 'Insurance Done', 'TR Done']),
        models.SalesRecord.pdi_completion_date >= time_48h_ago
    )
    if branch_id:
        query = query.filter(models.SalesRecord.Branch_ID == branch_id)

    records = query.all()
    return [record_to_dict(record) for record in records]


def record_to_dict(record: models.SalesRecord) -> Dict[str, Any]:
    """Convert SalesRecord SQLAlchemy object to dictionary"""
    return {
        'id': record.id,
        'dc_number': record.DC_Number,
        'chassis_no': record.chassis_no,
        'engine_no': record.engine_no,
        'customer_name': record.Customer_Name,
        'model': record.Model,
        'variant': record.Variant,
        'color': record.Paint_Color,
        'date_of_sale': record.Timestamp.strftime('%d-%m-%Y'),
        'fulfillment_status': record.fulfillment_status,
        'pdi_assigned_to': record.pdi_assigned_to,
        'pdi_completion_date': record.pdi_completion_date,
        'Branch_ID': record.Branch_ID,
        # Add any other fields you need
    }


def assign_pdi_mechanic(db: Session, sale_id: int, mechanic_name: str):
    """Assign PDI to a mechanic"""
    try:
        record = db.query(models.SalesRecord).filter(models.SalesRecord.id == sale_id).first()
        if record:
            record.pdi_assigned_to = mechanic_name
            record.fulfillment_status = "PDI In Progress"
            db.commit()
            return True, "Mechanic assigned successfully"
        return False, "Sales record not found"
    except Exception as e:
        db.rollback()
        return False, str(e)


def complete_pdi(db: Session, sale_id: int, chassis_no: str, engine_no: str = None, dc_number: str = None):
    """Complete PDI and link vehicle"""
    try:
        record = db.query(models.SalesRecord).filter(models.SalesRecord.id == sale_id).first()
        vehicle = db.query(models.VehicleMaster).filter(models.VehicleMaster.chassis_no == chassis_no).first()

        if not record:
            return False, "Sales Record not found."
        if not vehicle:
            return False, f"Chassis '{chassis_no}' not found."

        if vehicle.status != 'In Stock':
            if vehicle.sale_id == sale_id:
                record.fulfillment_status = "PDI Complete"
                record.pdi_completion_date = datetime.now(IST_TIMEZONE)
                db.commit()
                return True, "Already allotted. PDI marked complete."
            return False, f"Vehicle is '{vehicle.status}' (Linked to ID: {vehicle.sale_id})."

        # Link and Update
        vehicle.status = 'Allotted'
        vehicle.sale_id = sale_id

        record.chassis_no = vehicle.chassis_no
        record.engine_no = vehicle.engine_no if not engine_no else engine_no
        record.fulfillment_status = "PDI Complete"
        record.pdi_completion_date = datetime.now(IST_TIMEZONE)

        if dc_number:
            record.dc_number = dc_number

        db.commit()
        return True, "Success: PDI Complete and Vehicle Linked!"
    except Exception as e:
        db.rollback()
        return False, f"Database Error: {e}"
