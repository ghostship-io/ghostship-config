<?php
function saveConfig($inConfig) {
    // Ghostship: publish a complete protected INI atomically for concurrent readers.
    $temporary = tempnam(dirname(CONFIG), '.muximux-config-');
    if ($temporary === false) {
        throw new RuntimeException('Cannot create temporary Muximux settings');
    }
    try {
        $inConfig->write($temporary, $inConfig->get(), LOCK_EX);
        $body = file_get_contents($temporary);
        if ($body === false || file_put_contents(
            $temporary, "; <?php die('Access denied'); ?>\n" . $body, LOCK_EX
        ) === false || !chmod($temporary, 0600) || !rename($temporary, CONFIG)) {
            throw new RuntimeException('Cannot publish Muximux settings');
        }
    } finally {
        if (file_exists($temporary)) {
            unlink($temporary);
        }
    }
}
