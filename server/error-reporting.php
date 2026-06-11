<?php
// SnatchIT Error Reporting Endpoint
// POST: receives error reports from the app and stores in SQLite
// ----------------------------------------------------------

header('Content-Type: application/json; charset=utf-8');

// Only allow POST
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Method not allowed']);
    exit;
}

// Read and validate input
$input = json_decode(file_get_contents('php://input'), true);
if (!$input || empty($input['error_text'])) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing error_text']);
    exit;
}

$error_text  = mb_substr($input['error_text'], 0, 2000);
$app_version = mb_substr($input['app_version'] ?? 'unknown', 0, 20);
$ip_hash     = hash('sha256', $_SERVER['REMOTE_ADDR'] ?? '');  // anonymized, not reversible
$created_at  = date('Y-m-d H:i:s');

// Open (or create) SQLite database
$db_path = __DIR__ . '/reports.db';
try {
    $db = new SQLite3($db_path);
    $db->enableExceptions(true);

    // Create table if first run
    $db->exec("
        CREATE TABLE IF NOT EXISTS error_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            error_text  TEXT    NOT NULL,
            app_version TEXT    NOT NULL,
            ip_hash     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
    ");

    // Rate limiting: max 10 reports per IP hash per hour
    $stmt = $db->prepare("
        SELECT COUNT(*) as cnt FROM error_reports
        WHERE ip_hash = :ip_hash AND created_at > datetime('now', '-1 hour')
    ");
    $stmt->bindValue(':ip_hash', $ip_hash, SQLITE3_TEXT);
    $result = $stmt->execute()->fetchArray();
    if ($result['cnt'] >= 10) {
        http_response_code(429);
        echo json_encode(['error' => 'Too many reports, try later']);
        exit;
    }

    // Deduplicate: skip if same error text from same IP in last 5 minutes
    $stmt = $db->prepare("
        SELECT COUNT(*) as cnt FROM error_reports
        WHERE ip_hash = :ip_hash AND error_text = :error_text
          AND created_at > datetime('now', '-5 minutes')
    ");
    $stmt->bindValue(':ip_hash', $ip_hash, SQLITE3_TEXT);
    $stmt->bindValue(':error_text', $error_text, SQLITE3_TEXT);
    $result = $stmt->execute()->fetchArray();
    if ($result['cnt'] > 0) {
        // Already reported recently — return OK silently
        echo json_encode(['status' => 'ok', 'note' => 'duplicate skipped']);
        exit;
    }

    // Insert the report
    $stmt = $db->prepare("
        INSERT INTO error_reports (error_text, app_version, ip_hash, created_at)
        VALUES (:error_text, :app_version, :ip_hash, :created_at)
    ");
    $stmt->bindValue(':error_text', $error_text, SQLITE3_TEXT);
    $stmt->bindValue(':app_version', $app_version, SQLITE3_TEXT);
    $stmt->bindValue(':ip_hash', $ip_hash, SQLITE3_TEXT);
    $stmt->bindValue(':created_at', $created_at, SQLITE3_TEXT);
    $stmt->execute();

    echo json_encode(['status' => 'ok']);

} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['error' => 'Server error']);
}
