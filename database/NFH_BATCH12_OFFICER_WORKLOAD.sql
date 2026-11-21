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
