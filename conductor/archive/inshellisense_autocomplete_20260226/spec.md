# Specification: inshellisense Shell Autocomplete Configuration

## Overview
Configure `inshellisense` to utilize the shell's native autocompletion capabilities for an enhanced interactive experience within the Fish shell. This will involve creating a dedicated JSON configuration file managed by Home Manager.

## Functional Requirements
- **Configuration File Creation**: Create a JSON configuration file for `inshellisense` at a standard location (e.g., `~/.config/inshellisense/config.json`) managed by Home Manager (`home.file`).
- **Configuration Content**: The `config.json` file must contain the following settings:
    ```json
    {
      "shell": "fish",
      "showHelp": true,
      "completionMode": "shell"
    }
    ```
- **Integration**: Ensure that `inshellisense` picks up this configuration when launched within the Fish shell environment.

## Non-Functional Requirements
- **Seamless Operation**: Autocompletion should function without requiring manual intervention after initial setup.
- **Maintainability**: The configuration should be declarative and easily managed through Home Manager.

## Acceptance Criteria
- [ ] The `inshellisense` configuration file exists at `~/.config/inshellisense/config.json`.
- [ ] The `config.json` file contains the specified JSON content, specifically `"showHelp": true`.
- [ ] `inshellisense` provides autocompletion suggestions from the shell.
- [ ] `inshellisense` shows inline help automatically (as `showHelp` is true).

## Out of Scope
- Modifications to `inshellisense`'s core functionality or other shell integrations.
- Managing other `inshellisense` settings beyond those specified.