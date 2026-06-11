<?php
// SnatchIT Admin Panel — Error Reports Viewer
// Protected by Pocket ID (OIDC)
// ----------------------------------------------------------

require_once __DIR__ . '/auth.php';

// Handle logout
if (isset($_GET['logout'])) {
    oidc_logout();
}

// Require authentication — redirects to Pocket ID if not logged in
$user = oidc_require_auth();

$db_path = __DIR__ . '/reports.db';

// --- JSON API mode (AJAX requests) ---
if (isset($_GET['api'])) {
    header('Content-Type: application/json; charset=utf-8');

    if (!file_exists($db_path)) {
        echo json_encode(['reports' => [], 'total' => 0]);
        exit;
    }

    $db = new SQLite3($db_path);
    $db->enableExceptions(true);

    $action = $_GET['api'];

    // DELETE a single report
    if ($action === 'delete' && isset($_GET['id'])) {
        $stmt = $db->prepare("DELETE FROM error_reports WHERE id = :id");
        $stmt->bindValue(':id', (int)$_GET['id'], SQLITE3_INTEGER);
        $stmt->execute();
        echo json_encode(['status' => 'ok']);
        exit;
    }

    // DELETE ALL reports
    if ($action === 'delete_all') {
        $db->exec("DELETE FROM error_reports");
        echo json_encode(['status' => 'ok']);
        exit;
    }

    // LIST reports (default)
    $page  = max(1, (int)($_GET['page'] ?? 1));
    $limit = 50;
    $offset = ($page - 1) * $limit;

    $total = $db->querySingle("SELECT COUNT(*) FROM error_reports");

    $stmt = $db->prepare("
        SELECT id, error_text, app_version, created_at
        FROM error_reports
        ORDER BY id DESC
        LIMIT :limit OFFSET :offset
    ");
    $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
    $stmt->bindValue(':offset', $offset, SQLITE3_INTEGER);
    $result = $stmt->execute();

    $reports = [];
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        $reports[] = $row;
    }

    echo json_encode(['reports' => $reports, 'total' => $total, 'page' => $page]);
    exit;
}

// --- HTML page ---
$display_name = htmlspecialchars($user['name'] ?? $user['preferred_username'] ?? $user['email'] ?? 'Użytkownik');
?>
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SnatchIT — Zgłoszenia błędów</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0f1117;
            color: #e2e4e9;
            min-height: 100vh;
        }

        .container {
            max-width: 960px;
            margin: 0 auto;
            padding: 2rem 1.5rem;
        }

        .top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        .user-info {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.85rem;
            color: #8b8fa3;
        }

        .user-info strong {
            color: #c5c8d4;
        }

        .user-info a {
            color: #6d8aff;
            text-decoration: none;
            margin-left: 0.5rem;
        }

        .user-info a:hover {
            text-decoration: underline;
        }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
            flex-wrap: wrap;
            gap: 1rem;
        }

        h1 {
            font-size: 1.5rem;
            font-weight: 600;
            color: #fff;
        }

        h1 span {
            color: #6d8aff;
        }

        .stats {
            font-size: 0.85rem;
            color: #8b8fa3;
        }

        .actions {
            display: flex;
            gap: 0.75rem;
        }

        button {
            padding: 0.5rem 1rem;
            border: 1px solid #2a2d3a;
            background: #1a1d28;
            color: #c5c8d4;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
            transition: all 0.15s;
        }

        button:hover {
            background: #252838;
            border-color: #3d4157;
            color: #fff;
        }

        button.danger {
            border-color: #5c2020;
            color: #ff6b6b;
        }

        button.danger:hover {
            background: #2a1515;
            border-color: #7a3030;
        }

        .report-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .report-card {
            background: #181b24;
            border: 1px solid #2a2d3a;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            transition: border-color 0.15s;
        }

        .report-card:hover {
            border-color: #3d4157;
        }

        .report-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        .report-meta .version {
            background: #252838;
            color: #8b8fa3;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-family: monospace;
        }

        .report-meta .date {
            color: #6b6f82;
            font-size: 0.8rem;
        }

        .report-text {
            font-family: 'Cascadia Code', 'Fira Code', monospace;
            font-size: 0.85rem;
            color: #d4d6dc;
            background: #12141b;
            padding: 0.75rem;
            border-radius: 4px;
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.5;
        }

        .report-actions {
            margin-top: 0.5rem;
            text-align: right;
        }

        .report-actions button {
            padding: 0.3rem 0.7rem;
            font-size: 0.78rem;
        }

        .empty-state {
            text-align: center;
            padding: 4rem 1rem;
            color: #5a5e70;
            font-size: 0.95rem;
        }

        .pagination {
            display: flex;
            justify-content: center;
            gap: 0.75rem;
            margin-top: 1.5rem;
        }

        .loading {
            text-align: center;
            padding: 3rem;
            color: #6b6f82;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="top-bar">
            <div class="user-info">
                Zalogowano jako: <strong><?= $display_name ?></strong>
                <a href="?logout">Wyloguj</a>
            </div>
        </div>

        <header>
            <div>
                <h1><span>SnatchIT</span> — Zgłoszenia błędów</h1>
                <div class="stats" id="stats"></div>
            </div>
            <div class="actions">
                <button onclick="loadReports()">Odśwież</button>
                <button class="danger" onclick="deleteAll()">Usuń wszystko</button>
            </div>
        </header>

        <div id="report-list" class="report-list">
            <div class="loading">Ładowanie...</div>
        </div>

        <div id="pagination" class="pagination"></div>
    </div>

    <script>
        let currentPage = 1;

        async function loadReports(page = 1) {
            currentPage = page;
            const container = document.getElementById('report-list');
            container.innerHTML = '<div class="loading">Ładowanie...</div>';

            try {
                const resp = await fetch(`?api=list&page=${page}`);
                const data = await resp.json();

                document.getElementById('stats').textContent =
                    `Łącznie zgłoszeń: ${data.total}`;

                if (data.reports.length === 0) {
                    container.innerHTML =
                        '<div class="empty-state">Brak zgłoszeń — wszystko działa! 🎉</div>';
                    document.getElementById('pagination').innerHTML = '';
                    return;
                }

                container.innerHTML = data.reports.map(r => `
                    <div class="report-card" id="report-${r.id}">
                        <div class="report-meta">
                            <span class="version">v${escHtml(r.app_version)}</span>
                            <span class="date">${escHtml(r.created_at)}</span>
                        </div>
                        <div class="report-text">${escHtml(r.error_text)}</div>
                        <div class="report-actions">
                            <button class="danger" onclick="deleteReport(${r.id})">Usuń</button>
                        </div>
                    </div>
                `).join('');

                // Pagination
                const totalPages = Math.ceil(data.total / 50);
                const pag = document.getElementById('pagination');
                if (totalPages <= 1) {
                    pag.innerHTML = '';
                } else {
                    let html = '';
                    if (page > 1)
                        html += `<button onclick="loadReports(${page - 1})">← Poprzednia</button>`;
                    html += `<span style="color:#6b6f82; line-height:2.2">${page} / ${totalPages}</span>`;
                    if (page < totalPages)
                        html += `<button onclick="loadReports(${page + 1})">Następna →</button>`;
                    pag.innerHTML = html;
                }
            } catch (e) {
                container.innerHTML =
                    '<div class="empty-state">Błąd ładowania danych.</div>';
            }
        }

        async function deleteReport(id) {
            if (!confirm('Usunąć to zgłoszenie?')) return;
            await fetch(`?api=delete&id=${id}`);
            document.getElementById(`report-${id}`)?.remove();
        }

        async function deleteAll() {
            if (!confirm('Na pewno usunąć WSZYSTKIE zgłoszenia?')) return;
            await fetch('?api=delete_all');
            loadReports();
        }

        function escHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        // Initial load
        loadReports();
    </script>
</body>
</html>
