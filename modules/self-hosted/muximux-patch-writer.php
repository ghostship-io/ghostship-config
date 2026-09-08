<?php
// Run after the image installs Muximux and before PHP starts serving requests.
$path = $argv[1];
$source = file_get_contents($path);
$replacement = preg_replace('/^<\?php\r?\n/', '', file_get_contents($argv[2]));
if ($source === false || $replacement === null) {
    throw new RuntimeException('Cannot read the Muximux writer sources');
}
$updated = preg_replace_callback(
    '/^function saveConfig\(\$inConfig\) \{.*?^\}/ms',
    function () use ($replacement) { return rtrim($replacement); },
    $source, 1, $count
);
if ($count !== 1 || $updated === null) {
    throw new RuntimeException('Muximux saveConfig contract changed; refusing an unverified patch');
}
if (file_put_contents($path, $updated, LOCK_EX) === false) {
    throw new RuntimeException('Cannot install the Muximux settings writer');
}
