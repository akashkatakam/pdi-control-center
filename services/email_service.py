# services/email_service.py
import imaplib
import email
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Tuple, Optional
import models


def fetch_and_process_emails(
        db: Session,
        branch_id: str,
        email_config: dict,
        color_map: dict = None,
        progress_callback=None
) -> Tuple[List[dict], List[str]]:
    """
    Connects to email and filters emails by SENDER.
    Parses S08 files and extracts vehicle shipment data.
    """
    all_new_data = []
    logs = []

    def log(msg):
        logs.append(msg)
        print(f"[EMAIL SERVICE] {msg}")
        if progress_callback:
            progress_callback(msg)

    # 1. Load Decoder Mappings
    mappings = db.query(models.ProductMapping).all()
    decoder_map = {
        (m.model_code.strip(), m.variant_code.strip()): (m.real_model, m.real_variant)
        for m in mappings
    }

    log(f"Loaded {len(decoder_map)} product mappings")

    # 2. Extract config
    acc_name = email_config.get('name', 'Unknown')
    host = email_config.get('host', 'imap.gmail.com')
    user = email_config.get('user')
    password = email_config.get('password')
    target_sender = email_config.get('sender_filter', '')

    if not user or not password:
        log(f"❌ Missing email credentials for {acc_name}")
        return [], logs

    if not target_sender:
        log(f"❌ No 'sender_filter' defined for {acc_name}.")
        return [], logs

    log(f"🔌 Connecting to {host}...")

    try:
        with imaplib.IMAP4_SSL(host, 993) as mail:
            mail.login(user, password)
            mail.select("inbox")

            log(f"🎯 Searching emails from: {target_sender}")
            status, messages = mail.search(None, f'(FROM "{target_sender}")')

            if status != "OK" or not messages[0]:
                log(f"ℹ️ No emails found from target sender.")
                return [], logs

            email_ids = messages[0].split()
            # Scan Last 30 Emails
            recent_ids = list(reversed(email_ids))[:30]

            log(f"🔎 Found {len(email_ids)} emails. Scanning recent {len(recent_ids)}...")

            s08_files_found = 0
            target_count = 5

            for idx, eid in enumerate(recent_ids):
                if s08_files_found >= target_count:
                    break

                # Feedback every few emails
                if idx % 5 == 0:
                    log(f"   ⏳ Scanning email {idx + 1}/{len(recent_ids)}...")

                try:
                    _, msg_data = mail.fetch(eid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    content, filename = _extract_text_attachment(msg)

                    if not content:
                        continue

                    s08_files_found += 1

                    # 1. Peek Load Ref
                    first_ref = _peek_load_ref(content)
                    if not first_ref:
                        log(f"      ⚠️ Skipped {filename}: No Load Ref found.")
                        continue

                    # 2. Duplicate Check
                    exists = db.query(models.VehicleMaster).filter(
                        models.VehicleMaster.load_reference_number == first_ref
                    ).first()

                    if exists:
                        log(f"      ⏭️ Skipped Load {first_ref} (Already in DB).")
                        continue

                    # 3. Parse with Color Map
                    parsed = _parse_s08_content(content, acc_name, decoder_map, color_map)
                    if parsed:
                        all_new_data.extend(parsed)
                        log(f"      ✅ Imported Load {first_ref} ({len(parsed)} vehicles).")

                except Exception as e:
                    log(f"      ⚠️ Error parsing email {eid.decode()}: {e}")

            if s08_files_found == 0:
                log("   ℹ️ No S08 attachments found in recent emails.")
            else:
                log(f"✨ Scan complete. Found {len(all_new_data)} new vehicles.")

    except Exception as e:
        log(f"❌ Connection Error: {str(e)}")

    return all_new_data, logs


def _extract_text_attachment(msg):
    """Extract S08 text file from email attachment"""
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
            continue
        filename = part.get_filename() or ""
        if "s08" in filename.lower() and ".txt" in filename.lower():
            try:
                return part.get_payload(decode=True).decode("utf-8", errors='ignore'), filename
            except:
                return None, None
    return None, None


def _peek_load_ref(content):
    """Peek at first load reference in S08 file"""
    for line in content.splitlines():
        if len(line) < 180 or line[25] != 'B':
            continue
        return line[84:97].strip()
    return None


def _parse_s08_content(content, source_name, decoder_map, color_map=None):
    """Parse S08 fixed-width format and extract vehicle data"""
    batch = []
    for line in content.splitlines():
        if len(line) < 180 or line[25] != 'B':
            continue
        try:
            m_code = line[27:38].strip()
            v_code = line[38:45].strip()
            real_m, real_v = decoder_map.get((m_code, v_code), (m_code, v_code))

            # Color Mapping Logic
            raw_color_code = line[45:60].strip()
            final_color = raw_color_code
            if color_map:
                final_color = color_map.get(raw_color_code, raw_color_code)

            batch.append({
                'load_reference': line[84:97].strip(),
                'chassis_no': line[113:130].strip(),
                'engine_no': line[173:186].strip(),
                'color': final_color,
                'model': real_m,
                'variant': real_v,
            })
        except Exception as e:
            print(f"Error parsing line: {e}")
            continue
    return batch


def create_vehicles_from_email_data(db: Session, vehicle_data_list: List[dict], branch_id: str):
    """
    Create VehicleMaster records from parsed S08 data
    Groups by load_reference and creates in-transit vehicles
    """
    loads_created = {}

    for vehicle_data in vehicle_data_list:
        load_ref = vehicle_data['load_reference']

        # Check if vehicle already exists
        existing = db.query(models.VehicleMaster).filter(
            models.VehicleMaster.chassis_no == vehicle_data['chassis_no']
        ).first()

        if existing:
            print(f"Vehicle {vehicle_data['chassis_no']} already exists, skipping...")
            continue

        # Create new vehicle record
        new_vehicle = models.VehicleMaster(
            chassis_no=vehicle_data['chassis_no'],
            engine_no=vehicle_data['engine_no'],
            model=vehicle_data['model'],
            variant=vehicle_data['variant'],
            color=vehicle_data['color'],
            status="In Transit",
            load_reference_number=load_ref,
            current_branch_id=vehicle_data.get('source_branch') or branch_id,
        )
        db.add(new_vehicle)

        # Track loads
        if load_ref not in loads_created:
            loads_created[load_ref] = 0
        loads_created[load_ref] += 1

    db.commit()

    return loads_created


def get_pending_loads_for_branch(db: Session, branch_id: str):
    """
    Get all pending loads (vehicles in transit) grouped by load reference
    """
    # Get all in-transit vehicles
    in_transit_vehicles = db.query(models.VehicleMaster).filter(
        models.VehicleMaster.status == "In Transit",
        models.VehicleMaster.current_branch_id == branch_id
    ).all()

    # Group by load reference
    loads = {}
    for vehicle in in_transit_vehicles:
        load_ref = vehicle.load_reference_number
        if not load_ref:
            continue

        if load_ref not in loads:
            loads[load_ref] = {
                'load_reference': load_ref,
                'source_branch': vehicle.current_branch_id or 'Unknown',
                'vehicles': [],
                'vehicle_count': 0
            }

        loads[load_ref]['vehicles'].append({
            'chassis_no': vehicle.chassis_no,
            'model': vehicle.model,
            'variant': vehicle.variant,
            'color': vehicle.color,
            'received': False
        })
        loads[load_ref]['vehicle_count'] += 1

    return list(loads.values())
