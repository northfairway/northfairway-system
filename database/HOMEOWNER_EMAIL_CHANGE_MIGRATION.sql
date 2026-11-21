-- Apply once to the existing NFH-HOA database; backup before executing.
-- No existing users, addresses, or financial records are modified.
CREATE TABLE IF NOT EXISTS homeowner_email_changes (
  user_id INT NOT NULL PRIMARY KEY,
  new_email VARCHAR(150) NOT NULL,
  code_hash CHAR(64) NOT NULL,
  expires_at DATETIME NOT NULL,
  sent_at DATETIME NOT NULL,
  attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
  CONSTRAINT fk_homeowner_email_changes_user FOREIGN KEY (user_id)
    REFERENCES users(id) ON DELETE CASCADE,
  KEY idx_homeowner_email_change_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
