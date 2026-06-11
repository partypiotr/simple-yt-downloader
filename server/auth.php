<?php
// SnatchIT OIDC Authentication Helper
// Implements Authorization Code Flow with Pocket ID
// ----------------------------------------------------------

require_once __DIR__ . '/config.php';

session_start();

/**
 * Returns the authenticated user array, or null if not logged in.
 */
function oidc_get_user(): ?array {
    return $_SESSION['oidc_user'] ?? null;
}

/**
 * Ensures the user is authenticated. Redirects to Pocket ID if not.
 */
function oidc_require_auth(): array {
    $user = oidc_get_user();
    if ($user) {
        return $user;
    }

    // Check if this is the callback from Pocket ID
    if (isset($_GET['callback'])) {
        return oidc_handle_callback();
    }

    // Redirect to Pocket ID login
    oidc_redirect_to_login();
    exit;
}

/**
 * Redirects the browser to Pocket ID's authorization endpoint.
 */
function oidc_redirect_to_login(): void {
    // Generate and store a random state for CSRF protection
    $state = bin2hex(random_bytes(16));
    $_SESSION['oidc_state'] = $state;

    $params = http_build_query([
        'response_type' => 'code',
        'client_id'     => OIDC_CLIENT_ID,
        'redirect_uri'  => OIDC_REDIRECT_URI,
        'scope'         => 'openid profile email',
        'state'         => $state,
    ]);

    header('Location: ' . OIDC_AUTH_URL . '?' . $params);
    exit;
}

/**
 * Handles the callback from Pocket ID: exchanges code for tokens, fetches user info.
 */
function oidc_handle_callback(): array {
    // Verify state to prevent CSRF
    if (empty($_GET['state']) || $_GET['state'] !== ($_SESSION['oidc_state'] ?? '')) {
        http_response_code(403);
        die('Błąd bezpieczeństwa: nieprawidłowy stan sesji. Spróbuj ponownie.');
    }
    unset($_SESSION['oidc_state']);

    if (empty($_GET['code'])) {
        http_response_code(400);
        die('Brak kodu autoryzacji od Pocket ID.');
    }

    // Exchange authorization code for tokens
    $token_data = oidc_exchange_code($_GET['code']);
    if (!$token_data || empty($token_data['access_token'])) {
        http_response_code(500);
        die('Nie udało się uzyskać tokenu od Pocket ID.');
    }

    // Fetch user info using the access token
    $user = oidc_fetch_userinfo($token_data['access_token']);
    if (!$user) {
        http_response_code(500);
        die('Nie udało się pobrać danych użytkownika od Pocket ID.');
    }

    // Store user in session
    $_SESSION['oidc_user'] = $user;
    $_SESSION['oidc_id_token'] = $token_data['id_token'] ?? null;

    // Redirect to admin panel (remove query params)
    header('Location: admin.php');
    exit;
}

/**
 * Exchanges an authorization code for access + id tokens.
 */
function oidc_exchange_code(string $code): ?array {
    $post_data = http_build_query([
        'grant_type'    => 'authorization_code',
        'code'          => $code,
        'redirect_uri'  => OIDC_REDIRECT_URI,
        'client_id'     => OIDC_CLIENT_ID,
        'client_secret' => OIDC_CLIENT_SECRET,
    ]);

    $ctx = stream_context_create([
        'http' => [
            'method'  => 'POST',
            'header'  => 'Content-Type: application/x-www-form-urlencoded',
            'content' => $post_data,
            'timeout' => 10,
        ],
    ]);

    $response = @file_get_contents(OIDC_TOKEN_URL, false, $ctx);
    if ($response === false) return null;

    return json_decode($response, true);
}

/**
 * Fetches user profile from the OIDC userinfo endpoint.
 */
function oidc_fetch_userinfo(string $access_token): ?array {
    $ctx = stream_context_create([
        'http' => [
            'method'  => 'GET',
            'header'  => 'Authorization: Bearer ' . $access_token,
            'timeout' => 10,
        ],
    ]);

    $response = @file_get_contents(OIDC_USERINFO_URL, false, $ctx);
    if ($response === false) return null;

    return json_decode($response, true);
}

/**
 * Logs the user out (destroys session, optionally redirects to Pocket ID logout).
 */
function oidc_logout(): void {
    $id_token = $_SESSION['oidc_id_token'] ?? null;

    session_destroy();

    if ($id_token) {
        $params = http_build_query([
            'id_token_hint'            => $id_token,
            'post_logout_redirect_uri' => OIDC_REDIRECT_URI,
        ]);
        header('Location: ' . OIDC_LOGOUT_URL . '?' . $params);
    } else {
        header('Location: admin.php');
    }
    exit;
}
