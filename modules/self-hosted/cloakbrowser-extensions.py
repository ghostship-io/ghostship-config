import os
import pwd
import re
import shutil
import struct
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = Path("/srv/apps/cloakbrowser/data/extensions")
CHROME_VERSION = "140.0.7339.208"
CWS_URL = (
    "https://clients2.google.com/service/update2/crx"
    "?response=redirect"
    f"&prodversion={CHROME_VERSION}"
    "&acceptformat=crx2,crx3"
    "&x=id%3D{extension_id}%26installsource%3Dondemand%26uc"
)

EXTENSIONS = (
    {
        "name": "ublock-origin-lite",
        "url": CWS_URL.format(extension_id="ddkjiahejlhfcafbddmgiahcphecmpfh"),
    },
    {
        "name": "i-still-dont-care-about-cookies",
        "url": CWS_URL.format(extension_id="edibdbjcniadpccecjdfdjjppcpchdlm"),
    },
    {
        "name": "bypass-paywalls-chrome-clean",
        "url": "https://gitflic.ru/project/magnolia1234/bpc_uploads/blob/raw?file=bypass-paywalls-chrome-clean-master.zip",
    },
)

UBOL_RULESETS = {
    "ublock-filters",
    "easylist",
    "easyprivacy",
    "pgl",
    "adguard-mobile",
    "adguard-spyware-url",
    "block-lan",
    "ublock-badware",
    "urlhaus-full",
    "annoyances-ai",
    "annoyances-cookies",
    "annoyances-notifications",
    "annoyances-others",
    "annoyances-overlays",
    "annoyances-social",
    "annoyances-widgets",
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"empty download from {url}")
    return data


def crx_to_zip(data: bytes) -> bytes:
    if data.startswith(b"PK"):
        return data
    if not data.startswith(b"Cr24"):
        raise RuntimeError(f"unknown extension archive header: {data[:8]!r}")

    version = struct.unpack_from("<I", data, 4)[0]
    if version == 2:
        public_key_len, signature_len = struct.unpack_from("<II", data, 8)
        offset = 16 + public_key_len + signature_len
    elif version == 3:
        header_len = struct.unpack_from("<I", data, 8)[0]
        offset = 12 + header_len
    else:
        raise RuntimeError(f"unsupported CRX version {version}")

    payload = data[offset:]
    if not payload.startswith(b"PK"):
        raise RuntimeError("CRX payload is not a zip archive")
    return payload


def safe_extract_zip(data: bytes, destination: Path) -> None:
    archive = destination / "archive.zip"
    archive.write_bytes(data)
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            target = (destination / member.filename).resolve()
            if not str(target).startswith(str(destination.resolve()) + os.sep):
                raise RuntimeError(f"unsafe archive path: {member.filename}")
        zip_file.extractall(destination)
    archive.unlink()


def find_extension_root(extract_dir: Path) -> Path:
    manifests = [
        path
        for path in extract_dir.rglob("manifest.json")
        if "__MACOSX" not in path.parts
    ]
    if not manifests:
        raise RuntimeError(f"no manifest.json found under {extract_dir}")
    return min(manifests, key=lambda path: len(path.relative_to(extract_dir).parts)).parent


def install_extension(name: str, url: str) -> Path:
    target = BASE / name
    print(f"Installing {name}...")

    with tempfile.TemporaryDirectory(prefix=f"{name}.", dir=str(BASE)) as tmp_dir:
        temp = Path(tmp_dir)
        safe_extract_zip(crx_to_zip(fetch(url)), temp)
        root = find_extension_root(temp)

        staged = BASE / f".{name}.staged"
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(root, staged)

        if target.exists():
            shutil.rmtree(target)
        staged.rename(target)

    return target


def configure_ubol(root: Path) -> None:
    manifest = root / "manifest.json"
    manifest_data = json.loads(manifest.read_text())
    for ruleset in manifest_data.get("declarative_net_request", {}).get("rule_resources", []):
        if ruleset.get("id") in UBOL_RULESETS:
            ruleset["enabled"] = True
    manifest.write_text(json.dumps(manifest_data, indent=2) + "\n")

    ruleset_details = root / "rulesets" / "ruleset-details.json"
    details = json.loads(ruleset_details.read_text())
    for ruleset in details:
        if ruleset.get("id") in UBOL_RULESETS:
            ruleset["enabled"] = True
    ruleset_details.write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n")

    config = root / "js" / "config.js"
    text = config.read_text()
    text, count = re.subn(
        r"enabledRulesets:\s*\[\],",
        "enabledRulesets: " + json.dumps(sorted(UBOL_RULESETS)) + ",",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("unable to set uBlock Origin Lite default rulesets")
    config.write_text(text)

    mode_manager = root / "js" / "mode-manager.js"
    text = mode_manager.read_text()
    text, count = re.subn(
        r"complete:\s*\[\],",
        "complete: [ 'all-urls' ],",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("unable to set uBlock Origin Lite complete filtering")
    mode_manager.write_text(text)


def configure_bypass_paywalls(root: Path) -> None:
    manifest = root / "manifest.json"
    data = json.loads(manifest.read_text())
    host_permissions = set(data.get("host_permissions") or [])
    host_permissions.add("*://*/*")
    data["host_permissions"] = sorted(host_permissions)
    data["optional_host_permissions"] = [
        item for item in data.get("optional_host_permissions") or []
        if item != "*://*/*"
    ]
    manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    background = root / "background.js"
    text = background.read_text()
    text = re.sub(r"optIn:\s*false,", "optIn: true,", text, count=1)
    text = re.sub(r"optInUpdate:\s*(true|false)", "optInUpdate: true", text, count=1)
    text = re.sub(
        r"sites_custom:\s*\{\},",
        "sites_custom: {},\n  customOptIn: true,\n  optInShown: true,\n  customShown: true,\n  fetchShown: true,",
        text,
        count=1,
    )
    text = text.replace(
        "return val.domain && !val.domain.match(/^(###$|#options_(disable|optin)_)/)",
        "return val.domain && !val.domain.match(/^(###$|#options_)/) || val.domain === '#options_enable_new_sites' || val.domain === '#options_optin_update_rules'",
        1,
    )
    text = text.replace(
        "var sites = items.sites;",
        "var sites = items.sites;\n"
        "    if (!sites['#options_enable_new_sites']) "
        "sites['#options_enable_new_sites'] = '#options_enable_new_sites';\n"
        "    if (!sites['#options_optin_update_rules']) "
        "sites['#options_optin_update_rules'] = '#options_optin_update_rules';\n"
        "    delete sites['#options_on_update'];",
        1,
    )
    text = text.replace(
        "ext_api.runtime.openOptionsPage();",
        "void 0; /* ghostship default: suppress automatic options page */",
    )
    text = text.replace(
        "if (!result.optInShown || !result.customShown || (!ext_chromium && !result.fetchShown)) {",
        "if (false && (!result.optInShown || !result.customShown || (!ext_chromium && !result.fetchShown))) {",
        1,
    )
    background.write_text(text)


def make_readable(path: Path) -> None:
    user = pwd.getpwnam("apps")
    for root, dirs, files in os.walk(path):
        os.chown(root, user.pw_uid, user.pw_gid)
        os.chmod(root, 0o755)
        for dirname in dirs:
            item = os.path.join(root, dirname)
            os.chown(item, user.pw_uid, user.pw_gid)
            os.chmod(item, 0o755)
        for filename in files:
            item = os.path.join(root, filename)
            os.chown(item, user.pw_uid, user.pw_gid)
            os.chmod(item, 0o644)


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)

    for extension in EXTENSIONS:
        root = install_extension(extension["name"], extension["url"])
        if extension["name"] == "ublock-origin-lite":
            configure_ubol(root)
        elif extension["name"] == "bypass-paywalls-chrome-clean":
            configure_bypass_paywalls(root)

    make_readable(BASE)


if __name__ == "__main__":
    main()
