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
