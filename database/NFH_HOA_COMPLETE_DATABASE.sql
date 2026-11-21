-- NFH HOA FRESH INSTALLATION SQL (MySQL/MariaDB)
-- Reconstructed from the user-supplied consolidated schema on 2026-10-30.
-- Not tested against a running database server; deploy only after staging verification.
-- WARNING: Do not use this fresh-install script to upgrade a populated database.

-- NFH-HOA consolidated schema. FRESH EMPTY DATABASE ONLY.
-- DO NOT run this against a populated database: CREATE TABLE IF NOT EXISTS does not upgrade existing columns.
-- Original SQL scripts backed up separately; refer to DATABASE_UPGRADE_GUIDE.md.
-- DEVELOPMENT CANDIDATE ONLY: tables copied from included reference and additive schema.
-- NOT validated against running MySQL, app queries or complete legacy migrations.
-- Do not execute against populated databases. No demonstration users inserted.
CREATE DATABASE IF NOT EXISTS northfairwayportal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE northfairwayportal;
-- ---------------------------------------------------------------------------
-- USERS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (

    id INT AUTO_INCREMENT PRIMARY KEY,

    first_name VARCHAR(100) NOT NULL,

    middle_name VARCHAR(100) DEFAULT NULL,

    last_name VARCHAR(100) NOT NULL,

    suffix VARCHAR(20) DEFAULT NULL,

    gender VARCHAR(30) DEFAULT 'NA',

    dob DATE DEFAULT NULL,

    civil_status VARCHAR(30) DEFAULT 'Single',

    block VARCHAR(50) DEFAULT NULL,

    lot VARCHAR(50) DEFAULT NULL,

    address_line VARCHAR(180) DEFAULT NULL,

    homeowner_public_id VARCHAR(32) DEFAULT NULL,

    verification_status ENUM('Pending Verification','Verified','Rejected') NOT NULL DEFAULT 'Verified',

    verified_by VARCHAR(100) DEFAULT NULL,

    verified_at DATETIME DEFAULT NULL,

    household INT DEFAULT 1,

    email VARCHAR(150) NOT NULL,

    username VARCHAR(80) NOT NULL,

    mobile VARCHAR(20) NOT NULL,

    password_hash VARCHAR(255) NOT NULL,

    role ENUM('Homeowner','Secretary','Treasurer','President','Vice President','Board Director','Admin','Renter') NOT NULL DEFAULT 'Homeowner',

    status ENUM('Active','Inactive') NOT NULL DEFAULT 'Active',

    profile_image VARCHAR(255) DEFAULT NULL,

    e_signature_path VARCHAR(255) DEFAULT NULL,

    e_signature_updated_at DATETIME DEFAULT NULL,

    emergency_contact_name VARCHAR(150) DEFAULT NULL,

    emergency_contact_number VARCHAR(20) DEFAULT NULL,

    emergency_contact_relationship VARCHAR(50) DEFAULT NULL,

    email_notifications TINYINT(1) NOT NULL DEFAULT 1,

    sms_notifications TINYINT(1) NOT NULL DEFAULT 0,

    date_joined DATE DEFAULT (CURRENT_DATE),

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_users_username (username),

    UNIQUE KEY uq_users_email (email),

    UNIQUE KEY uq_homeowner_public_id (homeowner_public_id),

    KEY idx_users_role_status (role, status),

    KEY idx_users_verification (role, verification_status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- FEES (standard pricing configuration)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fees (

    item_name VARCHAR(100) PRIMARY KEY,

    amount DECIMAL(10,2) NOT NULL,

    proposed_amount DECIMAL(10,2) DEFAULT NULL,

    status ENUM('Active','Pending Executive Approval') NOT NULL DEFAULT 'Active'

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;



INSERT INTO fees (item_name, amount, status) VALUES

    ('Gate Pass', 50.00, 'Active'),

    ('Proof of Residency', 50.00, 'Active'),

    ('Certificate of Improvement', 50.00, 'Active'),

    ('Certificate of Membership', 100.00, 'Active'),

    ('Move-in Gate Pass', 50.00, 'Active'),

    ('Move-out Gate Pass', 50.00, 'Active'),

    ('Vehicle Sticker (4 Wheels)', 200.00, 'Active'),

    ('Vehicle Sticker (2/3 Wheels)', 100.00, 'Active'),

    ('Renters/Tenants Information Form', 50.00, 'Active'),

    ('Monthly Dues', 100.00, 'Active')

ON DUPLICATE KEY UPDATE item_name = item_name;
-- ---------------------------------------------------------------------------
-- REQUESTS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS requests (

    id VARCHAR(40) PRIMARY KEY,

    user_id INT NOT NULL,

    request_type VARCHAR(100) NOT NULL,

    category VARCHAR(60) DEFAULT 'Document Request',

    submission_type ENUM('Query','Problem') NOT NULL DEFAULT 'Query',

    assigned_officer VARCHAR(100) DEFAULT NULL,

    fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,

    details LONGTEXT DEFAULT NULL,

    attachment VARCHAR(255) DEFAULT NULL,

    remarks TEXT DEFAULT NULL,

    purpose VARCHAR(120) DEFAULT NULL,

    purpose_details TEXT DEFAULT NULL,

    payment_reference VARCHAR(120) DEFAULT NULL,

    official_receipt_no VARCHAR(120) DEFAULT NULL,

    payment_date DATE DEFAULT NULL,

    ready_for_release_at DATETIME DEFAULT NULL,

    issued_at DATETIME DEFAULT NULL,

    issued_by VARCHAR(150) DEFAULT NULL,

    sticker_valid_from DATE DEFAULT NULL,

    sticker_valid_until DATE DEFAULT NULL,

    document_template_id INT DEFAULT NULL,

    document_prepared_at DATETIME DEFAULT NULL,

    status ENUM('Submitted','Under Review','Checked','For Correction',

                'Pending Executive Approval','Approved','Awaiting Dues Clearance','Awaiting Payment Verification',

                'Ready for Payment & Release','Paid - Awaiting Release','Ready for Release','Issued / Completed','Rejected',

                'Paid and Approved','Cancelled') NOT NULL DEFAULT 'Submitted',

    payment_status ENUM('Unpaid','Paid','Not Required') NOT NULL DEFAULT 'Unpaid',

    cancellation_reason TEXT DEFAULT NULL,

    executive_decision_reason VARCHAR(80) DEFAULT NULL,

    executive_decision_details TEXT DEFAULT NULL,

    executive_decided_by VARCHAR(150) DEFAULT NULL,

    executive_decided_role VARCHAR(50) DEFAULT NULL,

    executive_decided_at DATETIME DEFAULT NULL,

    cancelled_by VARCHAR(100) DEFAULT NULL,

    edit_access_granted_at DATETIME DEFAULT NULL,

    edit_access_expires_at DATETIME DEFAULT NULL,

    edit_access_granted_by VARCHAR(150) DEFAULT NULL,

    edit_access_reason TEXT DEFAULT NULL,

    edit_access_expired_at DATETIME DEFAULT NULL,

    date_submitted DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    last_updated DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    KEY idx_requests_user_status (user_id, status),

    KEY idx_requests_status_payment (status, payment_status),

    KEY idx_requests_submitted (date_submitted),

    KEY idx_requests_assigned_status (assigned_officer, status),

    KEY idx_requests_type_status (request_type, status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- REQUEST HISTORY — transaction history separate from the administrative audit trail
CREATE TABLE IF NOT EXISTS request_history (

    id INT AUTO_INCREMENT PRIMARY KEY,

    request_id VARCHAR(40) NOT NULL,

    action VARCHAR(120) NOT NULL,

    previous_status VARCHAR(80) DEFAULT NULL,

    new_status VARCHAR(80) DEFAULT NULL,

    actor_name VARCHAR(150) DEFAULT NULL,

    actor_role VARCHAR(50) DEFAULT NULL,

    remarks TEXT DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,

    KEY idx_request_history_request (request_id, created_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ADMIN-MANAGED DOCUMENT / SERVICE TYPES
CREATE TABLE IF NOT EXISTS service_types (

    id INT AUTO_INCREMENT PRIMARY KEY,

    service_name VARCHAR(100) NOT NULL UNIQUE,

    category VARCHAR(60) NOT NULL DEFAULT 'Document Request',

    fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,

    initial_reviewer ENUM('Secretary','Treasurer','Shared') NOT NULL DEFAULT 'Secretary',

    requires_executive TINYINT(1) NOT NULL DEFAULT 1,

    requires_payment TINYINT(1) NOT NULL DEFAULT 1,

    requires_dues_clearance TINYINT(1) NOT NULL DEFAULT 1,

    purpose_required TINYINT(1) NOT NULL DEFAULT 1,

    release_role ENUM('Secretary','Treasurer','Initial Reviewer') NOT NULL DEFAULT 'Secretary',

    form_template VARCHAR(40) NOT NULL DEFAULT 'generic',

    description VARCHAR(255) DEFAULT NULL,

    status ENUM('Active','Inactive') NOT NULL DEFAULT 'Active',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;



INSERT INTO service_types

(service_name,category,fee,initial_reviewer,requires_executive,requires_payment,requires_dues_clearance,purpose_required,release_role,form_template,description) VALUES

('Gate Pass','Document Request',50.00,'Treasurer',1,1,1,1,'Secretary','gate-pass','Entry or exit pass for construction materials and authorized access.'),

('Proof of Residency','Document Request',50.00,'Secretary',1,1,1,1,'Secretary','proof-residency','Official certification of residency within North Fairway Homes.'),

('Certificate of Improvement','Document Request',50.00,'Secretary',1,1,1,1,'Secretary','cert-improvement','Certification related to approved property improvements or renovation.'),

('Certificate of Membership','Document Request',100.00,'Secretary',1,1,1,1,'Secretary','cert-membership','Official certification of active HOA membership.'),

('Move-in Gate Pass','Property & Moving',50.00,'Secretary',1,1,1,0,'Secretary','move-in','Authorization for a scheduled move-in activity.'),

('Move-out Gate Pass','Property & Moving',50.00,'Secretary',1,1,1,0,'Secretary','move-out','Authorization for a scheduled move-out activity.'),

('Vehicle Sticker Application','Vehicle Services',0.00,'Shared',1,1,1,0,'Secretary','vehicle-sticker','Application for an HOA vehicle identification sticker.'),

('Renters/Tenants Information Form','Tenant Services',50.00,'Shared',1,1,1,0,'Secretary','tenant-form','Registration of renter or tenant information for HOA records.')

ON DUPLICATE KEY UPDATE service_name=VALUES(service_name);
-- REQUEST CONCERNS — non-payable communication linked to an existing request
CREATE TABLE IF NOT EXISTS request_concerns (

    id INT AUTO_INCREMENT PRIMARY KEY,

    request_id VARCHAR(40) NOT NULL,

    user_id INT NOT NULL,

    assigned_role ENUM('Secretary','Treasurer') NOT NULL,

    concern_text TEXT NOT NULL,

    subject VARCHAR(150) NOT NULL DEFAULT 'Request Concern',

    response_text TEXT DEFAULT NULL,

    status ENUM('Open','Under Review','Responded','Resolved') NOT NULL DEFAULT 'Open',

    responded_by VARCHAR(150) DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    responded_at DATETIME DEFAULT NULL,

    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    KEY idx_concern_role_status (assigned_role,status),

    KEY idx_concern_request_status (request_id,status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- MONTHLY DUES (per-homeowner recurring dues ledger, used by Missing Dues flow)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monthly_dues (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    due_month DATE NOT NULL,

    amount DECIMAL(10,2) NOT NULL,

    status ENUM('Unpaid','Paid','Adjusted') NOT NULL DEFAULT 'Unpaid',

    settled_at DATETIME DEFAULT NULL,

    settled_by VARCHAR(100) DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    UNIQUE KEY uq_monthly_dues_user_month (user_id, due_month)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- FINANCIAL ADJUSTMENTS (Missing Monthly Dues — Treasurer applies directly,
-- no Executive approval step per current requirements)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_adjustments (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    homeowner_name VARCHAR(200) NOT NULL,

    monthly_due DECIMAL(10,2) NOT NULL,

    missing_months INT NOT NULL,

    proposed_adjustment DECIMAL(10,2) NOT NULL,

    previous_balance DECIMAL(10,2) DEFAULT NULL,

    new_balance DECIMAL(10,2) DEFAULT NULL,

    reason TEXT DEFAULT NULL,

    submitted_by VARCHAR(100) NOT NULL,

    status ENUM('Applied','Reversed') NOT NULL DEFAULT 'Applied',

    decided_by VARCHAR(100) DEFAULT NULL,

    decision_remarks TEXT DEFAULT NULL,

    decided_at DATETIME DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- ALERTS (in-app notifications)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    `text` TEXT NOT NULL,

    unread TINYINT(1) NOT NULL DEFAULT 1,

    `time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- NOTIFICATION LOG (email + in-app delivery record, used for dedupe)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_log (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    channel VARCHAR(20) NOT NULL,

    subject VARCHAR(255) DEFAULT NULL,

    body TEXT DEFAULT NULL,

    recipient VARCHAR(150) DEFAULT NULL,

    related_type VARCHAR(50) DEFAULT NULL,

    related_id VARCHAR(60) DEFAULT NULL,

    dedupe_key VARCHAR(150) DEFAULT NULL,

    status VARCHAR(20) DEFAULT NULL,

    sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    KEY idx_dedupe (dedupe_key)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- AUDIT LOGS (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (

    id INT AUTO_INCREMENT PRIMARY KEY,

    username VARCHAR(80) DEFAULT NULL,

    role VARCHAR(30) DEFAULT NULL,

    action VARCHAR(150) NOT NULL,

    item VARCHAR(150) DEFAULT NULL,

    prev_val TEXT DEFAULT NULL,

    new_val TEXT DEFAULT NULL,

    `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- HOA SETTINGS (key/value store — Treasurer contact info, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hoa_settings (

    setting_key VARCHAR(100) PRIMARY KEY,

    setting_value VARCHAR(255) DEFAULT NULL,

    updated_by VARCHAR(100) DEFAULT NULL,

    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;



INSERT INTO hoa_settings (setting_key, setting_value) VALUES

    ('treasurer_name', 'Office of the Treasurer'),

    ('treasurer_phone', '0900-000-0000'),

    ('treasurer_email', 'treasurer@northfairway.com'),

    ('treasurer_office_hours', 'Mon–Fri, 9:00 AM – 5:00 PM')

ON DUPLICATE KEY UPDATE setting_key = setting_key;
-- ---------------------------------------------------------------------------
-- DOCUMENT TEMPLATES (versioned, Administrator-managed soft copies)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_templates (

    id INT AUTO_INCREMENT PRIMARY KEY,

    template_key VARCHAR(60) NOT NULL,

    service_name VARCHAR(100) DEFAULT NULL,

    version_no INT NOT NULL DEFAULT 1,

    title VARCHAR(180) NOT NULL,

    body_text LONGTEXT NOT NULL,

    footer_text TEXT DEFAULT NULL,

    required_signatures VARCHAR(120) DEFAULT NULL,

    status ENUM('Active','Archived') NOT NULL DEFAULT 'Active',

    updated_by VARCHAR(100) DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_document_template_version (template_key, version_no),

    KEY idx_document_template_active (template_key, status)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;



INSERT INTO document_templates (template_key,service_name,version_no,title,body_text,footer_text,status,updated_by) VALUES

('cert-improvement','Certificate of Improvement',1,'CERTIFICATE OF IMPROVEMENT','This is to certify that {homeowner}, the owner of the unit in Blk {block} Lot {lot} of North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan, is going to improve their unit.','Issued this {issue_date} at North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan.','Active','System'),

('proof-residency','Proof of Residency',1,'Proof of Residency','This is to certify that {homeowner} of Block {block} Lot {lot} of North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan is a bona fide resident of North Fairway Homes Homeowners Association Inc.','Owner/Member: {homeowner}\nIssued this {issue_date} at North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan.','Active','System'),

('move-in','Move-in Gate Pass',1,'NFH/HOA GATE PASS FOR MOVE-IN','TO WHOM IT MAY CONCERN:\n\nThis is to certify that {homeowner}, the owner of the unit in Blk {block} Lot {lot}, is going to move in to their unit. They are allowed to bring the needed things inside the subdivision for their transfer to North Fairway Homes.','Issued this {issue_date} at North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan. This is upon the request of the interested party for whatever legal purpose it may serve.','Active','System'),

('move-out','Move-out Gate Pass',1,'NFH/HOA GATE PASS FOR MOVE-OUT','TO WHOM IT MAY CONCERN:\n\nThis is to certify that {homeowner}, the owner of the unit in Blk {block} Lot {lot}, is going to move out to another place. They are allowed to bring the needed things outside the subdivision for their transfer.','Issued this {issue_date} at North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan. This is upon the request of the interested party for whatever legal purpose it may serve.','Active','System'),

('cert-membership','Certificate of Membership',1,'Certificate of Membership','This is to certify that {homeowner} of Block {block} Lot {lot} of North Fairway Homes Subdivision, Brgy. Muzon West, City of San Jose del Monte, Bulacan is a bona fide member of North Fairway Homes Homeowners Association Inc.','Issued this {issue_date} at North Fairway Homes, Brgy. Muzon West, City of San Jose del Monte, Bulacan.','Active','System'),

('gate-pass','Gate Pass',1,'GATE PASS','NAME: {homeowner}\nADDRESS: BLK {block} LOT {lot}\n\nMajor/Minor Construction Permit No.: {permit_no}\nList of Materials: {materials}','Checked by the authorized HOA reviewer and approved by the authorized Executive.','Active','System'),

('vehicle-sticker','Vehicle Sticker Application',1,'VEHICLE STICKER APPLICATION FORM','This is to request for issuance of a vehicle sticker to the undersigned for the vehicle described in the attached copy of the Certificate of Registration. I shall hold NORTH FAIRWAY HOMES HOMEOWNERS’ ASSOCIATION, INC. free from any liability for any untoward operation of the said motor vehicle and/or use of this sticker within the premises of North Fairway Homes. I bind myself to follow all rules and regulations of North Fairway Homes Homeowners Association and commit to remove the sticker and surrender the same to the NFH HOA Administration Office upon sale or disposal of my vehicle.','I hereby certify that all information provided herein is true and correct.','Active','System'),

('tenant-form','Renters/Tenants Information Form',1,'RENTER’S / TENANT’S INFORMATION FORM','I, {tenant_name}, of legal age, residing at {rented_address}, hereby solemnly swear that:\n- I promise to abide by all subdivision rules, regulations, and policies set by the Homeowners Association (HOA) and the local Authorities.\n- I shall maintain peace, cleanliness and order within the premises and shall not engage in any activities that may disturb or endanger other residents.\n- I shall respect the rights and privacy of my neighbors and the community.\n- I shall ensure that all my guests and household members comply with the subdivision rules.\n- I understand that violations of subdivision policies may result in sanctions which may prevent me from availing privileges, documents, or requirements from the subdivision.\n\nI am executing this Oath freely and voluntarily for all legal intents and purposes.','Signed this {issue_date}.','Active','System')

ON DUPLICATE KEY UPDATE template_key=VALUES(template_key);



UPDATE document_templates SET required_signatures='Secretary,President' WHERE template_key IN ('cert-improvement','proof-residency','move-in','move-out','cert-membership');

UPDATE document_templates SET required_signatures='Treasurer,President' WHERE template_key='gate-pass';

UPDATE document_templates SET required_signatures='' WHERE template_key IN ('vehicle-sticker','tenant-form');
-- ---------------------------------------------------------------------------
-- REQUEST SIGNATURE SNAPSHOTS — preserve e-signatures used at issuance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS request_signature_snapshots (

    id INT AUTO_INCREMENT PRIMARY KEY,

    request_id VARCHAR(40) NOT NULL,

    role VARCHAR(50) NOT NULL,

    officer_id INT DEFAULT NULL,

    officer_name VARCHAR(150) NOT NULL,

    signature_path VARCHAR(255) NOT NULL,

    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_request_signature_role (request_id, role),

    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,

    FOREIGN KEY (officer_id) REFERENCES users(id) ON DELETE SET NULL

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- FACE-TO-FACE PAYMENT TRANSACTIONS AND RELEASE CONFIRMATION
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_transactions (

    id INT AUTO_INCREMENT PRIMARY KEY,

    request_id VARCHAR(40) NOT NULL,

    user_id INT NOT NULL,

    amount DECIMAL(10,2) NOT NULL,

    payment_method ENUM('Cash') NOT NULL DEFAULT 'Cash',

    system_reference VARCHAR(60) DEFAULT NULL,

    official_receipt_no VARCHAR(120) DEFAULT NULL,

    payment_date DATE NOT NULL,

    received_by VARCHAR(150) NOT NULL,

    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    document_released TINYINT(1) NOT NULL DEFAULT 0,

    released_by VARCHAR(150) DEFAULT NULL,

    released_at DATETIME DEFAULT NULL,

    remarks TEXT DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_payment_transaction_request (request_id),

    UNIQUE KEY uq_payment_transaction_reference (system_reference),

    UNIQUE KEY uq_payment_official_receipt_no (official_receipt_no),

    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ---------------------------------------------------------------------------
-- PAYMENT COMMITMENTS ARE OUTSIDE THE DOCUMENT-REQUEST STUDY SCOPE
-- ---------------------------------------------------------------------------
-- ---------------------------------------------------------------------------
-- ADMINISTRATOR IMPORT HISTORY
-- Records only import metadata/summary; uploaded source files are temporary.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_history (

    id INT AUTO_INCREMENT PRIMARY KEY,

    import_type ENUM('Excel') NOT NULL,

    source_filename VARCHAR(255) NOT NULL,

    dataset VARCHAR(180) NOT NULL,

    total_rows INT NOT NULL DEFAULT 0,

    successful_rows INT NOT NULL DEFAULT 0,

    rejected_rows INT NOT NULL DEFAULT 0,

    duplicate_rows INT NOT NULL DEFAULT 0,

    status VARCHAR(60) NOT NULL DEFAULT 'Completed',

    summary_json LONGTEXT DEFAULT NULL,

    imported_by VARCHAR(100) NOT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_import_history_created (created_at),

    KEY idx_import_history_type (import_type)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS system_feedback (id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,rating TINYINT NOT NULL,category VARCHAR(80) NOT NULL,comments TEXT NOT NULL,reviewed_at DATETIME NULL,reviewed_by INT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id),INDEX(user_id,created_at));
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS general_concerns (id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,assigned_role VARCHAR(40) NOT NULL DEFAULT 'Secretary',category VARCHAR(80) NOT NULL,subject VARCHAR(200) NOT NULL,description TEXT NOT NULL,status VARCHAR(30) NOT NULL DEFAULT 'Open',officer_response TEXT NULL,version INT NOT NULL DEFAULT 0,updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id),INDEX(assigned_role,status));
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS hoa_resolutions (id BIGINT AUTO_INCREMENT PRIMARY KEY,resolution_number VARCHAR(100) NOT NULL UNIQUE,title VARCHAR(250) NOT NULL,description TEXT,category VARCHAR(80),approval_date DATE NOT NULL,file_path VARCHAR(255) NOT NULL,status VARCHAR(20) NOT NULL DEFAULT 'Draft',uploaded_by INT NOT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(uploaded_by) REFERENCES users(id),INDEX(status,approval_date));
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS soa_requests (id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,purpose VARCHAR(250) NOT NULL,period_start DATE NOT NULL,period_end DATE NOT NULL,status VARCHAR(35) NOT NULL DEFAULT 'Submitted',reviewed_by INT NULL,reviewed_at DATETIME NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id),INDEX(user_id,status));
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS delinquency_reviews (user_id INT PRIMARY KEY,unpaid_months INT NOT NULL DEFAULT 0,outstanding_balance DECIMAL(12,2) NOT NULL DEFAULT 0,classification VARCHAR(30) NOT NULL DEFAULT 'Clear',reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS delinquency_notices (id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,period_key VARCHAR(10) NOT NULL,channel VARCHAR(15) NOT NULL,status VARCHAR(20) NOT NULL,attempts INT NOT NULL DEFAULT 0,last_error TEXT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP,UNIQUE KEY uq_delinquency_notice(user_id,period_key,channel),FOREIGN KEY(user_id) REFERENCES users(id));
-- Source: migration_20261022.sql
CREATE TABLE IF NOT EXISTS chatbot_faq (id INT AUTO_INCREMENT PRIMARY KEY, category VARCHAR(80) NOT NULL DEFAULT 'General', question VARCHAR(500) NOT NULL, answer TEXT NOT NULL, is_active TINYINT(1) NOT NULL DEFAULT 1, keywords TEXT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP);
-- Source: migration_monthly_dues_automation.sql
CREATE TABLE IF NOT EXISTS monthly_dues_payments (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 user_id INT NOT NULL,

 amount DECIMAL(12,2) NOT NULL,

 received_at DATETIME NOT NULL,

 verified_by VARCHAR(100) NOT NULL,

 unapplied_amount DECIMAL(12,2) NOT NULL DEFAULT 0,

 voided_at DATETIME NULL,

 void_reason VARCHAR(255) NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 CONSTRAINT fk_dues_payment_user FOREIGN KEY (user_id) REFERENCES users(id),

 INDEX idx_dues_payments_user_date (user_id, received_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: migration_monthly_dues_automation.sql
CREATE TABLE IF NOT EXISTS monthly_dues_allocations (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 payment_id BIGINT NOT NULL,

 monthly_due_id INT NOT NULL,

 amount DECIMAL(12,2) NOT NULL,

 CONSTRAINT fk_dues_alloc_payment FOREIGN KEY (payment_id) REFERENCES monthly_dues_payments(id),

 CONSTRAINT fk_dues_alloc_month FOREIGN KEY (monthly_due_id) REFERENCES monthly_dues(id),

 UNIQUE KEY uq_payment_month (payment_id, monthly_due_id),

 INDEX idx_dues_alloc_month (monthly_due_id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_ADVANCE_PAYMENT_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_advance_discount_policies (

 id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(180) NOT NULL,

 discount_type ENUM('Percentage','Fixed') NOT NULL, discount_value DECIMAL(12,2) NOT NULL,

 min_months INT NOT NULL DEFAULT 1, max_months INT NULL,

 effective_date DATE NOT NULL, expiration_date DATE NULL,

 resolution_reference VARCHAR(200) NOT NULL, authorized_by VARCHAR(150) NOT NULL,

 active TINYINT(1) NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

 CHECK (discount_value >= 0), CHECK (min_months >= 1)

) ENGINE=InnoDB;
-- Source: NFH_ADVANCE_PAYMENT_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_advance_transactions (

 id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, payment_id BIGINT NOT NULL,

 request_key VARCHAR(80) NOT NULL UNIQUE, gross_amount DECIMAL(12,2) NOT NULL,

 cash_received DECIMAL(12,2) NOT NULL, discount_amount DECIMAL(12,2) NOT NULL,

 policy_id INT NULL, discount_reference VARCHAR(200) NULL,

 payment_method VARCHAR(50) NOT NULL, payment_reference VARCHAR(120) NULL,

 remarks VARCHAR(1000) NULL, processed_by VARCHAR(120) NOT NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (payment_id) REFERENCES monthly_dues_payments(id),

 FOREIGN KEY (policy_id) REFERENCES nfh_advance_discount_policies(id),

 UNIQUE KEY uq_nfh_advance_payment (payment_id)

) ENGINE=InnoDB;
-- Source: NFH_ADVANCE_PAYMENT_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_advance_periods (

 id BIGINT AUTO_INCREMENT PRIMARY KEY, transaction_id BIGINT NOT NULL,

 monthly_due_id INT NOT NULL, due_month DATE NOT NULL,

 gross_amount DECIMAL(12,2) NOT NULL, cash_amount DECIMAL(12,2) NOT NULL,

 discount_amount DECIMAL(12,2) NOT NULL,

 UNIQUE KEY uq_advance_period_month (monthly_due_id),

 FOREIGN KEY (transaction_id) REFERENCES nfh_advance_transactions(id),

 FOREIGN KEY (monthly_due_id) REFERENCES monthly_dues(id)

) ENGINE=InnoDB;
-- Source: NFH_ADVANCE_PROMO_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_advance_promo_awards (

 id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, coverage_year INT NOT NULL,

 qualifying_paid_at DATE NOT NULL, raffle_tickets INT NOT NULL DEFAULT 0,

 certificate_credits INT NOT NULL DEFAULT 4, awarded_by VARCHAR(120) NOT NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_promo_homeowner_year (user_id,coverage_year),

 CONSTRAINT fk_promo_user FOREIGN KEY(user_id) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Source: NFH_ADVANCE_EMAIL_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_advance_promo_distributions (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 award_id BIGINT NOT NULL,

 tickets_distributed INT NOT NULL,

 confirmed_by VARCHAR(120) NOT NULL,

 confirmed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_promo_distribution_award (award_id),

 CONSTRAINT fk_promo_distribution_award FOREIGN KEY (award_id)

 REFERENCES nfh_advance_promo_awards(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_ADVANCE_PROMO_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_advance_promo_redemptions (

 id BIGINT AUTO_INCREMENT PRIMARY KEY, award_id BIGINT NOT NULL, request_id VARCHAR(40) NOT NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_promo_request (request_id),

 KEY idx_promo_award (award_id),

 CONSTRAINT fk_promo_redemption_award FOREIGN KEY(award_id) REFERENCES nfh_advance_promo_awards(id),

 CONSTRAINT fk_promo_redemption_request FOREIGN KEY(request_id) REFERENCES requests(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_HOA_DOCUMENTS_MIGRATION.sql
CREATE TABLE IF NOT EXISTS hoa_documents (

 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

 title VARCHAR(200) NOT NULL, description TEXT NULL,

 category VARCHAR(100) NOT NULL, resolution_number VARCHAR(100) NULL, resolution_date DATE NULL,

 stored_filename VARCHAR(80) NOT NULL UNIQUE, original_filename VARCHAR(225) NOT NULL,

 file_size BIGINT UNSIGNED NOT NULL, sha256 CHAR(64) NOT NULL,

 status ENUM('Draft','Published','Unpublished') NOT NULL DEFAULT 'Draft',

 uploaded_by INT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

 published_at DATETIME NULL, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

 KEY idx_hoa_documents_status(status,published_at), KEY idx_hoa_documents_category(category)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_WHOLE_PESO_PLAN_MIGRATION.sql
CREATE TABLE IF NOT EXISTS monthly_dues_payment_plans (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 user_id INT NOT NULL,

 total_amount DECIMAL(12,2) NOT NULL,

 installment_count INT NOT NULL,

 status ENUM('Active','Partially Paid','Overdue','Completed','Cancelled') NOT NULL DEFAULT 'Active',

 created_by VARCHAR(150) NULL,

 remarks VARCHAR(1000) NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 INDEX idx_plan_user (user_id),

 FOREIGN KEY (user_id) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_WHOLE_PESO_PLAN_MIGRATION.sql
CREATE TABLE IF NOT EXISTS monthly_dues_plan_installments (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 plan_id BIGINT NOT NULL,

 installment_number INT NOT NULL,

 due_date DATE NOT NULL,

 amount DECIMAL(12,2) NOT NULL,

 paid_amount DECIMAL(12,2) NOT NULL DEFAULT 0,

 UNIQUE KEY uq_plan_number(plan_id,installment_number),

 FOREIGN KEY (plan_id) REFERENCES monthly_dues_payment_plans(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_WHOLE_PESO_PLAN_MIGRATION.sql
CREATE TABLE IF NOT EXISTS monthly_dues_plan_coverage (

 plan_id BIGINT NOT NULL,

 monthly_due_id INT NOT NULL,

 original_covered_amount DECIMAL(12,2) NOT NULL,

 PRIMARY KEY (monthly_due_id),

 INDEX idx_plan_coverage(plan_id),

 FOREIGN KEY (plan_id) REFERENCES monthly_dues_payment_plans(id),

 FOREIGN KEY (monthly_due_id) REFERENCES monthly_dues(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_PLAN_CASH_RECEIPTS_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_plan_cash_receipts (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 payment_id BIGINT NOT NULL,

 user_id INT NOT NULL,

 request_key VARCHAR(80) NOT NULL,

 reference_no VARCHAR(100) NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_plan_cash_payment(payment_id),

 UNIQUE KEY uq_plan_cash_key(request_key),

 FOREIGN KEY(payment_id) REFERENCES monthly_dues_payments(id),

 FOREIGN KEY(user_id) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: NFH_OVERDUE_INSTALLMENT_EMAIL_MIGRATION.sql
CREATE TABLE IF NOT EXISTS nfh_installment_overdue_notices (

 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,

 installment_id BIGINT NOT NULL,

 plan_id BIGINT NOT NULL,

 user_id INT NOT NULL,

 due_date DATE NOT NULL,

 status ENUM('Pending','Sending','Sent','Failed') NOT NULL DEFAULT 'Pending',

 sent_at DATETIME NULL,

 error_details VARCHAR(1000) NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_nfh_installment_overdue_once(installment_id),

 KEY idx_nfh_installment_overdue_status(status),

 CONSTRAINT fk_nfh_overdue_inst FOREIGN KEY (installment_id) REFERENCES monthly_dues_plan_installments(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: migration_delinquency_email_20261022.sql
CREATE TABLE IF NOT EXISTS delinquency_email_reminders (

  id BIGINT AUTO_INCREMENT PRIMARY KEY,

  user_id INT NOT NULL,

  interval_bucket BIGINT NOT NULL,

  interval_seconds INT NOT NULL,

  status VARCHAR(20) NOT NULL DEFAULT 'Pending',

  last_error VARCHAR(500) NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  completed_at DATETIME NULL,

  UNIQUE KEY uq_delinquency_email_bucket (user_id, interval_seconds, interval_bucket),

  INDEX idx_delinquency_email_status (status, created_at),

  FOREIGN KEY (user_id) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Source: migration_concern_history_20261022.sql
CREATE TABLE IF NOT EXISTS general_concern_history (

 id BIGINT AUTO_INCREMENT PRIMARY KEY,

 concern_id BIGINT NOT NULL,

 officer_id INT NOT NULL,

 previous_status VARCHAR(30) NOT NULL,

 new_status VARCHAR(30) NOT NULL,

 message TEXT NOT NULL,

 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

 FOREIGN KEY (concern_id) REFERENCES general_concerns(id),

 FOREIGN KEY (officer_id) REFERENCES users(id),

 INDEX idx_concern_history (concern_id,created_at)

);
-- Additive, non-destructive schema. FIRST back up production tables and validate in staging.
CREATE TABLE IF NOT EXISTS nfh_historical_request_fees (

 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

 user_id INT NOT NULL,

 request_type VARCHAR(100) NOT NULL,

 request_date DATE NOT NULL,

 amount DECIMAL(12,2) NOT NULL,

 external_ref VARCHAR(160) NOT NULL,

 description VARCHAR(255),

 imported_by INT NOT NULL,

 imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_nfh_historical_fee (user_id,external_ref),

 KEY idx_nfh_fee_homeowner (user_id,request_date),

 CONSTRAINT fk_nfh_historical_user FOREIGN KEY(user_id) REFERENCES users(id),

 CONSTRAINT fk_nfh_historical_importer FOREIGN KEY(imported_by) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_import_batches (

 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

 import_type ENUM('dues','soa') NOT NULL,

 homeowner_id INT NOT NULL,

 source_filename VARCHAR(255) NOT NULL,

 imported_by INT NOT NULL,

 total_rows INT NOT NULL DEFAULT 0,

 accepted_rows INT NOT NULL DEFAULT 0,

 duplicate_rows INT NOT NULL DEFAULT 0,

 rejected_rows INT NOT NULL DEFAULT 0,

 validation_json LONGTEXT,

 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

 KEY idx_nfh_batches_created (created_at),

 KEY idx_nfh_batches_homeowner (homeowner_id),

 CONSTRAINT fk_nfh_batch_homeowner FOREIGN KEY(homeowner_id) REFERENCES users(id),

 CONSTRAINT fk_nfh_batch_importer FOREIGN KEY(imported_by) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Requires a compatible UNIQUE(user_id,due_month) on monthly_dues. Check integrity first.
-- Historical request fee receipts. Each receipt is linked to exactly one fee.
-- An official receipt number is unique system-wide, preventing accidental replay.
CREATE TABLE IF NOT EXISTS nfh_historical_fee_receipts (

 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

 fee_id BIGINT UNSIGNED NOT NULL,

 user_id INT NOT NULL,

 amount DECIMAL(12,2) NOT NULL,

 receipt_no VARCHAR(120) NOT NULL,

 received_on DATE NOT NULL,

 received_by INT NOT NULL,

 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

 UNIQUE KEY uq_nfh_historical_receipt (receipt_no),

 KEY idx_nfh_historical_receipt_fee (fee_id),

 CONSTRAINT fk_nfh_receipt_fee FOREIGN KEY (fee_id) REFERENCES nfh_historical_request_fees(id),

 CONSTRAINT fk_nfh_receipt_user FOREIGN KEY (user_id) REFERENCES users(id),

 CONSTRAINT fk_nfh_receipt_treasurer FOREIGN KEY (received_by) REFERENCES users(id),

 CONSTRAINT ck_nfh_receipt_amount CHECK (amount > 0)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Extension from migration_chatbot_keywords_20261022.sql
-- keywords defined in chatbot_faq for fresh installation.
-- Extension from migration_concern_history_20261022.sql
-- version defined in general_concerns for fresh installation.
-- Seed reference from migration_20261022.sql
INSERT INTO hoa_settings (setting_key,setting_value) VALUES ('delinquency_unpaid_months','5') ON DUPLICATE KEY UPDATE setting_key=setting_key;
-- Seed reference from migration_20261022.sql
INSERT INTO hoa_settings(setting_key,setting_value) VALUES ('chatbot_fallback','Thank you for your inquiry. Please contact the HOA office or submit a concern through Concerns & Feedback.') ON DUPLICATE KEY UPDATE setting_key=setting_key;
-- FAQ for free Statement of Account, preserved from the supplied SQL.
INSERT INTO chatbot_faq(category,question,answer,is_active,keywords)
SELECT 'Services','How do I request a Statement of Account?',
'Statement of Account requests are free (₱0.00). Open Homeowner Dashboard → Request and select Statement of Account. Homeowners with unpaid monthly dues may still request it. The request goes directly to the Treasurer, who verifies, processes, and releases it. Executive approval, dues clearance, and payment verification are not required.',1,
'SOA,statement of account,SOA fee,SOA free,unpaid dues SOA,request SOA,who approves SOA'
WHERE NOT EXISTS (SELECT 1 FROM chatbot_faq WHERE question='How do I request a Statement of Account?');
-- Canonical Statement of Account service: Treasurer-only; fee free; no executive approval,
-- dues clearance or payment verification. See user-provided HOA business requirements.
INSERT INTO service_types
(service_name,category,fee,initial_reviewer,requires_executive,requires_payment,
 requires_dues_clearance,purpose_required,release_role,form_template,description,status)
VALUES ('Statement of Account','Document Request',0.00,'Treasurer',0,0,0,1,
'Treasurer','statement-of-account','Free Statement of Account processed by Treasurer.','Active')
ON DUPLICATE KEY UPDATE fee=VALUES(fee), initial_reviewer=VALUES(initial_reviewer),
requires_executive=VALUES(requires_executive), requires_payment=VALUES(requires_payment),
requires_dues_clearance=VALUES(requires_dues_clearance), release_role=VALUES(release_role),
form_template=VALUES(form_template), status=VALUES(status);
-- Historical SOA rows: separates claimed Paid receipts awaiting verification
-- from authoritative verified payments. Does not constitute cash income.
CREATE TABLE IF NOT EXISTS nfh_historical_import_entries (

 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

 homeowner_id INT NOT NULL,

 external_ref VARCHAR(160) NOT NULL,

 transaction_type ENUM('Request','Monthly Dues','Others') NOT NULL,

 description VARCHAR(255) NOT NULL,

 transaction_date DATE NOT NULL,

 amount DECIMAL(12,2) NOT NULL,

 reported_status ENUM('Paid','Unpaid') NOT NULL,

 or_number VARCHAR(120) NULL,

 verification_status ENUM('Unpaid','Pending','Verified','Rejected') NOT NULL DEFAULT 'Pending',

 imported_by INT NOT NULL,

 imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

 verified_by INT NULL,

 verified_at DATETIME NULL,

 UNIQUE KEY uq_nfh_historical_entry (homeowner_id,external_ref),

 KEY idx_nfh_import_receipt (or_number),

 KEY idx_nfh_import_status (homeowner_id,verification_status),

 CONSTRAINT fk_nfh_entry_homeowner FOREIGN KEY(homeowner_id) REFERENCES users(id),

 CONSTRAINT fk_nfh_entry_importer FOREIGN KEY(imported_by) REFERENCES users(id),

 CONSTRAINT fk_nfh_entry_verifier FOREIGN KEY(verified_by) REFERENCES users(id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ---------------------------------------------------------------------------
-- INITIAL ADMINISTRATOR AND HOA OFFICER ACCOUNTS (USER-SUPPLIED)
-- This final statement is intended for an empty demonstration database.
-- Existing accounts with conflicting IDs or unique usernames/emails must be reviewed.
-- Replace and rotate demo credentials before any real-world deployment.
-- ---------------------------------------------------------------------------
INSERT INTO `users`
(`id`, `first_name`, `last_name`, `email`, `username`, `mobile`, `password_hash`, `role`, `status`) VALUES
(1, 'Admin', 'Administrator', 'northfairwayhoa@mail4.uk', 'admin', '09171234506', 'pbkdf2:sha256:600000$0lxkqezb0ueZLTiv$f6731d67610c1b0afd094050151b03c393f61d9b99611a855eaab385f657c6ba', 'Admin', 'Active'),
(2, 'Alejandro', 'Reyes', 'alejandroreyes1@mail4.uk', 'alejandro.reyes', '09171234501', 'pbkdf2:sha256:600000$FPu18H80POBhGmcu$49edadad2fce184c4bf7884d2334aa5eff8c554a6b7991b371f41b8e6464871d', 'President', 'Active'),
(3, 'Marissa', 'Santos', 'marissasantos2@mail4.uk', 'marissa.santos', '09171234502', 'pbkdf2:sha256:600000$zGbhaajGccXNsMPG$efc5e4a6a1e5cb196e60596cabe0f7a7a6b2156578daf94532ae8fb14b9ba879', 'Vice President', 'Active'),
(4, 'Clarissa', 'Mendoza', 'clarissamendoza3@mail4.uk', 'clarissa.mendoza', '09171234503', 'pbkdf2:sha256:600000$EGJdq5B5zAEft70a$26bd9986fe523cf34e787cfdbc2f5438c6d0e9afbd3610e62845e7d9adbecc53', 'Secretary', 'Active'),
(5, 'Ramon', 'Villanueva', 'ramonvillanueva4@mail4.uk', 'ramon.villanueva', '09171234504', 'pbkdf2:sha256:600000$VxRznF63ua6BKLtc$afe689c2dbb83f4b836d96dfa9ffc8f84753e51dc8b8868db43743f03d5c2ac4', 'Treasurer', 'Active'),
(6, 'Daniel', 'Navarro', 'danielnavarro5@mail4.uk', 'daniel.navarro', '09171234505', 'pbkdf2:sha256:600000$Fu3ts23W68WpRxFS$d58d248203b4ae36137e8aaabe33e4edd9aeb510a06b25687dd38f60a5ff78f7', 'Board Director', 'Active')
ON DUPLICATE KEY UPDATE
    `first_name` = VALUES(`first_name`),
    `last_name` = VALUES(`last_name`),
    `mobile` = VALUES(`mobile`),
    `password_hash` = VALUES(`password_hash`),
    `role` = VALUES(`role`),
    `status` = VALUES(`status`);

-- Registration rejection decision archive: retained even when pending user is safely deleted.
CREATE TABLE IF NOT EXISTS nfh_registration_rejections (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 original_user_id INT NOT NULL, homeowner_name VARCHAR(300) NOT NULL,
 homeowner_public_id VARCHAR(32),block_no VARCHAR(50),lot_no VARCHAR(50),
 email VARCHAR(150) NOT NULL,rejection_reason TEXT NOT NULL,
 rejected_by VARCHAR(100) NOT NULL,rejected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 cleanup_result ENUM('Deleted','Archived') NOT NULL,
 notification_status ENUM('Pending','Sent','Failed') NOT NULL DEFAULT 'Pending',
 UNIQUE KEY uq_registration_original_user (original_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Verified historical cash receipts (one parent OR; allocations avoid duplicated income)
CREATE TABLE IF NOT EXISTS nfh_historical_cash_receipts (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL, receipt_no VARCHAR(120) NOT NULL, received_on DATE NOT NULL,
 verified_by INT NOT NULL, import_batch_id BIGINT UNSIGNED NULL,
 source VARCHAR(60) NOT NULL DEFAULT 'Historical SOA Import', request_key VARCHAR(100) NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_historical_payment_key (request_key),
 UNIQUE KEY uq_hist_cash_or (receipt_no),
 FOREIGN KEY (user_id) REFERENCES users(id), FOREIGN KEY (verified_by) REFERENCES users(id),
 FOREIGN KEY (import_batch_id) REFERENCES nfh_import_batches(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS nfh_historical_cash_allocations (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 receipt_id BIGINT UNSIGNED NOT NULL, import_entry_id BIGINT UNSIGNED NOT NULL,
 monthly_due_id INT NULL, historical_fee_id BIGINT UNSIGNED NULL,
 category ENUM('Request','Monthly Dues','Others') NOT NULL,
 amount DECIMAL(12,2) NOT NULL,
 UNIQUE KEY uq_hist_cash_receipt_entry (receipt_id,import_entry_id),
 FOREIGN KEY (receipt_id) REFERENCES nfh_historical_cash_receipts(id),
 FOREIGN KEY (import_entry_id) REFERENCES nfh_historical_import_entries(id),
 FOREIGN KEY (monthly_due_id) REFERENCES monthly_dues(id),
 FOREIGN KEY (historical_fee_id) REFERENCES nfh_historical_request_fees(id),
 CHECK (amount>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- HOA membership classification: independent from users.status (login access).
-- Safe to run on an existing database; contains no DROP or destructive UPDATE.
CREATE TABLE IF NOT EXISTS nfh_homeowner_membership (
 homeowner_id INT NOT NULL PRIMARY KEY,
 status ENUM('Active','Inactive') NOT NULL DEFAULT 'Active',
 updated_by INT NULL,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 CONSTRAINT fk_nfh_membership_owner FOREIGN KEY (homeowner_id) REFERENCES users(id),
 CONSTRAINT fk_nfh_membership_editor FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS nfh_membership_import_batches (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 source_filename VARCHAR(255) NOT NULL,
 file_hash CHAR(64) NOT NULL,
 submitted_by INT NOT NULL,
 submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 total_rows INT NOT NULL,
 changed_rows INT NOT NULL,
 unchanged_rows INT NOT NULL,
 status ENUM('Pending Approval','Approved','Rejected') NOT NULL DEFAULT 'Pending Approval',
 reviewed_by INT NULL,
 reviewed_at DATETIME NULL,
 KEY idx_nfh_membership_batch_status (status,submitted_at),
 CONSTRAINT fk_nfh_membership_submit FOREIGN KEY (submitted_by) REFERENCES users(id),
 CONSTRAINT fk_nfh_membership_review FOREIGN KEY (reviewed_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS nfh_membership_import_changes (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 batch_id BIGINT NOT NULL,
 homeowner_id INT NOT NULL,
 homeowner_public_id VARCHAR(32) NOT NULL,
 name_snapshot VARCHAR(400) NOT NULL,
 address_snapshot VARCHAR(255) NOT NULL,
 previous_status ENUM('Active','Inactive') NOT NULL,
 proposed_status ENUM('Active','Inactive') NOT NULL,
 UNIQUE KEY uq_nfh_membership_batch_homeowner (batch_id,homeowner_id),
 CONSTRAINT fk_nfh_membership_change_batch FOREIGN KEY (batch_id) REFERENCES nfh_membership_import_batches(id),
 CONSTRAINT fk_nfh_membership_change_owner FOREIGN KEY (homeowner_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Pending manual roster IDs: separate from verified accounts and financial ledgers.
CREATE TABLE IF NOT EXISTS nfh_membership_pending_matches (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 imported_homeowner_id VARCHAR(64) NOT NULL,
 normalized_homeowner_id VARCHAR(64) NOT NULL,
 imported_name VARCHAR(400) NOT NULL,
 imported_address VARCHAR(255) NOT NULL,
 imported_status ENUM('Active','Inactive') NOT NULL,
 reconciliation_status ENUM('Pending Account Match','Requires Review','Reconciled') NOT NULL DEFAULT 'Pending Account Match',
 import_batch_id BIGINT NULL,
 matched_homeowner_id INT NULL,
 imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 reconciled_at DATETIME NULL,
 imported_by INT NULL,
 reconciled_by INT NULL,
 validation_remarks VARCHAR(600) NULL,
 UNIQUE KEY uq_nfh_pending_normalized_id (normalized_homeowner_id),
 UNIQUE KEY uq_nfh_pending_matched_account (matched_homeowner_id),
 KEY idx_nfh_pending_status (reconciliation_status,imported_at),
 CONSTRAINT fk_nfh_pending_batch FOREIGN KEY(import_batch_id) REFERENCES nfh_membership_import_batches(id),
 CONSTRAINT fk_nfh_pending_account FOREIGN KEY(matched_homeowner_id) REFERENCES users(id),
 CONSTRAINT fk_nfh_pending_importer FOREIGN KEY(imported_by) REFERENCES users(id),
 CONSTRAINT fk_nfh_pending_reviewer FOREIGN KEY(reconciled_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Batch 3: unique per-homeowner promo codes (MariaDB 10.4 compatible).
-- Apply after the existing advance-payment and promo awards schema.
CREATE TABLE IF NOT EXISTS nfh_promo_codes (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 award_id BIGINT NOT NULL,
 user_id INT NOT NULL,
 coverage_year INT NOT NULL,
 code VARCHAR(48) NOT NULL,
 expires_at DATETIME NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 redeemed_request_id VARCHAR(40) NULL,
 redeemed_at DATETIME NULL,
 original_request_fee DECIMAL(12,2) NULL,
 revoked_at DATETIME NULL,
 UNIQUE KEY uq_nfh_promo_code (code),
 UNIQUE KEY uq_nfh_promo_request (redeemed_request_id),
 KEY idx_nfh_promo_owner (user_id,coverage_year,expires_at),
 KEY idx_nfh_promo_award (award_id),
 CONSTRAINT fk_nfh_promo_award FOREIGN KEY (award_id) REFERENCES nfh_advance_promo_awards(id),
 CONSTRAINT fk_nfh_promo_owner FOREIGN KEY (user_id) REFERENCES users(id),
 CONSTRAINT fk_nfh_promo_request FOREIGN KEY (redeemed_request_id) REFERENCES requests(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- Batch 12 additive property-ledger foundation.
-- Batch 12: additive, non-destructive foundation for property-based dues.
-- Compatible with MariaDB 10.4; apply after backing up database.
-- DOES NOT automatically migrate/replace the legacy monthly_dues ledger.
-- No homeowner/renter billing should be switched until reconciliation is approved.
CREATE TABLE IF NOT EXISTS nfh_properties (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 property_code VARCHAR(64) NOT NULL,
 subdivision VARCHAR(120) NOT NULL DEFAULT 'North Fairway Homes',
 block VARCHAR(50) NOT NULL,
 lot VARCHAR(50) NOT NULL,
 status ENUM('Active','Inactive') NOT NULL DEFAULT 'Active',
 billing_start DATE NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_nfh_property_code (property_code),
 KEY idx_nfh_property_location (subdivision,block,lot)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_property_owners (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 property_id BIGINT NOT NULL,
 homeowner_id INT NOT NULL,
 effective_from DATE NOT NULL,
 effective_to DATE NULL,
 verified_at DATETIME NULL,
 verified_by INT NULL,
 CONSTRAINT fk_nfh_owner_property FOREIGN KEY (property_id) REFERENCES nfh_properties(id),
 CONSTRAINT fk_nfh_owner_homeowner FOREIGN KEY (homeowner_id) REFERENCES users(id),
 KEY idx_nfh_owner_property_dates (property_id,effective_from,effective_to),
 KEY idx_nfh_owner_homeowner (homeowner_id,property_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Renter identity is deliberately separate from the legacy users.role ENUM.
-- Account login/role activation requires a separately reviewed rollout.
CREATE TABLE IF NOT EXISTS nfh_renters (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 full_name VARCHAR(180) NOT NULL,
 email VARCHAR(150) NULL,
 mobile VARCHAR(30) NULL,
 verification_status ENUM('Pending','Verified','Rejected') NOT NULL DEFAULT 'Pending',
 verified_by INT NULL,
 verified_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY idx_nfh_renter_status (verification_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_rental_agreements (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 property_id BIGINT NOT NULL,
 homeowner_id INT NOT NULL,
 renter_id BIGINT NOT NULL,
 starts_on DATE NOT NULL,
 ends_on DATE NOT NULL,
 effective_from DATE NOT NULL,
 payer_type ENUM('Homeowner','Renter') NOT NULL,
 verification_status ENUM('Pending','Verified','Rejected','Revoked') NOT NULL DEFAULT 'Pending',
 verified_by INT NULL,
 verified_at DATETIME NULL,
 revoked_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_nfh_agreement_property FOREIGN KEY (property_id) REFERENCES nfh_properties(id),
 CONSTRAINT fk_nfh_agreement_owner FOREIGN KEY (homeowner_id) REFERENCES users(id),
 CONSTRAINT fk_nfh_agreement_renter FOREIGN KEY (renter_id) REFERENCES nfh_renters(id),
 CONSTRAINT chk_nfh_agreement_dates CHECK (ends_on>=starts_on AND effective_from<=ends_on),
 KEY idx_nfh_agreement_period (property_id,verification_status,effective_from,ends_on)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_property_monthly_dues (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 property_id BIGINT NOT NULL,
 billing_period DATE NOT NULL,
 amount_due DECIMAL(12,2) NOT NULL,
 homeowner_id INT NOT NULL,
 payer_type ENUM('Homeowner','Renter') NOT NULL,
 responsible_payer_id BIGINT NOT NULL,
 rental_agreement_id BIGINT NULL,
 status ENUM('Unpaid','Partially Paid','Paid','Adjusted') NOT NULL DEFAULT 'Unpaid',
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_nfh_dues_property FOREIGN KEY (property_id) REFERENCES nfh_properties(id),
 CONSTRAINT fk_nfh_dues_homeowner FOREIGN KEY (homeowner_id) REFERENCES users(id),
 CONSTRAINT fk_nfh_dues_agreement FOREIGN KEY (rental_agreement_id) REFERENCES nfh_rental_agreements(id),
 CONSTRAINT uq_nfh_property_billing_period UNIQUE (property_id,billing_period),
 CONSTRAINT chk_nfh_dues_amount CHECK (amount_due>=0),
 KEY idx_nfh_dues_payer (payer_type,responsible_payer_id,billing_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_property_due_receipts (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 property_id BIGINT NOT NULL,
 obligation_id BIGINT NOT NULL,
 payer_type ENUM('Homeowner','Renter','Other') NOT NULL,
 payer_id BIGINT NULL,
 payer_name VARCHAR(180) NOT NULL,
 amount DECIMAL(12,2) NOT NULL,
 official_receipt_no VARCHAR(120) NOT NULL,
 received_by INT NOT NULL,
 received_at DATETIME NOT NULL,
 voided_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_nfh_receipt_property FOREIGN KEY(property_id) REFERENCES nfh_properties(id),
 CONSTRAINT fk_nfh_receipt_obligation FOREIGN KEY(obligation_id) REFERENCES nfh_property_monthly_dues(id),
 CONSTRAINT fk_nfh_receipt_treasurer FOREIGN KEY(received_by) REFERENCES users(id),
 CONSTRAINT chk_nfh_receipt_amount CHECK (amount>0),
 KEY idx_nfh_receipt_property_date (property_id,received_at),
 KEY idx_nfh_receipt_obligation (obligation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_agreement_service_authorizations (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 agreement_id BIGINT NOT NULL,
 service_id INT NOT NULL,
 granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 revoked_at DATETIME NULL,
 CONSTRAINT fk_nfh_auth_agreement FOREIGN KEY(agreement_id) REFERENCES nfh_rental_agreements(id),
 UNIQUE KEY uq_nfh_agreement_service (agreement_id,service_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS nfh_property_migration_reviews (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 legacy_due_id INT NOT NULL,
 legacy_user_id INT NOT NULL,
 property_id BIGINT NULL,
 review_status ENUM('Unresolved','Confirmed','Excluded') NOT NULL DEFAULT 'Unresolved',
 reason VARCHAR(255) NOT NULL,
 reviewed_by INT NULL,
 reviewed_at DATETIME NULL,
 UNIQUE KEY uq_nfh_review_legacy_due (legacy_due_id),
 KEY idx_nfh_review_status (review_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Batch 12 renter-account extensions (run after all foundation tables)
-- Batch 12 renter accounts upgrade. Run after NFH_BATCH12_PROPERTY_FOUNDATION.sql.
-- BACK UP first. MariaDB 10.4.32. No existing account becomes a renter automatically.

ALTER TABLE nfh_renters ADD COLUMN IF NOT EXISTS account_user_id INT NULL;
-- Unique account binding: one renter user has at most one renter identity record.
-- Run after confirming no manually-created duplicate account_user_id mappings.
CREATE UNIQUE INDEX IF NOT EXISTS uq_nfh_renter_account ON nfh_renters (account_user_id);
CREATE TABLE IF NOT EXISTS nfh_renter_invitations (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 property_id BIGINT NOT NULL,
 homeowner_id INT NOT NULL,
 renter_id BIGINT NOT NULL,
 agreement_id BIGINT NOT NULL,
 token_hash CHAR(64) NOT NULL,
 email VARCHAR(150) NOT NULL,
 expires_at DATETIME NOT NULL,
 accepted_at DATETIME NULL,
 revoked_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_nfh_renter_invitation_token(token_hash),
 KEY idx_nfh_renter_invitation_renter(renter_id,expires_at),
 FOREIGN KEY(property_id) REFERENCES nfh_properties(id),
 FOREIGN KEY(homeowner_id) REFERENCES users(id),
 FOREIGN KEY(renter_id) REFERENCES nfh_renters(id),
 FOREIGN KEY(agreement_id) REFERENCES nfh_rental_agreements(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE nfh_rental_agreements ADD COLUMN IF NOT EXISTS homeowner_acknowledged_at DATETIME NULL;
ALTER TABLE nfh_rental_agreements ADD COLUMN IF NOT EXISTS renter_acknowledged_at DATETIME NULL;
-- Admin verification is intentionally required even after both acknowledgments.
-- Existing homeowner-based monthly_dues scheduler must NOT be run in parallel
-- with property_billing.bill_property_month(). No billing cutover in this patch.

-- B12-11 First-Time Enrollment
-- B12-11 additive schema. Apply AFTER property foundation and renter-account migrations.
-- Back up first. This migration NEVER creates property, ownership, agreement, or dues records.
CREATE TABLE IF NOT EXISTS nfh_property_claims (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 claimant_user_id INT NOT NULL,
 claim_type ENUM('Ownership','Occupancy') NOT NULL,
 subdivision VARCHAR(120) NOT NULL DEFAULT 'North Fairway Homes',
 block VARCHAR(50) NOT NULL,
 lot VARCHAR(50) NOT NULL,
 property_id BIGINT NULL,
 status ENUM('Pending','Verified','Rejected','Disputed') NOT NULL DEFAULT 'Pending',
 evidence_note VARCHAR(500) NULL,
 review_note VARCHAR(500) NULL,
 reviewed_by INT NULL,
 reviewed_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_claim_user_type_location (claimant_user_id,claim_type,subdivision,block,lot),
 KEY idx_claim_location_status (subdivision,block,lot,status),
 KEY idx_claim_user_status (claimant_user_id,status),
 CONSTRAINT fk_claim_user FOREIGN KEY(claimant_user_id) REFERENCES users(id),
 CONSTRAINT fk_claim_property FOREIGN KEY(property_id) REFERENCES nfh_properties(id),
 CONSTRAINT fk_claim_reviewer FOREIGN KEY(reviewed_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS nfh_property_claim_reviews (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 claim_id BIGINT NOT NULL,
 reviewer_id INT NOT NULL,
 previous_status VARCHAR(20) NOT NULL,
 new_status VARCHAR(20) NOT NULL,
 decision_note VARCHAR(500) NOT NULL,
 reviewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(claim_id) REFERENCES nfh_property_claims(id),
 FOREIGN KEY(reviewer_id) REFERENCES users(id),
 KEY idx_claim_history(claim_id,reviewed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Deliberately NO automatic unique index on nfh_properties(block,lot) until
-- existing duplicate location values are reconciled. Claims do not create properties.


-- Batch 12 Officer Workload task projection (fresh install)
-- B12-12..19 staging-only task projection. Run after B12-11 migration.
-- Does not change legacy payments, approvals, monthly dues or user permissions.
CREATE TABLE IF NOT EXISTS nfh_officer_tasks (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 source_type VARCHAR(40) NOT NULL,
 source_id VARCHAR(64) NOT NULL,
 task_type VARCHAR(80) NOT NULL,
 assigned_role VARCHAR(40) NOT NULL,
 assigned_user_id INT NULL,
 priority ENUM('Normal','High','Urgent') NOT NULL DEFAULT 'Normal',
 status ENUM('Pending','In Progress','Completed','Escalated','Awaiting Information','Canceled') NOT NULL DEFAULT 'Pending',
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 due_at DATETIME NULL,
 completed_at DATETIME NULL,
 source_link VARCHAR(180) NOT NULL,
 escalation_reason VARCHAR(500) NULL,
 UNIQUE KEY uq_task_source (source_type,source_id),
 INDEX idx_task_queue (assigned_role,status,due_at),
 INDEX idx_task_user (assigned_user_id,status),
 CONSTRAINT fk_task_assigned_user FOREIGN KEY(assigned_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Historical handoffs retained for future authorized delegation; no public
-- reassignment endpoint is enabled until HOA approval of delegation policy.
CREATE TABLE IF NOT EXISTS nfh_officer_task_history (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 task_id BIGINT NOT NULL,
 actor_user_id INT NOT NULL,
 event_type VARCHAR(40) NOT NULL,
 previous_assignee_id INT NULL,
 new_assignee_id INT NULL,
 note VARCHAR(500) NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX idx_task_history (task_id,created_at),
 CONSTRAINT fk_task_hist_task FOREIGN KEY(task_id) REFERENCES nfh_officer_tasks(id),
 CONSTRAINT fk_task_hist_actor FOREIGN KEY(actor_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
