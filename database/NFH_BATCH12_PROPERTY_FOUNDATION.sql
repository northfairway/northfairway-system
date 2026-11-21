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
