## ADDED Requirements

### Requirement: Gemini system settings remain free of deprecated config keys
The repo SHALL generate a Gemini system settings file for develop hosts that remains valid for the current supported Gemini CLI release and SHALL not emit deprecated settings keys that trigger startup warnings.

#### Scenario: Generated Gemini system settings omit deprecated experimental plan mode
- **WHEN** the generated develop-host `gemini-cli/settings.json` file is inspected
- **THEN** it SHALL not contain the `experimental.plan` setting

#### Scenario: Gemini starts without the deprecated system-settings warning
- **WHEN** a develop host launches the managed `gemini` wrapper after switching to the updated configuration
- **THEN** Gemini SHALL not warn that the read-only system configuration still contains deprecated `experimental.plan` settings
