-- Batch 12 renter accounts upgrade. Run after NFH_BATCH12_PROPERTY_FOUNDATION.sql.
-- BACK UP first. MariaDB 10.4.32. No existing account becomes a renter automatically.
ALTER TABLE users MODIFY COLUMN role ENUM('Homeowner','Secretary','Treasurer','President','Vice President','Board Director','Admin','Renter') NOT NULL DEFAULT 'Homeowner';
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
