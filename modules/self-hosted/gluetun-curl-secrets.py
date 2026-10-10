"""Send sensitive curl options over stdin, never through process arguments."""

import os
import sys


def option(name, value):
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'{name} = "{value}"\n'


def main():
    if sys.argv[1:] == ["token"]:
        sys.stdout.write(option("form-string", "username=" + os.environ["PIA_CURL_USER"]))
        sys.stdout.write(option("form-string", "password=" + os.environ["PIA_CURL_PASSWORD"]))
    elif sys.argv[1:] == ["add-key"]:
        sys.stdout.write(option("data-urlencode", "pt=" + os.environ["PIA_CURL_TOKEN"]))
    else:
        raise SystemExit("Expected token or add-key")


if __name__ == "__main__":
    main()
