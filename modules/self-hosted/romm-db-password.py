"""Converge an existing MariaDB's root accounts to the encrypted credential."""

import re
import subprocess
import sys
from pathlib import Path


def query(container, password, sql):
    # The password and SQL travel over stdin; neither appears in argv.
    return subprocess.run(
        ["podman", "exec", "-i", container, "sh", "-c",
         "IFS= read -r MYSQL_PWD; export MYSQL_PWD; "
         "exec mariadb --no-defaults --user=root --batch --skip-column-names"],
        input=password + "\n" + sql, text=True, capture_output=True, timeout=60,
    )


def migrate(container, password):
    # Generated credentials are hexadecimal, simplifying both SQL and stdin.
    if not re.fullmatch(r"[0-9a-f]{64}", password):
        raise ValueError("Expected a generated 256-bit database admin credential")
    sql = "SELECT HEX(Host) FROM mysql.user WHERE User='root';\n"
    result = query(container, password, sql)
    current_password = password
    if result.returncode:
        current_password = ""
        result = query(container, current_password, sql)
    if result.returncode:
        raise RuntimeError("Cannot authenticate database root; migration stopped")
    hosts = [bytes.fromhex(line).decode() for line in result.stdout.splitlines()]
    if not hosts:
        raise RuntimeError("No database root accounts found")
    statements = []
    for host in hosts:
        quoted_host = host.replace("\\", "\\\\").replace("'", "''")
        statements.append(
            f"ALTER USER 'root'@'{quoted_host}' IDENTIFIED BY '{password}';"
        )
    if query(container, current_password, "\n".join(statements) + "\n").returncode:
        raise RuntimeError("Database root-password migration failed")
    if query(container, password, "SELECT 1;\n").returncode:
        raise RuntimeError("New database root credential could not be verified")
    if query(container, "", "SELECT 1;\n").returncode == 0:
        raise RuntimeError("Passwordless database root access is still possible")


if __name__ == "__main__":
    try:
        source = Path(sys.argv[1]).read_text()
        password = re.search(r"^MYSQL_ROOT_PASSWORD=([0-9a-f]{64})$", source, re.MULTILINE)
        if password is None:
            raise ValueError("Missing database admin credential")
        migrate(sys.argv[2] if len(sys.argv) > 2 else "romm-db", password.group(1))
    except (KeyError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        raise SystemExit("RomM database root-password migration failed; credentials redacted")
