import sys
import os
import argparse
import logging
import re
import configparser
import tempfile
from io import StringIO
from lxml import etree
from ruamel.yaml import YAML

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class ValueResolver:
    def __init__(self, secrets_files=None):
        self.secrets = {}
        if secrets_files is None:
            return

        if isinstance(secrets_files, str):
            secrets_files = [secrets_files]

        for secrets_file in secrets_files:
            if not secrets_file or not os.path.exists(secrets_file):
                continue

            try:
                with open(secrets_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and "=" in line and not line.startswith("#"):
                            # Handle 'export KEY=VAL' or 'KEY=VAL'
                            if line.startswith("export "):
                                line = line[7:].strip()
                            if "=" in line:
                                k, v = line.split("=", 1)
                                self.secrets[k.strip()] = v.strip()
            except Exception as e:
                logging.error(
                    f"Failed to load secrets file {secrets_file}: {e}"
                )

    def resolve(self, value):
        if value.startswith("env:"):
            var_name = value[4:]
            # Check local secrets dict first, then OS environment
            val = self.secrets.get(var_name) or os.environ.get(var_name)
            if val is None:
                logging.warning(f"Secret variable {var_name} not found")
                return ""
            return val
        if value.startswith("file:"):
            path = value[5:]
            try:
                with open(path, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logging.error(f"Failed to read secret from {path}: {e}")
                return ""
        if value.startswith("literal:"):
            return value[8:]
        if value.startswith("yaml:"):
            yaml = YAML(typ="safe")
            return yaml.load(value[5:])
        return value


class XMLDriver:
    def __init__(self, content):
        self.root = etree.fromstring(content.encode("utf-8"))
        self.tree = etree.ElementTree(self.root)
        self.dirty = False

    def set(self, path, value):
        if "@" in path:
            tag_path, attr = path.rsplit(".@", 1)
        else:
            tag_path, attr = path, None

        parts = tag_path.split(".")
        # Skip root if it matches
        if parts[0] == self.root.tag:
            parts = parts[1:]

        curr = self.root
        for part in parts:
            next_node = curr.find(part)
            if next_node is None:
                logging.debug(f"Creating missing XML element: {part}")
                next_node = etree.SubElement(curr, part)
                self.dirty = True
            curr = next_node

        if attr:
            if curr.get(attr) != value:
                curr.set(attr, value)
                self.dirty = True
        else:
            if curr.text != value:
                curr.text = value
                self.dirty = True

    def serialize(self):
        return etree.tostring(self.tree, pretty_print=True, encoding="unicode")


class YAMLDriver:
    def __init__(self, content):
        self.yaml = YAML(typ="rt")
        self.yaml.preserve_quotes = True
        self.data = self.yaml.load(content)
        self.dirty = False
        self.allow_missing = False

    def _coerce_value(self, current, value):
        if not isinstance(value, str):
            return value

        lowered = value.lower()

        if isinstance(current, bool):
            if lowered == "true":
                return True
            if lowered == "false":
                return False

        if isinstance(current, int) and not isinstance(current, bool):
            try:
                return int(value)
            except ValueError:
                return value

        if isinstance(current, float):
            try:
                return float(value)
            except ValueError:
                return value

        return value

    def _split_path(self, path):
        parts = []
        curr = []
        bracket_depth = 0

        for ch in path:
            if ch == "." and bracket_depth == 0:
                parts.append("".join(curr))
                curr = []
                continue

            if ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(0, bracket_depth - 1)

            curr.append(ch)

        parts.append("".join(curr))
        return parts

    def _new_selector_container(self, next_part):
        if next_part and re.fullmatch(r"\[(.+)\]", next_part):
            return []
        return {}

    def _select_from_list(self, items, selector, create_missing=False):
        if selector.isdigit():
            index = int(selector)
            if 0 <= index < len(items):
                return items[index]
            return None

        if "=" in selector:
            attr_key, attr_val = selector.split("=", 1)
            for item in items:
                if (
                    isinstance(item, dict)
                    and str(item.get(attr_key)) == attr_val
                ):
                    return item
            return None

        for item in items:
            if isinstance(item, dict) and selector in item:
                val = item[selector]
                if val is None:
                    item[selector] = {}
                    self.dirty = True
                    return item[selector]
                return val

        if create_missing:
            # Create a new mapping with the selector as a key (likely a group name or service name)
            new_item = {selector: {}}
            items.append(new_item)
            self.dirty = True
            return new_item[selector]

        return None

    def _select_from_mapping(self, mapping, selector):
        if selector in mapping:
            return mapping[selector]

        return None

    def _get_target(self, path):
        parts = self._split_path(path)
        curr = self.data
        for part in parts[:-1]:
            # Attribute selector: [key=val] or [key]
            match = re.fullmatch(r"(.*)\[(.+)\]", part)
            if match:
                list_name, selector = match.groups()
                if list_name:
                    if not isinstance(curr, dict):
                        return None, None
                    items = curr.get(list_name)
                else:
                    items = curr

                if isinstance(items, list):
                    curr = self._select_from_list(items, selector)
                elif isinstance(items, dict):
                    curr = self._select_from_mapping(items, selector)
                else:
                    logging.warning(
                        "Expected list or mapping for selector, got %s",
                        type(items),
                    )
                    return None, None

                if curr is None:
                    return None, None
            elif part.isdigit() and isinstance(curr, list):
                index = int(part)
                if not (0 <= index < len(curr)):
                    return None, None
                curr = curr[index]
            elif isinstance(curr, dict):
                curr = curr.get(part)
                if curr is None:
                    return None, None
            else:
                return None, None
        return curr, parts[-1]

    def set(self, path, value):
        parts = self._split_path(path)
        curr = self.data

        for i, part in enumerate(parts[:-1]):
            # Attribute selector: [key=val] or [key]
            match = re.fullmatch(r"(.*)\[(.+)\]", part)
            if match:
                list_name, selector = match.groups()
                if list_name:
                    items = curr.setdefault(list_name, [])
                else:
                    items = curr

                if isinstance(items, list):
                    # Try to find existing
                    found = False
                    if selector.isdigit():
                        index = int(selector)
                        if 0 <= index < len(items):
                            curr = items[index]
                            found = True
                    elif "=" in selector:
                        attr_key, attr_val = selector.split("=", 1)
                        for item in items:
                            if isinstance(item, dict) and str(item.get(attr_key)) == attr_val:
                                curr = item
                                found = True
                                break
                    else:
                        for item in items:
                            if isinstance(item, dict) and selector in item:
                                curr = item[selector]
                                if curr is None:
                                    item[selector] = self._new_selector_container(
                                        parts[i + 1]
                                    )
                                    curr = item[selector]
                                    self.dirty = True
                                found = True
                                break

                    if not found:
                        if selector.isdigit():
                            logging.warning(f"Index out of range for path part: {part}")
                            return
                        elif "=" in selector:
                            logging.warning(f"Attribute selector not found and creation not supported for: {part}")
                            return
                        else:
                            # Create new service entry in group
                            new_service = {
                                selector: self._new_selector_container(
                                    parts[i + 1]
                                )
                            }
                            items.append(new_service)
                            curr = new_service[selector]
                            self.dirty = True
                elif isinstance(items, dict):
                    curr = self._select_from_mapping(items, selector)
                    if curr is None:
                        logging.warning(f"Selector {selector} not found in mapping for path part: {part}")
                        return
                else:
                    logging.warning(f"Expected list or mapping for selector, got {type(items)}")
                    return
            elif part.isdigit() and isinstance(curr, list):
                curr = curr[int(part)]
            elif isinstance(curr, dict):
                curr = curr.setdefault(part, {})
            else:
                logging.warning(f"Path part {part} not found or invalid type")
                return

        # Handle the leaf
        target = curr
        key = parts[-1]

        key_match = re.fullmatch(r"(.*)\[(.+)\]", key)
        if key_match:
            list_name, selector = key_match.groups()
            if list_name:
                items = target.setdefault(list_name, [])
            else:
                items = target

            if isinstance(items, list):
                if selector.isdigit():
                    index = int(selector)
                    if not (0 <= index < len(items)):
                        logging.warning(f"Index out of range for key: {path}")
                        return

                    current = items[index]
                    typed_value = self._coerce_value(current, value)

                    if current != typed_value:
                        items[index] = typed_value
                        self.dirty = True
                    return
                elif "=" not in selector:
                    # Key selector for list of dicts: [Utilities].[OmniTools]
                    found_item = None
                    for item in items:
                        if isinstance(item, dict) and selector in item:
                            found_item = item
                            break

                    if found_item is not None:
                        current = found_item[selector]
                        typed_value = self._coerce_value(current, value)
                        if found_item[selector] != typed_value:
                            found_item[selector] = typed_value
                            self.dirty = True
                    else:
                        items.append({selector: value})
                        self.dirty = True
                    return
                else:
                    logging.warning(
                        f"Unsupported list selector for key: {path}"
                    )
                    return

            if not isinstance(items, dict):
                logging.warning(f"Expected list or mapping for key: {path}")
                return

            current = items.get(selector)
            typed_value = self._coerce_value(current, value)

            if current != typed_value:
                items[selector] = typed_value
                self.dirty = True
            return

        if isinstance(target, dict):
            current = target.get(key)
        else:
            current = None

        typed_value = self._coerce_value(current, value)

        if current != typed_value:
            if isinstance(target, dict):
                target[key] = typed_value
                self.dirty = True
            else:
                if not self.allow_missing:
                    logging.warning(
                        f"Cannot set {key} on non-dict target for path {path}"
                    )
    def delete(self, path):
        target, key = self._get_target(path)
        if target is None:
            if not self.allow_missing:
                logging.warning(f"Path not found: {path}")
            return

        key_match = re.fullmatch(r"(.*)\[(.+)\]", key)
        if key_match:
            list_name, selector = key_match.groups()
            if list_name:
                items = target.get(list_name)
            else:
                items = target

            if isinstance(items, list):
                if selector.isdigit():
                    index = int(selector)
                    if 0 <= index < len(items):
                        items.pop(index)
                        self.dirty = True
                    return
                elif "=" not in selector:
                    # Key selector for list of dicts: [Media].[IT-Tools]
                    for i, item in enumerate(items):
                        if isinstance(item, dict) and selector in item:
                            items.pop(i)
                            self.dirty = True
                            return
                return

            if isinstance(items, dict) and selector in items:
                del items[selector]
                self.dirty = True
            return

        if isinstance(target, dict) and key in target:
            del target[key]
            self.dirty = True

    def serialize(self):
        stream = StringIO()
        self.yaml.dump(self.data, stream)
        return stream.getvalue()


class INIDriver:
    def __init__(self, content):
        self.header = ""
        if content.startswith("<?php"):
            lines = content.splitlines(keepends=True)
            self.header = lines[0]
            content = "".join(lines[1:])

        self.config = configparser.ConfigParser(interpolation=None)
        self.config.optionxform = str
        self.config.read_string(content)
        self.dirty = False

    def set(self, path, value):
        if "." not in path:
            logging.warning(f"INI path must be Section.Key: {path}")
            return

        section, key = path.split(".", 1)
        if section in ["WebUI", "BitTorrent", "LegalNotice"]:
            key = key.replace(".", "\\")

        if not self.config.has_section(section):
            self.config.add_section(section)

        if not self.config.has_option(section, key) or self.config.get(
            section, key
        ) != str(value):
            self.config.set(section, key, str(value))
            self.dirty = True

    def serialize(self):
        stream = StringIO()
        self.config.write(stream)
        return self.header + stream.getvalue()


class KVDriver:
    def __init__(self, content):
        self.lines = content.splitlines()
        self.dirty = False

    def set(self, key, value):
        pattern = re.compile(rf"^{re.escape(key)}\s*=\s*(.*)")
        new_line = f"{key}={value}"
        for i, line in enumerate(self.lines):
            match = pattern.match(line)
            if match:
                if match.group(1) != str(value):
                    self.lines[i] = new_line
                    self.dirty = True
                return
        self.lines.append(new_line)
        self.dirty = True

    def serialize(self):
        return "\n".join(self.lines) + "\n"


class ConfigManager:
    def __init__(self, file_path, format_override=None, allow_missing=False):
        self.file_path = file_path
        self.format = format_override or self._detect_format()
        self.driver = None
        self.content = ""
        self.allow_missing = allow_missing

    def _detect_format(self):
        if os.path.basename(self.file_path) == "qBittorrent.conf":
            return "ini"

        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".xml":
            return "xml"
        if ext in [".yaml", ".yml"]:
            return "yaml"
        if ext in [".ini", ".php"]:
            return "ini"
        if ext in [".conf", ".env"]:
            return "kv"
        return "kv"

    def load(self):
        with open(self.file_path, "r") as f:
            self.content = f.read()

        if self.format == "xml":
            self.driver = XMLDriver(self.content)
        elif self.format == "yaml":
            self.driver = YAMLDriver(self.content)
        elif self.format == "ini":
            self.driver = INIDriver(self.content)
        elif self.format == "kv":
            self.driver = KVDriver(self.content)

        if self.driver:
            self.driver.allow_missing = self.allow_missing

    def save(self, dry_run=False):
        if not self.driver or not self.driver.dirty:
            logging.info(f"No changes needed for {self.file_path}")
            return False

        new_content = self.driver.serialize()
        if dry_run:
            logging.info(f"Dry-run: Would write changes to {self.file_path}")
            return True

        with open(self.file_path, "w") as f:
            f.write(new_content)
        logging.info(f"Updated {self.file_path}")
        return True


def run_self_tests():
    logging.info("Running comprehensive self-tests...")

    def test_xml():
        content = (
            '<Preferences FriendlyName="old" TranscoderQuality="1">'
            "<Config><ApiKey>old</ApiKey></Config></Preferences>"
        )
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(content.encode())
            path = f.name
        try:
            m = ConfigManager(path)
            m.load()
            m.driver.set("Preferences.@FriendlyName", "new")
            m.driver.set("Preferences.Config.ApiKey", "new")
            m.driver.set("Preferences.NewTag", "new_val")
            m.save()
            with open(path, "r") as f:
                res = f.read()
                assert 'FriendlyName="new"' in res
                assert "<ApiKey>new</ApiKey>" in res
                assert "<NewTag>new_val</NewTag>" in res
            logging.info("XML comprehensive tests passed")
        finally:
            os.unlink(path)

    def test_yaml():
        content = """
services:
  - name: Sonarr
    key: old
server:
  image_proxy: true
  port: 8080
  bind_address: "127.0.0.1"
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(content.encode())
            path = f.name
        try:
            m = ConfigManager(path)
            m.load()
            m.driver.set("services[name=Sonarr].key", "new")
            m.driver.set("server.image_proxy", "false")
            m.driver.set("server.port", "5002")
            m.driver.set("server.bind_address", "0.0.0.0")
            m.save()
            with open(path, "r") as f:
                res = f.read()
                assert "key: new" in res
                assert "image_proxy: false" in res
                assert "port: 5002" in res
                assert 'bind_address: "0.0.0.0"' in res

            yaml = YAML(typ="safe")
            with open(path, "r") as f:
                data = yaml.load(f)
                assert data["server"]["image_proxy"] is False
                assert data["server"]["port"] == 5002
                assert data["server"]["bind_address"] == "0.0.0.0"
            logging.info("YAML comprehensive tests passed")
        finally:
            os.unlink(path)

    def test_yaml_poisoned_scalar_repair():
        content = """
server:
  image_proxy: 'true'
  port: '8080'
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(content.encode())
            path = f.name
        try:
            resolver = ValueResolver()
            m = ConfigManager(path)
            m.load()
            m.driver.set("server.image_proxy", resolver.resolve("yaml:false"))
            m.driver.set("server.port", resolver.resolve("yaml:5002"))
            m.save()

            yaml = YAML(typ="safe")
            with open(path, "r") as f:
                data = yaml.load(f)
                assert data["server"]["image_proxy"] is False
                assert data["server"]["port"] == 5002
            logging.info("YAML poisoned scalar repair tests passed")
        finally:
            os.unlink(path)

    def test_yaml_complex_paths():
        homepage_content = """
- Infrastructure:
  - Llama.cpp:
      icon: sh-old
      description: old
"""
        recyclarr_content = """
recyclarr:
  custom_formats:
  - trash_ids:
    - old-id
    assign_scores_to:
    - name: Optimal
      score: 100
"""
        searxng_content = """
plugins:
  searx.plugins.calculator.SXNGPlugin:
    active: false
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f1:
            with tempfile.NamedTemporaryFile(
                suffix=".yaml", delete=False
            ) as f2:
                with tempfile.NamedTemporaryFile(
                    suffix=".yaml", delete=False
                ) as f3:
                    f1.write(homepage_content.encode())
                    f2.write(recyclarr_content.encode())
                    f3.write(searxng_content.encode())
                    homepage_path = f1.name
                    recyclarr_path = f2.name
                    searxng_path = f3.name
        try:
            resolver = ValueResolver()
            homepage = ConfigManager(homepage_path)
            homepage.load()
            homepage.driver.set(
                "[Infrastructure].[Llama.cpp].icon", "sh-ollama"
            )
            homepage.save()

            recyclarr = ConfigManager(recyclarr_path)
            recyclarr.load()
            recyclarr.driver.set(
                "recyclarr.custom_formats[0].trash_ids[0]",
                "new-id",
            )
            recyclarr.driver.set(
                (
                    "recyclarr.custom_formats[0]."
                    "assign_scores_to[name=Optimal].score"
                ),
                resolver.resolve("yaml:900"),
            )
            recyclarr.save()

            searxng = ConfigManager(searxng_path)
            searxng.load()
            searxng.driver.set(
                (
                    "plugins[searx.plugins.calculator.SXNGPlugin]."
                    "active"
                ),
                resolver.resolve("yaml:true"),
            )
            searxng.save()

            yaml = YAML(typ="safe")
            with open(homepage_path, "r") as f:
                homepage_data = yaml.load(f)
                assert (
                    homepage_data[0]["Infrastructure"][0]["Llama.cpp"]["icon"]
                    == "sh-ollama"
                )
            with open(recyclarr_path, "r") as f:
                recyclarr_data = yaml.load(f)
                assert (
                    recyclarr_data["recyclarr"]["custom_formats"][0][
                        "trash_ids"
                    ][0]
                    == "new-id"
                )
                assert (
                    recyclarr_data["recyclarr"]["custom_formats"][0][
                        "assign_scores_to"
                    ][0]["score"]
                    == 900
                )
            with open(searxng_path, "r") as f:
                searxng_data = yaml.load(f)
                assert (
                    searxng_data["plugins"][
                        "searx.plugins.calculator.SXNGPlugin"
                    ]["active"]
                    is True
                )
            logging.info("YAML complex path tests passed")
        finally:
            os.unlink(homepage_path)
            os.unlink(recyclarr_path)
            os.unlink(searxng_path)

    def test_ini():
        content = "<?php die(); ?>\n[General]\nkey = old\n[WebUI]\nPort = 8080"
        with tempfile.NamedTemporaryFile(suffix=".ini.php", delete=False) as f:
            f.write(content.encode())
            path = f.name
        try:
            m = ConfigManager(path, format_override="ini")
            m.load()
            m.driver.set("General.key", "new")
            m.driver.set("WebUI.Port", "5000")
            m.save()
            with open(path, "r") as f:
                res = f.read()
                assert res.startswith("<?php die(); ?>")
                assert "key = new" in res
                assert "Port = 5000" in res
            logging.info("INI comprehensive tests passed")
        finally:
            os.unlink(path)

    def test_qbittorrent_conf_detection():
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "qBittorrent.conf")
            content = """
[Preferences]
WebUI\\Address=*
WebUI\\Port=5000
"""
            with open(path, "w") as f:
                f.write(content)

            m = ConfigManager(path)
            assert m.format == "ini"
            m.load()
            m.driver.set(
                "Preferences.WebUI\\ReverseProxySupportEnabled",
                "true",
            )
            m.driver.set(
                "Preferences.WebUI\\AlternativeUIEnabled",
                "true",
            )
            m.driver.set(
                "Preferences.WebUI\\AuthSubnetWhitelistEnabled",
                "true",
            )
            m.driver.set(
                "Preferences.WebUI\\AuthSubnetWhitelist",
                "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
            )
            m.driver.set(
                "Preferences.WebUI\\RootFolder",
                "/vuetorrent-ui",
            )
            m.save()

            with open(path, "r") as f:
                res = f.read()
                assert "WebUI\\ReverseProxySupportEnabled = true" in res
                assert "WebUI\\AlternativeUIEnabled = true" in res
                assert (
                    "WebUI\\AuthSubnetWhitelistEnabled = true" in res
                )
                assert (
                    "WebUI\\AuthSubnetWhitelist = "
                    "127.0.0.0/8,10.0.0.0/8,"
                    "172.16.0.0/12,192.168.0.0/16" in res
                )
                assert "WebUI\\RootFolder = /vuetorrent-ui" in res
            logging.info("qBittorrent INI detection tests passed")

    def test_kv():
        content = "Server1.Host = old\nServer1.Port=443"
        with tempfile.NamedTemporaryFile(suffix=".conf", delete=False) as f:
            f.write(content.encode())
            path = f.name
        try:
            m = ConfigManager(path)
            m.load()
            m.driver.set("Server1.Host", "new.host")
            m.driver.set("NewKey", "value")
            m.save()
            with open(path, "r") as f:
                res = f.read()
                assert "Server1.Host=new.host" in res
                assert "Server1.Port=443" in res
                assert "NewKey=value" in res
            logging.info("KV comprehensive tests passed")
        finally:
            os.unlink(path)

    def test_resolver():
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"KEY1=VAL1\nexport KEY2 = VAL2")
            path = f.name
        try:
            r = ValueResolver(secrets_files=path)
            assert r.resolve("env:KEY1") == "VAL1"
            assert r.resolve("env:KEY2") == "VAL2"
            logging.info("Resolver tests passed")
        finally:
            os.unlink(path)

    def test_resolver_multiple_files():
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            with tempfile.NamedTemporaryFile(delete=False) as f2:
                f1.write(b"KEY1=VAL1\nSHARED=ONE")
                f2.write(b"KEY2=VAL2\nSHARED=TWO")
                path1 = f1.name
                path2 = f2.name
        try:
            r = ValueResolver(secrets_files=[path1, path2])
            assert r.resolve("env:KEY1") == "VAL1"
            assert r.resolve("env:KEY2") == "VAL2"
            assert r.resolve("env:SHARED") == "TWO"
            logging.info("Multiple secrets file resolver tests passed")
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_resolver_yaml():
        r = ValueResolver()
        assert r.resolve("yaml:true") is True
        assert r.resolve("yaml:false") is False
        assert r.resolve("yaml:5002") == 5002
        assert r.resolve('yaml:"0.0.0.0"') == "0.0.0.0"
        logging.info("YAML resolver tests passed")

    def test_yaml_upsert_list():
        content = """
- Calendar:
  - Calendar:
      icon: mdi-calendar
- Media:
  - Plex:
      icon: plex.png
"""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(content.encode())
            path = f.name
        try:
            m = ConfigManager(path)
            m.load()
            # Test updating existing item in existing group
            m.driver.set("[Media].[Plex].icon", "plex-new.png")
            # Test adding new item to existing group
            m.driver.set("[Media].[RomM].icon", "romm.png")
            # Test adding new group and item
            m.driver.set("[Utilities].[OmniTools].icon", "fa-wrench")
            m.save()

            yaml = YAML(typ="safe")
            with open(path, "r") as f:
                data = yaml.load(f)
                
                # Verify Media group updates
                media_group = next(g["Media"] for g in data if "Media" in g)
                plex = next(s["Plex"] for s in media_group if "Plex" in s)
                assert plex["icon"] == "plex-new.png"
                
                romm = next(s["RomM"] for s in media_group if "RomM" in s)
                assert romm["icon"] == "romm.png"
                
                # Verify Utilities group creation
                utils_group = next(g["Utilities"] for g in data if "Utilities" in g)
                omni = next(s["OmniTools"] for s in utils_group if "OmniTools" in s)
                assert omni["icon"] == "fa-wrench"
                
            logging.info("YAML list upsert/creation tests passed")
        finally:
            os.unlink(path)

    test_xml()
    test_yaml()
    test_yaml_poisoned_scalar_repair()
    test_yaml_complex_paths()
    test_yaml_upsert_list()
    test_ini()
    test_qbittorrent_conf_detection()
    test_kv()
    test_resolver()
    test_resolver_multiple_files()
    test_resolver_yaml()
    logging.info("All comprehensive self-tests passed!")


def main():
    parser = argparse.ArgumentParser(description="Surgical Config Updater")
    parser.add_argument(
        "command", choices=["set", "delete"], nargs="?", help="Action to perform"
    )
    parser.add_argument("file", nargs="?", help="Path to config file")
    parser.add_argument("patches", nargs="*", help="Key=Value pairs or Paths to delete")
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't write to disk"
    )
    parser.add_argument("--format", help="Override format detection")
    parser.add_argument("--test", action="store_true", help="Run self-tests")
    parser.add_argument(
        "--allow-missing", action="store_true", help="Don't warn if path not found"
    )
    parser.add_argument(
        "--secrets-file",
        action="append",
        default=[],
        help="Path to env-style secrets file",
    )

    args = parser.parse_args()

    if args.test:
        run_self_tests()
        sys.exit(0)

    if not args.command or not args.file:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(args.file):
        logging.info(f"File not found: {args.file}. Skipping.")
        sys.exit(0)

    resolver = ValueResolver(secrets_files=args.secrets_file)
    manager = ConfigManager(args.file, args.format, allow_missing=args.allow_missing)
    manager.load()

    if manager.driver:
        if args.command == "set":
            for patch in args.patches:
                match = re.match(r"(.+)=(env|file|literal|yaml):(.*)", patch)
                if match:
                    key, prefix, val_ref = match.groups()
                    val = resolver.resolve(f"{prefix}:{val_ref}")
                    manager.driver.set(key, val)
                elif "=" in patch:
                    key, val = patch.split("=", 1)
                    manager.driver.set(key, val)
                else:
                    logging.warning(f"Invalid patch format: {patch}")
        elif args.command == "delete":
            for path in args.patches:
                manager.driver.delete(path)

    manager.save(args.dry_run)


if __name__ == "__main__":
    main()
