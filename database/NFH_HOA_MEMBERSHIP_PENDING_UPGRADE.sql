-- Apply once to existing installations after backing up. Non-destructive.
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
