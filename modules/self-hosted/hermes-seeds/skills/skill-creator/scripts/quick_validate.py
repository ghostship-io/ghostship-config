#!/usr/bin/env python3
"""
Quick validation script for skills - minimal version
"""

import sys
import re
import yaml
from pathlib import Path


REQUIRED_SECTIONS = (
    "## When to Use",
    "## Procedure",
    "## Pitfalls",
    "## Verification",
)

ALLOWED_CATEGORIES = {
    "autonomous-ai-agents",
    "creative",
    "data-science",
    "devops",
    "email",
    "gaming",
    "github",
    "leisure",
    "mcp",
    "media",
    "mlops",
    "note-taking",
    "productivity",
    "red-teaming",
    "research",
    "smart-home",
    "social-media",
    "software-development",
}


def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"

    # Read and validate frontmatter
    content = skill_md.read_text()
    if not content.startswith('---'):
        return False, "No YAML frontmatter found"

    # Extract frontmatter
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter_text = match.group(1)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary"
    except yaml.YAMLError as e:
        return False, f"Invalid YAML in frontmatter: {e}"

    # Define allowed properties
    ALLOWED_PROPERTIES = {
        'name',
        'description',
        'version',
        'license',
        'allowed-tools',
        'metadata',
        'platforms',
    }

    # Check for unexpected properties (excluding nested keys under metadata)
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    # Check required fields
    if 'name' not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if 'description' not in frontmatter:
        return False, "Missing 'description' in frontmatter"
    if 'version' not in frontmatter:
        return False, "Missing 'version' in frontmatter"

    # Extract name for validation
    name = frontmatter.get('name', '')
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if name:
        # Check naming convention (hyphen-case: lowercase with hyphens)
        if not re.match(r'^[a-z0-9-]+$', name):
            return False, f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)"
        if name.startswith('-') or name.endswith('-') or '--' in name:
            return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
        # Check name length (max 64 characters per spec)
        if len(name) > 64:
            return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    # Extract and validate description
    description = frontmatter.get('description', '')
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if description:
        # Check for angle brackets
        if '<' in description or '>' in description:
            return False, "Description cannot contain angle brackets (< or >)"
        # Check description length (max 1024 characters per spec)
        if len(description) > 1024:
            return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    version = frontmatter.get('version', '')
    if not isinstance(version, str) or not version.strip():
        return False, "Version must be a non-empty string"

    metadata = frontmatter.get('metadata')
    if metadata is not None:
        if not isinstance(metadata, dict):
            return False, "Metadata must be a YAML dictionary"
        hermes_metadata = metadata.get('hermes')
        if hermes_metadata is not None:
            if not isinstance(hermes_metadata, dict):
                return False, "metadata.hermes must be a YAML dictionary"

            allowed_hermes_keys = {'category', 'tags', 'config'}
            unexpected_hermes_keys = set(hermes_metadata.keys()) - allowed_hermes_keys
            if unexpected_hermes_keys:
                return False, (
                    "Unexpected key(s) in metadata.hermes: "
                    f"{', '.join(sorted(unexpected_hermes_keys))}. "
                    f"Allowed properties are: {', '.join(sorted(allowed_hermes_keys))}"
                )

            category = hermes_metadata.get('category')
            if category is not None and (not isinstance(category, str) or not category.strip()):
                return False, "metadata.hermes.category must be a non-empty string when present"

            tags = hermes_metadata.get('tags')
            if tags is not None:
                if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) and tag.strip() for tag in tags):
                    return False, "metadata.hermes.tags must be a non-empty list of strings when present"

            config = hermes_metadata.get('config')
            if config is not None:
                if not isinstance(config, list):
                    return False, "metadata.hermes.config must be a list when present"
                for index, entry in enumerate(config, start=1):
                    if not isinstance(entry, dict):
                        return False, f"metadata.hermes.config entry {index} must be a dictionary"
                    if 'key' not in entry or 'description' not in entry:
                        return False, f"metadata.hermes.config entry {index} must include 'key' and 'description'"
                    if not isinstance(entry['key'], str) or not entry['key'].strip():
                        return False, f"metadata.hermes.config entry {index} has an invalid 'key'"
                    if not isinstance(entry['description'], str) or not entry['description'].strip():
                        return False, f"metadata.hermes.config entry {index} has an invalid 'description'"

    if skill_path.name != name:
        return False, f"Skill directory name '{skill_path.name}' must match frontmatter name '{name}'"

    if skill_path.parent.name == 'skills':
        return False, (
            "Skill directory must live under a category folder like "
            "skills/<category>/<skill-name>, not directly under skills/"
        )

    if skill_path.parent.parent.name == 'skills':
        category = skill_path.parent.name
        if category not in ALLOWED_CATEGORIES:
            return False, (
                f"Skill category '{category}' is not one of the supported upstream categories: "
                + ', '.join(sorted(ALLOWED_CATEGORIES))
            )

    body = content[match.end():]
    missing_sections = [section for section in REQUIRED_SECTIONS if section not in body]
    if missing_sections:
        return False, (
            "Missing required section(s) in SKILL.md body: "
            + ', '.join(missing_sections)
        )

    return True, "Hermes skill is valid!"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
