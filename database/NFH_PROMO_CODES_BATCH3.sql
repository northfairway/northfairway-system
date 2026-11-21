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
