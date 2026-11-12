BEGIN;

CREATE TABLE IF NOT EXISTS quick_access_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    icon TEXT NOT NULL,
    target_url TEXT,
    display_order INTEGER NOT NULL DEFAULT 0 CHECK (display_order >= 0),
    visibility TEXT NOT NULL CHECK (visibility IN ('employees', 'hr_admin')),
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'inactive')),
    created_by TEXT REFERENCES users(username) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (status != 'active' OR target_url IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_quick_access_visibility_status_order
    ON quick_access_items(visibility, status, display_order);

INSERT INTO quick_access_items
    (id, title, description, category, icon, target_url, display_order,
     visibility, status, created_by, created_at, updated_at)
VALUES
    ('business-trip', 'Business Trip Form', 'Submit your business trip request.',
     'HR / Administration', 'fa-plane', NULL, 1, 'employees', 'draft', NULL,
     CURRENT_TIMESTAMP::text, CURRENT_TIMESTAMP::text),
    ('office-amenities', 'Office Amenities Form',
     'Request office supplies and amenities.', 'Office', 'fa-box-open', NULL, 2,
     'employees', 'draft', NULL, CURRENT_TIMESTAMP::text, CURRENT_TIMESTAMP::text)
ON CONFLICT (id) DO NOTHING;

COMMIT;
