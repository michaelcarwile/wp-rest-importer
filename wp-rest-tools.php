<?php

/**
 * WP REST API Post Exporter
 *
 * Exports all posts from a WordPress site via the REST API to an XML file.
 *
 * Usage: php wp-rest-importer.php --url=<site-url> [--output=<filename>] [--per-page=<n>] [--delay=<seconds>]
 *
 * Examples:
 *   php wp-rest-importer.php --url=https://www.example.com
 *   php wp-rest-importer.php --url=https://www.example.com --output=posts.xml --per-page=20
 */

error_reporting(E_ALL);
ini_set('display_errors', 1);

// --- Configuration via CLI args ---
$options = getopt('', ['url:', 'output:', 'per-page:', 'delay:']);

if (empty($options['url'])) {
    fwrite(STDERR, "Usage: php wp-rest-importer.php --url=<site-url> [--output=<filename>] [--per-page=<n>] [--delay=<seconds>]\n");
    exit(1);
}

$baseUrl       = rtrim($options['url'], '/');
$domain        = parse_url($baseUrl, PHP_URL_HOST);
$domain        = preg_replace('/^www\./', '', $domain);
$outputFile    = $options['output'] ?? "$domain-export.xml";
$postsPerPage  = (int) ($options['per-page'] ?? 10);
$delaySeconds  = (int) ($options['delay'] ?? 2);

// --- Discover total post count ---
$endpoint = "$baseUrl/wp-json/wp/v2/posts";

$headers = @get_headers("$endpoint?per_page=1", 1);
if ($headers === false) {
    fwrite(STDERR, "Error: Could not connect to $baseUrl\n");
    exit(1);
}

$totalPosts = (int) ($headers['X-WP-Total'] ?? $headers['x-wp-total'] ?? 0);
if ($totalPosts === 0) {
    fwrite(STDERR, "Error: No posts found or X-WP-Total header missing.\n");
    exit(1);
}

$totalPages = ceil($totalPosts / $postsPerPage);
echo "Found $totalPosts posts across $totalPages pages at $baseUrl\n";

// --- Fetch and write ---
$fp = fopen($outputFile, 'w');
if ($fp === false) {
    fwrite(STDERR, "Error: Could not open $outputFile for writing.\n");
    exit(1);
}

fwrite($fp, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
fwrite($fp, "<posts>\n");

$fieldsToSkip = ['id', 'guid', 'meta', 'yoast_head', 'yoast_head_json', 'class_list', '_links'];

for ($page = 1; $page <= $totalPages; $page++) {
    $offset = ($page - 1) * $postsPerPage;
    $url = "$endpoint?per_page=$postsPerPage&offset=$offset";

    echo "  Page $page/$totalPages (posts " . ($offset + 1) . "-" . min($offset + $postsPerPage, $totalPosts) . ")...";

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT        => 30,
    ]);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);

    if (curl_errno($ch)) {
        fwrite(STDERR, "\n  Error on page $page: " . curl_error($ch) . "\n");
        curl_close($ch);
        continue;
    }
    curl_close($ch);

    if ($httpCode !== 200) {
        fwrite(STDERR, "\n  HTTP $httpCode on page $page, skipping.\n");
        continue;
    }

    $posts = json_decode($response, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        fwrite(STDERR, "\n  JSON decode error on page $page: " . json_last_error_msg() . "\n");
        continue;
    }

    foreach ($posts as $post) {
        fwrite($fp, "  <item>\n");
        foreach ($post as $key => $value) {
            if (in_array($key, $fieldsToSkip, true)) {
                continue;
            }
            if (is_array($value)) {
                $value = json_encode($value);
            }
            fwrite($fp, "    <$key><![CDATA[$value]]></$key>\n");
        }
        fwrite($fp, "  </item>\n");
    }

    echo " done.\n";

    if ($page < $totalPages) {
        sleep($delaySeconds);
    }
}

fwrite($fp, "</posts>\n");
fclose($fp);

echo "Export complete: $outputFile ($totalPosts posts)\n";
