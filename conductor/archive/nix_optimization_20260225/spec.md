# Track Specification: Nix Build and Download Optimization

## Overview
This track addresses performance warnings and optimizes the Nix daemon configuration for a better development experience, specifically focusing on large downloads.

## Requirements
- **Download Buffer**: Increase `download-buffer-size` to `134217728` (128MB).
- **Concurrency**: Set `max-jobs` to `auto` (if not already default).
- **Cleanup**: Ensure `auto-optimise-store` remains enabled.

## Success Criteria
- `modules/common/default.nix` reflects the updated settings.
- The "download buffer is full" warning is resolved on subsequent builds.
