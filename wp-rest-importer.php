<?php

error_reporting(E_ALL);
ini_set('display_errors', 1);
$base_url = "https://www.spectator.org"; // Replace with your WordPress site URL
$file_name = "spectator-org.xml";
$postsPerRequest = 10;
$totalPosts = 0;

// Get the total number of posts
$response = file_get_contents($base_url . "/wp-json/wp/v2/posts?per_page=1");
$headers = get_headers($base_url . "/wp-json/wp/v2/posts?per_page=1", 1);
$totalPosts = $headers['X-WP-Total'];
$totalIterations = ceil($totalPosts / $postsPerRequest);

echo "Processing " . $totalPosts . " posts from " . $base_url . "...";

// Initialize the content variable
$file_content = '';

for ($i = 0; $i < $totalIterations; $i++) {
  // Calc the offset
  $offset = $i * $postsPerRequest;

    // Set the URL endpoint
  $url = $base_url . "/wp-json/wp/v2/posts?per_page=$postsPerRequest&offset=$offset";

  // State progress start
  echo "Processing posts " . ($offset + 1) . " to " . min($offset + $postsPerRequest, $totalPosts) . "...";

  // Initialize curl
  $ch = curl_init();
  curl_setopt($ch, CURLOPT_URL, $url);
  curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

  // Send the request and get the response
  $response = curl_exec($ch);

  // Check for errors
  if (curl_errno($ch)) {
      echo "Error: " . curl_error($ch);
  }

  // Close the curl connection
  curl_close($ch);

  // Decode the response JSON
  $posts = json_decode($response, true);

  // Write the posts to the file_content variable
  foreach ($posts as $post) {
    $file_content .= "<item>\n";
    foreach ($post as $key => $value) {
        // Exclude certain fields if desired
        if ($key === 'id' || $key === 'guid' || $key === 'meta') {
            continue;
        }

        // Append the field to the XML content
        if (is_array($value)) {
            $value = json_encode($value);
        }
        $file_content .= "  <$key><![CDATA[" . htmlspecialchars($value) . "]]></$key>\n";
    }
    $file_content .= "</item>\n";
    file_put_contents($file_name, $file_content, FILE_APPEND);
    echo "Posts " . ($offset + 1) . " to " . min($offset + $postsPerRequest, $totalPosts) . " have been processed and written to the file.";
    // Flush output buffer
    ob_flush();
    flush();

    // Sleep for a bit to avoid hitting rate limits or timeouts
    sleep(10);
  }
}



/*
// Retrieve the total number of posts
$response = file_get_contents($base_url . "/wp-json/wp/v2/posts?per_page=1");
$headers = get_headers($base_url . "/wp-json/wp/v2/posts?per_page=1", 1);
$total_posts = $headers['X-WP-Total'];

echo "Total Posts: $total_posts<br>";
echo "Import Progress: 0%<br>";

do {
    $url = $base_url . "/wp-json/wp/v2/posts?page=$page&per_page=$per_page";
    $response = file_get_contents($url);
    $posts = json_decode($response, true);

    if (!empty($posts)) {
        $all_posts = array_merge($all_posts, $posts);
    }

    $page++;
    
    // Calculate the progress percentage
    $progress = count($all_posts) / $total_posts * 100;
    echo "Import Progress: " . round($progress, 2) . "%<br>";
} while (!empty($posts));

// Generate the import file content
$file_content = '';

foreach ($all_posts as $post) {
    $file_content .= "<item>\n";
    foreach ($post as $key => $value) {
        // Exclude certain fields if desired
        if ($key === 'id' || $key === 'guid' || $key === 'meta') {
            continue;
        }

        // Append the field to the XML content
        $file_content .= "  <$key><![CDATA[$value]]></$key>\n";
    }
    $file_content .= "</item>\n";
}

// Write the import file
$file_path = "posts.xml"; // Specify the file path and name
file_put_contents($file_path, $file_content);

echo "Import Progress: 100%<br>";
echo "Posts have been written to $file_path";
?>
*/